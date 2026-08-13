"""GE-McKinsey market attractiveness matrix.

The GE-McKinsey (or GE/McKinsey nine-box) matrix is a real strategic planning
framework, developed by McKinsey for General Electric in the early 1970s to
allocate capital across GE's business units. It plots each unit on two axes —
**industry attractiveness** and **business unit competitive strength** — and
reads an investment verdict off the position.

This module implements it. The two axes are computed, not asserted:

    market_attractiveness = w1·growth + w2·size + w3·profitability
                          + w4·(6 − competitive_intensity)

``(6 − intensity)`` inverts intensity onto the same 1-5 axis as the other three
terms without flipping the sign of the weight, so all four weights stay
positive and comparable. Weights sum to 1.0 (enforced in ``Settings``), which is
what keeps the output on the 1-5 scale the thresholds assume.

    competitive_strength = mean(strength impacts) − penalty·(mean(weakness impacts) − 3)

The spec for this project defines competitive strength as the mean of SWOT
strength impact scores alone. That formula has a real defect: a company with one
outstanding margin and four structural weaknesses scores as strong, because
nothing in the formula can see the weaknesses. The penalty term fixes it, and is
centred on 3.0 so a company with *average* weaknesses is unaffected. Setting
``swot_weakness_penalty = 0`` reproduces the original formula exactly, and a
test pins that equivalence.

Quadrant placement uses the documented thresholds, plus a ``borderline`` flag
when the point sits within ``quadrant_borderline_margin`` of a boundary. A
score of 3.51 is not meaningfully different from 3.49, and reporting the first
as a confident INVEST_GROW is how a model gets a strategy committee to make a
decision the arithmetic does not support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from app.config import Settings
from app.enums import Quadrant
from app.services.swot_engine import SwotResult, band_score

# Profitability of the market as a whole (not the firm), on the 1-5 axis.
# Band edges in percentage points of industry operating margin.
INDUSTRY_PROFITABILITY_BANDS = (4.0, 8.0, 15.0, 25.0)
MARKET_GROWTH_BANDS = (3.0, 6.0, 10.0, 15.0)
MARKET_SIZE_BANDS = (1.0, 5.0, 20.0, 75.0)

NEUTRAL_SCORE = 3.0


@dataclass
class AttractivenessResult:
    market_growth_score: float
    market_size_score: float
    profitability_score: float
    competitive_intensity_score: float
    overall_attractiveness_score: float
    competitive_strength_score: float
    quadrant: Quadrant
    borderline: bool
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def _axis_score(
    raw: Any, bands: tuple[float, ...], label: str, trace: dict[str, Any]
) -> float:
    """Band-score a market input, falling back to neutral when absent."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        score = float(band_score(float(raw), bands))
        trace[label] = {"raw": float(raw), "score": score, "bands": list(bands), "imputed": False}
        return score
    trace[label] = {
        "raw": None,
        "score": NEUTRAL_SCORE,
        "bands": list(bands),
        "imputed": True,
        "note": f"{label} not supplied; imputed neutral {NEUTRAL_SCORE}",
    }
    return NEUTRAL_SCORE


def compute_competitive_strength(
    swot: SwotResult, settings: Settings
) -> tuple[float, dict[str, Any]]:
    """Net competitive strength on the 1-5 axis, with its derivation.

    The empty-strengths case needs care, and getting it wrong was a real bug
    caught by the end-to-end smoke run. There are two different situations
    that both produce ``strengths == []`` and they must not be treated alike:

    * **Nothing was evaluated.** No financial metrics cleared a benchmark
      because none were supplied. That is an absence of evidence, and the
      honest base is neutral 3.0 with a loud warning.
    * **Everything was evaluated and none of it was a strength.** The engine
      scored nine weaknesses and zero strengths. That is not missing evidence,
      it is evidence — of a company that is behind its peers on every axis it
      reported. Defaulting that to 3.0 handed a failing manufacturer a
      competitive-strength score of 2.56 and a SELECTIVE_INVEST verdict when
      the correct read was HARVEST_DIVEST.

    So the base falls to the floor of the axis when weaknesses exist and
    strengths do not.
    """
    strength_scores = [f.impact_score for f in swot.strengths]
    weakness_scores = [f.impact_score for f in swot.weaknesses]

    if strength_scores:
        raw_strength = float(mean(strength_scores))
        base_reason = "mean of scored strength impacts"
    elif weakness_scores:
        raw_strength = 1.0
        base_reason = (
            "no strengths scored while weaknesses were - the company was evaluated and "
            "came out behind on every axis, so the base sits at the floor of the scale"
        )
    else:
        raw_strength = NEUTRAL_SCORE
        base_reason = "nothing was scored at all - neutral base, absence of evidence"

    raw_weakness = float(mean(weakness_scores)) if weakness_scores else settings.swot_neutral_impact

    penalty = settings.swot_weakness_penalty * (raw_weakness - settings.swot_neutral_impact)
    score = max(1.0, min(5.0, raw_strength - penalty))

    basis = {
        "formula": (
            "competitive_strength = base - swot_weakness_penalty * "
            "(mean(weakness_impacts) - swot_neutral_impact), clamped to [1, 5]"
        ),
        "base_value": round(raw_strength, 4),
        "base_reason": base_reason,
        "spec_deviation": (
            "The project spec defines this as mean(strength_impacts) alone. The "
            "penalty term is a deliberate correction so that weaknesses can move "
            "the axis; set swot_weakness_penalty=0 to recover the spec formula "
            "whenever at least one strength was scored."
        ),
        "mean_strength_impact": round(float(mean(strength_scores)), 4)
        if strength_scores
        else None,
        "mean_weakness_impact": round(raw_weakness, 4),
        "strength_factor_count": len(strength_scores),
        "weakness_factor_count": len(weakness_scores),
        "weakness_penalty_applied": round(penalty, 4),
        "swot_weakness_penalty": settings.swot_weakness_penalty,
        "spec_formula_value": round(float(mean(strength_scores)), 4)
        if strength_scores
        else None,
        "clamped": not (1.0 <= raw_strength - penalty <= 5.0),
    }
    if not strength_scores and not weakness_scores:
        basis["warning"] = (
            "Nothing was scored at all, so competitive strength defaults to neutral 3.0. "
            "That is an absence of evidence, not evidence of average strength - supply "
            "financial data before reading the quadrant."
        )
    elif not strength_scores:
        basis["warning"] = (
            f"Zero strengths against {len(weakness_scores)} weaknesses. The strength axis "
            "is at its floor, which is a finding rather than a data gap."
        )
    return round(score, 4), basis


def place_quadrant(
    attractiveness: float, strength: float, settings: Settings
) -> tuple[Quadrant, bool, dict[str, Any]]:
    """Quadrant verdict plus a borderline flag and the distance to each boundary."""
    high = settings.quadrant_high_threshold
    low = settings.quadrant_low_threshold

    if attractiveness > high and strength > high:
        quadrant = Quadrant.INVEST_GROW
    elif attractiveness < low and strength < low:
        quadrant = Quadrant.HARVEST_DIVEST
    else:
        quadrant = Quadrant.SELECTIVE_INVEST

    distances = {
        "attractiveness_to_high": round(abs(attractiveness - high), 4),
        "attractiveness_to_low": round(abs(attractiveness - low), 4),
        "strength_to_high": round(abs(strength - high), 4),
        "strength_to_low": round(abs(strength - low), 4),
    }
    nearest = min(distances.values())
    borderline = nearest <= settings.quadrant_borderline_margin

    basis = {
        "thresholds": {"high": high, "low": low},
        "rule": (
            "attractiveness > high AND strength > high -> INVEST_GROW; "
            "attractiveness < low AND strength < low -> HARVEST_DIVEST; "
            "otherwise SELECTIVE_INVEST"
        ),
        "distance_to_boundaries": distances,
        "nearest_boundary_distance": round(nearest, 4),
        "borderline_margin": settings.quadrant_borderline_margin,
        "borderline": borderline,
    }
    if borderline:
        basis["borderline_note"] = (
            f"The position sits {nearest:.3f} from a quadrant boundary. Treat the "
            "verdict as provisional - a small revision to any input flips it."
        )
    return quadrant, borderline, basis


def run_attractiveness_matrix(
    *,
    market_data: dict,
    swot: SwotResult,
    competitive_intensity_score: float,
    settings: Settings,
) -> AttractivenessResult:
    """Compute both axes and place the company on the GE-McKinsey grid."""
    axis_trace: dict[str, Any] = {}

    growth = _axis_score(
        market_data.get("market_growth_pct"), MARKET_GROWTH_BANDS, "market_growth", axis_trace
    )
    size = _axis_score(
        market_data.get("market_size_usd_bn"), MARKET_SIZE_BANDS, "market_size", axis_trace
    )
    profitability = _axis_score(
        market_data.get("industry_operating_margin_pct"),
        INDUSTRY_PROFITABILITY_BANDS,
        "industry_profitability",
        axis_trace,
    )
    intensity = max(1.0, min(5.0, float(competitive_intensity_score)))

    weights = settings.attractiveness_weights
    inverted_intensity = 6.0 - intensity

    terms = {
        "market_growth": weights["market_growth"] * growth,
        "market_size": weights["market_size"] * size,
        "profitability": weights["profitability"] * profitability,
        "competitive_intensity_inverted": weights["competitive_intensity"] * inverted_intensity,
    }
    attractiveness = round(sum(terms.values()), 4)

    strength, strength_basis = compute_competitive_strength(swot, settings)
    quadrant, borderline, quadrant_basis = place_quadrant(attractiveness, strength, settings)

    imputed = [name for name, entry in axis_trace.items() if entry.get("imputed")]

    return AttractivenessResult(
        market_growth_score=growth,
        market_size_score=size,
        profitability_score=profitability,
        competitive_intensity_score=round(intensity, 4),
        overall_attractiveness_score=attractiveness,
        competitive_strength_score=strength,
        quadrant=quadrant,
        borderline=borderline,
        calculation_basis={
            "framework": "GE-McKinsey market attractiveness matrix (GE / McKinsey, c. 1971)",
            "attractiveness_formula": (
                "w_growth*growth + w_size*size + w_profitability*profitability "
                "+ w_intensity*(6 - competitive_intensity)"
            ),
            "weights": weights,
            "weighted_terms": {k: round(v, 4) for k, v in terms.items()},
            "axis_inputs": axis_trace,
            "competitive_intensity_raw": intensity,
            "competitive_intensity_inverted": round(inverted_intensity, 4),
            "competitive_strength": strength_basis,
            "quadrant_placement": quadrant_basis,
            "imputed_axes": imputed,
            "confidence_note": (
                f"{len(imputed)} of 3 market axes were imputed as neutral because they "
                "were not supplied; the attractiveness score is correspondingly weaker."
                if imputed
                else "All market axes were supplied; no values were imputed."
            ),
        },
    )
