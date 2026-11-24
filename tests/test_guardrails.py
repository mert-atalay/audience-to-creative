import pytest

from pipeline.config import load_profile
from pipeline.guardrails import check, required_disclaimers

PROFILE = load_profile("b2c")
FEED, SEARCH = PROFILE["platforms"]["feed_image"], PROFILE["platforms"]["search_text"]
GOOD = {"headline": "Open 24/7 at every location", "primary_text": "Train when it suits you at Harbour Fitness.", "cta": "Learn More"}
COMPETITORS = PROFILE["competitors"]


def failed(copy, spec=FEED):
    return {c["rule"]: c["detail"] for c in check(copy, spec, PROFILE, COMPETITORS) if not c["passed"]}


def test_good_copy_passes_every_rule():
    results = check(GOOD, FEED, PROFILE, COMPETITORS)
    assert {c["rule"] for c in results} == {"length", "cta_allowed", "banned_claims", "disclaimer", "brand_spelling", "competitor_names"}
    assert all(c["passed"] for c in results)


@pytest.mark.parametrize("change, rule", [
    ({"headline": "x" * 41}, "length"),
    ({"primary_text": "y" * 126}, "length"),
    ({"headline": " "}, "length"),
    ({"cta": "Join the club"}, "cta_allowed"),
    ({"headline": "Results guaranteed"}, "banned_claims"),
    ({"primary_text": "Lose 10 kg before summer."}, "banned_claims"),
    ({"primary_text": "Our classes cure back pain."}, "banned_claims"),
    ({"headline": "The best gym in town"}, "banned_claims"),
    ({"primary_text": "Start with a free induction."}, "disclaimer"),
    ({"primary_text": "Train at Harbor Fitness today."}, "brand_spelling"),
    ({"primary_text": "Train at harbour fitness today."}, "brand_spelling"),
    ({"primary_text": "Cheaper than Gullwing Gyms."}, "competitor_names"),
])
def test_each_rule_rejects(change, rule):
    assert list(failed({**GOOD, **change})) == [rule]


def test_disclaimer_passes_when_present_and_search_ads_have_no_button():
    copy = {**GOOD, "primary_text": "Start with a free induction. Terms apply."}
    assert required_disclaimers(copy, PROFILE) == ["Terms apply."] and not failed(copy)
    assert list(failed(GOOD, SEARCH)) == ["cta_allowed"]
    assert not failed({**GOOD, "cta": ""}, SEARCH)
    assert "length" in failed({**GOOD, "headline": "A headline that is over thirty chars", "cta": ""}, SEARCH)


def test_b2b_rules_differ():
    b2b = load_profile("b2b")
    spec = b2b["platforms"]["linkedin_image"]
    copy = {"headline": "Cuts staff turnover by 30%", "primary_text": "Try a pilot.", "cta": "Request Demo"}
    rules = {c["rule"] for c in check(copy, spec, b2b, b2b["competitors"]) if not c["passed"]}
    assert rules == {"banned_claims", "disclaimer"}
