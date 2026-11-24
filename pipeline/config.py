"""Paths, config loading and a compact JSON writer shared by all stages."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
FIXTURES = ROOT / "data" / "fixtures"
PROFILES = ("b2c", "b2b")


def load_yaml(path: Path | str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_profile(name: str) -> dict:
    """Profile config (brand, segments, angles, guardrails) plus the platform specs it uses."""
    if name not in PROFILES:
        raise ValueError(f"Unknown profile '{name}'. Choose one of: {', '.join(PROFILES)}")
    profile = load_yaml(CONFIG / "profiles" / f"{name}.yaml")
    platforms = load_yaml(CONFIG / "platforms.yaml")
    profile["platforms"] = {fmt: platforms[fmt] for fmt in profile["formats"]}
    return profile


def dumps(obj) -> str:
    """Indented JSON with arrays and objects of plain values kept on one line (id lists stay readable)."""
    text = json.dumps(obj, indent=1, ensure_ascii=False)
    flat = lambda m: re.sub(r"\s*\n\s*", " ", m.group())
    text = re.sub(r"\[[^\[\]{}]*\]", flat, text)
    return re.sub(r"\{[^\[\]{}]*\}", flat, text) + "\n"
