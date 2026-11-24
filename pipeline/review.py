"""Stage 5: human review. Variants start as 'pending'. A person approves or rejects them with a note."""
from __future__ import annotations

from .memory import Memory, now
from .storage import Storage

VARIANTS = "variants.json"


class ReviewError(ValueError):
    pass


def load_variants(store: Storage) -> list[dict]:
    return store.read_json(VARIANTS)["variants"] if store.exists(VARIANTS) else []


def decide(store: Storage, variant_id: str, decision: str, note: str = "", reviewer: str = "reviewer", at: str | None = None) -> dict:
    """Approve or reject one variant. Approval never publishes anything, it only changes the status."""
    if decision not in ("approved", "rejected"):
        raise ReviewError("decision must be 'approved' or 'rejected'")
    data = store.read_json(VARIANTS) if store.exists(VARIANTS) else {"variants": []}
    variant = next((v for v in data["variants"] if v["id"] == variant_id), None)
    if variant is None:
        raise ReviewError(f"No variant '{variant_id}' in the current run")
    if variant["status"] == "rejected_by_guardrails":
        failed = ", ".join(c["rule"] for c in variant["guardrails"] if not c["passed"])
        raise ReviewError(f"{variant_id} failed guardrails ({failed}) and cannot be reviewed")
    at = at or now()
    variant["status"] = decision
    variant["review"] = {"decision": decision, "note": note, "reviewer": reviewer, "at": at}
    store.write_json(VARIANTS, data)
    Memory(store).append("review", at=at, variant_id=variant_id, decision=decision, note=note, reviewer=reviewer)
    return variant


def describe(variant: dict) -> str:
    failed = [f"{c['rule']}: {c['detail']}" for c in variant["guardrails"] if not c["passed"]]
    lines = [f"{variant['id']}  [{variant['status']}]  {variant['platform']} / {variant['segment']} / {variant['angle']}",
             f"  headline: {variant['headline']}", f"  text:     {variant['primary_text']}"]
    if variant["cta"]:
        lines.append(f"  button:   {variant['cta']}")
    if failed:
        lines.append("  guardrails failed: " + " | ".join(failed))
    if variant["review"]:
        lines.append(f"  review: {variant['review']['decision']} by {variant['review']['reviewer']}: {variant['review']['note']}")
    return "\n".join(lines)


def interactive(store: Storage, input_fn=input, print_fn=print, reviewer: str = "reviewer") -> int:
    """Walk through pending variants and ask for a decision on each. Returns how many were decided."""
    decided = 0
    for variant in [v for v in load_variants(store) if v["status"] == "pending"]:
        print_fn(describe(variant))
        answer = input_fn("approve (a), reject (r), skip (s), quit (q)? ").strip().lower()
        if answer == "q":
            break
        if answer in ("a", "r"):
            note = input_fn("note: ").strip()
            decide(store, variant["id"], "approved" if answer == "a" else "rejected", note, reviewer)
            decided += 1
    return decided
