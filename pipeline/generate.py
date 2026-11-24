"""Stage 4: creative generation. Two generators behind one interface, then guardrails and visuals."""
from __future__ import annotations

import json
import os
import sys

from . import guardrails, svg

DEFAULT_MODEL = "claude-sonnet-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class GenerationError(RuntimeError):
    pass


class GeneratorUnavailable(RuntimeError):
    pass


def _with_disclaimers(copy: dict, profile: dict) -> dict:
    """Append any disclaimer the copy triggers to the primary text."""
    missing = [d for d in guardrails.required_disclaimers(copy, profile) if d.lower() not in copy["primary_text"].lower()]
    return {**copy, "primary_text": " ".join([copy["primary_text"], *missing])}


class TemplateGenerator:
    """Deterministic copy from the angle templates in the profile config. The default, used in tests and CI."""

    name = "template"

    def generate(self, brief: dict, spec: dict, profile: dict) -> list[dict]:
        template = profile["angles"][brief["angle"]]["copy"]
        phrase = brief["language"][0]["phrase"] if brief["language"] else ""
        cta = template["cta"] if spec.get("cta_options") else ""
        out = []
        for hook in brief["hooks"]:
            base = {"hook_type": hook, "headline": template["headlines"][hook], "cta": cta}
            options = [b.format(phrase=phrase) for b in template["body"] if phrase or "{phrase}" not in b]
            candidates = [_with_disclaimers({**base, "primary_text": text}, profile) for text in options]
            # Longest first in the config. Use the first body that fits the placement, else the shortest.
            fits = [c for c in candidates if len(c["primary_text"]) <= spec["limits"]["primary_text"]]
            out.append(fits[0] if fits else candidates[-1])
        return out


SCHEMA = {
    "type": "object",
    "properties": {"variants": {"type": "array", "items": {
        "type": "object",
        "properties": {k: {"type": "string"} for k in ("hook_type", "headline", "primary_text", "cta")},
        "required": ["hook_type", "headline", "primary_text", "cta"],
        "additionalProperties": False,
    }}},
    "required": ["variants"],
    "additionalProperties": False,
}


def build_prompt(brief: dict, spec: dict, profile: dict) -> str:
    rules = profile["guardrails"]
    lines = [
        f"Write ad copy for {profile['business']} ({profile['audience']}).",
        f"Placement: {spec['platform']}, {spec['placement']}.",
        f"Segment: {brief['segment_label']}. Angle: {brief['angle_label']}.",
        "Phrases this segment uses: " + (", ".join(f'"{p["phrase"]}"' for p in brief["language"]) or "none found"),
        f"Objection to answer: {brief['objection']['reason'].replace('_', ' ') if brief['objection'] else 'none recorded'}.",
        f"Write one variant for each hook type, in this order: {', '.join(brief['hooks'])}.",
        "Character limits: " + ", ".join(f"{k} max {v}" for k, v in spec["limits"].items()) + ".",
        ("cta must be exactly one of: " + ", ".join(spec["cta_options"]) + ".") if spec.get("cta_options") else 'This placement has no button. Set cta to "".',
        "Never use: " + ", ".join(b["name"] for b in rules["banned_claims"]) + ". No competitor names. No invented statistics.",
        *[f"If the copy matches /{d['trigger']}/, the primary text must include: {d['text']}" for d in rules["disclaimers"]],
        f"Write the brand exactly as \"{profile['brand']['spelling']['correct']}\" if you mention it.",
        "Plain language. Return JSON only.",
    ]
    return "\n".join(lines)


class LLMGenerator:
    """Copy written by Claude through the Anthropic API. Optional. Guardrails still run on its output."""

    name = "llm"

    def __init__(self, client, model: str = DEFAULT_MODEL, api_errors: tuple = (), use_fallback: bool = True):
        self.client, self.model, self.api_errors, self.use_fallback = client, model, api_errors, use_fallback

    @classmethod
    def from_env(cls) -> "LLMGenerator":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise GeneratorUnavailable("The LLM generator needs ANTHROPIC_API_KEY. It is not set.")
        try:
            import anthropic
        except ImportError as exc:
            raise GeneratorUnavailable("The LLM generator needs the anthropic package. Install it with: uv sync --extra llm") from exc
        # The SDK already retries rate limits, server errors and connection errors.
        # What still raises after that is treated as a failed generation for this brief.
        return cls(anthropic.Anthropic(), os.environ.get("PIPELINE_LLM_MODEL", DEFAULT_MODEL),
                   api_errors=(anthropic.APIError,), use_fallback=os.environ.get("PIPELINE_LLM_FALLBACK", "1") != "0")

    def generate(self, brief: dict, spec: dict, profile: dict) -> list[dict]:
        request = dict(
            model=self.model,
            max_tokens=16000,
            system="You write short, honest ad copy. You follow the limits and rules you are given exactly.",
            messages=[{"role": "user", "content": build_prompt(brief, spec, profile)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        try:
            if self.use_fallback:
                # If a safety classifier declines, the API reruns the request on its default fallback model.
                response = self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **request)
            else:
                response = self.client.messages.create(**request)
        except self.api_errors as exc:
            raise GenerationError(f"Anthropic API call failed: {exc}") from exc
        if response.stop_reason in ("refusal", "max_tokens"):
            raise GenerationError(f"Model stopped early: {response.stop_reason}")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            variants = json.loads(text)["variants"]
        except (ValueError, KeyError, TypeError) as exc:
            raise GenerationError("Model output was not the expected JSON") from exc
        if not variants:
            raise GenerationError("Model returned no variants")
        return [{k: str(v.get(k, "")).strip() for k in ("hook_type", "headline", "primary_text", "cta")} for v in variants]


def get_generator(name: str = "template", warn=lambda msg: print(msg, file=sys.stderr)):
    """Resolve a generator by name. 'llm' falls back to the template generator when it cannot run."""
    if name == "template":
        return TemplateGenerator()
    if name != "llm":
        raise ValueError("generator must be 'template' or 'llm'")
    try:
        return LLMGenerator.from_env()
    except GeneratorUnavailable as exc:
        warn(f"warning: {exc} Using the template generator instead.")
        return TemplateGenerator()


def make_variants(briefs: list[dict], generator, profile: dict, competitors: list[str], rejected_before: dict | None = None,
                  warn=lambda msg: print(msg, file=sys.stderr)) -> tuple[list[dict], dict[str, str]]:
    """Copy variants for each brief, checked by guardrails, with one SVG each where the placement has a visual.

    rejected_before maps (segment, angle, lowercased headline) to the note of a reviewer who rejected it in an earlier run.
    """
    rejected_before = rejected_before or {}
    variants, visuals = [], {}
    for brief in briefs:
        spec = profile["platforms"][brief["format"]]
        used = generator.name
        try:
            copies = generator.generate(brief, spec, profile)
        except GenerationError as exc:
            warn(f"warning: {exc} Using the template generator for brief {brief['id']}.")
            copies, used = TemplateGenerator().generate(brief, spec, profile), "template"
        for n, copy in enumerate(copies, 1):
            vid = f"{brief['id']}-v{n}"
            checks = guardrails.check(copy, spec, profile, competitors)
            note = rejected_before.get((brief["segment"], brief["angle"], copy["headline"].lower()))
            checks.append({"rule": "not_rejected_before", "passed": note is None,
                           "detail": "ok" if note is None else f"a reviewer rejected this headline for this segment before: {note}"})
            disclaimers = guardrails.required_disclaimers(copy, profile)
            svg_key = None
            if spec.get("visual"):
                try:
                    visuals[f"creatives/{vid}.svg"] = svg.render(copy, profile, spec, disclaimers, title=f"{vid}: {copy['headline']}",
                                                                 scene=svg.scene_for(profile["id"], brief["angle"]))
                    svg_key = f"creatives/{vid}.svg"
                    checks.append({"rule": "visual_fit", "passed": True, "detail": "ok"})
                except svg.FitError as exc:
                    checks.append({"rule": "visual_fit", "passed": False, "detail": str(exc)})
            passed = all(c["passed"] for c in checks)
            variants.append({
                "id": vid, "brief_id": brief["id"], "run": brief["run"], "segment": brief["segment"], "angle": brief["angle"],
                "format": brief["format"], "platform": spec["platform"], "placement": spec["placement"], "generator": used,
                **copy, "disclaimers": disclaimers, "guardrails": checks,
                # Nothing is published. A person approves or rejects pending variants in the review step.
                "status": "pending" if passed else "rejected_by_guardrails",
                "review": None, "svg": svg_key,
            })
    return variants, visuals
