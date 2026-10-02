"""Uncertainty propagation: how likely is this verdict, given what I don't know?"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import Settings
from app.enums import Quadrant, VerdictStability
from app.services.attractiveness_matrix import (
    INDUSTRY_PROFITABILITY_BANDS,
    MARKET_GROWTH_BANDS,
    MARKET_SIZE_BANDS,
    NEUTRAL_SCORE,
    place_quadrant,
)
from app.services.swot_engine import band_score

AXIS_MIN = 1.0
AXIS_MAX = 5.0


class UncertaintyInputError(ValueError):
    """A distribution that cannot be sampled from."""


# Which inputs accept a distribution, and how a sampled raw value becomes a
# 1-5 axis score. The two direct inputs are already on the 1-5 scale.
BANDED_INPUTS: dict[str, tuple[str, tuple[float, ...]]] = {
    "market_growth_pct": ("market_growth", MARKET_GROWTH_BANDS),
    "market_size_usd_bn": ("market_size", MARKET_SIZE_BANDS),
    "industry_operating_margin_pct": ("profitability", INDUSTRY_PROFITABILITY_BANDS),
}
DIRECT_INPUTS: tuple[str, ...] = (
    "competitive_intensity_score",
    "competitive_strength_score",
)
SUPPORTED_INPUTS: tuple[str, ...] = tuple(BANDED_INPUTS) + DIRECT_INPUTS


@dataclass(frozen=True)
class ThreePoint:
    """A low / mode / high estimate for one input."""

    key: str
    low: float
    mode: float
    high: float

    @property
    def degenerate(self) -> bool:
        """``low == high``: a point estimate wearing a distribution's clothes."""
        return self.high - self.low < 1e-12

    def to_dict(self) -> dict[str, Any]:
        return {"low": self.low, "mode": self.mode, "high": self.high}


def parse_three_point(key: str, raw: Any) -> ThreePoint | None:
    """Read ``{low, mode, high}``. ``None`` when the input is a plain number."""
    if not isinstance(raw, dict):
        return None
    missing = [field_name for field_name in ("low", "mode", "high") if field_name not in raw]
    if missing:
        raise UncertaintyInputError(
            f"{key}: a three-point estimate needs low, mode and high; missing {missing}"
        )
    try:
        low, mode, high = (float(raw["low"]), float(raw["mode"]), float(raw["high"]))
    except (TypeError, ValueError) as exc:
        raise UncertaintyInputError(f"{key}: low, mode and high must be numbers") from exc

    if low > high:
        raise UncertaintyInputError(f"{key}: low {low} is above high {high}")
    if not low <= mode <= high:
        raise UncertaintyInputError(
            f"{key}: mode {mode} sits outside [{low}, {high}]. Clamping it would "
            "sample a distribution you did not describe."
        )
    return ThreePoint(key=key, low=low, mode=mode, high=high)


def pert_parameters(estimate: ThreePoint, lam: float) -> tuple[float, float]:
    """``(alpha, beta)`` of the Beta distribution underlying a PERT."""
    span = estimate.high - estimate.low
    alpha = 1.0 + lam * (estimate.mode - estimate.low) / span
    beta = 1.0 + lam * (estimate.high - estimate.mode) / span
    return alpha, beta


def sample_once(estimate: ThreePoint, rng: random.Random, settings: Settings) -> float:
    """One draw from the configured distribution over ``estimate``."""
    if estimate.degenerate:
        return estimate.mode

    kind = settings.uncertainty_distribution
    if kind == "UNIFORM":
        return rng.uniform(estimate.low, estimate.high)
    if kind == "TRIANGULAR":
        return rng.triangular(estimate.low, estimate.high, estimate.mode)

    alpha, beta = pert_parameters(estimate, settings.uncertainty_pert_lambda)
    return estimate.low + rng.betavariate(alpha, beta) * (estimate.high - estimate.low)


def shannon_entropy_bits(probabilities: dict[str, float]) -> float:
    """Entropy over the quadrant distribution, in bits."""
    total = 0.0
    for probability in probabilities.values():
        if probability > 0.0:
            total -= probability * math.log2(probability)
    return total


def stability_band(entropy_bits: float, settings: Settings) -> VerdictStability:
    if entropy_bits < settings.uncertainty_decisive_below:
        return VerdictStability.DECISIVE
    if entropy_bits < settings.uncertainty_contested_at_or_above:
        return VerdictStability.LEANING
    return VerdictStability.CONTESTED


def percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_values:
        raise UncertaintyInputError("no draws to take a percentile of")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _axis_draw(sampled: dict[str, float], key: str, bands: tuple[float, ...]) -> float:
    """Band-score one sampled market input, imputing neutral when it is absent."""
    value = sampled.get(key)
    if value is None:
        return NEUTRAL_SCORE
    return float(band_score(value, bands))


@dataclass
class UncertaintyResult:
    point_verdict: str
    point_attractiveness: float
    point_strength: float
    quadrant_probabilities: dict[str, float]
    modal_quadrant: str
    attractiveness_ci: list[float]
    strength_ci: list[float]
    entropy_bits: float
    verdict_stability: VerdictStability
    draws: int
    seed: int
    sampled_inputs: dict[str, dict[str, float]] = field(default_factory=dict)
    fixed_inputs: dict[str, float] = field(default_factory=dict)
    calculation_basis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["verdict_stability"] = self.verdict_stability.value
        return payload


def run_uncertainty_analysis(
    *,
    market_data: dict,
    uncertainty_inputs: dict | None,
    competitive_intensity_score: float,
    competitive_strength_score: float,
    point_attractiveness: float,
    point_strength: float,
    point_quadrant: str,
    settings: Settings,
) -> UncertaintyResult:
    """Monte Carlo over the stated distributions. Seeded and deterministic."""
    supplied = dict(uncertainty_inputs or {})
    unknown = sorted(set(supplied) - set(SUPPORTED_INPUTS))
    if unknown:
        raise UncertaintyInputError(
            f"unsupported uncertainty inputs {unknown}. Distributions are accepted "
            f"for {list(SUPPORTED_INPUTS)} - the inputs the matrix actually reads. "
            "Silently ignoring the rest would report a tighter distribution than "
            "the one you described."
        )

    point_values: dict[str, float] = {
        "competitive_intensity_score": float(competitive_intensity_score),
        "competitive_strength_score": float(competitive_strength_score),
    }
    for key in BANDED_INPUTS:
        raw = market_data.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            point_values[key] = float(raw)

    estimates: dict[str, ThreePoint] = {}
    for key, raw in supplied.items():
        parsed = parse_three_point(key, raw)
        if parsed is not None:
            estimates[key] = parsed

    weights = settings.attractiveness_weights
    rng = random.Random(settings.uncertainty_seed)
    draws = settings.uncertainty_draws

    counts: dict[str, int] = {quadrant.value: 0 for quadrant in Quadrant}
    attractiveness_draws: list[float] = []
    strength_draws: list[float] = []

    for _ in range(draws):
        sampled: dict[str, float] = dict(point_values)
        for key, estimate in estimates.items():
            sampled[key] = sample_once(estimate, rng, settings)

        # Band-scoring, weighted sum, and placement are the same functions the point
        # pipeline uses.
        growth = _axis_draw(sampled, "market_growth_pct", MARKET_GROWTH_BANDS)
        size = _axis_draw(sampled, "market_size_usd_bn", MARKET_SIZE_BANDS)
        profitability = _axis_draw(
            sampled, "industry_operating_margin_pct", INDUSTRY_PROFITABILITY_BANDS
        )
        intensity = min(AXIS_MAX, max(AXIS_MIN, sampled["competitive_intensity_score"]))
        strength = min(AXIS_MAX, max(AXIS_MIN, sampled["competitive_strength_score"]))

        attractiveness = (
            weights["market_growth"] * growth
            + weights["market_size"] * size
            + weights["profitability"] * profitability
            + weights["competitive_intensity"] * (6.0 - intensity)
        )
        quadrant, _borderline, _basis = place_quadrant(attractiveness, strength, settings)
        counts[quadrant.value] += 1
        attractiveness_draws.append(attractiveness)
        strength_draws.append(strength)

    probabilities = {key: round(value / draws, 4) for key, value in counts.items()}
    entropy = shannon_entropy_bits({k: v / draws for k, v in counts.items()})
    stability = stability_band(entropy, settings)
    modal = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]

    attractiveness_draws.sort()
    strength_draws.sort()
    tail = (100.0 - settings.uncertainty_credible_interval_pct) / 200.0
    attractiveness_ci = [
        round(percentile(attractiveness_draws, tail), 4),
        round(percentile(attractiveness_draws, 1.0 - tail), 4),
    ]
    strength_ci = [
        round(percentile(strength_draws, tail), 4),
        round(percentile(strength_draws, 1.0 - tail), 4),
    ]

    return UncertaintyResult(
        point_verdict=point_quadrant,
        point_attractiveness=round(point_attractiveness, 4),
        point_strength=round(point_strength, 4),
        quadrant_probabilities=probabilities,
        modal_quadrant=modal,
        attractiveness_ci=attractiveness_ci,
        strength_ci=strength_ci,
        entropy_bits=round(entropy, 4),
        verdict_stability=stability,
        draws=draws,
        seed=settings.uncertainty_seed,
        sampled_inputs={key: est.to_dict() for key, est in estimates.items()},
        fixed_inputs={
            key: value for key, value in sorted(point_values.items()) if key not in estimates
        },
        calculation_basis=_basis_block(
            estimates=estimates,
            point_values=point_values,
            probabilities=probabilities,
            entropy=entropy,
            stability=stability,
            modal=modal,
            point_quadrant=point_quadrant,
            settings=settings,
        ),
    )


def _basis_block(
    *,
    estimates: dict[str, ThreePoint],
    point_values: dict[str, float],
    probabilities: dict[str, float],
    entropy: float,
    stability: VerdictStability,
    modal: str,
    point_quadrant: str,
    settings: Settings,
) -> dict[str, Any]:
    distribution = settings.uncertainty_distribution
    formula = {
        "PERT": (
            "x = low + Beta(alpha, beta) * (high - low), with "
            "alpha = 1 + L*(mode-low)/(high-low) and beta = 1 + L*(high-mode)/(high-low), "
            f"L = {settings.uncertainty_pert_lambda}"
        ),
        "TRIANGULAR": "x ~ Triangular(low, high, mode)",
        "UNIFORM": "x ~ Uniform(low, high); the mode is discarded",
    }[distribution]

    return {
        "THE DISTRIBUTIONS ARE ANALYST-SUPPLIED": (
            "Every probability on this payload is conditional on ranges a human "
            "typed. This is NOT an objective probability that the verdict is "
            f"{modal}. It is the share of the uncertainty YOU STATED that lands "
            "there. Widen the ranges and the probabilities move; guess the ranges "
            "and a confident-looking number is built on a guess. Read it as "
            "'given the uncertainty I stated', never as 'the chance this is true'."
        ),
        "distribution": distribution,
        "distribution_formula": formula,
        "distribution_choice_note": (
            "PERT rather than uniform because a three-point estimate carries a "
            "mode and uniform throws it away; PERT rather than triangular because "
            "it weights the mode more sensibly and is the standard in project "
            "estimation. Both alternatives are selectable via "
            "UNCERTAINTY_DISTRIBUTION. None of the three is 'correct' - the "
            "choice is a modelling assumption, which is why it is recorded here."
        ),
        "draws": settings.uncertainty_draws,
        "seed": settings.uncertainty_seed,
        "determinism": (
            "Seeded. The same inputs and seed produce the same probabilities to "
            "the last digit, which is what makes a figure quotable in a report. "
            "A Monte Carlo that moves between runs cannot be cited."
        ),
        "sampled_inputs": {key: est.to_dict() for key, est in estimates.items()},
        "held_fixed": sorted(set(point_values) - set(estimates)),
        "held_fixed_note": (
            "Inputs with no stated distribution do not vary across draws. The "
            "reported spread is therefore a LOWER BOUND on the true uncertainty: "
            "it contains only the uncertainty that was declared."
        ),
        "weights": settings.attractiveness_weights,
        "quadrant_probabilities": probabilities,
        "entropy_definition": (
            "Shannon entropy over the three quadrant probabilities, in bits: "
            "H = -sum(p * log2 p). 0 = every draw agreed; log2(3) = 1.585 = a "
            "three-way coin flip."
        ),
        "entropy_bits": round(entropy, 4),
        "max_entropy_bits": round(settings.max_entropy_bits, 4),
        "verdict_stability": stability.value,
        "stability_bands": {
            "DECISIVE_below": settings.uncertainty_decisive_below,
            "CONTESTED_at_or_above": settings.uncertainty_contested_at_or_above,
        },
        "point_verdict_relationship": (
            f"The point verdict is {point_quadrant} and remains the headline; the "
            f"modal quadrant across draws is {modal}. Where they disagree, the "
            "point estimate sits near a boundary the sampled mass straddles - "
            "which is a finding about the inputs, not a defect in either number."
        ),
        "versus_sensitivity_analysis": (
            "GET /companies/{id}/sensitivity answers a DIFFERENT question: how far "
            "would ONE input have to move to flip the verdict, solved exactly. This "
            "answers: how likely is each verdict given the uncertainty stated across "
            "ALL inputs. They frequently disagree - a ROBUST placement with wide "
            "ranges can be CONTESTED, and a FRAGILE one with tight ranges can be "
            "DECISIVE. The disagreement is informative and is not reconciled here."
        ),
        "credible_interval_pct": settings.uncertainty_credible_interval_pct,
        "credible_interval_method": (
            "Empirical percentiles of the draws, linearly interpolated. Not a "
            "normal approximation: the band-scoring step is a step function, so "
            "the attractiveness distribution is lumpy and often multi-modal."
        ),
    }
