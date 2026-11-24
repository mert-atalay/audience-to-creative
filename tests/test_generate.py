import json
from types import SimpleNamespace

import pytest

from pipeline.audience import build_audience
from pipeline.generate import (DEFAULT_MODEL, GenerationError, GeneratorUnavailable, LLMGenerator, TemplateGenerator,
                               build_prompt, get_generator, make_variants)
from pipeline.recommend import recommend


@pytest.fixture
def briefs(profile, sources):
    return recommend(build_audience(sources, profile), sources, [], profile, run=1)["briefs"]


class FakeClient:
    """Stands in for anthropic.Anthropic(). Records the request and returns a canned response."""

    def __init__(self, text=None, stop_reason="end_turn", error=None):
        self.text, self.stop_reason, self.error, self.calls = text, stop_reason, error, []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="thinking", thinking=""),
                                                                      SimpleNamespace(type="text", text=self.text)])


def llm_reply(brief, spec):
    cta = spec["cta_options"][0] if spec["cta_options"] else ""
    return json.dumps({"variants": [{"hook_type": h, "headline": f"Fake {h} line", "primary_text": "Fake body text.", "cta": cta}
                                    for h in brief["hooks"]]})


def test_template_generator_is_deterministic_and_within_limits(profile, briefs):
    gen = TemplateGenerator()
    for brief in briefs:
        spec = profile["platforms"][brief["format"]]
        first = gen.generate(brief, spec, profile)
        assert first == gen.generate(brief, spec, profile)
        assert [c["hook_type"] for c in first] == brief["hooks"]
        for copy in first:
            assert len(copy["headline"]) <= spec["limits"]["headline"]
            assert len(copy["primary_text"]) <= spec["limits"]["primary_text"]
    feed_like = next(b for b in briefs if profile["platforms"][b["format"]]["visual"])
    copy = gen.generate(feed_like, profile["platforms"][feed_like["format"]], profile)[0]
    assert feed_like["language"][0]["phrase"] in copy["primary_text"]  # customer wording is used


def test_variants_start_pending_and_guardrails_always_run(profile, briefs):
    variants, visuals = make_variants(briefs, TemplateGenerator(), profile, profile["competitors"])
    assert len(variants) == 2 * len(briefs) and len({v["id"] for v in variants}) == len(variants)
    assert {v["status"] for v in variants} == {"pending", "rejected_by_guardrails"}
    for v in variants:
        assert len(v["guardrails"]) >= 7 and v["review"] is None
        assert (v["status"] == "pending") == all(c["passed"] for c in v["guardrails"])
        if profile["platforms"][v["format"]]["visual"]:
            assert v["svg"] in visuals
        else:
            assert v["svg"] is None


def test_llm_generator_with_fake_client(profile, briefs):
    brief = briefs[0]
    spec = profile["platforms"][brief["format"]]
    client = FakeClient(llm_reply(brief, spec))
    gen = LLMGenerator(client)
    copies = gen.generate(brief, spec, profile)
    assert [c["headline"] for c in copies] == [f"Fake {h} line" for h in brief["hooks"]]
    call = client.calls[0]
    assert call["model"] == DEFAULT_MODEL == "claude-sonnet-5-5"
    assert call["output_config"]["format"]["type"] == "json_schema" and call["fallbacks"] == "default"
    assert "thinking" not in call and "temperature" not in call
    prompt = call["messages"][0]["content"]
    assert brief["segment_label"] in prompt and str(spec["limits"]["headline"]) in prompt and prompt == build_prompt(brief, spec, profile)
    variants, _ = make_variants([brief], gen, profile, profile["competitors"])
    assert {v["generator"] for v in variants} == {"llm"} and all(v["guardrails"] for v in variants)
    LLMGenerator(plain := FakeClient(llm_reply(brief, spec)), use_fallback=False).generate(brief, spec, profile)
    assert "betas" not in plain.calls[0]


def test_llm_output_still_goes_through_guardrails(profile, briefs):
    brief = briefs[0]
    spec = profile["platforms"][brief["format"]]
    bad = json.dumps({"variants": [{"hook_type": "proof", "headline": "Results guaranteed", "primary_text": "Body.", "cta": ""}]})
    variants, _ = make_variants([brief], LLMGenerator(FakeClient(bad)), profile, profile["competitors"])
    assert variants[0]["status"] == "rejected_by_guardrails"


@pytest.mark.parametrize("client", [
    FakeClient("not json"),
    FakeClient('{"variants": []}'),
    FakeClient("{}", stop_reason="refusal"),
    FakeClient(error=ConnectionError("network down")),
])
def test_llm_failures_fall_back_to_the_template(profile, briefs, client):
    brief = briefs[0]
    gen = LLMGenerator(client, api_errors=(ConnectionError,))
    with pytest.raises(GenerationError):
        gen.generate(brief, profile["platforms"][brief["format"]], profile)
    warnings = []
    variants, _ = make_variants([brief], gen, profile, profile["competitors"], warn=warnings.append)
    assert {v["generator"] for v in variants} == {"template"} and len(warnings) == 1


def test_llm_generator_without_a_key_fails_gracefully(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(GeneratorUnavailable, match="ANTHROPIC_API_KEY"):
        LLMGenerator.from_env()
    warnings = []
    gen = get_generator("llm", warn=warnings.append)
    assert isinstance(gen, TemplateGenerator) and "template generator" in warnings[0]
    with pytest.raises(ValueError):
        get_generator("other")
