"""One self-contained HTML page per profile: segments, ranked briefs and creatives with their status.

Inline CSS and inline SVG only. No scripts and no external requests.
"""
from __future__ import annotations

from html import escape as e

CSS = """
:root{--bg:#f5f6f8;--card:#fff;--text:#18212c;--muted:#5a6573;--line:#dde2e8;--chip:#eef1f5;
--performance:#2f6fb0;--demand:#1f8a7d;--fit:#b97a14;--whitespace:#8456a3;--freshness:#c2504c;
--ok:#1d7a46;--warn:#9a6700;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#10151b;--card:#19212a;--text:#e7ebf0;--muted:#9ba7b5;--line:#2b3541;--chip:#232d38;
--performance:#6aa5e0;--demand:#4fc0b1;--fit:#e3ad4f;--whitespace:#b891d3;--freshness:#e58985;
--ok:#5fcf8f;--warn:#e3b341;--bad:#ff8a80}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 56px}
h1{font-size:1.6rem;line-height:1.25;margin:0 0 6px}
h2{font-size:1.2rem;margin:40px 0 4px}
h3{font-size:1rem;margin:0}
h4{font-size:.74rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin:14px 0 4px}
p{margin:4px 0}
.muted,small{color:var(--muted)}
.notice{border:1px solid var(--line);border-left:4px solid var(--warn);background:var(--card);padding:10px 14px;border-radius:6px;margin:14px 0}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,270px),1fr));margin-top:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;min-width:0}
ul{margin:0;padding:0;list-style:none}
li{display:flex;flex-wrap:wrap;justify-content:space-between;gap:0 10px;padding:2px 0}
li small{margin-left:auto;text-align:right;overflow-wrap:anywhere}
.kpis{display:flex;flex-wrap:wrap;gap:6px 18px;margin:8px 0 0}
.kpis b{display:block;font-size:1.15rem}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 9px;margin:2px 4px 2px 0;font-size:.82rem}
.badge{display:inline-block;border:1px solid currentColor;border-radius:4px;padding:0 6px;font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.pending{color:var(--warn)}.approved,.exploit{color:var(--ok)}.rejected,.rejected_by_guardrails{color:var(--bad)}.explore{color:var(--whitespace)}
.head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.score{font-size:1.5rem;font-weight:700;line-height:1}
.bar{display:flex;gap:2px;height:14px;margin:12px 0 8px;background:var(--chip);border-radius:4px;overflow:hidden}
.bar span{display:block;height:100%}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.86rem}
th,td{text-align:left;padding:5px 12px 5px 0;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600}
td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}
.visual{background:var(--chip);border-radius:8px;padding:10px;text-align:center;margin-bottom:12px}
.visual svg{display:block;margin:0 auto;max-width:100%;width:auto;height:auto;max-height:400px;border-radius:4px}
.textad{text-align:left;font-size:.9rem}
.textad b{font-size:1.05rem;color:var(--performance)}
.copy{overflow-wrap:anywhere}
.fail{color:var(--bad);font-weight:600}.pass{color:var(--ok)}
footer{margin-top:44px;color:var(--muted);font-size:.85rem}
"""


def _records(evidence: list[dict]) -> int:
    return sum(ev["count"] for ev in evidence)


def _items(rows: list[tuple[str, str]], empty: str = "None found") -> str:
    if not rows:
        return f'<p class="muted">{empty}</p>'
    return "<ul>" + "".join(f"<li><span>{e(a)}</span><small>{e(b)}</small></li>" for a, b in rows) + "</ul>"


def _segment(seg: dict) -> str:
    size, value = seg["size"], seg["value"]
    rule = seg["rule"] if isinstance(seg["rule"], str) else "; ".join(f"{k} in {', '.join(v)}" for k, v in seg["rule"].items())
    voice = lambda items: [(i["label"], f"{i['mentions']} mention{'' if i['mentions'] == 1 else 's'}") for i in items[:3]]
    phrases = "".join(f'<span class="chip">{e(p["phrase"])} &times;{p["count"]}</span>' for p in sorted(seg["language"], key=lambda p: -p["count"])[:6])
    gaps = "".join(f"<p>{e(g['label'])}<br><small>demand score {g['demand']:.2f}, competitor share {g['competitor_share']:.0%}, "
                   f"our impressions {g['own_impressions']:,}, {_records(g['evidence'])} records</small></p>" for g in seg["gaps"])
    gaps = gaps or '<p class="muted">No gap by the current rule</p>'
    return f"""<article class="card"><h3>{e(seg['label'])}</h3><small>Rule: {e(rule)}</small>
<div class="kpis"><span><b>{size['leads']}</b><small>leads</small></span><span><b>{size['customers']}</b><small>customers</small></span>
<span><b>{value['conversion_rate']:.0%}</b><small>conversion</small></span><span><b>{value['monthly_value']:,}</b><small>monthly value</small></span></div>
<h4>Motivations (survey)</h4>{_items(voice(seg['motivations']))}
<h4>Objections (chat and lost deals)</h4>{_items(voice(seg['objections']))}
<h4>Lost reasons (CRM)</h4>{_items([(l['reason'].replace('_', ' '), f"{l['count']} lost, {l['share']:.0%}") for l in seg['lost_reasons'][:3]])}
<h4>Phrases they use</h4><p>{phrases or '<span class="muted">None repeated</span>'}</p>
<h4>Channels</h4>{_items([(c['channel'].replace('_', ' '), f"{c['leads']} leads") for c in seg['channels'][:3]])}
<h4>What competitors say to them</h4>{_items([(c['label'], f"{c['ads']} ads, {c['share']:.0%}") for c in seg['competitor_messaging'][:3]])}
<h4>Gaps (demand visible, competitors and our ads quiet)</h4>{gaps}
</article>"""


def _brief(b: dict) -> str:
    parts = b["score"]["parts"]
    bar = "".join(f'<span style="width:{p["points"]}%;background:var(--{k})" title="{k}: {p["points"]}"></span>' for k, p in parts.items())
    rows = "".join(f'<tr><td><span class="sw" style="background:var(--{k})"></span>{k}</td><td class="num">{p["points"]} / {100 * p["weight"]:.0f}</td>'
                   f'<td>{e(p["detail"])}</td></tr>' for k, p in parts.items())
    phrases = "".join(f'<span class="chip">{e(p["phrase"])} &times;{p["count"]}</span>' for p in b["language"]) or '<span class="muted">none repeated</span>'
    objection = f"{b['objection']['reason'].replace('_', ' ')} ({b['objection']['count']} lost)" if b["objection"] else "none recorded"
    sources = "".join(f'<span class="chip">{e(ev["source"])}: {ev["count"]}</span>' for ev in b["evidence"])
    return f"""<article class="card"><div class="head"><div><span class="badge {b['slot']}">{b['slot']}</span>
<h3>{b['rank']}. {e(b['segment_label'])} / {e(b['angle_label'])}</h3><small>{e(b['platform'])}, {e(b['format'])} &middot; {e(b['id'])}</small></div>
<div><span class="score">{b['score']['total']}</span> <small>/ 100</small></div></div>
<p class="muted">{e(b['slot_note'])}</p>
<div class="bar" role="img" aria-label="Score parts">{bar}</div>
<div class="scroll"><table><tr><th>Part</th><th>Points</th><th>Why</th></tr>{rows}</table></div>
<h4>Customer language to use</h4><p>{phrases}</p>
<h4>Objection to answer</h4><p>{e(objection)}</p>
<h4>Hook types to test</h4><p>{e(', '.join(b['hooks']))}</p>
<h4>Evidence (records by source)</h4><p>{sources}</p></article>"""


def _variant(v: dict, visuals: dict, limits: dict) -> str:
    if v["svg"]:
        visual = f'<div class="visual">{visuals[v["svg"]]}</div>'
    else:
        visual = f'<div class="visual textad"><small>Text ad, no image</small><br><b>{e(v["headline"])}</b><br>{e(v["primary_text"])}</div>'
    checks = "".join(f'<li><span>{e(c["rule"])}</span><small class="{"pass" if c["passed"] else "fail"}">{e("ok" if c["passed"] else c["detail"])}</small></li>'
                     for c in v["guardrails"])
    review = v["review"]
    note = f'<p><small>Review: {e(review["decision"])} by {e(review["reviewer"])}. {e(review["note"])}</small></p>' if review else ""
    count = lambda field: f'{len(v[field])} / {limits[field]}'
    return f"""<article class="card">{visual}<div class="head"><small>{e(v['id'])} &middot; {e(v['hook_type'])} hook &middot; {e(v['generator'])} generator</small>
<span class="badge {v['status']}">{v['status'].replace('_', ' ')}</span></div>
<h4>Headline <small>{count('headline')}</small></h4><p class="copy">{e(v['headline'])}</p>
<h4>Primary text <small>{count('primary_text')}</small></h4><p class="copy">{e(v['primary_text'])}</p>
<h4>Button</h4><p>{e(v['cta']) or '<span class="muted">none on this placement</span>'}</p>
<h4>Guardrails</h4><ul>{checks}</ul>{note}</article>"""


def _memory(events: list[dict]) -> str:
    reviews = {ev["variant_id"]: ev for ev in events if ev["type"] == "review"}
    results = {ev["variant_id"]: ev for ev in events if ev["type"] == "result"}
    rows = ""
    for ev in (x for x in events if x["type"] == "variant"):
        vid, r, res = ev["variant_id"], reviews.get(ev["variant_id"]), results.get(ev["variant_id"])
        status = r["decision"] if r else ev["status"]
        outcome = f"{res['impressions']:,} impressions, {res['clicks']} clicks, {res['leads']} leads" if res else ""
        rows += (f'<tr><td class="num">{ev["run"]}</td><td>{e(vid)}</td><td>{e(ev["segment"])} / {e(ev["angle"])} / {e(ev["format"])}</td>'
                 f'<td>{e(ev["headline"])}</td><td><span class="badge {status}">{status.replace("_", " ")}</span></td>'
                 f'<td>{e(r["note"]) if r else ""}</td><td>{outcome}</td></tr>')
    return f"""<div class="card scroll"><table><tr><th>Run</th><th>Variant</th><th>Segment / angle / format</th><th>Headline</th>
<th>Status</th><th>Review note</th><th>Result</th></tr>{rows}</table></div>"""


def build(profile: dict, audience: dict, briefs: dict, variants: dict, visuals: dict, events: list[dict]) -> str:
    by_brief = {b["id"]: [v for v in variants["variants"] if v["brief_id"] == b["id"]] for b in briefs["briefs"]}
    creatives = ""
    for b in briefs["briefs"]:
        limits = profile["platforms"][b["format"]]["limits"]
        creatives += (f'<h4>{e(b["id"])}: {e(b["segment_label"])} / {e(b["angle_label"])} / {e(b["platform"])}</h4>'
                      f'<div class="grid">{"".join(_variant(v, visuals, limits) for v in by_brief[b["id"]])}</div>')
    weights = ", ".join(f"{k} {w:.0%}" for k, w in briefs["weights"].items())
    records = ", ".join(f"{n} {name.replace('_', ' ')}" for name, n in audience["records"].items())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(profile['business'])}: audience to creative</title><style>{CSS}</style></head><body><main>
<h1>{e(profile['business'])}: audience to creative</h1>
<p class="muted">{e(profile['audience'])}. Run {briefs['run']}, data as of {e(audience['as_of'])}, {e(variants['generator'])} generator.</p>
<p class="notice">All data on this page is synthetic. The business and its competitors are invented. Nothing here was published or run as a real ad. The photos are example scenes made with an image model for this repository; the logo, headline and button are placed on top by code.</p>
<h2>1. Segments</h2><p class="muted">Built by rules from {e(records)} records. Every figure traces to record ids in audience.json.</p>
<div class="grid">{''.join(_segment(s) for s in audience['segments'])}</div>
<h2>2. Ranked briefs</h2><p class="muted">{briefs['considered']} segment, angle and format combinations scored. Weights: {e(weights)}.
Angles never run: {e(', '.join(briefs['untried_angles']) or 'none')}.</p>
<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr))">{''.join(_brief(b) for b in briefs['briefs'])}</div>
<h2>3. Creatives</h2><p class="muted">Every variant starts as pending. A person approves or rejects it. Variants that fail a guardrail are rejected automatically.</p>
{creatives}
<h2>4. Experiment memory</h2><p class="muted">{len(events)} events in the append-only log. Imported results feed the next recommendation run.</p>
{_memory(events)}
<footer>Generated by the audience-to-creative example pipeline. Synthetic data only.</footer>
</main></body></html>
"""
