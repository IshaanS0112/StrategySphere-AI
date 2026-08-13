"""SWOT scoring.

The interesting cases are the boundaries and the abstentions: a metric just
inside the neutral band must produce no factor at all, and a missing benchmark
must be skipped rather than imputed. A SWOT engine that always finds something
to say is a SWOT engine that is not measuring anything.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.enums import BenchmarkBasis, SwotCategory
from app.services.market_structure import assess_market_structure
from app.services.swot_engine import (
    band_score,
    favourable_deviation_pct,
    impact_from_deviation,
    run_swot_analysis,
)


class TestDeviation:
    def test_higher_is_better_above_benchmark_is_favourable(self):
        assert favourable_deviation_pct(15.0, 10.0, higher_is_better=True) == pytest.approx(50.0)

    def test_higher_is_better_below_benchmark_is_unfavourable(self):
        assert favourable_deviation_pct(5.0, 10.0, higher_is_better=True) == pytest.approx(-50.0)

    def test_lower_is_better_inverts_the_sign(self):
        # Debt-to-equity of 0.5 against a benchmark of 1.0 is GOOD.
        assert favourable_deviation_pct(0.5, 1.0, higher_is_better=False) == pytest.approx(50.0)
        assert favourable_deviation_pct(2.0, 1.0, higher_is_better=False) == pytest.approx(-100.0)

    def test_zero_benchmark_is_undefined_not_infinite(self):
        # Returning a huge number here would manufacture a 5-impact factor out
        # of a missing benchmark.
        assert favourable_deviation_pct(5.0, 0.0, higher_is_better=True) is None

    def test_negative_benchmark_uses_absolute_denominator(self):
        # A -5% margin against a -10% benchmark is a 50% improvement, not -50%.
        assert favourable_deviation_pct(-5.0, -10.0, higher_is_better=True) == pytest.approx(50.0)


class TestImpactBuckets:
    @pytest.mark.parametrize(
        ("deviation", "expected"),
        [
            (5.0, 1),      # just past the neutral band
            (9.99, 1),
            (10.0, 2),     # exactly on an edge lands in the higher bucket
            (24.99, 2),
            (25.0, 3),
            (49.99, 3),
            (50.0, 4),
            (99.99, 4),
            (100.0, 5),
            (10_000.0, 5),  # saturates, never 6
        ],
    )
    def test_boundaries(self, deviation: float, expected: int, settings: Settings):
        assert impact_from_deviation(deviation, settings) == expected


class TestBandScore:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(0.0, 1), (2.9, 1), (3.0, 2), (5.9, 2), (6.0, 3), (10.0, 4), (15.0, 5), (900.0, 5)],
    )
    def test_ascending_bands(self, value: float, expected: int):
        assert band_score(value, (3.0, 6.0, 10.0, 15.0)) == expected


class TestFullAnalysis:
    def _run(self, financials, market, competitors, settings, qualitative=None):
        concentration = assess_market_structure(
            company_market_share_pct=financials.get("market_share_pct"),
            competitors=competitors,
            analyst_intensity_override=None,
            settings=settings,
        )
        return run_swot_analysis(
            financial_data=financials,
            market_data=market,
            qualitative_inputs=qualitative or [],
            competitors=competitors,
            industry=None,
            concentration=concentration,
            settings=settings,
        )

    def test_strong_company_scores_strengths_not_weaknesses(
        self, strong_financials, growth_market, competitors, settings
    ):
        result = self._run(strong_financials, growth_market, competitors, settings)
        assert result.strengths
        assert not any(
            f.source == "computed_financial" for f in result.weaknesses
        ), "a company ahead on every metric should have no computed weaknesses"

    def test_weak_company_scores_weaknesses_not_strengths(
        self, weak_financials, declining_market, competitors, settings
    ):
        result = self._run(weak_financials, declining_market, competitors, settings)
        assert result.weaknesses
        assert not any(f.source == "computed_financial" for f in result.strengths)

    def test_metric_inside_neutral_band_produces_no_factor(self, settings, competitors):
        # Default industry operating margin band is 12.0; 12.3 is +2.5%,
        # inside the +/-5% neutral band.
        result = self._run({"operating_margin_pct": 12.3}, {}, [], settings)
        assert result.strengths == []
        assert result.weaknesses == []
        trace = result.calculation_basis["financial_metric_trace"]
        entry = next(e for e in trace if e["metric"] == "operating_margin_pct")
        assert entry["status"] == "neutral"

    def test_metric_just_outside_neutral_band_produces_a_factor(self, settings):
        # 12.7 is +5.83%, past the band.
        result = self._run({"operating_margin_pct": 12.7}, {}, [], settings)
        assert [f.factor for f in result.strengths] == ["Operating margin"]
        assert result.strengths[0].impact_score == 1

    def test_unreported_metric_is_skipped_not_imputed(self, settings):
        result = self._run({"operating_margin_pct": 30.0}, {}, [], settings)
        trace = {e["metric"]: e for e in result.calculation_basis["financial_metric_trace"]}
        assert trace["gross_margin_pct"]["status"] == "skipped"
        assert trace["gross_margin_pct"]["reason"] == "not reported"

    def test_peer_median_is_preferred_over_the_industry_table(
        self, strong_financials, competitors, settings
    ):
        # Four competitors report operating_margin_pct, above the minimum of 3.
        result = self._run(strong_financials, {}, competitors, settings)
        factor = next(f for f in result.strengths if f.metric == "operating_margin_pct")
        assert factor.benchmark_basis == BenchmarkBasis.PEER_SET.value
        # median(10, 12, 8, 14) = 11.0
        trace = next(
            e
            for e in result.calculation_basis["financial_metric_trace"]
            if e["metric"] == "operating_margin_pct"
        )
        assert trace["benchmark"] == pytest.approx(11.0)

    def test_too_few_peers_falls_back_to_the_industry_table(
        self, strong_financials, competitors, settings
    ):
        result = self._run(strong_financials, {}, competitors[:2], settings)
        factor = next(f for f in result.strengths if f.metric == "operating_margin_pct")
        assert factor.benchmark_basis == BenchmarkBasis.INDUSTRY_TABLE.value

    def test_evidence_carries_the_benchmark_it_was_scored_against(
        self, strong_financials, settings
    ):
        result = self._run(strong_financials, {}, [], settings)
        for factor in result.strengths + result.weaknesses:
            if factor.source == "computed_financial":
                assert "vs" in factor.evidence and "%" in factor.evidence

    def test_low_growth_market_is_a_high_impact_threat(self, settings):
        # Growth of 1.0 band-scores 1/5, which must invert into a 5/5 threat.
        result = self._run({}, {"market_growth_pct": 1.0}, [], settings)
        threat = next(f for f in result.threats if f.metric == "market_growth_pct")
        assert threat.impact_score == 5

    def test_high_growth_market_is_an_opportunity(self, settings):
        result = self._run({}, {"market_growth_pct": 18.0}, [], settings)
        assert any(f.metric == "market_growth_pct" for f in result.opportunities)

    def test_analyst_input_is_tagged_and_never_relabelled_as_computed(self, settings):
        result = self._run(
            {},
            {},
            [],
            settings,
            qualitative=[
                {
                    "factor": "Founder brand recognition",
                    "category": "STRENGTH",
                    "evidence": "Widely covered in trade press",
                    "impact_score": 4,
                }
            ],
        )
        assert len(result.strengths) == 1
        assert result.strengths[0].source == "analyst_input"

    def test_malformed_analyst_input_is_rejected_with_a_reason(self, settings):
        result = self._run(
            {},
            {},
            [],
            settings,
            qualitative=[
                {"factor": "No category given", "impact_score": 3},
                {"category": "STRENGTH", "impact_score": 3},
                {"factor": "Bad score", "category": "STRENGTH", "impact_score": "high"},
                "not even an object",
            ],
        )
        rejected = result.calculation_basis["qualitative_inputs_rejected"]
        assert len(rejected) == 4
        assert result.strengths == []

    def test_out_of_range_analyst_score_is_clamped_not_rejected(self, settings):
        result = self._run(
            {},
            {},
            [],
            settings,
            qualitative=[{"factor": "Overscored", "category": "STRENGTH", "impact_score": 97}],
        )
        assert result.strengths[0].impact_score == 5

    def test_factors_are_sorted_by_descending_impact(
        self, strong_financials, growth_market, settings
    ):
        result = self._run(strong_financials, growth_market, [], settings)
        scores = [f.impact_score for f in result.strengths]
        assert scores == sorted(scores, reverse=True)

    def test_analysis_is_deterministic(self, strong_financials, growth_market, competitors, settings):
        first = self._run(strong_financials, growth_market, competitors, settings)
        second = self._run(strong_financials, growth_market, competitors, settings)
        assert [f.to_dict() for f in first.all_factors] == [
            f.to_dict() for f in second.all_factors
        ]
