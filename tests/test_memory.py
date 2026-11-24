import json

from pipeline import review, run
from pipeline.memory import Memory

from conftest import quiet

AT = "2026-10-15T09:00:00Z"


def test_log_is_append_only_and_complete(store):
    memory = Memory(store)
    before = store.read_text("memory.jsonl")
    events = memory.events()
    assert [e["id"] for e in events] == [f"mem-{i:04d}" for i in range(1, len(events) + 1)]
    variants = review.load_variants(store)
    assert len(memory.events("run")) == 1 and len(memory.events("variant")) == len(variants)
    for brief in memory.events("brief"):
        assert brief["why"] and brief["evidence"] and brief["score_parts"]
    memory.append("note", at=AT, text="x")
    assert store.read_text("memory.jsonl").startswith(before)


def test_results_feed_the_next_recommendation_run(store, name):
    memory = Memory(store)
    first = store.read_json("briefs.json")
    explore = next(b for b in first["briefs"] if b["slot"] == "explore")
    variants = [v for v in review.load_variants(store) if v["brief_id"] == explore["id"]]
    pending_elsewhere = next(v for v in review.load_variants(store) if v["status"] == "pending" and v["brief_id"] != explore["id"])
    for v in variants:
        review.decide(store, v["id"], "approved", "test it", at=AT)
    rows = [{"variant_id": v["id"], "impressions": 30000, "clicks": 400, "leads": 60, "spend": 500.0, "weeks_running": 4} for v in variants]
    rows.append({**rows[0], "variant_id": pending_elsewhere["id"]})   # never approved
    rows.append({**rows[0], "variant_id": "unknown-variant"})
    imported, skipped = memory.import_results(rows, at=AT)
    assert len(imported) == len(variants)
    assert sorted(s["reason"] for s in skipped) == ["unknown variant", "variant was not approved"]
    assert memory.import_results(rows[:1], at=AT)[1][0]["reason"] == "results already imported"

    run.run_profile(name, store, at=AT, log=quiet)
    second = store.read_json("briefs.json")
    assert second["run"] == 2
    # The explored angle now has data, so it is no longer untried and the explore slot moves on.
    assert explore["angle"] in first["untried_angles"] and explore["angle"] not in second["untried_angles"]
    assert next(b for b in second["briefs"] if b["slot"] == "explore")["angle"] != explore["angle"]
    key = lambda r: (r["segment"], r["angle"], r["format"])
    before = next(r for r in first["ranking"] if key(r) == key(explore))
    after = next(r for r in second["ranking"] if key(r) == key(explore))
    assert before["leads"] == 0 and after["leads"] == 60 * len(variants)
    assert after["performance_points"] > before["performance_points"]
    # Strong results earn the combination a normal slot, with the memory rows as evidence.
    promoted = next(b for b in second["briefs"] if key(b) == key(explore))
    assert promoted["slot"] == "exploit"
    result_ids = {e["id"] for e in memory.events("result")}
    assert {i for ev in promoted["evidence"] if ev["source"] == "memory" for i in ev["ids"]} == result_ids
    assert "briefed 1 times before" in promoted["score"]["parts"]["freshness"]["detail"]


def test_a_headline_a_reviewer_rejected_is_not_proposed_again(store, name):
    target = next(v for v in review.load_variants(store) if v["status"] == "pending")
    review.decide(store, target["id"], "rejected", "not true for us", at=AT)
    run.run_profile(name, store, at=AT, log=quiet)
    again = [v for v in review.load_variants(store)
             if (v["segment"], v["angle"], v["headline"]) == (target["segment"], target["angle"], target["headline"])]
    for v in again:
        failed = {c["rule"]: c["detail"] for c in v["guardrails"] if not c["passed"]}
        assert v["status"] == "rejected_by_guardrails" and "not true for us" in failed["not_rejected_before"]
    assert json.loads(store.read_text("memory.jsonl").splitlines()[0])["type"] == "run"
