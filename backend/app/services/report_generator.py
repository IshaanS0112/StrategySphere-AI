"""Executive strategy report: structured context -> constrained LLM narrative.

The ordering is the whole point of the module.

1. ``build_structured_context`` assembles every figure the report will contain
   from work the deterministic engines already did — the SWOT grid, the
   GE-McKinsey placement, the pricing recommendation. Nothing in it is inferred
   by a language model.
2. ``generate_narrative`` hands that context to the model under a JSON-only
   contract with an explicit instruction not to introduce facts, not to
   recompute, and not to contradict the quadrant verdict.
3. ``_validate_narrative`` discards any cited factor name that does not appear
   verbatim in the context's SWOT grid. A hallucinated citation is dropped
   rather than surfaced, and the drop is counted in the response.
4. If the call fails, times out, returns unparseable output, or no API key is
   configured, ``_fallback_narrative`` produces the same report from a template.
   Every number is identical; only the prose is missing.

So the answer to "does your AI decide the strategy?" is no — it writes it up.
The SWOT scoring, the matrix, and the pricing formula decide it. Every figure in
a generated report exists in ``structured_context``, which is stored beside the
narrative and returned by the API, so the claim is checkable rather than
asserted.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import Settings
from app.enums import NarrativeSource
from app.services.attractiveness_matrix import AttractivenessResult
from app.services.pricing_engine import PricingResult
from app.services.swot_engine import SwotResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a strategy analyst writing an executive summary.

You will receive a structured strategic context containing a scored SWOT grid, a
GE-McKinsey market attractiveness placement, and a pricing recommendation. All
of it has ALREADY been computed by deterministic analytical code.

Your job is to narrate that context, not to recompute or second-guess it.

Rules:
- Cite specific numbers from the context. Do not round beyond one decimal.
- In key_factors you may only name factors that appear verbatim in the
  swot_summary lists. Do not invent, merge, or rename factors.
- Do not contradict the quadrant verdict or the recommended price.
- If the context marks the quadrant placement as borderline, say so explicitly.
- If the context marks the pricing confidence as LOW, say so explicitly.
- Do not invent market events, competitor names, dates, or any figure not
  present in the context. If the context does not support a claim, omit it.
- Write for an executive audience: plain language, no hedging filler.

Respond with JSON only. No preamble, no code fences. Schema:
{
  "executive_summary": "<4-6 sentences citing concrete scores>",
  "strategic_position": "<what the GE-McKinsey quadrant means for this company>",
  "key_factors": [
    {"factor": "<exact factor name from swot_summary>", "implication": "<so what>"}
  ],
  "pricing_rationale": "<why the recommended price follows from the inputs>",
  "recommendation": "<one concrete, actionable strategic recommendation>"
}"""


def build_structured_context(
    *,
    company_id: str,
    company_name: str,
    industry: str | None,
    data_source: str | None,
    swot: SwotResult,
    attractiveness: AttractivenessResult,
    pricing: PricingResult | None,
) -> dict[str, Any]:
    """Freeze every computed signal into the payload the LLM is allowed to use."""
    context: dict[str, Any] = {
        "company_id": company_id,
        "company_name": company_name,
        "industry": industry or "unspecified",
        "data_source": data_source or "unspecified",
        "swot_summary": {
            "strengths": [f.to_dict() for f in swot.strengths],
            "weaknesses": [f.to_dict() for f in swot.weaknesses],
            "opportunities": [f.to_dict() for f in swot.opportunities],
            "threats": [f.to_dict() for f in swot.threats],
            "factor_counts": swot.calculation_basis.get("factor_counts", {}),
            "benchmark_provenance": swot.calculation_basis.get("benchmark_provenance"),
        },
        "market_position": {
            "framework": "GE-McKinsey market attractiveness matrix",
            "market_attractiveness_score": attractiveness.overall_attractiveness_score,
            "competitive_strength_score": attractiveness.competitive_strength_score,
            "quadrant": attractiveness.quadrant.value,
            "borderline": attractiveness.borderline,
            "axis_scores": {
                "market_growth": attractiveness.market_growth_score,
                "market_size": attractiveness.market_size_score,
                "industry_profitability": attractiveness.profitability_score,
                "competitive_intensity": attractiveness.competitive_intensity_score,
            },
            "weights": attractiveness.calculation_basis.get("weights", {}),
            "imputed_axes": attractiveness.calculation_basis.get("imputed_axes", []),
        },
        "pricing": None,
        "calculation_basis": {
            "swot": swot.calculation_basis,
            "attractiveness": attractiveness.calculation_basis,
            "pricing": pricing.calculation_basis if pricing else None,
        },
    }

    if pricing is not None:
        context["pricing"] = {
            "cost_base": pricing.cost_base,
            "target_margin_pct": pricing.target_margin_pct,
            "margin_basis": pricing.margin_basis.value,
            "cost_plus_price": pricing.cost_plus_price,
            "competitor_avg_price": pricing.competitor_avg_price,
            "value_adjustment_factor": pricing.value_adjustment_factor,
            "recommended_price": pricing.recommended_price,
            "recommended_price_range": pricing.recommended_price_range,
            "implied_margin_pct": pricing.implied_margin_pct,
            "confidence": pricing.confidence,
            "warnings": pricing.reasoning.get("warnings", []),
        }

    return context


def _valid_factor_names(context: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for bucket in context["swot_summary"].values():
        if isinstance(bucket, list):
            for factor in bucket:
                if isinstance(factor, dict) and "factor" in factor:
                    names.add(str(factor["factor"]))
    return names


def _top_factors(context: dict[str, Any], bucket: str, limit: int = 2) -> list[dict[str, Any]]:
    return list(context["swot_summary"].get(bucket, []))[:limit]


def _fallback_narrative(context: dict[str, Any], reason: str) -> dict[str, Any]:
    """Template report built from the same numbers, no model involved."""
    position = context["market_position"]
    strengths = _top_factors(context, "strengths")
    weaknesses = _top_factors(context, "weaknesses")
    threats = _top_factors(context, "threats")
    pricing = context.get("pricing")

    borderline_clause = (
        " The placement is borderline: the position sits close to a quadrant boundary, "
        "so treat the verdict as provisional."
        if position["borderline"]
        else ""
    )

    summary = (
        f"{context['company_name']} scores {position['market_attractiveness_score']} on market "
        f"attractiveness and {position['competitive_strength_score']} on competitive strength, "
        f"placing it in the {position['quadrant']} quadrant of the GE-McKinsey matrix."
        f"{borderline_clause} The SWOT grid contains "
        f"{context['swot_summary']['factor_counts'].get('strengths', 0)} scored strengths and "
        f"{context['swot_summary']['factor_counts'].get('weaknesses', 0)} scored weaknesses."
    )
    if pricing:
        summary += (
            f" Recommended price is {pricing['recommended_price']} "
            f"(range {pricing['recommended_price_range']['min']}-"
            f"{pricing['recommended_price_range']['max']}), an implied margin of "
            f"{pricing['implied_margin_pct']}% at confidence {pricing['confidence']}."
        )

    key_factors = [
        {"factor": f["factor"], "implication": f["evidence"]}
        for f in (strengths + weaknesses + threats)
    ]

    return {
        "executive_summary": summary,
        "strategic_position": _fallback_position(position),
        "key_factors": key_factors,
        "pricing_rationale": (
            " ".join(pricing["warnings"]) or "No pricing warnings were raised."
            if pricing
            else "No pricing recommendation has been computed for this company."
        ),
        "recommendation": _fallback_recommendation(position, pricing),
        "generated_by": NarrativeSource.TEMPLATE_FALLBACK.value,
        "fallback_reason": reason,
    }


def _fallback_position(position: dict[str, Any]) -> str:
    quadrant = position["quadrant"]
    if quadrant == "INVEST_GROW":
        return (
            "An attractive market the company is well positioned to compete in. The "
            "GE-McKinsey reading is to fund growth and defend share."
        )
    if quadrant == "HARVEST_DIVEST":
        return (
            "A weak position in an unattractive market. The GE-McKinsey reading is to "
            "harvest cash rather than reinvest, and to evaluate exit."
        )
    return (
        "One axis is strong and the other is not. The GE-McKinsey reading is selective "
        "investment: fund only where the company already has an advantage."
    )


def _fallback_recommendation(position: dict[str, Any], pricing: dict[str, Any] | None) -> str:
    if position["borderline"]:
        return (
            "Before committing capital, tighten the inputs closest to the quadrant "
            "boundary - the current placement flips on a small revision to any single axis."
        )
    if position["quadrant"] == "INVEST_GROW":
        base = "Fund growth in this market and defend the scored strengths."
    elif position["quadrant"] == "HARVEST_DIVEST":
        base = "Do not add capital; harvest cash and prepare an exit assessment."
    else:
        base = "Invest selectively, only where a scored strength already exists."
    if pricing and pricing["confidence"] == "LOW":
        base += (
            " Treat the price recommendation as indicative only - its confidence is LOW; "
            "widen the competitor set before acting on it."
        )
    return base


def _validate_narrative(raw: str, context: dict[str, Any]) -> dict[str, Any]:
    """Parse the model output and strip anything not backed by the context."""
    text = raw.strip()
    if text.startswith("```"):
        # Defensive: the contract says no code fences, models sometimes add them.
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Model returned JSON that is not an object")
    for key in ("executive_summary", "strategic_position", "key_factors", "recommendation"):
        if key not in parsed:
            raise ValueError(f"Model response missing required key: {key}")

    allowed = _valid_factor_names(context)
    verified: list[dict[str, str]] = []
    dropped: list[Any] = []
    for item in parsed.get("key_factors") or []:
        if not isinstance(item, dict):
            dropped.append(item)
            continue
        name = str(item.get("factor", "")).strip()
        if name in allowed:
            verified.append({"factor": name, "implication": str(item.get("implication", ""))})
        else:
            dropped.append(item)

    if dropped:
        logger.warning(
            "Dropped %d factor citation(s) not present in the structured context: %s",
            len(dropped),
            dropped,
        )

    return {
        "executive_summary": str(parsed["executive_summary"]),
        "strategic_position": str(parsed["strategic_position"]),
        "key_factors": verified,
        "pricing_rationale": str(parsed.get("pricing_rationale", "")),
        "recommendation": str(parsed["recommendation"]),
        "generated_by": NarrativeSource.LLM.value,
        "dropped_citations": len(dropped),
    }


def generate_narrative(context: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Narrate the context via the LLM, or return the template fallback on any failure."""
    if not settings.anthropic_api_key:
        return _fallback_narrative(context, "no ANTHROPIC_API_KEY configured")

    try:
        from anthropic import Anthropic

        client = Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds
        )
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.llm_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": json.dumps(context, indent=2, default=str)},
                # Prefilling the opening brace makes the JSON-only contract
                # mechanical rather than a request the model may preamble past.
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + response.content[0].text
        return _validate_narrative(raw, context)

    except json.JSONDecodeError as exc:
        logger.warning("LLM returned unparseable JSON, falling back: %s", exc)
        return _fallback_narrative(context, f"unparseable model output: {exc}")
    except Exception as exc:  # noqa: BLE001 - the report must degrade, never 500
        logger.warning("LLM narrative generation failed, falling back: %s", exc)
        return _fallback_narrative(context, f"{type(exc).__name__}: {exc}")
