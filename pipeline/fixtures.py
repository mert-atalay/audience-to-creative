"""Seeded generator for the bundled synthetic data. Same seed, same files, every time.

Nothing here is real. Records carry coarse attributes only: no names, emails or phone numbers.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from .audience import assign_segment
from .config import CONFIG, FIXTURES, load_profile, load_yaml


def _pick(rng: random.Random, weights: dict):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _companies(rng, seed) -> list[dict]:
    first = ["north", "quay", "mill", "east", "tide", "stone", "oak", "river", "hill", "lake"]
    second = ["works", "partners", "group", "labs", "supply", "care", "foods", "freight", "studio", "systems"]
    names = rng.sample([a + b for a in first for b in second], seed["companies"])
    return [{"id": f"firm-{i:03d}", "domain": f"{name}.example", "industry": rng.choice(seed["industries"]),
             "size_band": _pick(rng, seed["size_bands"]), "region": rng.choice(seed["regions"])}
            for i, name in enumerate(names, 1)]


def _crm(rng, seed, profile, firms) -> tuple[list[dict], dict]:
    """Leads (people for B2C, companies for B2B) and the segment of each lead."""
    as_of = date.fromisoformat(profile["as_of"])
    angles, leads, seg_of = profile["angles"], [], {}
    companies = rng.sample(firms, seed["leads"]) if firms else []
    for i in range(1, seed["leads"] + 1):
        lead = {"id": f"crm-{i:04d}", "created": (as_of - timedelta(days=rng.randint(1, 180))).isoformat()}
        if firms:
            firm = companies[i - 1]
            lead["company_domain"] = firm["domain"]
            lead["seats_quoted"] = rng.randint(*seed["seats"][firm["size_band"]])
            seg = assign_segment({**lead, **firm}, profile)
        else:
            lead["location"] = rng.choice(seed["locations"])
            lead["plan_interest"] = _pick(rng, seed["plans"])
            lead["experience"] = _pick(rng, seed["experience"])
            seg = assign_segment(lead, profile)
        lead["channel"] = _pick(rng, seed["channels"][seg])
        lead["stage"] = _pick(rng, seed["stages"][seg])
        lead["lost_reason"] = None
        if lead["stage"] == "lost":
            angle = _pick(rng, seed["affinity"][seg])
            lead["lost_reason"] = rng.choice(angles[angle]["answers"]) if rng.random() < 0.85 else "moved_or_closed"
        won = lead["stage"] == profile["won_stage"]
        price = lead["seats_quoted"] * seed["price_per_seat"] if firms else seed["plan_value"][lead["plan_interest"]]
        lead["monthly_value"] = price if won else 0
        leads.append(lead)
        seg_of[lead["id"]] = seg
    return leads, seg_of


def _ads(rng, seed, profile) -> list[dict]:
    as_of, cfg, rows = date.fromisoformat(profile["as_of"]), seed["ads"], []
    long_running = [tuple(x) for x in cfg["long_running"]]

    def add(segment, angle, fmt, hook, impressions, clicks, leads, weeks):
        n = len(rows) + 1
        rows.append({"id": f"ad-{n:03d}", "creative_name": f"{segment}_{angle}_{fmt}_{hook}", "segment": segment,
                     "angle": angle, "format": fmt, "hook_type": hook,
                     "first_run": (as_of - timedelta(weeks=weeks)).isoformat(), "weeks_running": weeks,
                     "impressions": impressions, "clicks": clicks, "leads": leads,
                     "spend": round(clicks * rng.uniform(0.6, 1.4), 2)})

    for seg in profile["segments"]:
        for angle, angle_mult in cfg["tried"].items():
            for fmt, rates in cfg["formats"].items():
                for hook, hook_mult in cfg["hooks"].items():
                    if rng.random() < cfg["skip"]:
                        continue
                    impressions = rng.randrange(8000, 40000, 100)
                    clicks = round(impressions * rates["ctr"] * rng.uniform(0.85, 1.15))
                    fit = 0.6 + 0.12 * seed["affinity"][seg["id"]][angle]
                    leads = round(clicks * rates["cvr"] * angle_mult * hook_mult * fit * rng.uniform(0.85, 1.15))
                    weeks = rng.randint(18, 26) if (seg["id"], angle) in long_running else rng.randint(2, 8)
                    add(seg["id"], angle, fmt, hook, impressions, clicks, leads, weeks)
    lucky = cfg["lucky"]
    add(lucky["segment"], lucky["angle"], lucky["format"], lucky["hook_type"],
        lucky["impressions"], lucky["clicks"], lucky["leads"], lucky["weeks_running"])
    return rows


def generate(profile_name: str) -> dict[str, list[dict]]:
    profile = load_profile(profile_name)
    seed = load_yaml(CONFIG / "fixture_seed.yaml")[profile_name]
    rng = random.Random(seed["seed"])
    vocab, as_of = seed["vocab"], date.fromisoformat(profile["as_of"])
    data: dict[str, list[dict]] = {}

    firms = _companies(rng, seed) if "companies" in seed else []
    if firms:
        data["firmographics"] = firms
    crm, seg_of = _crm(rng, seed, profile, firms)
    data["crm"] = crm
    data["ad_performance"] = _ads(rng, seed, profile)

    data["survey"] = []
    for lead in crm:
        if rng.random() < 0.45:
            angle = _pick(rng, seed["affinity"][seg_of[lead["id"]]])
            data["survey"].append({"id": f"srv-{len(data['survey']) + 1:04d}", "lead_id": lead["id"],
                                   "question": seed["survey_question"], "text": rng.choice(vocab[angle]["say"])})

    data["chat"] = []
    for i in range(1, seed["chats"] + 1):
        lead = rng.choice(crm) if rng.random() < 0.7 else None  # most chats join to a CRM id, some are anonymous
        angle = _pick(rng, seed["affinity"][seg_of[lead["id"]]] if lead else seed["demand"])
        data["chat"].append({"id": f"chat-{i:04d}", "lead_id": lead["id"] if lead else None,
                             "text": rng.choice(vocab[angle]["ask"])})

    data["site_search"], data["search_demand"] = [], []
    for angle, words in vocab.items():
        weight = seed["demand"][angle]
        for term in words["search"]:
            data["site_search"].append({"id": f"ss-{len(data['site_search']) + 1:03d}", "term": term,
                                        "count": weight * rng.randint(8, 20)})
        for query in words["demand"]:
            data["search_demand"].append({"id": f"sd-{len(data['search_demand']) + 1:03d}", "query": query,
                                          "monthly_searches": weight * rng.randint(90, 160)})

    callouts = [s["keywords"][0].capitalize() for s in profile["segments"] if s["keywords"]]
    data["competitor_ads"] = []
    for i in range(1, seed["competitor_ads"] + 1):
        text = rng.choice(vocab[_pick(rng, seed["competitor_weight"])]["competitor"])
        if rng.random() < 0.25:
            text = f"{rng.choice(callouts)}: {text}"  # some competitor ads address one segment by name
        data["competitor_ads"].append({"id": f"comp-{i:03d}", "advertiser": rng.choice(profile["competitors"]),
                                       "start_date": (as_of - timedelta(days=rng.randint(3, 150))).isoformat(),
                                       "format": rng.choice(["image", "video", "carousel"]), "text": text})

    data["reviews"] = []
    for i in range(1, seed["reviews"] + 1):
        positive = rng.random() < 0.6
        data["reviews"].append({"id": f"rev-{i:03d}", "subject": rng.choice([profile["business"]] + profile["competitors"]),
                                "rating": rng.choice([4, 5]) if positive else rng.choice([1, 2]),
                                "text": vocab[_pick(rng, seed["demand"])]["review"][0 if positive else 1]})
    return data


def write(profile_name: str, directory: Path = FIXTURES) -> Path:
    target = Path(directory) / profile_name
    target.mkdir(parents=True, exist_ok=True)
    for name, records in generate(profile_name).items():
        body = ",\n".join(json.dumps(r, ensure_ascii=False) for r in records)
        (target / f"{name}.json").write_text(f"[\n{body}\n]\n", encoding="utf-8")
    return target
