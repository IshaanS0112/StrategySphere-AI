"""Sensitivity analysis: how much would have to be wrong for the verdict to change?"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import Settings
from app.enums import Quadrant, SensitivityVerdict
from app.services.attractiveness_matrix import place_quadrant

# The four attractiveness axes and the sign of their effect on the score.
# Intensity enters as (6 - i), so raising intensity LOWERS attractiveness.
AXIS_WEIGHT_KEYS: dict[str, str] = {
    "market_growth": "market_growth",
    "market_size": "market_size",
    "industry_profitability": "profitability",
    "competitive_intensity": "competitive_intensity",
}
AXIS_SIGN: dict[str, float] = {
    "market_growth": 1.0,
    "market_size": 1.0,
    "industry_profitability": 1.0,
    "competitive_intensity": -1.0,
}

AXIS_MIN = 1.0
AXIS_MAX = 5.0


@dataclass(frozen=True)
class AxisSensitivity:
    axis: str
    current_value: float
    weight: float
    # d(attractiveness)/d(axis). Negative for competitive intensity.
    derivative: float
    # Signed minimum change in this axis that lands in a different quadrant.
    required_delta: float | None
    required_value: float | None
    reachable: bool
    resulting_quadrant: str | None
    headroom_up: float
    headroom_down: float
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SensitivityResult:
    baseline_quadrant: Quadrant
    baseline_attractiveness: float
    baseline_strength: float
    verdict: SensitivityVerdict
    # Ranked most-influential first: the axis needing the smallest reachable move.
    axes: list[AxisSensitivity] = field(default_factory=list)
    strength_sensitivity: AxisSensitivity | None = None
    # The single input needing the smallest reachable move, across the four
    # attractiveness axes AND the strength axis.
    binding_constraint: AxisSensitivity | None = None
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def _quadrant_at(
    attractiveness: float, strength: float, settings: Settings
) -> Quadrant:
    quadrant, _, _ = place_quadrant(attractiveness, strength, settings)
    return quadrant


def _smallest_flip_for_axis(
    *,
    axis: str,
    current: float,
    derivative: float,
    attractiveness: float,
    strength: float,
    settings: Settings,
) -> tuple[float | None, float | None, str | None, bool, str]:
    """Return (delta, new_axis_value, new_quadrant, reachable, note)."""
    baseline_quadrant = _quadrant_at(attractiveness, strength, settings)

    if abs(derivative) < 1e-12:
        return None, None, None, False, "Zero weight: this axis cannot move the score."

    candidates: list[tuple[float, float, Quadrant]] = []
    for threshold in (settings.quadrant_low_threshold, settings.quadrant_high_threshold):
        # Aim marginally past the threshold: the rule uses strict inequalities,
        # so landing exactly on it does not change the verdict.
        for epsilon in (1e-6, -1e-6):
            target = threshold + epsilon
            delta_axis = (target - attractiveness) / derivative
            new_axis_value = current + delta_axis
            if not (AXIS_MIN - 1e-9 <= new_axis_value <= AXIS_MAX + 1e-9):
                continue
            new_attractiveness = attractiveness + derivative * delta_axis
            new_quadrant = _quadrant_at(new_attractiveness, strength, settings)
            if new_quadrant is not baseline_quadrant:
                candidates.append((delta_axis, new_axis_value, new_quadrant))

    if not candidates:
        # Distinguish "no threshold is reachable inside the axis bounds" from
        # "crossing it does not change the quadrant because the rule is conjunctive"
        # - they need different advice.
        reachable_up = derivative * (AXIS_MAX - current)
        reachable_down = derivative * (AXIS_MIN - current)
        span_lo, span_hi = sorted((attractiveness + reachable_down, attractiveness + reachable_up))
        crosses = any(
            span_lo <= t <= span_hi
            for t in (settings.quadrant_low_threshold, settings.quadrant_high_threshold)
        )
        note = (
            "Crossing the threshold on this axis alone does not change the quadrant - "
            "the other axis holds the verdict in place."
            if crosses
            else (
                f"Unreachable: even at the axis limit the score only spans "
                f"{span_lo:.2f}-{span_hi:.2f}, which clears no boundary."
            )
        )
        return None, None, None, False, note

    delta, new_value, new_quadrant = min(candidates, key=lambda c: abs(c[0]))
    direction = "increase" if delta > 0 else "decrease"
    return (
        round(delta, 4),
        round(new_value, 4),
        new_quadrant.value,
        True,
        f"A {abs(delta):.2f}-point {direction} on this 1-5 axis flips the verdict to "
        f"{new_quadrant.value}.",
    )


def run_sensitivity_analysis(
    *,
    market_growth_score: float,
    market_size_score: float,
    profitability_score: float,
    competitive_intensity_score: float,
    attractiveness: float,
    strength: float,
    settings: Settings,
) -> SensitivityResult:
    """Exact single-input flip distances for every axis, ranked by fragility."""
    weights = settings.attractiveness_weights
    baseline_quadrant = _quadrant_at(attractiveness, strength, settings)

    current_values = {
        "market_growth": market_growth_score,
        "market_size": market_size_score,
        "industry_profitability": profitability_score,
        "competitive_intensity": competitive_intensity_score,
    }

    axes: list[AxisSensitivity] = []
    for axis, current in current_values.items():
        weight = weights[AXIS_WEIGHT_KEYS[axis]]
        derivative = weight * AXIS_SIGN[axis]
        delta, new_value, new_quadrant, reachable, note = _smallest_flip_for_axis(
            axis=axis,
            current=current,
            derivative=derivative,
            attractiveness=attractiveness,
            strength=strength,
            settings=settings,
        )
        axes.append(
            AxisSensitivity(
                axis=axis,
                current_value=round(current, 4),
                weight=weight,
                derivative=round(derivative, 4),
                required_delta=delta,
                required_value=new_value,
                reachable=reachable,
                resulting_quadrant=new_quadrant,
                headroom_up=round(AXIS_MAX - current, 4),
                headroom_down=round(current - AXIS_MIN, 4),
                note=note,
            )
        )

    # Strength is the SWOT formula's output, not a weighted axis: unit derivative.
    s_delta, s_value, s_quadrant, s_reachable, s_note = _smallest_flip_for_axis(
        axis="competitive_strength",
        current=strength,
        derivative=1.0,
        attractiveness=strength,  # solve on the strength axis itself
        strength=attractiveness,  # ... with attractiveness as the fixed partner
        settings=settings,
    )
    strength_sensitivity = AxisSensitivity(
        axis="competitive_strength",
        current_value=round(strength, 4),
        weight=1.0,
        derivative=1.0,
        required_delta=s_delta,
        required_value=s_value,
        reachable=s_reachable,
        resulting_quadrant=s_quadrant,
        headroom_up=round(AXIS_MAX - strength, 4),
        headroom_down=round(strength - AXIS_MIN, 4),
        note=s_note,
    )

    # Rank: reachable flips first, smallest move first. Unreachable axes sort
    # last regardless of their arithmetic, since they cannot change anything.
    axes.sort(key=lambda a: (not a.reachable, abs(a.required_delta or 1e9)))

    # The binding constraint is whichever single input — attractiveness axis or the
    # strength axis — needs the smallest reachable move.
    candidates = [
        a
        for a in axes + [strength_sensitivity]
        if a.reachable and a.required_delta is not None
    ]
    binding = min(candidates, key=lambda a: abs(a.required_delta)) if candidates else None
    smallest = abs(binding.required_delta) if binding else None

    if smallest is None:
        verdict = SensitivityVerdict.ROBUST
    elif smallest <= settings.sensitivity_knife_edge_threshold:
        verdict = SensitivityVerdict.KNIFE_EDGE
    elif smallest <= settings.sensitivity_fragile_threshold:
        verdict = SensitivityVerdict.FRAGILE
    else:
        verdict = SensitivityVerdict.ROBUST

    return SensitivityResult(
        baseline_quadrant=baseline_quadrant,
        baseline_attractiveness=round(attractiveness, 4),
        baseline_strength=round(strength, 4),
        verdict=verdict,
        axes=axes,
        strength_sensitivity=strength_sensitivity,
        binding_constraint=binding,
        calculation_basis={
            "method": (
                "Analytic. The attractiveness score is linear in its axes, so "
                "d(attractiveness)/d(axis) is the axis weight (negated for "
                "competitive intensity, which enters as 6 - i). The minimum "
                "single-axis change that reaches a boundary is therefore "
                "(threshold - attractiveness) / derivative exactly, with no "
                "perturbation step to choose."
            ),
            "formula": "required_delta = (threshold - A) / (dA/d_axis)",
            "weights": weights,
            "derivatives": {
                a.axis: a.derivative for a in axes
            },
            "axis_bounds": [AXIS_MIN, AXIS_MAX],
            "thresholds": {
                "high": settings.quadrant_high_threshold,
                "low": settings.quadrant_low_threshold,
            },
            "conjunctive_rule_note": (
                "INVEST_GROW and HARVEST_DIVEST both require BOTH axes past a "
                "threshold, so crossing one alone may not change the quadrant. "
                "Every candidate is verified by re-placing the quadrant rather "
                "than assumed from the threshold crossing."
            ),
            "smallest_reachable_flip": smallest,
            "binding_constraint": binding.axis if binding else None,
            "binding_constraint_note": (
                f"The verdict hangs on '{binding.axis}': a "
                f"{abs(binding.required_delta):.2f}-point move flips it to "
                f"{binding.resulting_quadrant}. Read this rather than the top of "
                f"the axis list - the attractiveness axes can all be unreachable "
                f"while strength still decides the placement."
                if binding
                else "No single input flips the verdict within its 1-5 range."
            ),
            "verdict_thresholds": {
                "knife_edge_at_or_below": settings.sensitivity_knife_edge_threshold,
                "fragile_at_or_below": settings.sensitivity_fragile_threshold,
            },
            "interpretation": (
                "ROBUST: no single axis flips the verdict within its 1-5 range. "
                "FRAGILE: at least one axis flips it with a move smaller than half "
                "a band, which is well inside normal input error. "
                "KNIFE_EDGE: a trivial change flips it - do not present the "
                "quadrant as a finding."
            ),
        },
    )
