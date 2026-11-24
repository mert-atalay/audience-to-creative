import re
from pathlib import Path

from pipeline.__main__ import main
from pipeline.config import PROFILES, ROOT

from conftest import read

EXAMPLES = ROOT / "examples"


def files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()}


def test_demo_writes_every_output(demo_dir, name):
    for key in ("sources.json", "audience.json", "briefs.json", "variants.json", "gallery.html", "memory.jsonl"):
        assert (demo_dir / name / key).stat().st_size > 0
    briefs, variants = read(demo_dir, name, "briefs.json"), read(demo_dir, name, "variants.json")["variants"]
    assert briefs["run"] == 2 and len(briefs["briefs"]) == 4 and len(variants) == 8
    assert {v["status"] for v in variants} == {"pending", "rejected_by_guardrails"}  # nothing is auto-approved
    memory = (demo_dir / name / "memory.jsonl").read_text()
    assert memory.count('"type": "result"') >= 4 and '"reviewer": "demo-script"' in memory


def test_gallery_is_self_contained(demo_dir, name):
    html = (demo_dir / name / "gallery.html").read_text()
    for banned in ("<script", "<link", "<img", "<iframe", "@import", "url(", " src=", "href="):
        assert banned not in html, banned
    assert "prefers-color-scheme:dark" in html and 'name="viewport"' in html
    assert html.count("<svg") == sum(1 for v in read(demo_dir, name, "variants.json")["variants"] if v["svg"])
    assert "synthetic" in html and "rejected by guardrails" in html and "explore" in html
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", html)  # only the SVG namespace, which is not a request


def test_committed_examples_are_not_stale(demo_dir):
    """examples/ must equal a fresh demo run. Refresh with: uv run python -m pipeline demo --out examples"""
    fresh, committed = files(demo_dir), files(EXAMPLES)
    assert set(fresh) == set(committed)
    for key in fresh:
        assert fresh[key] == committed[key], f"examples/{key} is stale"


def test_run_command(tmp_path, capsys):
    for name in PROFILES:
        assert main(["run", "--profile", name, "--out", str(tmp_path), "--generator", "template"]) == 0
        assert (tmp_path / name / "gallery.html").exists()
    assert "pending review" in capsys.readouterr().out
