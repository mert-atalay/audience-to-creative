"""Guardrails. They run on every variant, whichever generator wrote it."""
from __future__ import annotations

import re

FIELDS = ("headline", "primary_text", "cta")


def _all_text(copy: dict) -> str:
    return " ".join(copy.get(f, "") for f in FIELDS)


def required_disclaimers(copy: dict, profile: dict) -> list[str]:
    """Disclaimer texts that the copy triggers, e.g. a free offer needs 'Terms apply.'"""
    text = _all_text(copy)
    return [d["text"] for d in profile["guardrails"]["disclaimers"] if re.search(d["trigger"], text, re.I)]


def check(copy: dict, spec: dict, profile: dict, competitors: list[str]) -> list[dict]:
    """One result per rule: {'rule', 'passed', 'detail'}."""
    text = _all_text(copy)
    results = []

    def add(rule: str, problems: list[str]):
        results.append({"rule": rule, "passed": not problems, "detail": "; ".join(problems) or "ok"})

    over = [f"{field} is {len(copy.get(field, ''))} characters, limit {limit}"
            for field, limit in spec["limits"].items() if len(copy.get(field, "")) > limit]
    empty = [f"{field} is empty" for field in spec["limits"] if not copy.get(field, "").strip()]
    add("length", over + empty)

    options = spec.get("cta_options") or []
    cta = copy.get("cta", "")
    if options:
        add("cta_allowed", [] if cta in options else [f"'{cta}' is not a button this placement offers"])
    else:
        add("cta_allowed", [f"this placement has no button, got '{cta}'"] if cta else [])

    add("banned_claims", [f"{b['name']}: '{m.group(0)}'" for b in profile["guardrails"]["banned_claims"]
                          if (m := re.search(b["pattern"], text, re.I))])

    add("disclaimer", [f"'{d}' is required but missing from the primary text"
                       for d in required_disclaimers(copy, profile) if d.lower() not in copy.get("primary_text", "").lower()])

    spelling = profile["brand"]["spelling"]
    add("brand_spelling", [f"'{m.group(0)}' should be written '{spelling['correct']}'"
                           for m in re.finditer(spelling["pattern"], text, re.I) if m.group(0) != spelling["correct"]])

    add("competitor_names", [f"mentions competitor '{name}'" for name in competitors if name.lower() in text.lower()])
    return results
