"""Market concentration and competitive intensity, derived rather than asked for."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Any

from app.config import Settings
from app.enums import MarketConcentration

# Base rivalry level implied by each concentration band, on the 1-5 intensity axis.
_BASE_INTENSITY: dict[MarketConcentration, float] = {
    MarketConcentration.UNCONCENTRATED: 4.5,
    MarketConcentration.MODERATELY_CONCENTRATED: 3.0,
    MarketConcentration.HIGHLY_CONCENTRATED: 1.5,
}

# Commoditised markets show tightly clustered prices; differentiated ones
# spread out. Used to nudge the concentration-derived base by +/- 0.5.
_COMMODITISED_CV = 0.10
_DIFFERENTIATED_CV = 0.30

NEUTRAL_INTENSITY = 3.0


@dataclass(frozen=True)
class ConcentrationResult:
    hhi: float | None
    concentration: MarketConcentration | None
    competitive_intensity_score: float
    shares_used: list[dict[str, Any]]
    residual_share_pct: float | None
    price_coefficient_of_variation: float | None
    basis: dict[str, Any] = field(default_factory=dict)


def _clean_shares(company_share: float | None, competitors: list[dict]) -> list[dict[str, Any]]:
    shares: list[dict[str, Any]] = []
    if isinstance(company_share, (int, float)) and not isinstance(company_share, bool):
        if company_share > 0:
            shares.append({"name": "__focal_company__", "market_share_pct": float(company_share)})
    for competitor in competitors:
        value = competitor.get("market_share_pct")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            shares.append(
                {
                    "name": str(competitor.get("competitor_name", "unnamed")),
                    "market_share_pct": float(value),
                }
            )
    return shares


def compute_hhi(shares_pct: list[float]) -> float:
    """Sum of squared percentage-point shares. Monopoly = 10,000."""
    return round(sum(share**2 for share in shares_pct), 2)


def classify_concentration(hhi: float, settings: Settings) -> MarketConcentration:
    if hhi < settings.hhi_unconcentrated_max:
        return MarketConcentration.UNCONCENTRATED
    if hhi <= settings.hhi_highly_concentrated_min:
        return MarketConcentration.MODERATELY_CONCENTRATED
    return MarketConcentration.HIGHLY_CONCENTRATED


def price_dispersion(prices: list[float]) -> float | None:
    """Coefficient of variation of competitor prices, or ``None`` if undefined."""
    usable = [float(p) for p in prices if isinstance(p, (int, float)) and not isinstance(p, bool)]
    if len(usable) < 2:
        return None
    average = mean(usable)
    if average == 0:
        return None
    return round(pstdev(usable) / abs(average), 4)


def assess_market_structure(
    *,
    company_market_share_pct: float | None,
    competitors: list[dict],
    analyst_intensity_override: float | None,
    settings: Settings,
) -> ConcentrationResult:
    """Derive competitive intensity from the competitor set."""
    shares = _clean_shares(company_market_share_pct, competitors)
    prices = [c.get("price_point") for c in competitors]
    cv = price_dispersion([p for p in prices if p is not None])

    if not shares:
        if analyst_intensity_override is not None:
            intensity = max(1.0, min(5.0, float(analyst_intensity_override)))
            source = "analyst_override"
            note = "No market shares supplied; used the analyst-provided intensity score."
        else:
            intensity = NEUTRAL_INTENSITY
            source = "neutral_default"
            note = (
                "No market shares and no analyst override; competitive intensity "
                "defaulted to neutral 3.0. This weakens the attractiveness score - "
                "supply competitor market shares to compute it."
            )
        return ConcentrationResult(
            hhi=None,
            concentration=None,
            competitive_intensity_score=round(intensity, 3),
            shares_used=[],
            residual_share_pct=None,
            price_coefficient_of_variation=cv,
            basis={"intensity_source": source, "note": note},
        )

    share_values = [entry["market_share_pct"] for entry in shares]
    total_named = sum(share_values)
    residual = round(max(0.0, 100.0 - total_named), 3)

    hhi = compute_hhi(share_values)
    concentration = classify_concentration(hhi, settings)
    base = _BASE_INTENSITY[concentration]

    dispersion_adjustment = 0.0
    dispersion_note = "no usable price spread"
    if cv is not None:
        if cv <= _COMMODITISED_CV:
            dispersion_adjustment = 0.5
            dispersion_note = f"prices tightly clustered (CV {cv:.3f}) - commoditised, raises rivalry"
        elif cv >= _DIFFERENTIATED_CV:
            dispersion_adjustment = -0.5
            dispersion_note = f"prices widely spread (CV {cv:.3f}) - differentiated, lowers rivalry"
        else:
            dispersion_note = f"price spread unremarkable (CV {cv:.3f})"

    intensity = max(1.0, min(5.0, base + dispersion_adjustment))

    over_allocated = total_named > 100.0 + 1e-6

    return ConcentrationResult(
        hhi=hhi,
        concentration=concentration,
        competitive_intensity_score=round(intensity, 3),
        shares_used=shares,
        residual_share_pct=residual,
        price_coefficient_of_variation=cv,
        basis={
            "intensity_source": "computed_hhi",
            "hhi": hhi,
            "hhi_bands": {
                "unconcentrated_below": settings.hhi_unconcentrated_max,
                "highly_concentrated_above": settings.hhi_highly_concentrated_min,
                "reference": "US DOJ/FTC 2023 Merger Guidelines",
            },
            "concentration_band": concentration.value,
            "base_intensity_from_band": base,
            "dispersion_adjustment": dispersion_adjustment,
            "dispersion_note": dispersion_note,
            "named_share_total_pct": round(total_named, 3),
            "residual_share_pct": residual,
            "residual_treatment": (
                "Unnamed residual assumed to be an atomistic fringe contributing ~0 to "
                "HHI. This biases HHI downward (toward 'more competitive')."
            ),
            "warnings": (
                [f"Named market shares sum to {total_named:.1f}%, which exceeds 100%."]
                if over_allocated
                else []
            ),
        },
    )
