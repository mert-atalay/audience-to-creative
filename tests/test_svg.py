import xml.etree.ElementTree as ET

import pytest

from pipeline import svg
from pipeline.config import load_profile
from pipeline.generate import TemplateGenerator, make_variants

from conftest import read

NS = "{http://www.w3.org/2000/svg}"


def assert_text_fits(markup: str):
    """Parse the SVG and check that no text element can leave the canvas, using the same width estimate."""
    root = ET.fromstring(markup)
    _, _, width, height = (float(x) for x in root.get("viewBox").split())
    texts = root.findall(f"{NS}text")
    assert texts
    for t in texts:
        size, x, y = float(t.get("font-size")), float(t.get("x")), float(t.get("y"))
        w = svg.text_width(t.text, size, bold=t.get("font-weight") == "700")
        left, right = (x - w / 2, x + w / 2) if t.get("text-anchor") == "middle" else (x, x + w)
        assert left >= 0 and right <= width, t.text
        assert y - size >= 0 and y <= height, t.text
    return root


def test_wrap_keeps_every_line_inside_the_box():
    lines = svg.wrap("Never been to a gym before? Start with a free induction", 80, 900, bold=True)
    assert len(lines) > 1 and all(svg.text_width(line, 80, True) <= 900 for line in lines)
    assert " ".join(lines) == "Never been to a gym before? Start with a free induction"
    with pytest.raises(svg.FitError):
        svg.wrap("Supercalifragilisticexpialidocious", 120, 300)


def test_font_size_shrinks_until_text_fits():
    big, _ = svg.fit_text("Short one", 900, 400, 104, 60, 4)
    small, lines = svg.fit_text("A much longer headline that needs more room to fit", 900, 400, 104, 60, 4)
    assert big == 104 and small < big and len(lines) <= 4
    with pytest.raises(svg.FitError):
        svg.fit_text("word " * 40, 900, 400, 104, 60, 4)


@pytest.mark.parametrize("name", ["b2c", "b2b"])
def test_every_template_headline_fits_every_visual_placement(name):
    profile = load_profile(name)
    for fmt, spec in profile["platforms"].items():
        if not spec["visual"]:
            continue
        for angle in profile["angles"].values():
            for headline in angle["copy"]["headlines"].values():
                copy = {"headline": headline, "cta": angle["copy"]["cta"]}
                root = assert_text_fits(svg.render(copy, profile, spec, ["Terms apply."]))
                assert root.get("viewBox") == f"0 0 {spec['visual']['width']} {spec['visual']['height']}"


def test_demo_visuals_are_valid_and_fit(demo_dir, name):
    variants = read(demo_dir, name, "variants.json")["variants"]
    with_visual = [v for v in variants if v["svg"]]
    assert with_visual
    for v in with_visual:
        markup = (demo_dir / name / v["svg"]).read_text()
        assert_text_fits(markup)
        assert "<image" not in markup and "href" not in markup


def test_overflowing_text_is_rejected_not_drawn():
    profile = load_profile("b2c")
    brief = {"id": "t-r1-b1", "run": 1, "segment": "students", "angle": "classes", "format": "feed_image", "language": [], "hooks": ["direct"]}

    class LongHeadline(TemplateGenerator):
        def generate(self, brief, spec, profile):
            return [{"hook_type": "direct", "headline": "Extraordinarilylongunbreakableheadlinewordthatcannotwrap", "primary_text": "ok", "cta": "Sign Up"}]

    variants, visuals = make_variants([brief], LongHeadline(), profile, [])
    checks = {c["rule"]: c["passed"] for c in variants[0]["guardrails"]}
    assert checks["visual_fit"] is False and not visuals
    assert variants[0]["status"] == "rejected_by_guardrails" and variants[0]["svg"] is None
