"""Stage 3: recommendations. Score segment x angle x format and write ranked creative briefs."""
from __future__ import annotations

from collections import defaultdict

from .audience import evidence

# Score parts and their weights. They add up to 1. These are judgement calls, not fitted values.
WEIGHTS = {"performance": 0.35, "demand": 0.20, "fit": 0.20, "whitespace": 0.15, "freshness": 0.10}
PRIOR_LEADS = 15       # shrinkage strength: pseudo-leads at the format's average rate
MIN_IMPRESSIONS = 2000 # below this, a combination's own results are ignored and it scores as average
FATIGUE_WEEKS = 26     # weeks of running after which an angle counts as fully fatigued
REPEAT_PENALTY = 0.15  # freshness lost each time memory shows we already briefed the same segment and angle


def shrunk_lift(leads: float, expected: float, prior: float = PRIOR_LEADS) -> float:
    """Lead rate relative to the format average, pulled towards 1.0 when the sample is small.

    expected = impressions x the format's average lead rate. With no data the lift is exactly 1.0.
    """
    return (leads + prior) / (expected + prior)


def performance_rows(sources: dict, memory_events: list[dict]) -> list[dict]:
    """Our own ad history plus results imported into memory, in one shape."""
    rows = [{**r, "source": "ad_performance"} for r in sources["ad_performance"]]
    rows += [{**e, "source": "memory"} for e in memory_events if e["type"] == "result"]
    return rows


def _lift(rows: list[dict], rate: dict) -> tuple[float, float, float]:
    leads = sum(r["leads"] for r in rows)
    expected = sum(r["impressions"] * rate[r["format"]] for r in rows)
    return shrunk_lift(leads, expected), leads, expected


def _evidence(rows: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for r in rows:
        grouped[r["source"]].append(r)
    return [evidence(s, rs) for s, rs in sorted(grouped.items())]


def recommend(audience: dict, sources: dict, memory_events: list[dict], profile: dict, run: int, top_n: int = 3) -> dict:
    rows = performance_rows(sources, memory_events)
    rate = {}  # average leads per impression for each format, the baseline every creative is compared with
    for fmt in profile["formats"]:
        fr = [r for r in rows if r["format"] == fmt]
        rate[fmt] = sum(r["leads"] for r in fr) / max(1, sum(r["impressions"] for r in fr))
    tried_angles = {r["angle"] for r in rows}
    briefed = defaultdict(int)
    for e in memory_events:
        if e["type"] == "brief":
            briefed[(e["segment"], e["angle"])] += 1

    hook_lift = {h: _lift([r for r in rows if r["hook_type"] == h], rate)[0] for h in profile["hooks"]}
    hooks = sorted(profile["hooks"], key=lambda h: (-hook_lift[h], h))[:2]

    opportunities = []
    for seg in audience["segments"]:
        sid = seg["id"]
        demand = {d["angle"]: d for d in seg["demand"]}
        comp = {c["angle"]: c for c in seg["competitor_messaging"]}
        voice = {a: {"mentions": 0, "evidence": []} for a in profile["angles"]}
        for item in seg["motivations"] + seg["objections"]:
            voice[item["angle"]]["mentions"] += item["mentions"]
            voice[item["angle"]]["evidence"] += item["evidence"]
        max_demand = max(d["score"] for d in demand.values()) or 1
        max_comp = max(c["share"] for c in comp.values()) or 1
        max_voice = max(v["mentions"] for v in voice.values()) or 1

        for angle, cfg in profile["angles"].items():
            seg_angle = [r for r in rows if r["segment"] == sid and r["angle"] == angle]
            weeks = max((r["weeks_running"] for r in seg_angle), default=0)
            fatigue = min(1.0, weeks / FATIGUE_WEEKS + REPEAT_PENALTY * briefed[(sid, angle)])
            for fmt in profile["formats"]:
                own = [r for r in seg_angle if r["format"] == fmt]
                lift, leads, expected = _lift(own, rate)
                impressions = sum(r["impressions"] for r in own)
                thin = 0 < impressions < MIN_IMPRESSIONS
                if thin:
                    lift = 1.0
                values = {
                    "performance": min(1.0, lift / 2),  # lift 1.0 (average, or no data) scores 0.5
                    "demand": demand[angle]["score"] / max_demand,
                    "fit": voice[angle]["mentions"] / max_voice,
                    "whitespace": 1 - comp[angle]["share"] / max_comp,
                    "freshness": 1 - fatigue,
                }
                detail = {
                    "performance": f"{leads} leads from {impressions} impressions, " + (
                        f"below the {MIN_IMPRESSIONS} impression minimum so scored as average" if thin
                        else f"shrunk lift {lift:.2f} vs format average"),
                    "demand": f"demand score {demand[angle]['score']:.3f}, top angle in segment {max_demand:.3f}",
                    "fit": f"{voice[angle]['mentions']} mentions by this segment, most mentioned angle {max_voice}",
                    "whitespace": f"{comp[angle]['ads']} competitor ads, {comp[angle]['share']:.0%} of what this segment sees",
                    "freshness": f"longest run on this segment and angle is {weeks} weeks, briefed {briefed[(sid, angle)]} times before",
                }
                parts = {k: {"value": round(values[k], 3), "weight": w, "points": round(100 * w * values[k], 1),
                             "detail": detail[k]} for k, w in WEIGHTS.items()}
                language = [p for p in seg["language"] if p["angle"] == angle]
                lost = next((l for l in seg["lost_reasons"] if l["answered_by"] == angle), None)
                opportunities.append({
                    "segment": sid, "segment_label": seg["label"], "angle": angle, "angle_label": cfg["label"],
                    "format": fmt, "platform": profile["platforms"][fmt]["platform"], "hooks": hooks,
                    "language": [{"phrase": p["phrase"], "count": p["count"], "evidence": p["evidence"]} for p in language],
                    "objection": ({"reason": lost["reason"], "count": lost["count"], "evidence": lost["evidence"]} if lost else None),
                    "score": {"total": round(sum(p["points"] for p in parts.values()), 1), "parts": parts},
                    "sample": {"impressions": impressions, "leads": leads, "expected_leads": round(expected, 1)},
                    "evidence": _evidence(own) + demand[angle]["evidence"] + comp[angle]["evidence"],
                })

    opportunities.sort(key=lambda o: (-o["score"]["total"], o["segment"], o["angle"], o["format"]))

    briefs, taken, used_angles = [], set(), set()

    def take(opp, slot, note):
        taken.add((opp["segment"], opp["angle"]))
        used_angles.add(opp["angle"])
        rank = len(briefs) + 1
        briefs.append({"id": f"{profile['id']}-r{run}-b{rank}", "rank": rank, "run": run, "slot": slot, "slot_note": note, **opp})

    # Exploit slots: the best opportunities among angles we have data for. One brief per angle,
    # so a run tests different messages instead of one message three times.
    for opp in opportunities:
        if len(briefs) < top_n and opp["angle"] in tried_angles and opp["angle"] not in used_angles:
            take(opp, "exploit", "Best scoring opportunity among angles we have already run.")

    # Explore slot: one deliberate test of an angle we have never run. If every angle has been run,
    # test the opportunity with the least data instead.
    fresh = [o for o in opportunities if (o["segment"], o["angle"]) not in taken]
    untried = [o for o in fresh if o["angle"] not in tried_angles]
    if untried:
        take(untried[0], "explore", "Deliberate test: we have never run this angle, so there is no performance data behind it.")
    elif fresh:
        thin = min(fresh, key=lambda o: (o["sample"]["impressions"], -o["score"]["total"]))
        take(thin, "explore", "Deliberate test: every angle has been run, so this slot goes to the combination with the least data.")

    return {"profile": profile["id"], "run": run, "weights": WEIGHTS,
            "rules": {"prior_leads": PRIOR_LEADS, "min_impressions": MIN_IMPRESSIONS, "fatigue_weeks": FATIGUE_WEEKS, "repeat_penalty": REPEAT_PENALTY},
            "format_baseline_leads_per_1000_impressions": {f: round(1000 * v, 3) for f, v in rate.items()},
            "hook_lift": {h: round(v, 3) for h, v in hook_lift.items()},
            "considered": len(opportunities), "untried_angles": sorted(set(profile["angles"]) - tried_angles),
            "briefs": briefs,
            # Every scored combination, so a reader can see what was not chosen.
            "ranking": [{"segment": o["segment"], "angle": o["angle"], "format": o["format"], "score": o["score"]["total"],
                         "performance_points": o["score"]["parts"]["performance"]["points"], **o["sample"]} for o in opportunities]}
