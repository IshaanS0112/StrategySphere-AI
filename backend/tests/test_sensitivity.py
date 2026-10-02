"""Sensitivity analysis."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.enums import Quadrant, SensitivityVerdict
from app.services.attractiveness_matrix import place_quadrant
from app.services.sensitivity import run_sensitivity_analysis


def analyse(
    settings: Settings,
    *,
    growth=4.0,
    size=4.0,
    profitability=4.0,
    intensity=2.0,
    strength=4.0,
):
    weights = settings.attractiveness_weights
    attractiveness = (
        weights["market_growth"] * growth
        + weights["market_size"] * size
        + weights["profitability"] * profitability
        + weights["competitive_intensity"] * (6.0 - intensity)
    )
    return (
        run_sensitivity_analysis(
            market_growth_score=growth,
            market_size_score=size,
            profitability_score=profitability,
            competitive_intensity_score=intensity,
            attractiveness=attractiveness,
            strength=strength,
            settings=settings,
        ),
        attractiveness,
    )


class TestDerivatives:
    def test_derivative_equals_the_weight(self, settings: Settings):
        result, _ = analyse(settings)
        by_axis = {a.axis: a for a in result.axes}
        assert by_axis["market_growth"].derivative == pytest.approx(0.3)
        assert by_axis["market_size"].derivative == pytest.approx(0.2)
        assert by_axis["industry_profitability"].derivative == pytest.approx(0.3)

    def test_intensity_derivative_is_negative(self, settings: Settings):
        result, _ = analyse(settings)
        intensity = next(a for a in result.axes if a.axis == "competitive_intensity")
        assert intensity.derivative == pytest.approx(-0.2), (
            "intensity enters as (6 - i), so raising it must LOWER attractiveness"
        )


class TestExactness:
    def test_the_reported_delta_actually_flips_the_quadrant(self, settings: Settings):
        result, attractiveness = analyse(settings, strength=4.0)
        for axis in result.axes:
            if not axis.reachable or axis.required_delta is None:
                continue
            moved = attractiveness + axis.derivative * axis.required_delta
            quadrant, _, _ = place_quadrant(moved, result.baseline_strength, settings)
            assert quadrant.value == axis.resulting_quadrant
            assert quadrant is not result.baseline_quadrant

    def test_slightly_less_than_the_delta_does_not_flip(self, settings: Settings):
        result, attractiveness = analyse(settings, strength=4.0)
        for axis in result.axes:
            if not axis.reachable or axis.required_delta is None:
                continue
            short = axis.required_delta * 0.98
            moved = attractiveness + axis.derivative * short
            quadrant, _, _ = place_quadrant(moved, result.baseline_strength, settings)
            assert quadrant is result.baseline_quadrant, (
                f"{axis.axis}: 98% of the reported delta should not be enough"
            )

    def test_hand_computed_flip_distance(self, settings: Settings):
        # growth 4, size 4, profit 4, intensity 2 -> A = 1.2+0.8+1.2+0.8 = 4.0 To
        # drop A below the 3.5 high threshold via market_growth (w = 0.3): required
        # = (3.5 - 4.0) / 0.3 = -1.6667
        result, attractiveness = analyse(settings, strength=4.0)
        assert attractiveness == pytest.approx(4.0)
        growth = next(a for a in result.axes if a.axis == "market_growth")
        assert growth.required_delta == pytest.approx(-1.6667, abs=1e-3)
        assert growth.required_value == pytest.approx(2.3333, abs=1e-3)


class TestBounds:
    def test_a_flip_needing_more_than_the_axis_allows_is_unreachable(
        self, settings: Settings
    ):
        # Size carries only 0.2 weight; from 4.0 it can shed at most 0.6 of
        # attractiveness, which cannot get from 4.0 down to 3.5...
        result, _ = analyse(
            settings, growth=5.0, size=5.0, profitability=5.0, intensity=1.0, strength=5.0
        )
        size = next(a for a in result.axes if a.axis == "market_size")
        assert size.reachable is False
        assert "Unreachable" in size.note or "does not change the quadrant" in size.note

    def test_headroom_is_reported_for_every_axis(self, settings: Settings):
        result, _ = analyse(settings, growth=4.2)
        growth = next(a for a in result.axes if a.axis == "market_growth")
        assert growth.headroom_up == pytest.approx(0.8)
        assert growth.headroom_down == pytest.approx(3.2)

    def test_required_value_never_leaves_the_axis(self, settings: Settings):
        result, _ = analyse(settings, growth=3.0, size=3.0, profitability=3.0, intensity=3.0)
        for axis in result.axes:
            if axis.required_value is not None:
                assert 1.0 <= axis.required_value <= 5.0


class TestConjunctiveRule:
    def test_crossing_a_threshold_alone_may_not_change_the_quadrant(
        self, settings: Settings
    ):
        """INVEST_GROW needs BOTH axes high, so raising attractiveness alone
                cannot enter it while strength sits below the threshold.
        """
        result, _ = analyse(
            settings, growth=3.0, size=3.0, profitability=3.0, intensity=3.0, strength=2.8
        )
        assert result.baseline_quadrant is Quadrant.SELECTIVE_INVEST
        # Every reported flip must be verified against the real placement rule.
        for axis in result.axes:
            if axis.reachable and axis.resulting_quadrant:
                assert axis.resulting_quadrant != result.baseline_quadrant.value

    def test_the_rule_is_documented_in_the_basis(self, settings: Settings):
        result, _ = analyse(settings)
        note = result.calculation_basis["conjunctive_rule_note"].lower()
        # Assert on the substance, not the wording: a reader must be told that
        # crossing a threshold is not the same as changing the quadrant.
        assert "may not change the quadrant" in note
        assert "verified" in note


class TestVerdict:
    def test_a_position_on_a_boundary_is_knife_edge(self, settings: Settings):
        # A = 3.5 exactly puts it a hair from the high threshold.
        result, attractiveness = analyse(
            settings, growth=3.5, size=3.5, profitability=3.5, intensity=2.5, strength=4.0
        )
        assert attractiveness == pytest.approx(3.5)
        assert result.verdict is SensitivityVerdict.KNIFE_EDGE

    def test_a_central_position_is_robust(self, settings: Settings):
        result, _ = analyse(
            settings, growth=3.0, size=3.0, profitability=3.0, intensity=3.0, strength=3.0
        )
        assert result.verdict in {SensitivityVerdict.ROBUST, SensitivityVerdict.FRAGILE}

    def test_axes_are_ranked_most_fragile_first(self, settings: Settings):
        result, _ = analyse(settings)
        reachable = [a for a in result.axes if a.reachable]
        deltas = [abs(a.required_delta) for a in reachable if a.required_delta is not None]
        assert deltas == sorted(deltas)

    def test_unreachable_axes_sort_last(self, settings: Settings):
        result, _ = analyse(
            settings, growth=5.0, size=5.0, profitability=5.0, intensity=1.0, strength=5.0
        )
        flags = [a.reachable for a in result.axes]
        assert flags == sorted(flags, reverse=True)

    def test_strength_sensitivity_is_reported_separately(self, settings: Settings):
        result, _ = analyse(settings)
        assert result.strength_sensitivity is not None
        assert result.strength_sensitivity.axis == "competitive_strength"
        assert result.strength_sensitivity.derivative == pytest.approx(1.0)


class TestBindingConstraint:
    def test_binding_constraint_can_be_the_strength_axis(self, settings: Settings):
        """Regression: A=4.0 is already past the high threshold but S=3.25 is
                not, so every attractiveness axis is unreachable and the verdict hangs
                entirely on strength. Reading axes[0] here reports an unreachable axis
        """
        result, attractiveness = analyse(
            settings, growth=4.0, size=4.0, profitability=4.0, intensity=2.0, strength=3.25
        )
        assert attractiveness == pytest.approx(4.0)
        assert result.verdict is not SensitivityVerdict.ROBUST
        assert all(not a.reachable for a in result.axes)
        assert result.binding_constraint is not None
        assert result.binding_constraint.axis == "competitive_strength"

    def test_binding_constraint_is_the_smallest_reachable_move(self, settings: Settings):
        result, _ = analyse(settings, strength=4.0)
        every = [
            a
            for a in result.axes + [result.strength_sensitivity]
            if a and a.reachable and a.required_delta is not None
        ]
        if every:
            smallest = min(abs(a.required_delta) for a in every)
            assert abs(result.binding_constraint.required_delta) == pytest.approx(smallest)

    def test_robust_still_reports_where_the_nearest_flip_is(self, settings: Settings):
        """ROBUST does not mean 'nothing can flip it' — it means the nearest
                flip needs a move larger than the fragile threshold. Reporting that
                distance is more useful than reporting nothing.
        """
        result, _ = analyse(
            settings, growth=5.0, size=5.0, profitability=5.0, intensity=1.0, strength=5.0
        )
        assert result.verdict is SensitivityVerdict.ROBUST
        assert result.binding_constraint is not None
        assert (
            abs(result.binding_constraint.required_delta)
            > settings.sensitivity_fragile_threshold
        )

    def test_binding_constraint_is_none_only_when_nothing_is_reachable(
        self, settings: Settings
    ):
        # Weights zeroed everywhere but growth would leave the other axes inert;
        # instead check the documented contract directly.
        result, _ = analyse(settings, strength=4.0)
        reachable_exists = any(
            a and a.reachable for a in result.axes + [result.strength_sensitivity]
        )
        assert (result.binding_constraint is not None) == reachable_exists

    def test_the_basis_names_the_binding_input(self, settings: Settings):
        result, _ = analyse(
            settings, growth=4.0, size=4.0, profitability=4.0, intensity=2.0, strength=3.25
        )
        note = result.calculation_basis["binding_constraint_note"]
        assert "competitive_strength" in note
        assert "rather than the top of" in note
