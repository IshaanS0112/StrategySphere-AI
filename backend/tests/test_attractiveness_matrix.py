"""GE-McKinsey matrix.

The two things worth pinning hard: the weighted sum stays on the 1-5 axis (it
does not if the weights drift off 1.0), and the competitive-strength correction
reduces exactly to the unadjusted strength mean when its penalty is switched
off. The second is what makes the deviation a deliberate correction rather than
a different formula wearing the same name.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.enums import Quadrant, SwotCategory
from app.services.attractiveness_matrix import (
    compute_competitive_strength,
    place_quadrant,
    run_attractiveness_matrix,
)
from app.services.swot_engine import SwotFactor, SwotResult


def swot_with(strengths: list[int], weaknesses: list[int] | None = None) -> SwotResult:
    result = SwotResult()
    for index, score in enumerate(strengths):
        result.strengths.append(
            SwotFactor(
                factor=f"S{index}",
                category=SwotCategory.STRENGTH,
                evidence="fixture",
                impact_score=score,
                source="computed_financial",
            )
        )
    for index, score in enumerate(weaknesses or []):
        result.weaknesses.append(
            SwotFactor(
                factor=f"W{index}",
                category=SwotCategory.WEAKNESS,
                evidence="fixture",
                impact_score=score,
                source="computed_financial",
            )
        )
    return result


class TestCompetitiveStrength:
    def test_average_of_strengths_when_weaknesses_are_neutral(self, settings: Settings):
        score, _ = compute_competitive_strength(swot_with([4, 4, 5], [3, 3]), settings)
        assert score == pytest.approx(13 / 3, abs=1e-4)

    def test_weaknesses_pull_the_score_down(self, settings: Settings):
        without, _ = compute_competitive_strength(swot_with([5, 5], [3]), settings)
        with_weak, _ = compute_competitive_strength(swot_with([5, 5], [5, 5]), settings)
        assert with_weak < without

    def test_penalty_zero_reproduces_the_unadjusted_mean(self):
        """The documented deviation must be switchable, or it is not a deviation."""
        unadjusted = Settings(_env_file=None, swot_weakness_penalty=0.0)
        swot = swot_with([4, 2, 5], [5, 5, 5])
        score, basis = compute_competitive_strength(swot, unadjusted)
        assert score == pytest.approx(basis["unadjusted_strength_mean"])
        assert score == pytest.approx((4 + 2 + 5) / 3, abs=1e-4)

    def test_nothing_scored_at_all_is_neutral_and_warns(self, settings: Settings):
        score, basis = compute_competitive_strength(swot_with([], []), settings)
        assert score == pytest.approx(3.0)
        assert "warning" in basis, "an absence of evidence must be flagged, not scored as average"

    def test_only_weaknesses_puts_the_axis_on_the_floor(self, settings: Settings):
        """Regression: a company evaluated on nine metrics that produced only
        weaknesses used to score 2.56 and land in SELECTIVE_INVEST. Zero
        strengths against real weaknesses is a finding, not a data gap."""
        score, basis = compute_competitive_strength(swot_with([], [4, 4, 4, 3, 5]), settings)
        assert score == pytest.approx(1.0)
        assert basis["strength_factor_count"] == 0
        assert "floor" in basis["base_reason"]

    def test_only_weaknesses_reaches_harvest_divest(self, settings: Settings):
        result = run_attractiveness_matrix(
            market_data={
                "market_growth_pct": 1.5,
                "market_size_usd_bn": 3.0,
                "industry_operating_margin_pct": 5.0,
            },
            swot=swot_with([], [4, 4, 4, 3, 5]),
            competitive_intensity_score=3.0,
            settings=settings,
        )
        assert result.quadrant is Quadrant.HARVEST_DIVEST

    def test_score_is_clamped_to_the_axis(self, settings: Settings):
        score, basis = compute_competitive_strength(swot_with([1], [5, 5, 5, 5]), settings)
        assert 1.0 <= score <= 5.0
        assert basis["clamped"] is True


class TestQuadrantPlacement:
    @pytest.mark.parametrize(
        ("attractiveness", "strength", "expected"),
        [
            (4.5, 4.5, Quadrant.INVEST_GROW),
            (3.51, 3.51, Quadrant.INVEST_GROW),
            (3.5, 3.5, Quadrant.SELECTIVE_INVEST),    # strictly greater than, not >=
            (4.5, 2.0, Quadrant.SELECTIVE_INVEST),
            (2.0, 4.5, Quadrant.SELECTIVE_INVEST),
            (2.49, 2.49, Quadrant.HARVEST_DIVEST),
            (2.5, 2.5, Quadrant.SELECTIVE_INVEST),    # strictly less than, not <=
            (1.0, 1.0, Quadrant.HARVEST_DIVEST),
        ],
    )
    def test_boundaries(self, attractiveness, strength, expected, settings: Settings):
        quadrant, _, _ = place_quadrant(attractiveness, strength, settings)
        assert quadrant is expected

    def test_position_near_a_boundary_is_flagged_borderline(self, settings: Settings):
        _, borderline, basis = place_quadrant(3.55, 3.60, settings)
        assert borderline is True
        assert "borderline_note" in basis

    def test_position_far_from_every_boundary_is_not_borderline(self, settings: Settings):
        _, borderline, _ = place_quadrant(4.8, 4.9, settings)
        assert borderline is False

    def test_distances_to_all_four_boundaries_are_reported(self, settings: Settings):
        _, _, basis = place_quadrant(3.0, 3.0, settings)
        assert set(basis["distance_to_boundaries"]) == {
            "attractiveness_to_high",
            "attractiveness_to_low",
            "strength_to_high",
            "strength_to_low",
        }


class TestAttractivenessScore:
    def test_all_axes_maximum_gives_exactly_five(self, settings: Settings):
        """The weighted sum must stay on the 1-5 axis. It only does if weights sum to 1."""
        result = run_attractiveness_matrix(
            market_data={
                "market_growth_pct": 100.0,
                "market_size_usd_bn": 500.0,
                "industry_operating_margin_pct": 60.0,
            },
            swot=swot_with([5, 5]),
            competitive_intensity_score=1.0,   # inverted to 5
            settings=settings,
        )
        assert result.overall_attractiveness_score == pytest.approx(5.0)
        assert result.quadrant is Quadrant.INVEST_GROW

    def test_all_axes_minimum_gives_exactly_one(self, settings: Settings):
        result = run_attractiveness_matrix(
            market_data={
                "market_growth_pct": 0.0,
                "market_size_usd_bn": 0.0,
                "industry_operating_margin_pct": 0.0,
            },
            swot=swot_with([1]),
            competitive_intensity_score=5.0,   # inverted to 1
            settings=settings,
        )
        assert result.overall_attractiveness_score == pytest.approx(1.0)
        assert result.quadrant is Quadrant.HARVEST_DIVEST

    def test_hand_computed_case(self, settings: Settings):
        # growth 18 -> 5, size 40 -> 4, profitability 20 -> 4, intensity 2 -> 6-2 = 4
        # 0.3*5 + 0.2*4 + 0.3*4 + 0.2*4 = 1.5 + 0.8 + 1.2 + 0.8 = 4.3
        result = run_attractiveness_matrix(
            market_data={
                "market_growth_pct": 18.0,
                "market_size_usd_bn": 40.0,
                "industry_operating_margin_pct": 20.0,
            },
            swot=swot_with([4, 4]),
            competitive_intensity_score=2.0,
            settings=settings,
        )
        assert result.overall_attractiveness_score == pytest.approx(4.3, abs=1e-6)

    def test_higher_intensity_lowers_attractiveness(self, settings: Settings):
        market = {
            "market_growth_pct": 12.0,
            "market_size_usd_bn": 30.0,
            "industry_operating_margin_pct": 18.0,
        }
        calm = run_attractiveness_matrix(
            market_data=market,
            swot=swot_with([4]),
            competitive_intensity_score=1.0,
            settings=settings,
        )
        brutal = run_attractiveness_matrix(
            market_data=market,
            swot=swot_with([4]),
            competitive_intensity_score=5.0,
            settings=settings,
        )
        assert brutal.overall_attractiveness_score < calm.overall_attractiveness_score

    def test_missing_axes_are_imputed_neutral_and_disclosed(self, settings: Settings):
        result = run_attractiveness_matrix(
            market_data={},
            swot=swot_with([4]),
            competitive_intensity_score=3.0,
            settings=settings,
        )
        assert set(result.calculation_basis["imputed_axes"]) == {
            "market_growth",
            "market_size",
            "industry_profitability",
        }
        assert "imputed" in result.calculation_basis["confidence_note"]

    def test_weighted_terms_sum_to_the_headline_score(self, settings: Settings):
        result = run_attractiveness_matrix(
            market_data={
                "market_growth_pct": 7.0,
                "market_size_usd_bn": 9.0,
                "industry_operating_margin_pct": 11.0,
            },
            swot=swot_with([3]),
            competitive_intensity_score=3.4,
            settings=settings,
        )
        terms = result.calculation_basis["weighted_terms"]
        assert sum(terms.values()) == pytest.approx(result.overall_attractiveness_score, abs=1e-3)


class TestWeightValidation:
    def test_weights_that_do_not_sum_to_one_are_rejected_at_config_load(self):
        with pytest.raises(ValueError, match="must sum to 1.0"):
            Settings(_env_file=None, attractiveness_w_growth=0.9)

    def test_inverted_quadrant_thresholds_are_rejected(self):
        with pytest.raises(ValueError, match="quadrant_low_threshold"):
            Settings(_env_file=None, quadrant_low_threshold=4.0)
