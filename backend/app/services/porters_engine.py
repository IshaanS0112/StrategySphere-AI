"""Porter's Five Forces."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from app.config import Settings
from app.enums import ForceSource, IndustryAttractiveness, PorterForce
from app.services.market_structure import ConcentrationResult

# Analyst inputs this engine understands, all 1-5, all "higher = stronger force
# = worse for incumbents". Read from company.market_data.
ANALYST_INPUT_KEYS = {
    "buyer_concentration": "Few large buyers able to dictate terms",
    "buyer_switching_cost": "How cheaply a customer can leave (5 = trivially)",
    "substitute_availability": "Alternatives that meet the same need",
    "substitute_price_performance": "How favourably substitutes compare on price/performance",
    "capital_intensity": "Capital required to enter (5 = trivial, so a weak barrier)",
    "regulatory_barrier": "Licensing/regulatory protection (5 = none, so a weak barrier)",
    "supplier_concentration": "Few suppliers able to dictate terms",
}


@dataclass(frozen=True)
class ForceResult:
    force: PorterForce
    score: float | None
    source: ForceSource
    evidence: str
    inputs_used: list[str] = field(default_factory=list)
    inputs_missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "force": self.force.value,
            "score": self.score,
            "source": self.source.value,
            "evidence": self.evidence,
            "inputs_used": self.inputs_used,
            "inputs_missing": self.inputs_missing,
            "scale": "1-5, higher = stronger force = worse for incumbents",
        }


@dataclass
class PortersResult:
    forces: list[ForceResult]
    composite_score: float | None
    industry_attractiveness: IndustryAttractiveness | None
    forces_scored: int
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def _num(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _clamp(value: float) -> float:
    return max(1.0, min(5.0, value))


def _collect(market_data: dict, keys: list[str]) -> tuple[dict[str, float], list[str]]:
    """Pull the analyst inputs that are present; report the ones that are not."""
    present: dict[str, float] = {}
    missing: list[str] = []
    for key in keys:
        value = _num(market_data.get(key))
        if value is None:
            missing.append(key)
        else:
            present[key] = _clamp(value)
    return present, missing


# --------------------------------------------------------------------------
# Force 1: competitive rivalry — fully computed
# --------------------------------------------------------------------------

def score_rivalry(concentration: ConcentrationResult) -> ForceResult:
    """Reuses the intensity already derived from HHI for the GE-McKinsey axis."""
    if concentration.hhi is None:
        return ForceResult(
            force=PorterForce.COMPETITIVE_RIVALRY,
            score=None,
            source=ForceSource.UNAVAILABLE,
            evidence=(
                "No competitor market shares supplied, so HHI could not be computed "
                "and rivalry has no data-derived basis."
            ),
            inputs_missing=["competitor market_share_pct"],
        )

    band = concentration.concentration.value if concentration.concentration else "UNKNOWN"
    return ForceResult(
        force=PorterForce.COMPETITIVE_RIVALRY,
        score=round(concentration.competitive_intensity_score, 3),
        source=ForceSource.COMPUTED,
        evidence=(
            f"HHI {concentration.hhi:g} places the market in the {band} band "
            f"(DOJ/FTC 2023 Merger Guidelines); "
            f"{concentration.basis.get('dispersion_note', 'no price-spread signal')}. "
            f"Derived rivalry {concentration.competitive_intensity_score:g}/5."
        ),
        inputs_used=["competitor market shares", "competitor price points"],
    )


# --------------------------------------------------------------------------
# Force 2: threat of new entrants — partially computed
# --------------------------------------------------------------------------

def score_new_entrants(
    market_data: dict, concentration: ConcentrationResult, settings: Settings
) -> ForceResult:
    """A profitable, fragmented industry invites entry; barriers hold it off."""
    industry_margin = _num(market_data.get("industry_operating_margin_pct"))
    analyst, missing = _collect(market_data, ["capital_intensity", "regulatory_barrier"])

    structural: list[float] = []
    used: list[str] = []

    if industry_margin is not None:
        # 0% margin -> 1 (nothing to come for); 25%+ -> 5 (very attractive prize)
        structural.append(_clamp(1.0 + (industry_margin / 25.0) * 4.0))
        used.append("industry_operating_margin_pct")
    else:
        missing.append("industry_operating_margin_pct")

    if concentration.hhi is not None:
        # HHI 0 -> 5 (wide open); HHI 5000+ -> 1 (entrenched incumbents)
        structural.append(_clamp(5.0 - (concentration.hhi / 5000.0) * 4.0))
        used.append("HHI")
    else:
        missing.append("competitor market shares")

    components = structural + list(analyst.values())
    used += list(analyst.keys())

    coverage = len(components) / 4.0
    if not components or coverage < settings.porter_min_input_coverage:
        return ForceResult(
            force=PorterForce.THREAT_OF_NEW_ENTRANTS,
            score=None,
            source=ForceSource.UNAVAILABLE,
            evidence=(
                f"Only {len(components)} of 4 inputs available "
                f"({coverage:.0%} coverage, minimum "
                f"{settings.porter_min_input_coverage:.0%}). Not scored."
            ),
            inputs_used=used,
            inputs_missing=missing,
        )

    score = _clamp(mean(components))
    source = ForceSource.PARTIALLY_COMPUTED if analyst and structural else (
        ForceSource.COMPUTED if structural else ForceSource.ANALYST_INPUT
    )
    return ForceResult(
        force=PorterForce.THREAT_OF_NEW_ENTRANTS,
        score=round(score, 3),
        source=source,
        evidence=(
            (
                f"Industry operating margin {industry_margin:g}% sets the size of the prize; "
                if industry_margin is not None
                else ""
            )
            + (
                f"HHI {concentration.hhi:g} indicates how entrenched incumbents are"
                if concentration.hhi is not None
                else ""
            )
            + (
                f". Analyst inputs {sorted(analyst)} adjust for barriers not visible in the data."
                if analyst
                else ". No analyst barrier inputs supplied."
            )
        ),
        inputs_used=used,
        inputs_missing=missing,
    )


# --------------------------------------------------------------------------
# Force 3: supplier power — partially computed
# --------------------------------------------------------------------------

def score_supplier_power(
    financial_data: dict, market_data: dict, settings: Settings
) -> ForceResult:
    """Input cost share is a real, if partial, proxy for supplier leverage."""
    gross_margin = _num(financial_data.get("gross_margin_pct"))
    analyst, missing = _collect(market_data, ["supplier_concentration"])

    components: list[float] = []
    used: list[str] = []

    if gross_margin is not None:
        cost_share = _clamp(1.0 + ((100.0 - gross_margin) / 100.0) * 4.0)
        components.append(cost_share)
        used.append("gross_margin_pct")
    else:
        missing.append("gross_margin_pct")

    components += list(analyst.values())
    used += list(analyst.keys())

    coverage = len(components) / 2.0
    if not components or coverage < settings.porter_min_input_coverage:
        return ForceResult(
            force=PorterForce.SUPPLIER_POWER,
            score=None,
            source=ForceSource.UNAVAILABLE,
            evidence="Neither gross margin nor a supplier-concentration input was supplied.",
            inputs_used=used,
            inputs_missing=missing,
        )

    source = (
        ForceSource.PARTIALLY_COMPUTED
        if analyst and gross_margin is not None
        else (ForceSource.COMPUTED if gross_margin is not None else ForceSource.ANALYST_INPUT)
    )
    return ForceResult(
        force=PorterForce.SUPPLIER_POWER,
        score=round(_clamp(mean(components)), 3),
        source=source,
        evidence=(
            (
                f"Gross margin {gross_margin:g}% implies {100 - gross_margin:g}% of revenue "
                f"goes to input costs, which bounds supplier exposure"
                if gross_margin is not None
                else "No gross margin supplied"
            )
            + (
                f"; analyst supplier concentration {analyst['supplier_concentration']:g}/5."
                if analyst
                else ". Supplier concentration not supplied, so leverage is inferred from cost share alone."
            )
        ),
        inputs_used=used,
        inputs_missing=missing,
    )


# --------------------------------------------------------------------------
# Forces 4 and 5: analyst input only
# --------------------------------------------------------------------------

def _analyst_only_force(
    force: PorterForce, market_data: dict, keys: list[str], label: str
) -> ForceResult:
    analyst, missing = _collect(market_data, keys)
    if not analyst:
        return ForceResult(
            force=force,
            score=None,
            source=ForceSource.UNAVAILABLE,
            evidence=(
                f"{label} has no proxy in financial or competitor data and no analyst "
                f"input was supplied. Not scored - a default of 3 would be a guess "
                f"presented as a measurement."
            ),
            inputs_missing=missing,
        )
    return ForceResult(
        force=force,
        score=round(_clamp(mean(analyst.values())), 3),
        source=ForceSource.ANALYST_INPUT,
        evidence=(
            f"{label} from analyst judgement: "
            + ", ".join(f"{k} {v:g}/5" for k, v in sorted(analyst.items()))
            + ". This is a judgement, not a measurement."
        ),
        inputs_used=sorted(analyst),
        inputs_missing=missing,
    )


def score_buyer_power(market_data: dict) -> ForceResult:
    return _analyst_only_force(
        PorterForce.BUYER_POWER,
        market_data,
        ["buyer_concentration", "buyer_switching_cost"],
        "Buyer power",
    )


def score_substitutes(market_data: dict) -> ForceResult:
    return _analyst_only_force(
        PorterForce.THREAT_OF_SUBSTITUTES,
        market_data,
        ["substitute_availability", "substitute_price_performance"],
        "Threat of substitutes",
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def classify_attractiveness(
    composite: float, settings: Settings
) -> IndustryAttractiveness:
    """Weaker forces mean more structural profit is available to incumbents."""
    if composite < settings.porter_attractive_below:
        return IndustryAttractiveness.ATTRACTIVE
    if composite > settings.porter_unattractive_above:
        return IndustryAttractiveness.UNATTRACTIVE
    return IndustryAttractiveness.MODERATE


def run_porters_analysis(
    *,
    financial_data: dict,
    market_data: dict,
    concentration: ConcentrationResult,
    settings: Settings,
) -> PortersResult:
    """Score all five forces. Deterministic; no LLM anywhere in this path."""
    forces = [
        score_rivalry(concentration),
        score_new_entrants(market_data, concentration, settings),
        score_supplier_power(financial_data, market_data, settings),
        score_buyer_power(market_data),
        score_substitutes(market_data),
    ]

    scored = [f for f in forces if f.score is not None]

    composite: float | None = None
    attractiveness: IndustryAttractiveness | None = None
    if len(scored) >= 2:
        composite = round(mean(f.score for f in scored), 4)
        attractiveness = classify_attractiveness(composite, settings)

    return PortersResult(
        forces=forces,
        composite_score=composite,
        industry_attractiveness=attractiveness,
        forces_scored=len(scored),
        calculation_basis={
            "framework": "Porter's Five Forces (Porter, HBR 1979)",
            "scale_direction": (
                "1-5, higher = stronger force = worse for incumbents. This is the "
                "OPPOSITE direction to the GE-McKinsey attractiveness axis, where "
                "higher is better."
            ),
            "composite_status": (
                "PROJECT-DEFINED COMPOSITE, not part of Porter's framework. Porter "
                "does not weight or average the forces - they are meant to be read "
                "individually. This mean exists only to give the UI one sortable "
                "number and should not be quoted as a Porter output."
            ),
            "composite_method": "unweighted mean of the forces that could be scored",
            "forces_scored": len(scored),
            "forces_unavailable": [
                f.force.value for f in forces if f.score is None
            ],
            "source_breakdown": {f.force.value: f.source.value for f in forces},
            "attractiveness_bands": {
                "attractive_below": settings.porter_attractive_below,
                "unattractive_above": settings.porter_unattractive_above,
            },
            "min_input_coverage": settings.porter_min_input_coverage,
            "recognised_analyst_inputs": ANALYST_INPUT_KEYS,
            "note": (
                "Two of five forces (buyer power, substitutes) have no proxy in the "
                "data this system stores and are analyst input or nothing. Treat a "
                "composite built mostly from analyst inputs as an opinion with "
                "arithmetic applied to it."
            ),
        },
    )
