"""Market concentration and derived competitive intensity."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.enums import MarketConcentration
from app.services.market_structure import (
    assess_market_structure,
    classify_concentration,
    compute_hhi,
    price_dispersion,
)


class TestHHI:
    def test_monopoly_is_ten_thousand(self):
        assert compute_hhi([100.0]) == pytest.approx(10_000.0)

    def test_duopoly_of_equals_is_five_thousand(self):
        assert compute_hhi([50.0, 50.0]) == pytest.approx(5_000.0)

    def test_hand_computed(self):
        # 30^2 + 25^2 + 20^2 + 15^2 + 10^2 = 900+625+400+225+100 = 2250
        assert compute_hhi([30.0, 25.0, 20.0, 15.0, 10.0]) == pytest.approx(2_250.0)

    def test_fragmented_market_is_near_zero(self):
        assert compute_hhi([1.0] * 100) == pytest.approx(100.0)

    @pytest.mark.parametrize(
        ("hhi", "expected"),
        [
            (0.0, MarketConcentration.UNCONCENTRATED),
            (999.9, MarketConcentration.UNCONCENTRATED),
            (1000.0, MarketConcentration.MODERATELY_CONCENTRATED),
            (1800.0, MarketConcentration.MODERATELY_CONCENTRATED),
            (1800.1, MarketConcentration.HIGHLY_CONCENTRATED),
            (10_000.0, MarketConcentration.HIGHLY_CONCENTRATED),
        ],
    )
    def test_doj_ftc_bands(self, hhi: float, expected: MarketConcentration, settings: Settings):
        assert classify_concentration(hhi, settings) is expected


class TestPriceDispersion:
    def test_identical_prices_have_zero_dispersion(self):
        assert price_dispersion([100.0, 100.0, 100.0]) == pytest.approx(0.0)

    def test_single_price_is_undefined(self):
        assert price_dispersion([100.0]) is None

    def test_empty_is_undefined(self):
        assert price_dispersion([]) is None

    def test_cv_is_scale_invariant(self):
        small = price_dispersion([90.0, 110.0])
        large = price_dispersion([90_000.0, 110_000.0])
        assert small == pytest.approx(large)


class TestIntensityDerivation:
    def test_fragmented_market_scores_high_intensity(self, settings: Settings):
        result = assess_market_structure(
            company_market_share_pct=5.0,
            competitors=[
                {"competitor_name": f"C{i}", "market_share_pct": 5.0, "price_point": 100.0 + i}
                for i in range(15)
            ],
            analyst_intensity_override=None,
            settings=settings,
        )
        assert result.concentration is MarketConcentration.UNCONCENTRATED
        assert result.competitive_intensity_score >= 4.0

    def test_concentrated_market_scores_low_intensity(self, settings: Settings):
        result = assess_market_structure(
            company_market_share_pct=55.0,
            competitors=[
                {"competitor_name": "Other", "market_share_pct": 40.0, "price_point": 100.0},
            ],
            analyst_intensity_override=None,
            settings=settings,
        )
        assert result.concentration is MarketConcentration.HIGHLY_CONCENTRATED
        assert result.competitive_intensity_score <= 2.5

    def test_residual_share_is_reported(self, settings: Settings):
        result = assess_market_structure(
            company_market_share_pct=30.0,
            competitors=[{"competitor_name": "A", "market_share_pct": 20.0}],
            analyst_intensity_override=None,
            settings=settings,
        )
        assert result.residual_share_pct == pytest.approx(50.0)
        assert "atomistic fringe" in result.basis["residual_treatment"]

    def test_over_allocated_shares_are_warned_about(self, settings: Settings):
        result = assess_market_structure(
            company_market_share_pct=70.0,
            competitors=[{"competitor_name": "A", "market_share_pct": 60.0}],
            analyst_intensity_override=None,
            settings=settings,
        )
        assert result.basis["warnings"]
        assert result.residual_share_pct == pytest.approx(0.0)

    def test_no_shares_falls_back_to_the_analyst_override(self, settings: Settings):
        result = assess_market_structure(
            company_market_share_pct=None,
            competitors=[],
            analyst_intensity_override=4.5,
            settings=settings,
        )
        assert result.competitive_intensity_score == pytest.approx(4.5)
        assert result.basis["intensity_source"] == "analyst_override"

    def test_no_shares_and_no_override_is_neutral_and_says_so(self, settings: Settings):
        result = assess_market_structure(
            company_market_share_pct=None,
            competitors=[],
            analyst_intensity_override=None,
            settings=settings,
        )
        assert result.competitive_intensity_score == pytest.approx(3.0)
        assert result.basis["intensity_source"] == "neutral_default"
        assert "weakens the attractiveness score" in result.basis["note"]

    def test_intensity_never_leaves_the_axis(self, settings: Settings):
        for count in (1, 2, 5, 40):
            result = assess_market_structure(
                company_market_share_pct=100.0 / (count + 1),
                competitors=[
                    {
                        "competitor_name": f"C{i}",
                        "market_share_pct": 100.0 / (count + 1),
                        "price_point": 100.0,
                    }
                    for i in range(count)
                ],
                analyst_intensity_override=None,
                settings=settings,
            )
            assert 1.0 <= result.competitive_intensity_score <= 5.0
