"""Pricing recommendation engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from app.config import Settings
from app.enums import MarginBasis
from app.services.market_structure import price_dispersion


class PricingInputError(ValueError):
    """Raised when the inputs cannot produce a meaningful price."""


@dataclass
class PricingResult:
    cost_base: float
    target_margin_pct: float
    margin_basis: MarginBasis
    cost_plus_price: float
    competitor_avg_price: float | None
    value_adjustment_factor: float
    recommended_price: float
    recommended_price_range: dict[str, float]
    implied_margin_pct: float
    confidence: str
    reasoning: dict[str, Any] = field(default_factory=dict)
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def cost_plus_price(cost_base: float, target_margin_pct: float, basis: MarginBasis) -> float:
    """Cost-plus anchor under either interpretation of ``target_margin_pct``."""
    if cost_base < 0:
        raise PricingInputError("cost_base cannot be negative")
    if basis is MarginBasis.MARKUP:
        if target_margin_pct <= -1:
            raise PricingInputError("markup must be greater than -100%")
        return cost_base * (1.0 + target_margin_pct)
    if target_margin_pct >= 1.0:
        raise PricingInputError(
            "A target margin of 100% or more is unachievable on MARGIN basis: "
            "cost / (1 - m) is undefined at m = 1 and negative above it. "
            "Use MARKUP basis if you meant a 100%+ markup."
        )
    return cost_base / (1.0 - target_margin_pct)


def _feature_average(scores: dict) -> float | None:
    usable = [
        float(v)
        for v in scores.values()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    return float(mean(usable)) if usable else None


def compute_value_adjustment(
    *,
    company_feature_scores: dict,
    competitor_feature_scores: list[dict],
    settings: Settings,
) -> tuple[float, dict[str, Any]]:
    """Multiplier from the relative feature gap, on shared features only."""
    company_scores = company_feature_scores if isinstance(company_feature_scores, dict) else {}
    competitor_maps = [m for m in competitor_feature_scores if isinstance(m, dict) and m]

    if not company_scores or not competitor_maps:
        return 1.0, {
            "applied": False,
            "reason": "feature scores missing on the company or every competitor",
            "shared_features": [],
            "value_adjustment_factor": 1.0,
        }

    competitor_features: set[str] = set()
    for scores in competitor_maps:
        competitor_features |= set(scores.keys())
    shared = sorted(set(company_scores.keys()) & competitor_features)

    if not shared:
        return 1.0, {
            "applied": False,
            "reason": "company and competitors share no feature names",
            "company_features": sorted(company_scores.keys()),
            "competitor_features": sorted(competitor_features),
            "shared_features": [],
            "value_adjustment_factor": 1.0,
        }

    company_avg = _feature_average({k: company_scores[k] for k in shared})
    per_competitor: list[float] = []
    for scores in competitor_maps:
        subset = {k: scores[k] for k in shared if k in scores}
        avg = _feature_average(subset)
        if avg is not None:
            per_competitor.append(avg)

    if company_avg is None or not per_competitor:
        return 1.0, {
            "applied": False,
            "reason": "shared features present but no numeric scores behind them",
            "shared_features": shared,
            "value_adjustment_factor": 1.0,
        }

    competitor_avg = float(mean(per_competitor))
    delta = company_avg - competitor_avg
    raw_factor = 1.0 + settings.pricing_value_coefficient * delta
    cap = settings.pricing_value_adjustment_cap
    factor = max(1.0 - cap, min(1.0 + cap, raw_factor))

    dropped = sorted(
        (set(company_scores.keys()) | competitor_features) - set(shared)
    )

    return round(factor, 6), {
        "applied": True,
        "shared_features": shared,
        "dropped_features": dropped,
        "company_feature_avg": round(company_avg, 4),
        "competitor_feature_avg": round(competitor_avg, 4),
        "feature_delta": round(delta, 4),
        "coefficient_k": settings.pricing_value_coefficient,
        "raw_factor": round(raw_factor, 6),
        "cap": cap,
        "clamped": abs(raw_factor - factor) > 1e-9,
        "value_adjustment_factor": round(factor, 6),
    }


def run_pricing_engine(
    *,
    cost_base: float,
    target_margin_pct: float,
    margin_basis: MarginBasis,
    competitors: list[dict],
    company_feature_scores: dict,
    settings: Settings,
) -> PricingResult:
    """Blend the anchors, apply the value adjustment, and floor at cost."""
    if cost_base <= 0:
        raise PricingInputError("cost_base must be greater than zero")

    anchor = cost_plus_price(cost_base, target_margin_pct, margin_basis)

    competitor_prices = [
        float(c["price_point"])
        for c in competitors
        if isinstance(c, dict)
        and isinstance(c.get("price_point"), (int, float))
        and not isinstance(c.get("price_point"), bool)
        and c["price_point"] > 0
    ]
    benchmark = float(mean(competitor_prices)) if competitor_prices else None
    cv = price_dispersion(competitor_prices)

    if benchmark is None:
        # No competitor anchor: the weight on it has to go somewhere, and the
        # only defensible place is the anchor that still exists.
        w_cost, w_comp = 1.0, 0.0
        blend_note = (
            "No competitor price points supplied; the full weight collapsed onto "
            "the cost-plus anchor. This is a cost-plus recommendation, not a "
            "market-benchmarked one."
        )
        blended = anchor
    else:
        w_cost, w_comp = settings.pricing_w_cost_plus, settings.pricing_w_competitor
        blend_note = (
            f"Blended {w_cost:.0%} cost-plus / {w_comp:.0%} competitor benchmark "
            f"across {len(competitor_prices)} competitor price point(s)."
        )
        blended = w_cost * anchor + w_comp * benchmark

    factor, value_basis = compute_value_adjustment(
        company_feature_scores=company_feature_scores,
        competitor_feature_scores=[c.get("feature_scores") or {} for c in competitors],
        settings=settings,
    )

    raw_recommended = blended * factor

    # Floor at cost. A cost-plus engine returning a below-cost price is a bug.
    floored = max(raw_recommended, cost_base)
    price_floor_applied = floored > raw_recommended + 1e-9

    spread = settings.pricing_range_spread
    range_min = max(floored * (1.0 - spread), cost_base)
    range_max = floored * (1.0 + spread)
    range_floor_applied = range_min > floored * (1.0 - spread) + 1e-9

    implied_margin = (floored - cost_base) / floored * 100.0 if floored > 0 else 0.0

    warnings: list[str] = []
    if price_floor_applied:
        warnings.append(
            f"The blended recommendation ({raw_recommended:.2f}) fell below the cost base "
            f"({cost_base:.2f}) and was floored at cost. Revisit the cost structure or the "
            "competitor set before pricing this product."
        )
    if range_floor_applied:
        warnings.append(
            f"The bottom of the recommended range was raised to the cost base "
            f"({cost_base:.2f}) to keep the whole band above water."
        )
    if cv is not None and cv > settings.pricing_dispersion_warning_cv:
        warnings.append(
            f"Competitor prices vary widely (coefficient of variation {cv:.2f} > "
            f"{settings.pricing_dispersion_warning_cv}). Their mean is an average of unlike "
            "products; treat the benchmark anchor as weak evidence."
        )
    if benchmark is None:
        warnings.append(blend_note)
    if not value_basis["applied"]:
        warnings.append(
            f"Value adjustment not applied: {value_basis['reason']}. The recommendation "
            "reflects cost and competitor price only, with no quality differential."
        )

    confidence = "LOW" if len(warnings) >= 2 else ("MEDIUM" if warnings else "HIGH")

    steps = [
        f"Cost base: {cost_base:.2f}",
        (
            f"Cost-plus anchor ({margin_basis.value} basis, target {target_margin_pct:.1%}): "
            f"{anchor:.2f}"
            + (
                f"  [cost / (1 - {target_margin_pct:.2f})]"
                if margin_basis is MarginBasis.MARGIN
                else f"  [cost x (1 + {target_margin_pct:.2f})]"
            )
        ),
        (
            f"Competitor benchmark (mean of {len(competitor_prices)}): {benchmark:.2f}"
            if benchmark is not None
            else "Competitor benchmark: unavailable"
        ),
        f"Blend: {blend_note} -> {blended:.2f}",
        (
            f"Value adjustment x{factor:.4f} "
            f"(feature delta {value_basis.get('feature_delta', 0)}, k="
            f"{settings.pricing_value_coefficient})"
            if value_basis["applied"]
            else "Value adjustment: not applied (x1.0000)"
        ),
        f"Recommended price: {floored:.2f}",
        f"Recommended range: {range_min:.2f} - {range_max:.2f}",
        f"Implied margin at the recommended price: {implied_margin:.2f}%",
    ]

    return PricingResult(
        cost_base=cost_base,
        target_margin_pct=target_margin_pct,
        margin_basis=margin_basis,
        cost_plus_price=round(anchor, 4),
        competitor_avg_price=round(benchmark, 4) if benchmark is not None else None,
        value_adjustment_factor=factor,
        recommended_price=round(floored, 4),
        recommended_price_range={
            "min": round(range_min, 4),
            "optimal": round(floored, 4),
            "max": round(range_max, 4),
        },
        implied_margin_pct=round(implied_margin, 4),
        confidence=confidence,
        reasoning={
            "steps": steps,
            "warnings": warnings,
            "margin_basis_note": (
                f"Target margin interpreted on {margin_basis.value} basis. "
                f"MARGIN: price = cost / (1 - m), realised margin = m. "
                f"MARKUP: price = cost x (1 + m), realised margin = m / (1 + m). "
                f"At m = {target_margin_pct:.2f} on cost {cost_base:.2f} these differ "
                f"({cost_plus_price(cost_base, target_margin_pct, MarginBasis.MARGIN):.2f} vs "
                f"{cost_plus_price(cost_base, target_margin_pct, MarginBasis.MARKUP):.2f})."
            ),
            "confidence": confidence,
        },
        calculation_basis={
            "formula": (
                "recommended = (w_cost * cost_plus + w_comp * competitor_benchmark) "
                "* value_adjustment, floored at cost_base"
            ),
            "weights": {"cost_plus": w_cost, "competitor_benchmark": w_comp},
            "cost_plus_anchor": round(anchor, 4),
            "competitor_prices": competitor_prices,
            "competitor_price_cv": cv,
            "dispersion_warning_cv": settings.pricing_dispersion_warning_cv,
            "blended_price": round(blended, 4),
            "value_adjustment": value_basis,
            "raw_recommended_before_floor": round(raw_recommended, 4),
            "price_floor_applied": price_floor_applied,
            "range_floor_applied": range_floor_applied,
            "range_spread": spread,
            "implied_margin_pct": round(implied_margin, 4),
        },
    )
