import json
import re

from pipeline.audience import TEXT_FIELDS, assign_segment, build_audience, tag_angles, top_phrases

from conftest import read


def walk_evidence(node):
    """Every {'source', 'ids', 'count'} entry anywhere in a JSON document."""
    if isinstance(node, dict):
        if {"source", "ids", "count"} <= set(node):
            yield node
        for value in node.values():
            yield from walk_evidence(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_evidence(value)


def test_every_lead_lands_in_exactly_one_segment(profile, sources):
    audience = build_audience(sources, profile)
    assert sum(s["size"]["leads"] for s in audience["segments"]) == len(sources["crm"])
    known = {s["id"] for s in profile["segments"]}
    assert {assign_segment(r, profile) for r in sources["crm"]} <= known


def test_segment_insights_are_filled(profile, sources):
    audience = build_audience(sources, profile)
    for seg in audience["segments"]:
        for key in ("channels", "lost_reasons", "motivations", "objections", "language", "demand", "competitor_messaging"):
            assert seg[key], f"{seg['id']} has no {key}"
        assert 0 <= seg["value"]["conversion_rate"] <= 1
    assert any(seg["gaps"] for seg in audience["segments"])
    for seg in audience["segments"]:
        for gap in seg["gaps"]:  # a gap means demand without competitor or own activity
            assert gap["demand"] >= 1 / len(profile["angles"]) and gap["competitor_share"] < gap["demand"]


def test_every_insight_traces_back_to_source_rows(demo_dir, name):
    known = {src: {r["id"] for r in rows} for src, rows in read(demo_dir, name, "sources.json").items()}
    memory = (demo_dir / name / "memory.jsonl").read_text().splitlines()
    known["memory"] = {json.loads(line)["id"] for line in memory}
    for doc in ("audience.json", "briefs.json"):
        entries = list(walk_evidence(read(demo_dir, name, doc)))
        assert len(entries) > 20
        for ev in entries:
            assert ev["ids"] and ev["count"] == len(ev["ids"])
            assert set(ev["ids"]) <= known[ev["source"]], f"{doc}: unknown ids for {ev['source']}"
    for brief in read(demo_dir, name, "briefs.json")["briefs"]:
        assert brief["evidence"], brief["id"]


def test_phrases_are_real_customer_wording(profile, sources):
    audience = build_audience(sources, profile)
    words = lambda text: " ".join(re.findall(r"[a-z0-9/']+", text.lower()))
    by_id = {src: {r["id"]: words(r[field]) for r in sources[src]} for src, field in TEXT_FIELDS.items()}
    for seg in audience["segments"]:
        for item in seg["language"]:
            assert item["count"] >= 2
            for ev in item["evidence"]:
                assert all(item["phrase"] in by_id[ev["source"]][i] for i in ev["ids"])


def test_phrase_counting_and_tagging_units(profile):
    rows = [("chat", {"id": "1"}, "Can I cancel anytime?"), ("chat", {"id": "2"}, "I want to cancel anytime"),
            ("survey", {"id": "3"}, "Something said only once")]
    phrases = top_phrases(rows)
    assert [p["phrase"] for p in phrases] == ["cancel anytime"] and phrases[0]["count"] == 2
    assert {e["source"]: e["ids"] for e in phrases[0]["evidence"]} == {"chat": ["1", "2"]}
    assert tag_angles("nothing relevant here", profile) == []
    first = next(iter(profile["angles"]))
    assert first in tag_angles(f"About {profile['angles'][first]['keywords'][0]} please", profile)
