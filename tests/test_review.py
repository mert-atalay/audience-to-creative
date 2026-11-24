import pytest

from pipeline import review
from pipeline.__main__ import main
from pipeline.memory import Memory


def by_status(store, status):
    return [v for v in review.load_variants(store) if v["status"] == status]


def test_everything_starts_pending_or_guardrail_rejected(store):
    statuses = {v["status"] for v in review.load_variants(store)}
    assert statuses == {"pending", "rejected_by_guardrails"}
    assert "pending" in store.read_text("gallery.html")


def test_approve_and_reject_with_notes(store):
    first, second = by_status(store, "pending")[:2]
    review.decide(store, first["id"], "approved", "looks right", reviewer="sam", at="2026-10-01T10:00:00Z")
    review.decide(store, second["id"], "rejected", "off brand", reviewer="sam")
    saved = {v["id"]: v for v in review.load_variants(store)}
    assert saved[first["id"]]["status"] == "approved"
    assert saved[first["id"]]["review"] == {"decision": "approved", "note": "looks right", "reviewer": "sam", "at": "2026-10-01T10:00:00Z"}
    assert saved[second["id"]]["status"] == "rejected" and saved[second["id"]]["review"]["note"] == "off brand"
    events = Memory(store).events("review")
    assert [(e["variant_id"], e["decision"]) for e in events] == [(first["id"], "approved"), (second["id"], "rejected")]


def test_review_refuses_bad_requests(store):
    blocked = by_status(store, "rejected_by_guardrails")[0]
    with pytest.raises(review.ReviewError, match="failed guardrails"):
        review.decide(store, blocked["id"], "approved")
    with pytest.raises(review.ReviewError, match="No variant"):
        review.decide(store, "does-not-exist", "approved")
    with pytest.raises(review.ReviewError):
        review.decide(store, by_status(store, "pending")[0]["id"], "published")


def test_interactive_review(store):
    pending = by_status(store, "pending")
    answers = iter(["a", "good", "r", "too vague", "s", "q"])
    shown = []
    decided = review.interactive(store, input_fn=lambda prompt: next(answers), print_fn=shown.append)
    saved = {v["id"]: v["status"] for v in review.load_variants(store)}
    assert decided == 2 and len(shown) == 4
    assert [saved[v["id"]] for v in pending[:4]] == ["approved", "rejected", "pending", "pending"]


def test_review_cli(store, name, capsys):
    out = str(store.root.parent)
    target = by_status(store, "pending")[0]["id"]
    assert main(["review", "--profile", name, "--out", out, "--list"]) == 0
    assert target in capsys.readouterr().out
    assert main(["review", "--profile", name, "--out", out, "--approve", target, "--note", "ship it"]) == 0
    assert "[approved]" in capsys.readouterr().out
    assert "ship it" in store.read_text("gallery.html")
    assert main(["review", "--profile", name, "--out", out, "--approve", "nope"]) == 2
