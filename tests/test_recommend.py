import pytest

from pipeline.audience import build_audience
from pipeline.config import load_profile
from pipeline.recommend import MIN_IMPRESSIONS, PRIOR_LEADS, WEIGHTS, recommend, shrunk_lift
from pipeline.sources import load_sources


def test_shrinkage_pulls_small_samples_to_the_average():
    assert shrunk_lift(0, 0) == 1.0                      # no data: exactly average
    tiny = shrunk_lift(leads=4, expected=0.2)            # raw lift 20x on almost no data
    solid = shrunk_lift(leads=60, expected=40)           # raw lift 1.5x on a real sample
    assert tiny < solid < 1.5
    assert shrunk_lift(400, 200) == pytest.approx(2.0, abs=0.08)  # large samples keep their own rate
    assert PRIOR_LEADS > 0


def test_lucky_tiny_sample_does_not_win():
    """A creative with a few impressions and a huge raw rate must not outrank well-sampled ones."""
    profile, data = load_profile("b2c"), load_sources("b2c")
    lucky = data["ad_performance"][-1]
    key = lambda r: (r["segment"], r["angle"], r["format"])
    data["ad_performance"] = [r for r in data["ad_performance"] if key(r) != key(lucky)] + [lucky]
    ranking = recommend(build_audience(data, profile), data, [], profile, run=1)["ranking"]
    same_format = [r for r in ranking if r["format"] == lucky["format"] and r["impressions"]]
    raw = lambda r: r["leads"] / r["impressions"]
    lucky_row = next(r for r in same_format if key(r) == key(lucky))
    assert lucky_row["impressions"] < MIN_IMPRESSIONS and raw(lucky_row) == max(raw(r) for r in same_format)
    assert lucky_row["performance_points"] == 17.5  # exactly the average score: 0.5 x 35 points
    assert lucky_row["performance_points"] < max(r["performance_points"] for r in same_format)


def test_scores_and_briefs(profile, sources):
    out = recommend(build_audience(sources, profile), sources, [], profile, run=1, top_n=3)
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    briefs = out["briefs"]
    assert [b["rank"] for b in briefs] == [1, 2, 3, 4]
    for b in briefs:
        parts = b["score"]["parts"]
        assert set(parts) == set(WEIGHTS)
        assert b["score"]["total"] == pytest.approx(sum(p["points"] for p in parts.values()), abs=0.01)
        assert all(0 <= p["value"] <= 1 for p in parts.values())
        assert b["language"] and b["hooks"] and b["format"] in profile["formats"] and b["evidence"]
    exploit = [b for b in briefs if b["slot"] == "exploit"]
    assert [b["score"]["total"] for b in exploit] == sorted((b["score"]["total"] for b in exploit), reverse=True)
    assert len({b["angle"] for b in exploit}) == len(exploit)
    assert out["ranking"][0]["score"] == max(r["score"] for r in out["ranking"]) and len(out["ranking"]) == out["considered"]


def test_explore_slot_is_an_untried_angle_and_labelled(profile, sources):
    out = recommend(build_audience(sources, profile), sources, [], profile, run=1)
    explore = [b for b in out["briefs"] if b["slot"] == "explore"]
    assert len(explore) == 1
    brief = explore[0]
    assert brief["angle"] in out["untried_angles"] and brief["sample"]["impressions"] == 0
    assert "test" in brief["slot_note"].lower()
    assert all(b["angle"] not in out["untried_angles"] for b in out["briefs"] if b["slot"] == "exploit")
