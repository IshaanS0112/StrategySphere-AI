"""Porter's Five Forces.

The behaviour worth pinning hardest is what the engine does when it *cannot*
score a force. Returning 3.0 for an unmeasurable force would be a guess wearing
the same typeface as a computed HHI, which is the exact failure the whole
project is built to avoid.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.enums import ForceSource, IndustryAttractiveness, PorterForce
from app.services.market_structure import assess_market_structure
from app.services.porters_engine import (
    classify_attractiveness,
    run_porters_analysis,
    score_buyer_power,
    score_rivalry,
    score_substitutes,
    score_supplier_power,
)


def concentration_for(shares: list[float], settings: Settings, prices: list[float] | None = None):
    prices = prices or [100.0] * len(shares)
    return assess_market_structure(
        company_market_share_pct=shares[0] if shares else None,
        competitors=[
            {"competitor_name": f"C{i}", "market_share_pct": s, "price_point": p}
            for i, (s, p) in enumerate(zip(shares[1:], prices[1:]))
        ],
        analyst_intensity_override=None,
        settings=settings,
    )


class TestRivalry:
    def test_reuses_the_hhi_derived_intensity(self, settings: Settings):
        conc = concentration_for([20, 20, 20, 20, 20], settings)
        force = score_rivalry(conc)
        assert force.source is ForceSource.COMPUTED
        assert force.score == pytest.approx(conc.competitive_intensity_score)

    def test_unavailable_without_market_shares(self, settings: Settings):
        conc = assess_market_structure(
            company_market_share_pct=None,
            competitors=[],
            analyst_intensity_override=None,
            settings=settings,
        )
        force = score_rivalry(conc)
        assert force.score is None
        assert force.source is ForceSource.UNAVAILABLE

    def test_evidence_names_the_guidelines(self, settings: Settings):
        force = score_rivalry(concentration_for([55, 40], settings))
        assert "DOJ/FTC" in force.evidence and "HHI" in force.evidence


class TestAnalystOnlyForces:
    def test_buyer_power_unavailable_without_input(self):
        force = score_buyer_power({})
        assert force.score is None
        assert force.source is ForceSource.UNAVAILABLE
        assert "would be a guess presented as a measurement" in force.evidence

    def test_substitutes_unavailable_without_input(self):
        assert score_substitutes({}).score is None

    def test_buyer_power_from_input_is_tagged_analyst(self):
        force = score_buyer_power(
            {"buyer_concentration": 4, "buyer_switching_cost": 5}
        )
        assert force.score == pytest.approx(4.5)
        assert force.source is ForceSource.ANALYST_INPUT
        assert "judgement, not a measurement" in force.evidence

    def test_partial_input_still_scores_but_reports_the_gap(self):
        force = score_buyer_power({"buyer_concentration": 2})
        assert force.score == pytest.approx(2.0)
        assert force.inputs_missing == ["buyer_switching_cost"]

    def test_out_of_range_analyst_input_is_clamped(self):
        assert score_buyer_power({"buyer_concentration": 99}).score == pytest.approx(5.0)


class TestSupplierPower:
    def test_low_gross_margin_implies_high_supplier_exposure(self, settings: Settings):
        thin = score_supplier_power({"gross_margin_pct": 10.0}, {}, settings)
        fat = score_supplier_power({"gross_margin_pct": 90.0}, {}, settings)
        assert thin.score > fat.score

    def test_gross_margin_alone_is_computed_not_analyst(self, settings: Settings):
        force = score_supplier_power({"gross_margin_pct": 40.0}, {}, settings)
        assert force.source is ForceSource.COMPUTED

    def test_with_analyst_input_it_becomes_partially_computed(self, settings: Settings):
        force = score_supplier_power(
            {"gross_margin_pct": 40.0}, {"supplier_concentration": 4}, settings
        )
        assert force.source is ForceSource.PARTIALLY_COMPUTED

    def test_neither_input_is_unavailable(self, settings: Settings):
        assert score_supplier_power({}, {}, settings).score is None


class TestFullAnalysis:
    def test_scores_are_all_on_the_axis(self, settings: Settings):
        result = run_porters_analysis(
            financial_data={"gross_margin_pct": 55.0},
            market_data={
                "industry_operating_margin_pct": 18.0,
                "buyer_concentration": 3,
                "substitute_availability": 2,
                "capital_intensity": 2,
                "supplier_concentration": 3,
            },
            concentration=concentration_for([20, 20, 20, 20, 20], settings),
            settings=settings,
        )
        for force in result.forces:
            assert force.score is None or 1.0 <= force.score <= 5.0

    def test_every_force_carries_a_source(self, settings: Settings):
        result = run_porters_analysis(
            financial_data={},
            market_data={},
            concentration=concentration_for([], settings),
            settings=settings,
        )
        assert {f.force for f in result.forces} == set(PorterForce)
        assert all(isinstance(f.source, ForceSource) for f in result.forces)

    def test_empty_inputs_score_nothing_rather_than_defaulting(self, settings: Settings):
        result = run_porters_analysis(
            financial_data={},
            market_data={},
            concentration=concentration_for([], settings),
            settings=settings,
        )
        assert result.forces_scored == 0
        assert result.composite_score is None
        assert result.industry_attractiveness is None

    def test_composite_needs_at_least_two_forces(self, settings: Settings):
        result = run_porters_analysis(
            financial_data={},
            market_data={"buyer_concentration": 4},
            concentration=concentration_for([], settings),
            settings=settings,
        )
        assert result.forces_scored == 1
        assert result.composite_score is None, "one force is not a composite"

    def test_composite_is_labelled_as_not_porters(self, settings: Settings):
        result = run_porters_analysis(
            financial_data={"gross_margin_pct": 50.0},
            market_data={"buyer_concentration": 3},
            concentration=concentration_for([30, 30, 20], settings),
            settings=settings,
        )
        status = result.calculation_basis["composite_status"]
        assert "PROJECT-DEFINED" in status
        assert "not part of Porter's framework" in status

    def test_scale_direction_is_stated(self, settings: Settings):
        result = run_porters_analysis(
            financial_data={},
            market_data={},
            concentration=concentration_for([], settings),
            settings=settings,
        )
        assert "OPPOSITE" in result.calculation_basis["scale_direction"]

    @pytest.mark.parametrize(
        ("composite", "expected"),
        [
            (1.0, IndustryAttractiveness.ATTRACTIVE),
            (2.49, IndustryAttractiveness.ATTRACTIVE),
            (2.5, IndustryAttractiveness.MODERATE),
            (3.5, IndustryAttractiveness.MODERATE),
            (3.51, IndustryAttractiveness.UNATTRACTIVE),
            (5.0, IndustryAttractiveness.UNATTRACTIVE),
        ],
    )
    def test_attractiveness_bands(
        self, composite: float, expected: IndustryAttractiveness, settings: Settings
    ):
        assert classify_attractiveness(composite, settings) is expected

    def test_deterministic(self, settings: Settings):
        args = dict(
            financial_data={"gross_margin_pct": 45.0},
            market_data={"industry_operating_margin_pct": 12.0, "buyer_concentration": 3},
            concentration=concentration_for([25, 25, 25, 25], settings),
            settings=settings,
        )
        first = run_porters_analysis(**args)
        second = run_porters_analysis(**args)
        assert [f.to_dict() for f in first.forces] == [f.to_dict() for f in second.forces]
