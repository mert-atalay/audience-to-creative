"""Runs the stages in order for one profile and writes every output through the storage backend."""
from __future__ import annotations

import json
from pathlib import Path

from . import gallery, review
from .audience import build_audience
from .config import PROFILES, ROOT, load_profile
from .generate import get_generator, make_variants
from .memory import Memory, now
from .recommend import recommend
from .sources import dump_sources, load_sources
from .storage import Storage, open_store

DEMO_DATA = ROOT / "data" / "demo"


def write_gallery(store: Storage, profile: dict) -> None:
    variants = store.read_json(review.VARIANTS)
    visuals = {v["svg"]: store.read_text(v["svg"]) for v in variants["variants"] if v["svg"]}
    html = gallery.build(profile, store.read_json("audience.json"), store.read_json("briefs.json"),
                         variants, visuals, Memory(store).events())
    store.write_text("gallery.html", html, "text/html")


def run_profile(name: str, store: Storage, generator: str = "template", top_n: int = 3, at: str | None = None, log=print) -> dict:
    profile, memory, at = load_profile(name), Memory(store), at or now()
    run = memory.next_run()

    sources = load_sources(name)                                             # 1. sources
    store.write_text("sources.json", dump_sources(sources), "application/json")
    audience = build_audience(sources, profile)                              # 2. audience intelligence
    store.write_json("audience.json", audience)
    briefs = recommend(audience, sources, memory.events(), profile, run, top_n)  # 3. recommendations
    store.write_json("briefs.json", briefs)
    gen = get_generator(generator)                                           # 4. generation and guardrails
    competitors = sorted(set(profile["competitors"]) | {r["advertiser"] for r in sources["competitor_ads"]})
    variants, visuals = make_variants(briefs["briefs"], gen, profile, competitors, memory.rejected_headlines())
    for key in store.list("creatives/"):                                     # 5. storage, everything pending review
        store.delete(key)
    for key, text in visuals.items():
        store.write_text(key, text, "image/svg+xml")
    store.write_json(review.VARIANTS, {"profile": name, "run": run, "generator": gen.name, "variants": variants})

    memory.append("run", at=at, run=run, profile=name, generator=gen.name)   # 6. memory
    for b in briefs["briefs"]:
        memory.append("brief", at=at, run=run, brief_id=b["id"], slot=b["slot"], segment=b["segment"], angle=b["angle"],
                      format=b["format"], score=b["score"]["total"], why=b["slot_note"],
                      score_parts={k: p["points"] for k, p in b["score"]["parts"].items()},
                      evidence=[{"source": e["source"], "count": e["count"]} for e in b["evidence"]])
    for v in variants:
        memory.append("variant", at=at, run=run, variant_id=v["id"], brief_id=v["brief_id"], segment=v["segment"],
                      angle=v["angle"], format=v["format"], hook_type=v["hook_type"], generator=v["generator"],
                      headline=v["headline"], status=v["status"],
                      guardrail_failures=[c["rule"] for c in v["guardrails"] if not c["passed"]])
    write_gallery(store, profile)

    pending = sum(v["status"] == "pending" for v in variants)
    log(f"[{name}] run {run}: {len(audience['segments'])} segments, {len(briefs['briefs'])} briefs, "
        f"{len(variants)} variants ({pending} pending review, {len(variants) - pending} rejected by guardrails) -> {store}")
    return {"run": run, "briefs": briefs, "variants": variants}


def import_results(name: str, store: Storage, path: Path | None = None, at: str | None = None, log=print) -> tuple[list, list]:
    rows = json.loads(Path(path or DEMO_DATA / name / "results.json").read_text(encoding="utf-8"))
    imported, skipped = Memory(store).import_results(rows, at=at)
    write_gallery(store, load_profile(name))
    log(f"[{name}] results: {len(imported)} imported, {len(skipped)} skipped")
    for row in skipped:
        log(f"  skipped {row['variant_id']}: {row['reason']}")
    return imported, skipped


def demo(location: str = "out", log=print) -> None:
    """The whole loop on synthetic data, for both profiles, with fixed timestamps so output is reproducible.

    The review step is scripted here from data/demo/<profile>/review_decisions.json. In real use a person decides.
    """
    for name in PROFILES:
        store = open_store(location, name)
        store.clear()
        at = load_profile(name)["as_of"] + "T09:00:00Z"
        run_profile(name, store, at=at, log=log)
        decisions = json.loads((DEMO_DATA / name / "review_decisions.json").read_text(encoding="utf-8"))
        for d in decisions:
            review.decide(store, d["variant_id"], d["decision"], d["note"], reviewer="demo-script", at=at)
        log(f"[{name}] scripted review: {len(decisions)} decisions applied")
        import_results(name, store, at=at, log=log)
        result = run_profile(name, store, at=at, log=log)
        log(f"[{name}] run 2 briefs: " + "; ".join(f"{b['segment']}/{b['angle']}/{b['format']} ({b['slot']}, {b['score']['total']})"
                                                    for b in result["briefs"]["briefs"]))
        log(f"[{name}] open {store}/gallery.html")
