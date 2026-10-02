"""Pricing."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.enums import MarginBasis
from app.services.pricing_engine import (
    PricingInputError,
    compute_value_adjustment,
    cost_plus_price,
    run_pricing_engine,
)


class TestCostPlusAnchor:
    def test_margin_basis_actually_delivers_the_target_margin(self):
        price = cost_plus_price(100.0, 0.40, MarginBasis.MARGIN)
        assert price == pytest.approx(166.6667, abs=1e-3)
        realised = (price - 100.0) / price
        assert realised == pytest.approx(0.40, abs=1e-9)

    def test_markup_basis_does_not(self):
        """The textbook shorthand, cost x (1 + m). A 40% 'margin' is really 28.6%."""
        price = cost_plus_price(100.0, 0.40, MarginBasis.MARKUP)
        assert price == pytest.approx(140.0)
        realised = (price - 100.0) / price
        assert realised == pytest.approx(0.2857, abs=1e-4)

    def test_the_two_bases_agree_only_at_zero(self):
        assert cost_plus_price(100.0, 0.0, MarginBasis.MARGIN) == pytest.approx(
            cost_plus_price(100.0, 0.0, MarginBasis.MARKUP)
        )

    def test_margin_of_one_hundred_percent_is_rejected(self):
        with pytest.raises(PricingInputError, match="unachievable"):
            cost_plus_price(100.0, 1.0, MarginBasis.MARGIN)

    def test_zero_cost_is_allowed_by_the_anchor_but_not_by_the_engine(self, settings: Settings):
        assert cost_plus_price(0.0, 0.4, MarginBasis.MARGIN) == 0.0
        with pytest.raises(PricingInputError, match="greater than zero"):
            run_pricing_engine(
                cost_base=0.0,
                target_margin_pct=0.4,
                margin_basis=MarginBasis.MARGIN,
                competitors=[],
                company_feature_scores={},
                settings=settings,
            )


class TestValueAdjustment:
    def test_better_features_raise_the_factor(self, competitors, settings: Settings):
        factor, basis = compute_value_adjustment(
            company_feature_scores={"speed": 5, "support": 5, "uptime": 5},
            competitor_feature_scores=[c["feature_scores"] for c in competitors],
            settings=settings,
        )
        assert factor > 1.0
        assert basis["applied"] is True

    def test_worse_features_lower_the_factor(self, competitors, settings: Settings):
        factor, _ = compute_value_adjustment(
            company_feature_scores={"speed": 1, "support": 1, "uptime": 1},
            competitor_feature_scores=[c["feature_scores"] for c in competitors],
            settings=settings,
        )
        assert factor < 1.0

    def test_only_shared_features_are_compared(self, settings: Settings):
        _, basis = compute_value_adjustment(
            company_feature_scores={"speed": 5, "onboarding": 5},
            competitor_feature_scores=[{"speed": 3, "support": 1}],
            settings=settings,
        )
        assert basis["shared_features"] == ["speed"]
        assert set(basis["dropped_features"]) == {"onboarding", "support"}

    def test_no_shared_features_means_no_adjustment(self, settings: Settings):
        factor, basis = compute_value_adjustment(
            company_feature_scores={"onboarding": 5},
            competitor_feature_scores=[{"speed": 1}],
            settings=settings,
        )
        assert factor == 1.0
        assert basis["applied"] is False

    def test_extreme_delta_is_clamped(self, settings: Settings):
        # A 4-point gap at k=0.10 would be 1.40 unclamped; the cap is 0.30.
        factor, basis = compute_value_adjustment(
            company_feature_scores={"speed": 5},
            competitor_feature_scores=[{"speed": 1}],
            settings=Settings(_env_file=None, pricing_value_coefficient=0.5),
        )
        assert factor == pytest.approx(1.30)
        assert basis["clamped"] is True


class TestRecommendation:
    def test_hand_computed_blend(self, competitors, settings: Settings):
        # cost 60, margin 0.4 MARGIN -> anchor 100.0 competitor mean of (100, 110,
        # 95, 105) = 102.5 blend 0.5/0.5 -> 101.25 company features {speed 3,
        # support 3, uptime 3} = 3.0 competitor shared-feature averages: A 10/3, B
        # 3.0, C 3.0, D 8/3 mean = (3.3333 + 3.0 + 3.0 + 2.6667)/4 = 3.0 delta 0 ->
        # factor 1.0 -> recommended 101.25
        result = run_pricing_engine(
            cost_base=60.0,
            target_margin_pct=0.40,
            margin_basis=MarginBasis.MARGIN,
            competitors=competitors,
            company_feature_scores={"speed": 3, "support": 3, "uptime": 3},
            settings=settings,
        )
        assert result.cost_plus_price == pytest.approx(100.0, abs=1e-3)
        assert result.competitor_avg_price == pytest.approx(102.5)
        assert result.value_adjustment_factor == pytest.approx(1.0, abs=1e-6)
        assert result.recommended_price == pytest.approx(101.25, abs=1e-3)

    def test_range_brackets_the_point_estimate(self, competitors, settings: Settings):
        result = run_pricing_engine(
            cost_base=60.0,
            target_margin_pct=0.40,
            margin_basis=MarginBasis.MARGIN,
            competitors=competitors,
            company_feature_scores={"speed": 3, "support": 3, "uptime": 3},
            settings=settings,
        )
        band = result.recommended_price_range
        assert band["min"] < band["optimal"] < band["max"]
        assert band["min"] == pytest.approx(result.recommended_price * 0.9, abs=1e-3)
        assert band["max"] == pytest.approx(result.recommended_price * 1.1, abs=1e-3)

    def test_implied_margin_matches_the_target_on_a_pure_cost_plus_run(self, settings: Settings):
        result = run_pricing_engine(
            cost_base=100.0,
            target_margin_pct=0.35,
            margin_basis=MarginBasis.MARGIN,
            competitors=[],
            company_feature_scores={},
            settings=settings,
        )
        # No competitors, no value adjustment: the recommendation IS the anchor,
        # so the implied margin must be exactly the target.
        assert result.implied_margin_pct == pytest.approx(35.0, abs=1e-6)

    def test_no_competitors_collapses_weight_onto_cost_plus(self, settings: Settings):
        result = run_pricing_engine(
            cost_base=100.0,
            target_margin_pct=0.25,
            margin_basis=MarginBasis.MARGIN,
            competitors=[],
            company_feature_scores={"speed": 5},
            settings=settings,
        )
        assert result.competitor_avg_price is None
        assert result.calculation_basis["weights"] == {
            "cost_plus": 1.0,
            "competitor_benchmark": 0.0,
        }
        assert result.recommended_price == pytest.approx(result.cost_plus_price)

    def test_price_is_floored_at_cost(self, settings: Settings):
        """A cost-plus engine must never recommend selling below cost."""
        result = run_pricing_engine(
            cost_base=500.0,
            target_margin_pct=0.0,
            margin_basis=MarginBasis.MARGIN,
            competitors=[{"competitor_name": "Cheap", "price_point": 10.0, "feature_scores": {}}],
            company_feature_scores={},
            settings=settings,
        )
        # blend = 0.5*500 + 0.5*10 = 255, which is below the 500 cost base.
        assert result.calculation_basis["raw_recommended_before_floor"] == pytest.approx(255.0)
        assert result.recommended_price == pytest.approx(500.0)
        assert result.calculation_basis["price_floor_applied"] is True
        assert result.recommended_price_range["min"] == pytest.approx(500.0)
        assert result.implied_margin_pct == pytest.approx(0.0)

    def test_wide_competitor_dispersion_downgrades_confidence(self, settings: Settings):
        result = run_pricing_engine(
            cost_base=50.0,
            target_margin_pct=0.3,
            margin_basis=MarginBasis.MARGIN,
            competitors=[
                {"competitor_name": "A", "price_point": 10.0, "feature_scores": {"speed": 3}},
                {"competitor_name": "B", "price_point": 400.0, "feature_scores": {"speed": 3}},
            ],
            company_feature_scores={"speed": 3},
            settings=settings,
        )
        assert result.confidence in {"LOW", "MEDIUM"}
        assert any("vary widely" in w for w in result.reasoning["warnings"])

    def test_clean_inputs_produce_high_confidence(self, competitors, settings: Settings):
        result = run_pricing_engine(
            cost_base=60.0,
            target_margin_pct=0.4,
            margin_basis=MarginBasis.MARGIN,
            competitors=competitors,
            company_feature_scores={"speed": 4, "support": 4, "uptime": 4},
            settings=settings,
        )
        assert result.confidence == "HIGH"
        assert result.reasoning["warnings"] == []

    def test_margin_basis_note_shows_both_numbers(self, settings: Settings):
        result = run_pricing_engine(
            cost_base=100.0,
            target_margin_pct=0.40,
            margin_basis=MarginBasis.MARGIN,
            competitors=[],
            company_feature_scores={},
            settings=settings,
        )
        note = result.reasoning["margin_basis_note"]
        assert "166.67" in note and "140.00" in note

    def test_non_numeric_and_negative_prices_are_ignored(self, settings: Settings):
        result = run_pricing_engine(
            cost_base=50.0,
            target_margin_pct=0.2,
            margin_basis=MarginBasis.MARGIN,
            competitors=[
                {"competitor_name": "Good", "price_point": 100.0, "feature_scores": {}},
                {"competitor_name": "Null", "price_point": None, "feature_scores": {}},
                {"competitor_name": "Bool", "price_point": True, "feature_scores": {}},
                {"competitor_name": "Negative", "price_point": -20.0, "feature_scores": {}},
            ],
            settings=settings,
            company_feature_scores={},
        )
        assert result.calculation_basis["competitor_prices"] == [100.0]
