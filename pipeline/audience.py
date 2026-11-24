"""Stage 2: audience intelligence. Rule-based segments, counted phrases, evidence on every insight."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

STOP = set(
    "a an the i you we it is are was were be been am to of in on at for and or do does did can could "
    "my me our us your there that this with so how what where when which who will would have had has "
    "not much any as by from if about up out they them their over more most just also than into but "
    "because every some per".split()
)
TEXT_FIELDS = {"survey": "text", "chat": "text", "site_search": "term", "reviews": "text"}


def assign_segment(record: dict, profile: dict) -> str:
    """First segment whose match rule fits the record. An empty rule matches everything."""
    for seg in profile["segments"]:
        if all(record.get(field) in allowed for field, allowed in seg["match"].items()):
            return seg["id"]
    return profile["segments"][-1]["id"]


def tag_angles(text: str, profile: dict) -> list[str]:
    """Angles whose keywords appear in the text."""
    low = text.lower()
    return [a for a, cfg in profile["angles"].items() if any(k in low for k in cfg["keywords"])]


def evidence(source: str, records) -> dict:
    ids = sorted({r["id"] for r in records})
    return {"source": source, "ids": ids, "count": len(ids)}


def evidence_by_source(rows) -> list[dict]:
    """rows are (source, record) pairs. Returns one evidence entry per source."""
    grouped = defaultdict(list)
    for source, rec in rows:
        grouped[source].append(rec)
    return [evidence(s, recs) for s, recs in sorted(grouped.items()) if recs]


def ngrams(text: str):
    """Two and three word phrases that do not start or end with a stop word."""
    toks = re.findall(r"[a-z0-9/']+", text.lower())
    for n in (2, 3):
        for i in range(len(toks) - n + 1):
            gram = toks[i:i + n]
            if gram[0] not in STOP and gram[-1] not in STOP:
                yield " ".join(gram)


def top_phrases(rows, limit: int = 3, min_count: int = 2) -> list[dict]:
    """Most repeated phrases across text rows. rows are (source, record, text)."""
    seen, wordings = defaultdict(dict), defaultdict(set)
    for source, rec, text in rows:
        for phrase in set(ngrams(text)):
            seen[phrase][(source, rec["id"])] = (source, rec)
            wordings[phrase].add(text.lower())
    # A phrase that shows up in several different sentences beats one repeated sentence. Then record count.
    ranked = sorted(seen.items(), key=lambda kv: (-len(wordings[kv[0]]), -len(kv[1]), -len(kv[0].split()), kv[0]))
    out = []
    for phrase, hits in ranked:
        if len(hits) < min_count or len(out) >= limit:
            break
        if any(phrase in p["phrase"] or p["phrase"] in phrase for p in out):
            continue  # skip near duplicates such as "cancel anytime" inside "can cancel anytime"
        out.append({"phrase": phrase, "count": len(hits), "evidence": evidence_by_source(hits.values())})
    return out


def _share(counter: Counter, key) -> float:
    total = sum(counter.values())
    return counter[key] / total if total else 0.0


def build_audience(sources: dict, profile: dict) -> dict:
    angles = profile["angles"]
    label = {a: cfg["label"] for a, cfg in angles.items()}
    answered_by = {reason: a for a, cfg in angles.items() for reason in cfg["answers"]}
    even = 1 / len(angles)
    crm = sources["crm"]
    seg_of = {r["id"]: assign_segment(r, profile) for r in crm}

    # Tag every text record once: source, record, text, segment (if it joins to the CRM), angles.
    texts = []
    for source, field in TEXT_FIELDS.items():
        for rec in sources.get(source, []):
            texts.append((source, rec, rec[field], seg_of.get(rec.get("lead_id")), tag_angles(rec[field], profile)))

    # Market-wide demand: external search volume, and on-site searches plus anonymous chat questions.
    search_vol, search_rows = Counter(), defaultdict(list)
    for rec in sources["search_demand"]:
        for a in tag_angles(rec["query"], profile):
            search_vol[a] += rec["monthly_searches"]
            search_rows[a].append(("search_demand", rec))
    site_vol, site_rows = Counter(), defaultdict(list)
    for source, rec, _, seg, tags in texts:
        if source == "site_search" or (source == "chat" and seg is None):
            for a in tags:
                site_vol[a] += rec.get("count", 1)
                site_rows[a].append((source, rec))

    comp_ads = [(rec, tag_angles(rec["text"], profile)) for rec in sources["competitor_ads"]]
    ads = sources["ad_performance"]

    segments = []
    for seg in profile["segments"]:
        sid = seg["id"]
        leads = [r for r in crm if seg_of[r["id"]] == sid]
        won = [r for r in leads if r["stage"] == profile["won_stage"]]
        lost = [r for r in leads if r["stage"] == "lost"]

        by_channel = defaultdict(list)
        for r in leads:
            by_channel[r["channel"]].append(r)
        channels = [{"channel": c, "leads": len(rs), "evidence": [evidence("crm", rs)]}
                    for c, rs in sorted(by_channel.items(), key=lambda kv: (-len(kv[1]), kv[0]))]

        by_reason = defaultdict(list)
        for r in lost:
            by_reason[r["lost_reason"]].append(r)
        lost_reasons = [{"reason": reason, "count": len(rs), "share": round(len(rs) / len(lost), 3),
                         "answered_by": answered_by.get(reason), "evidence": [evidence("crm", rs)]}
                        for reason, rs in sorted(by_reason.items(), key=lambda kv: (-len(kv[1]), kv[0]))]

        # What this segment says: survey answers are motivations, chat questions and lost reasons are objections.
        motive, objection = defaultdict(list), defaultdict(list)
        for source, rec, _, tseg, tags in texts:
            if tseg == sid and source in ("survey", "chat"):
                for a in tags:
                    (motive if source == "survey" else objection)[a].append((source, rec))
        for r in lost:
            if r["lost_reason"] in answered_by:
                objection[answered_by[r["lost_reason"]]].append(("crm", r))
        voice = Counter({a: len(motive[a]) + len(objection[a]) for a in angles})

        def ranked(bucket):
            items = [{"angle": a, "label": label[a], "mentions": len(rows), "evidence": evidence_by_source(rows)}
                     for a, rows in bucket.items() if rows]
            return sorted(items, key=lambda x: (-x["mentions"], x["angle"]))

        # Competitor ads that speak to this segment: ads naming the segment, plus ads naming no segment.
        other_kw = [k for s in profile["segments"] if s["id"] != sid for k in s["keywords"]]
        seg_comp = [(rec, tags) for rec, tags in comp_ads if not any(k in rec["text"].lower() for k in other_kw)]
        comp_count = Counter(a for _, tags in seg_comp for a in tags)
        own_impr = Counter()
        for row in ads:
            if row["segment"] == sid:
                own_impr[row["angle"]] += row["impressions"]

        language, demand, competitors, gaps = [], [], [], []
        for a in angles:
            pool = [(src, rec, text) for src, rec, text, tseg, tags in texts if a in tags and tseg in (sid, None)]
            for p in top_phrases(pool):
                language.append({"angle": a, **p})

            parts = {"search_demand": _share(search_vol, a), "on_site": _share(site_vol, a), "segment_voice": _share(voice, a)}
            demand.append({"angle": a, "label": label[a], "score": round(sum(parts.values()) / 3, 4),
                           "parts": {k: round(v, 4) for k, v in parts.items()},
                           "evidence": evidence_by_source(search_rows[a] + site_rows[a] + motive[a] + objection[a])})

            c_rows = [rec for rec, tags in seg_comp if a in tags]
            competitors.append({"angle": a, "label": label[a], "ads": len(c_rows), "share": round(_share(comp_count, a), 4),
                                "advertisers": sorted({r["advertiser"] for r in c_rows}),
                                "evidence": [evidence("competitor_ads", c_rows)] if c_rows else []})

            own_share = _share(own_impr, a)
            d, c = demand[-1], competitors[-1]
            if d["score"] >= even and c["share"] <= 0.75 * even and own_share <= 0.5 * even:
                own_rows = [r for r in ads if r["segment"] == sid and r["angle"] == a]
                gaps.append({"angle": a, "label": label[a], "demand": d["score"], "competitor_share": c["share"],
                             "own_impressions": own_impr[a],
                             "reason": "Demand is above an even share, competitors rarely use this angle and we have run little or nothing on it.",
                             "evidence": d["evidence"] + c["evidence"] + ([evidence("ad_performance", own_rows)] if own_rows else [])})

        value = sum(r["monthly_value"] for r in won)
        segments.append({
            "id": sid, "label": seg["label"], "rule": seg["match"] or "everything else",
            "size": {"leads": len(leads), "customers": len(won), "share_of_leads": round(len(leads) / len(crm), 3),
                     "evidence": [evidence("crm", leads)]},
            "value": {"conversion_rate": round(len(won) / len(leads), 3) if leads else 0.0,
                      "monthly_value": value, "avg_monthly_value": round(value / len(won), 2) if won else 0.0,
                      "evidence": [evidence("crm", won)] if won else []},
            "channels": channels, "lost_reasons": lost_reasons,
            "motivations": ranked(motive), "objections": ranked(objection),
            "language": language, "demand": sorted(demand, key=lambda x: (-x["score"], x["angle"])),
            "competitor_messaging": sorted(competitors, key=lambda x: (-x["share"], x["angle"])),
            "gaps": sorted(gaps, key=lambda x: (-x["demand"], x["angle"])),
        })

    return {"profile": profile["id"], "business": profile["business"], "as_of": profile["as_of"],
            "records": {name: len(rows) for name, rows in sources.items()},
            "segments": [s for s in segments if s["size"]["leads"]]}
