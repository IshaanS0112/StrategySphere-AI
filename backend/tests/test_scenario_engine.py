"""What-if scenarios.

Two properties matter more than the arithmetic: a scenario must never mutate
the baseline it was run against, and an override key that does not exist must
be an error rather than a no-op. A typo'd override that silently does nothing
produces a scenario showing "no change", which reads as evidence the verdict is
stable — the most dangerous possible failure for this feature.
"""

from __future__ import annotations

import copy

import pytest

from app.config import Settings
from app.services.scenario_engine import (
    ScenarioInputError,
    describe_move,
    result_snapshot,
    run_scenario,
)

BASE_FINANCIAL = {
    "revenue_growth_pct": 30.0,
    "gross_margin_pct": 80.0,
    "operating_margin_pct": 18.0,
    "market_share_pct": 22.0,
}
BASE_MARKET = {
    "market_growth_pct": 16.0,
    "market_size_usd_bn": 30.0,
    "industry_operating_margin_pct": 18.0,
}
BASE_COMPETITORS = [
    {
        "competitor_name": "Rival A",
        "price_point": 100.0,
        "market_share_pct": 18.0,
        "feature_scores": {"speed": 3},
        "financial_data": {"operating_margin_pct": 10.0},
    },
    {
        "competitor_name": "Rival B",
        "price_point": 110.0,
        "market_share_pct": 14.0,
        "feature_scores": {"speed": 2},
        "financial_data": {"operating_margin_pct": 12.0},
    },
]


def baseline_snapshot_for(settings: Settings) -> dict:
    """Run the pipeline once with no overrides to get a comparable baseline."""
    result = run_scenario(
        baseline_financial_data=BASE_FINANCIAL,
        baseline_market_data=BASE_MARKET,
        baseline_qualitative_inputs=[],
        baseline_competitors=BASE_COMPETITORS,
        baseline_snapshot={},
        industry="saas",
        overrides={"market_data": {"market_growth_pct": BASE_MARKET["market_growth_pct"]}},
        settings=settings,
    )
    return result_snapshot(result.attractiveness)


def run(settings: Settings, overrides: dict, baseline: dict | None = None):
    return run_scenario(
        baseline_financial_data=BASE_FINANCIAL,
        baseline_market_data=BASE_MARKET,
        baseline_qualitative_inputs=[],
        baseline_competitors=BASE_COMPETITORS,
        baseline_snapshot=baseline if baseline is not None else baseline_snapshot_for(settings),
        industry="saas",
        overrides=overrides,
        settings=settings,
    )


class TestValidation:
    def test_unknown_market_key_is_rejected(self, settings: Settings):
        with pytest.raises(ScenarioInputError, match="Unknown market_data override"):
            run(settings, {"market_data": {"markert_growth_pct": 8.0}})

    def test_unknown_financial_key_is_rejected(self, settings: Settings):
        with pytest.raises(ScenarioInputError, match="Unknown financial_data override"):
            run(settings, {"financial_data": {"revenue_growth": 5.0}})

    def test_empty_overrides_are_rejected(self, settings: Settings):
        with pytest.raises(ScenarioInputError, match="no overrides"):
            run(settings, {})

    def test_competitor_op_must_be_known(self, settings: Settings):
        with pytest.raises(ScenarioInputError, match="unsupported competitor op"):
            run(settings, {"competitors": [{"op": "explode", "competitor_name": "Rival A"}]})

    def test_remove_needs_a_target(self, settings: Settings):
        with pytest.raises(ScenarioInputError, match="needs a competitor_name"):
            run(settings, {"competitors": [{"op": "remove"}]})


class TestNonMutation:
    def test_the_baseline_inputs_are_never_modified(self, settings: Settings):
        financial_before = copy.deepcopy(BASE_FINANCIAL)
        market_before = copy.deepcopy(BASE_MARKET)
        competitors_before = copy.deepcopy(BASE_COMPETITORS)

        run(
            settings,
            {
                "market_data": {"market_growth_pct": 2.0},
                "financial_data": {"operating_margin_pct": 1.0},
                "competitors": [
                    {"op": "add", "competitor_name": "Entrant", "market_share_pct": 15.0},
                    {"op": "remove", "competitor_name": "Rival A"},
                ],
            },
        )

        assert BASE_FINANCIAL == financial_before
        assert BASE_MARKET == market_before
        assert BASE_COMPETITORS == competitors_before


class TestEffects:
    def test_a_market_downturn_lowers_attractiveness(self, settings: Settings):
        baseline = baseline_snapshot_for(settings)
        result = run(settings, {"market_data": {"market_growth_pct": 1.0}}, baseline)
        assert (
            result.attractiveness.overall_attractiveness_score
            < baseline["overall_attractiveness_score"]
        )
        assert result.delta["overall_attractiveness_score"]["delta"] < 0

    def test_adding_a_large_entrant_changes_concentration(self, settings: Settings):
        baseline = baseline_snapshot_for(settings)
        result = run(
            settings,
            {
                "competitors": [
                    {"op": "add", "competitor_name": "Entrant", "market_share_pct": 30.0}
                ]
            },
            baseline,
        )
        assert "competitive_intensity_score" in result.delta

    def test_removing_a_competitor_that_does_not_exist_warns(self, settings: Settings):
        result = run(
            settings, {"competitors": [{"op": "remove", "competitor_name": "Ghost"}]}
        )
        assert any("not found in the baseline" in w for w in result.warnings)

    def test_update_changes_only_the_named_competitor(self, settings: Settings):
        result = run(
            settings,
            {
                "competitors": [
                    {"op": "update", "competitor_name": "Rival A", "market_share_pct": 40.0}
                ]
            },
        )
        assert result.resulting_inputs["competitor_count"] == 2
        assert "Rival A" in result.resulting_inputs["competitor_names"]

    def test_overrides_are_stored_as_deltas_not_merged_inputs(self, settings: Settings):
        result = run(settings, {"market_data": {"market_growth_pct": 3.0}})
        assert result.applied_overrides == {"market_data": {"market_growth_pct": 3.0}}
        # the merged inputs are separate, so the delta stays readable later
        assert result.resulting_inputs["market_data"]["market_size_usd_bn"] == 30.0

    def test_a_no_op_override_is_flagged(self, settings: Settings):
        baseline = baseline_snapshot_for(settings)
        result = run(
            settings,
            {"market_data": {"market_growth_pct": BASE_MARKET["market_growth_pct"]}},
            baseline,
        )
        assert result.delta == {}
        assert any("no change in any scored output" in w for w in result.warnings)

    def test_quadrant_changed_flag_matches_the_snapshot(self, settings: Settings):
        baseline = baseline_snapshot_for(settings)
        result = run(settings, {"market_data": {"market_growth_pct": 0.5}}, baseline)
        snapshot = result_snapshot(result.attractiveness)
        assert result.quadrant_changed == (baseline["quadrant"] != snapshot["quadrant"])


class TestNarrative:
    def test_holding_position_is_described_as_such(self):
        assert "holds" in describe_move("INVEST_GROW", "INVEST_GROW")

    def test_downgrade_reads_as_deterioration(self):
        assert "deteriorates" in describe_move("INVEST_GROW", "SELECTIVE_INVEST")

    def test_upgrade_reads_as_improvement(self):
        assert "improves" in describe_move("HARVEST_DIVEST", "SELECTIVE_INVEST")
