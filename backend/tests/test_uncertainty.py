"""Determinism, entropy bounds, and the degenerate cases."""

from __future__ import annotations

import math

import pytest

from app.config import Settings
from app.enums import Quadrant, VerdictStability
from app.services.attractiveness_matrix import run_attractiveness_matrix
from app.services.swot_engine import SwotResult
from app.services.uncertainty import (
    SUPPORTED_INPUTS,
    ThreePoint,
    UncertaintyInputError,
    parse_three_point,
    percentile,
    pert_parameters,
    run_uncertainty_analysis,
    shannon_entropy_bits,
    stability_band,
)

GROWTH_MARKET = {
    "market_growth_pct": 18.0,
    "market_size_usd_bn": 42.0,
    "industry_operating_margin_pct": 17.0,
}


def run(settings: Settings, **overrides):
    payload = {
        "market_data": GROWTH_MARKET,
        "uncertainty_inputs": None,
        "competitive_intensity_score": 3.0,
        "competitive_strength_score": 3.6,
        "point_attractiveness": 3.8,
        "point_strength": 3.6,
        "point_quadrant": Quadrant.INVEST_GROW.value,
        "settings": settings,
    }
    payload.update(overrides)
    return run_uncertainty_analysis(**payload)


class TestDeterminism:
    def test_the_same_inputs_and_seed_give_identical_probabilities(self, settings):
        inputs = {"market_growth_pct": {"low": 9.0, "mode": 18.0, "high": 24.0}}
        first = run(settings, uncertainty_inputs=inputs)
        second = run(settings, uncertainty_inputs=inputs)
        assert first.quadrant_probabilities == second.quadrant_probabilities
        assert first.entropy_bits == second.entropy_bits
        assert first.attractiveness_ci == second.attractiveness_ci

    def test_the_pinned_numbers_do_not_drift(self, settings):
        # If a refactor changes the sampling order or the RNG draw sequence,
        # every number this project publishes silently moves. Pinned exactly.
        result = run(
            settings,
            uncertainty_inputs={
                "market_growth_pct": {"low": 9.0, "mode": 18.0, "high": 24.0},
                "competitive_strength_score": {"low": 3.2, "mode": 3.6, "high": 4.0},
            },
        )
        assert result.seed == 20260921
        assert result.draws == 10000
        assert result.quadrant_probabilities["INVEST_GROW"] == pytest.approx(0.7147, abs=1e-4)
        assert result.entropy_bits == pytest.approx(0.8626, abs=1e-4)

    def test_a_different_seed_gives_a_different_sample(self, settings):
        inputs = {"market_growth_pct": {"low": 3.0, "mode": 10.0, "high": 20.0}}
        other = Settings(_env_file=None, uncertainty_seed=settings.uncertainty_seed + 1)
        assert (
            run(settings, uncertainty_inputs=inputs).quadrant_probabilities
            != run(other, uncertainty_inputs=inputs).quadrant_probabilities
        )


class TestDegenerateCases:
    def test_no_distributions_at_all_collapses_to_the_point_verdict(self, settings):
        result = run(settings)
        assert result.quadrant_probabilities[Quadrant.INVEST_GROW.value] == 1.0
        assert result.entropy_bits == 0.0
        assert result.verdict_stability is VerdictStability.DECISIVE

    def test_a_zero_width_range_is_a_point_estimate(self, settings):
        result = run(
            settings,
            uncertainty_inputs={"market_growth_pct": {"low": 18.0, "mode": 18.0, "high": 18.0}},
        )
        assert result.entropy_bits == 0.0
        assert result.attractiveness_ci[0] == result.attractiveness_ci[1]

    def test_probabilities_always_sum_to_one(self, settings):
        result = run(
            settings,
            uncertainty_inputs={"competitive_strength_score": {"low": 1.0, "mode": 3.0, "high": 5.0}},
        )
        assert sum(result.quadrant_probabilities.values()) == pytest.approx(1.0, abs=1e-6)

    def test_every_quadrant_is_reachable_from_a_wide_enough_range(self, settings):
        result = run(
            settings,
            competitive_strength_score=3.0,
            uncertainty_inputs={
                "market_growth_pct": {"low": 0.0, "mode": 10.0, "high": 40.0},
                "market_size_usd_bn": {"low": 0.1, "mode": 20.0, "high": 200.0},
                "industry_operating_margin_pct": {"low": 0.0, "mode": 12.0, "high": 40.0},
                "competitive_strength_score": {"low": 1.0, "mode": 3.0, "high": 5.0},
            },
        )
        assert all(p > 0 for p in result.quadrant_probabilities.values())


class TestInputValidation:
    def test_a_mode_outside_its_range_is_rejected_not_clamped(self):
        with pytest.raises(UncertaintyInputError) as exc:
            parse_three_point("market_growth_pct", {"low": 1.0, "mode": 9.0, "high": 5.0})
        assert "outside" in str(exc.value)

    def test_low_above_high_is_rejected(self):
        with pytest.raises(UncertaintyInputError):
            parse_three_point("x", {"low": 10.0, "mode": 10.0, "high": 2.0})

    def test_a_missing_field_is_named(self):
        with pytest.raises(UncertaintyInputError) as exc:
            parse_three_point("x", {"low": 1.0, "high": 2.0})
        assert "mode" in str(exc.value)

    def test_non_numeric_bounds_are_rejected(self):
        with pytest.raises(UncertaintyInputError):
            parse_three_point("x", {"low": "a", "mode": "b", "high": "c"})

    def test_a_plain_number_is_not_a_distribution(self):
        assert parse_three_point("x", 18.0) is None

    def test_an_unsupported_input_key_is_refused_loudly(self, settings):
        # Silently ignoring it would report a tighter distribution than the one
        # the analyst described, which is the worst possible failure here.
        with pytest.raises(UncertaintyInputError) as exc:
            run(settings, uncertainty_inputs={"gross_margin_pct": {"low": 1, "mode": 2, "high": 3}})
        assert "gross_margin_pct" in str(exc.value)

    def test_the_supported_set_is_exactly_what_the_matrix_reads(self):
        assert set(SUPPORTED_INPUTS) == {
            "market_growth_pct",
            "market_size_usd_bn",
            "industry_operating_margin_pct",
            "competitive_intensity_score",
            "competitive_strength_score",
        }


class TestEntropy:
    def test_a_certain_verdict_has_zero_entropy(self):
        assert shannon_entropy_bits({"a": 1.0, "b": 0.0, "c": 0.0}) == 0.0

    def test_a_three_way_split_is_log2_three(self):
        third = 1.0 / 3.0
        assert shannon_entropy_bits({"a": third, "b": third, "c": third}) == pytest.approx(
            math.log2(3), abs=1e-9
        )

    def test_entropy_never_exceeds_the_configured_maximum(self, settings):
        assert shannon_entropy_bits({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}) <= (
            settings.max_entropy_bits + 1e-9
        )

    @pytest.mark.parametrize(
        "bits,expected",
        [
            (0.0, VerdictStability.DECISIVE),
            (0.24, VerdictStability.DECISIVE),
            (0.25, VerdictStability.LEANING),
            (0.84, VerdictStability.LEANING),
            (0.85, VerdictStability.CONTESTED),
            (1.58, VerdictStability.CONTESTED),
        ],
    )
    def test_the_band_edges(self, settings, bits, expected):
        assert stability_band(bits, settings) is expected

    def test_a_wide_range_raises_entropy(self, settings):
        tight = run(
            settings,
            uncertainty_inputs={"competitive_strength_score": {"low": 3.55, "mode": 3.6, "high": 3.65}},
        )
        wide = run(
            settings,
            uncertainty_inputs={"competitive_strength_score": {"low": 1.5, "mode": 3.6, "high": 5.0}},
        )
        assert wide.entropy_bits > tight.entropy_bits


class TestPertSampling:
    def test_the_beta_parameters_match_the_published_formula(self):
        alpha, beta = pert_parameters(ThreePoint("x", 0.0, 0.5, 1.0), 4.0)
        assert (alpha, beta) == (3.0, 3.0)

    def test_a_mode_at_the_low_end_skews_the_distribution(self, settings):
        alpha, beta = pert_parameters(ThreePoint("x", 0.0, 0.0, 1.0), 4.0)
        assert alpha == 1.0 and beta == 5.0

    def test_draws_stay_inside_the_stated_range(self, settings):
        import random

        from app.services.uncertainty import sample_once

        estimate = ThreePoint("x", 2.0, 7.0, 11.0)
        rng = random.Random(1)
        draws = [sample_once(estimate, rng, settings) for _ in range(2000)]
        assert min(draws) >= 2.0
        assert max(draws) <= 11.0

    def test_the_sample_mean_approaches_the_pert_mean(self, settings):
        import random

        from app.services.uncertainty import sample_once

        estimate = ThreePoint("x", 0.0, 2.0, 10.0)
        expected = (0.0 + 4.0 * 2.0 + 10.0) / 6.0
        rng = random.Random(7)
        draws = [sample_once(estimate, rng, settings) for _ in range(20000)]
        assert sum(draws) / len(draws) == pytest.approx(expected, abs=0.05)

    @pytest.mark.parametrize("kind", ["PERT", "TRIANGULAR", "UNIFORM"])
    def test_every_distribution_is_selectable_and_recorded(self, kind):
        settings = Settings(_env_file=None, uncertainty_distribution=kind)
        result = run(
            settings,
            uncertainty_inputs={"market_growth_pct": {"low": 3.0, "mode": 12.0, "high": 20.0}},
        )
        assert result.calculation_basis["distribution"] == kind

    def test_uniform_and_pert_disagree_on_a_skewed_estimate(self):
        skewed = {"market_growth_pct": {"low": 3.0, "mode": 3.5, "high": 30.0}}
        pert = run(Settings(_env_file=None, uncertainty_distribution="PERT"), uncertainty_inputs=skewed)
        uniform = run(
            Settings(_env_file=None, uncertainty_distribution="UNIFORM"), uncertainty_inputs=skewed
        )
        # Uniform throws the mode away, so it puts far more mass at the top of
        # the range. If these agreed, the mode would not be doing anything.
        assert uniform.quadrant_probabilities != pert.quadrant_probabilities


class TestCredibleIntervals:
    def test_the_interval_brackets_the_point_estimate(self, settings):
        result = run(
            settings,
            uncertainty_inputs={"competitive_strength_score": {"low": 3.0, "mode": 3.6, "high": 4.2}},
        )
        low, high = result.strength_ci
        assert low <= 3.6 <= high

    def test_a_wider_interval_setting_widens_the_band(self):
        inputs = {"competitive_strength_score": {"low": 1.0, "mode": 3.0, "high": 5.0}}
        narrow = run(Settings(_env_file=None, uncertainty_credible_interval_pct=50.0), uncertainty_inputs=inputs)
        wide = run(Settings(_env_file=None, uncertainty_credible_interval_pct=99.0), uncertainty_inputs=inputs)
        assert (wide.strength_ci[1] - wide.strength_ci[0]) > (
            narrow.strength_ci[1] - narrow.strength_ci[0]
        )

    def test_percentiles_interpolate(self):
        assert percentile([0.0, 1.0], 0.5) == pytest.approx(0.5)
        assert percentile([0.0, 10.0, 20.0], 0.0) == 0.0
        assert percentile([0.0, 10.0, 20.0], 1.0) == 20.0

    def test_strength_draws_are_clamped_to_the_axis(self, settings):
        result = run(
            settings,
            uncertainty_inputs={"competitive_strength_score": {"low": -5.0, "mode": 3.0, "high": 12.0}},
        )
        assert result.strength_ci[0] >= 1.0
        assert result.strength_ci[1] <= 5.0


class TestAgreementWithThePointPipeline:
    def test_a_point_run_reproduces_the_matrix_exactly(self, settings):
        # The Monte Carlo must use the same band-scoring and weighted sum the matrix
        # uses.
        matrix = run_attractiveness_matrix(
            market_data=GROWTH_MARKET,
            swot=SwotResult(),
            competitive_intensity_score=3.0,
            settings=settings,
        )
        result = run(
            settings,
            competitive_strength_score=matrix.competitive_strength_score,
            point_attractiveness=matrix.overall_attractiveness_score,
            point_strength=matrix.competitive_strength_score,
            point_quadrant=matrix.quadrant.value,
        )
        assert result.attractiveness_ci[0] == pytest.approx(
            matrix.overall_attractiveness_score, abs=1e-9
        )

    def test_missing_market_axes_are_imputed_neutral_as_the_matrix_does(self, settings):
        matrix = run_attractiveness_matrix(
            market_data={},
            swot=SwotResult(),
            competitive_intensity_score=3.0,
            settings=settings,
        )
        result = run(settings, market_data={}, competitive_strength_score=3.0)
        assert result.attractiveness_ci[0] == pytest.approx(
            matrix.overall_attractiveness_score, abs=1e-9
        )


class TestTheStatedLimits:
    def test_the_basis_says_in_words_that_the_distributions_are_analyst_supplied(self, settings):
        basis = run(settings).calculation_basis
        key = "THE DISTRIBUTIONS ARE ANALYST-SUPPLIED"
        assert key in basis
        assert "not an objective probability" in basis[key].lower()

    def test_the_basis_explains_how_this_differs_from_sensitivity(self, settings):
        text = run(settings).calculation_basis["versus_sensitivity_analysis"]
        assert "DIFFERENT question" in text
        assert "disagree" in text

    def test_inputs_held_fixed_are_listed_with_the_lower_bound_warning(self, settings):
        basis = run(
            settings, uncertainty_inputs={"market_growth_pct": {"low": 9.0, "mode": 18.0, "high": 24.0}}
        ).calculation_basis
        assert "market_size_usd_bn" in basis["held_fixed"]
        assert "LOWER BOUND" in basis["held_fixed_note"]

    def test_the_point_verdict_is_carried_beside_the_distribution(self, settings):
        result = run(settings, point_quadrant=Quadrant.INVEST_GROW.value)
        assert result.point_verdict == Quadrant.INVEST_GROW.value
