"""Stage 1: sources. One interface, a fixture mode and a documented, unimplemented live mode."""
from __future__ import annotations

import json
from pathlib import Path

from .config import CONFIG, FIXTURES, load_yaml


class SourceUnavailable(RuntimeError):
    pass


class Source:
    """A source returns a list of flat records. Every record has a unique 'id'."""

    def __init__(self, name: str, cfg: dict):
        self.name, self.cfg = name, cfg

    def load(self) -> list[dict]:
        raise NotImplementedError


class FixtureSource(Source):
    def __init__(self, name, cfg, profile: str, directory: Path = FIXTURES):
        super().__init__(name, cfg)
        self.path = Path(directory) / profile / f"{name}.json"

    def load(self):
        return json.loads(self.path.read_text(encoding="utf-8"))


class LiveSource(Source):
    """Placeholder for a real connector. It only explains what it would need."""

    def load(self):
        live = self.cfg.get("live", {})
        raise SourceUnavailable(
            f"Live mode for source '{self.name}' is not implemented in this example. "
            f"Planned connector: {live.get('connector', 'not set')}, credentials in ${live.get('auth_env', '?')}. "
            f"{live.get('notes', '')} Use official APIs or exports and respect each site's terms. "
            "Set mode: fixture in config/sources.yaml to use the bundled synthetic data."
        )


def build_sources(profile: str, config_path: Path = CONFIG / "sources.yaml", directory: Path = FIXTURES) -> list[Source]:
    out = []
    for name, cfg in load_yaml(config_path)["sources"].items():
        if profile not in cfg.get("profiles", [profile]):
            continue
        mode = cfg.get("mode", "fixture")
        if mode == "fixture":
            out.append(FixtureSource(name, cfg, profile, directory))
        elif mode == "live":
            out.append(LiveSource(name, cfg))
        else:
            raise ValueError(f"Source '{name}': mode must be 'fixture' or 'live', got '{mode}'")
    return out


def enrich_companies(leads: list[dict], firmographics: list[dict]) -> list[dict]:
    """B2B enrichment: join company-level fields by company domain. People are never enriched."""
    by_domain = {f["domain"]: f for f in firmographics}
    fields = ("industry", "size_band", "region")
    out = []
    for lead in leads:
        firm = by_domain.get(lead.get("company_domain"), {})
        out.append({**lead, **{f: firm.get(f, "unknown") for f in fields}})
    return out


def load_sources(profile: str, config_path: Path = CONFIG / "sources.yaml", directory: Path = FIXTURES) -> dict[str, list[dict]]:
    data = {s.name: s.load() for s in build_sources(profile, config_path, directory)}
    if "firmographics" in data:
        data["crm"] = enrich_companies(data["crm"], data["firmographics"])
    return data


def dump_sources(data: dict[str, list[dict]]) -> str:
    """Snapshot of every record used in a run, one record per line, so evidence ids can be looked up."""
    blocks = []
    for name, records in data.items():
        rows = ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in records)
        blocks.append(f' "{name}": [\n{rows}\n ]')
    return "{\n" + ",\n".join(blocks) + "\n}\n"
