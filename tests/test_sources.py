import json

import pytest

from pipeline import fixtures
from pipeline.config import CONFIG, FIXTURES, load_yaml
from pipeline.sources import SourceUnavailable, enrich_companies, load_sources

PERSONAL = {"name", "first_name", "last_name", "email", "phone", "address", "date_of_birth"}


def test_generator_is_deterministic(name):
    assert fixtures.generate(name) == fixtures.generate(name)


def test_bundled_fixtures_match_the_generator(name):
    for source, records in fixtures.generate(name).items():
        assert json.loads((FIXTURES / name / f"{source}.json").read_text()) == records, source


def test_fixture_mode_loads_every_source_with_unique_ids(name, sources):
    expected = {"crm", "ad_performance", "site_search", "chat", "survey", "competitor_ads", "reviews", "search_demand"}
    assert expected <= set(sources)
    assert ("firmographics" in sources) == (name == "b2b")
    for source, records in sources.items():
        ids = [r["id"] for r in records]
        assert records and len(ids) == len(set(ids)), source


def test_no_personal_fields_anywhere(sources):
    for source, records in sources.items():
        assert not PERSONAL & {key for r in records for key in r}, source


def test_b2b_leads_are_enriched_by_company_domain_only():
    crm = load_sources("b2b")["crm"]
    assert all(r["industry"] != "unknown" and r["size_band"] and r["region"] for r in crm)
    assert enrich_companies([{"id": "x", "company_domain": "nowhere.example"}], [])[0]["industry"] == "unknown"


def test_live_mode_is_documented_but_not_implemented(tmp_path):
    cfg = load_yaml(CONFIG / "sources.yaml")
    assert all({"connector", "auth_env", "notes"} <= set(s["live"]) for s in cfg["sources"].values())
    cfg["sources"]["competitor_ads"]["mode"] = "live"
    path = tmp_path / "sources.yaml"
    path.write_text(json.dumps(cfg))  # JSON is valid YAML
    with pytest.raises(SourceUnavailable, match="official APIs or exports"):
        load_sources("b2c", config_path=path)
    cfg["sources"]["competitor_ads"]["mode"] = "scrape"
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError):
        load_sources("b2c", config_path=path)
