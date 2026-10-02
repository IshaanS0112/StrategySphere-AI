"""The min-n rule, coverage reporting, and the drop-and-count paths."""

from __future__ import annotations

import json
from statistics import median

import pytest

from app.enums import BenchmarkBasis
from app.services import benchmarks as bench
from app.services.edgar import sic as sic_mod
from app.services.edgar.benchmark_builder import build_benchmark_table, instant_period


@pytest.fixture
def built(edgar_client):
    # min_sector_n = 10 against fixture sectors of 12/12/12/4: three sectors
    # publish and 'financials' falls below, which is the case worth testing.
    return build_benchmark_table(
        edgar_client, period="CY2024", min_sector_n=10, sic_lookup_limit=100
    )


class TestSicMapping:
    @pytest.mark.parametrize(
        "code,expected",
        [
            (7372, "saas"),
            (7370, "saas"),
            (7379, "saas"),
            (5331, "retail"),
            (3714, "manufacturing"),
            (2834, "biotech"),
            (8731, "biotech"),
            (3674, "semiconductors"),
            (6022, "financials"),
            (4813, "telecom"),
        ],
    )
    def test_codes_map_to_their_sector(self, code, expected):
        assert sic_mod.sector_for_sic(code) == expected

    def test_narrow_ranges_win_over_the_blocks_containing_them(self):
        # 7372 sits inside the 7000-8999 services block. If the block matched
        # first every software filer would be classified as a services company.
        assert sic_mod.sector_for_sic(7372) == "saas"
        assert sic_mod.sector_for_sic(7011) == "services"
        assert sic_mod.sector_for_sic(8731) == "biotech"
        assert sic_mod.sector_for_sic(8111) == "services"

    @pytest.mark.parametrize("raw", [None, "", "  ", "not-a-code", 99999])
    def test_unknown_codes_are_unclassified_rather_than_guessed(self, raw):
        assert sic_mod.sector_for_sic(raw) == sic_mod.UNCLASSIFIED

    def test_string_codes_from_the_api_parse(self):
        # submissions returns sic as a string.
        assert sic_mod.sector_for_sic("7372") == "saas"

    def test_ranges_do_not_overlap_within_a_sector_ordering(self):
        seen: list[tuple[int, int]] = []
        for entry in sic_mod.SIC_RANGES:
            assert entry.low <= entry.high
            seen.append((entry.low, entry.high))
        assert len(seen) == len(set(seen))


class TestMinimumSampleRule:
    def test_a_sector_above_the_minimum_is_published(self, built):
        assert "saas" in built.table
        assert built.table["saas"]["_basis"] == BenchmarkBasis.EDGAR_SECTOR_MEDIAN.value

    def test_a_sector_below_the_minimum_is_omitted_and_named(self, built):
        assert "financials" not in built.table
        entry = built.provenance["sectors_below_min_n"]["financials"]
        # Membership and metric coverage are different numbers, and reporting only
        # the first makes "biotech (20)" look like it should have cleared a minimum
        # of 20 when no metric resolved that many.
        assert entry["classified_members"] == 4
        assert entry["best_metric_n"] <= entry["classified_members"]

    def test_an_omitted_sector_falls_through_to_the_all_filer_median(self, tmp_path, built):
        path = tmp_path / "table.json"
        path.write_text(json.dumps(built.payload()))
        table = bench.load_benchmark_table(str(path))
        point = table.lookup("financials", "gross_margin_pct")
        assert point is not None
        assert point.sector == "_default"
        assert point.basis == BenchmarkBasis.EDGAR_ALL_FILER_MEDIAN.value

    def test_raising_the_minimum_removes_more_sectors(self, edgar_client):
        strict = build_benchmark_table(
            edgar_client, period="CY2024", min_sector_n=1000, sic_lookup_limit=100
        )
        assert strict.provenance["sectors_published"] == []
        assert "_default" in strict.table, "the all-filer row never depends on min_sector_n"

    def test_the_configured_minimum_is_recorded_in_the_provenance(self, built):
        assert built.provenance["min_sector_n"] == 10


class TestMedians:
    def test_sector_medians_differ_from_each_other(self, built):
        # The fixture sectors have deliberately different margins. Identical
        # medians would mean the SIC grouping is not being applied at all.
        assert built.table["saas"]["gross_margin_pct"] > 65.0
        assert built.table["retail"]["gross_margin_pct"] < 40.0

    def test_the_median_is_computed_over_the_sector_members(self, built, edgar_client):
        from app.services.edgar.frames import resolve_candidates
        from app.services.edgar import concepts

        revenue = resolve_candidates(
            edgar_client, concepts.REVENUE_TAGS, period="CY2024"
        ).values
        gross = resolve_candidates(
            edgar_client, concepts.GROSS_PROFIT_TAGS, period="CY2024"
        ).values
        saas_ciks = [c for c in range(1000, 1012) if c in revenue and c in gross]
        expected = median(gross[c] / revenue[c] * 100.0 for c in saas_ciks)
        assert built.table["saas"]["gross_margin_pct"] == pytest.approx(expected, abs=1e-4)

    def test_every_published_metric_carries_its_own_n(self, built):
        for metric, meta in built.table["saas"]["_meta"].items():
            assert meta["n"] >= 10, metric
            assert meta["basis"] == BenchmarkBasis.EDGAR_SECTOR_MEDIAN.value

    def test_the_default_row_uses_the_whole_resolved_universe(self, built):
        n_default = built.table["_default"]["_meta"]["gross_margin_pct"]["n"]
        n_saas = built.table["saas"]["_meta"]["gross_margin_pct"]["n"]
        assert n_default > n_saas


class TestCoverageAndDrops:
    def test_coverage_is_reported_per_metric(self, built):
        coverage = built.provenance["coverage_by_metric"]
        assert set(coverage) == {
            "revenue_growth_pct",
            "gross_margin_pct",
            "operating_margin_pct",
            "net_margin_pct",
            "return_on_capital_pct",
            "rnd_intensity_pct",
            "debt_to_equity",
        }
        for metric, entry in coverage.items():
            assert entry["resolved"] + entry["dropped"] == entry["resolved"] + sum(
                entry["drop_reasons"].values()
            ), metric

    def test_coverage_is_meaningfully_below_one_hundred_percent(self, built):
        # If it were 100% the drop paths would not be exercised at all, and a
        # real build never is.
        assert built.provenance["coverage_by_metric"]["gross_margin_pct"]["coverage_pct"] < 100.0

    def test_companies_with_no_numerator_are_dropped_with_a_reason(self, built):
        reasons = built.provenance["coverage_by_metric"]["gross_margin_pct"]["drop_reasons"]
        assert any("GrossProfit" in reason for reason in reasons)

    def test_a_non_positive_denominator_is_dropped_not_signed(self, built):
        reasons = built.provenance["coverage_by_metric"]["gross_margin_pct"]["drop_reasons"]
        assert reasons.get("non-positive denominator", 0) >= 2

    def test_negative_book_equity_is_dropped_from_debt_to_equity(self, built):
        reasons = built.provenance["coverage_by_metric"]["debt_to_equity"]["drop_reasons"]
        assert reasons.get("non-positive denominator", 0) >= 4
        assert built.table["_default"]["debt_to_equity"] > 0

    def test_a_revenue_tag_that_changes_between_periods_is_dropped(self, built):
        reasons = built.provenance["coverage_by_metric"]["revenue_growth_pct"]["drop_reasons"]
        assert reasons["revenue tag differs between the two periods"] == 3

    def test_a_company_missing_the_prior_period_is_dropped(self, built):
        reasons = built.provenance["coverage_by_metric"]["revenue_growth_pct"]["drop_reasons"]
        assert reasons["no revenue tag resolved for CY2023"] >= 3

    def test_nothing_is_imputed(self, built, edgar_client):
        from app.services.edgar import concepts
        from app.services.edgar.frames import resolve_candidates

        gross = resolve_candidates(edgar_client, concepts.GROSS_PROFIT_TAGS, period="CY2024")
        resolved = built.provenance["coverage_by_metric"]["gross_margin_pct"]["resolved"]
        assert resolved <= len(gross.values), (
            "more companies resolved a margin than reported a gross profit, which "
            "can only happen if something was filled in"
        )


class TestTagResolutionTrace:
    def test_the_resolved_tag_is_recorded_per_metric(self, built):
        trace = built.provenance["tag_resolution"]["gross_margin_pct"]
        assert any("GrossProfit/" in tag for tag in trace)
        assert sum(trace.values()) == (
            built.provenance["coverage_by_metric"]["gross_margin_pct"]["resolved"]
        )

    def test_both_revenue_tags_appear_in_the_growth_trace(self, built):
        trace = built.provenance["tag_resolution"]["revenue_growth_pct"]
        assert "Revenues" in trace
        assert "RevenueFromContractWithCustomerExcludingAssessedTax" in trace


class TestProvenanceBlock:
    def test_it_names_the_source_period_and_sample_rule(self, built):
        provenance = built.provenance
        assert "data.sec.gov" in provenance["source"]
        assert provenance["period"] == "CY2024"
        assert provenance["prior_period_for_growth"] == "CY2023"
        assert "bias" in provenance["sic_sample"]

    def test_it_declares_the_metrics_that_cannot_be_sourced(self, built):
        assert set(built.provenance["metrics_not_derivable"]) == {
            "market_share_pct",
            "customer_retention_pct",
        }

    def test_the_file_is_loadable_by_the_existing_loader(self, tmp_path, built):
        path = tmp_path / "edgar.json"
        path.write_text(json.dumps(built.payload()))
        table = bench.load_benchmark_table(str(path))
        assert "data.sec.gov" in table.provenance
        assert table.provenance_detail is not None
        point = table.lookup("saas", "gross_margin_pct")
        assert point.basis == BenchmarkBasis.EDGAR_SECTOR_MEDIAN.value
        assert "n=" in point.label()

    def test_underscore_keys_never_reach_the_metric_rows(self, tmp_path, built):
        # V2's loader ran float() over every value in a row.
        path = tmp_path / "edgar.json"
        path.write_text(json.dumps(built.payload()))
        table = bench.load_benchmark_table(str(path))
        assert all(
            not key.startswith("_")
            for row in table.rows.values()
            for key in row
        )
        assert all(isinstance(v, float) for row in table.rows.values() for v in row.values())


class TestInstantaneousPeriods:
    """Balance-sheet concepts live under a different period key than income ones."""

    def test_a_calendar_year_maps_to_its_q4_instant(self):
        assert instant_period("CY2024") == "CY2024Q4I"
        assert instant_period("CY2024Q4I") == "CY2024Q4I"

    def test_an_unparseable_period_raises_rather_than_guessing(self):
        with pytest.raises(ValueError):
            instant_period("last year")

    def test_balance_sheet_legs_are_requested_with_the_instant_key(
        self, edgar_client, recorded_transport
    ):
        build_benchmark_table(
            edgar_client, period="CY2024", min_sector_n=10, sic_lookup_limit=0
        )
        assert any("/Assets/USD/CY2024Q4I.json" in url for url in recorded_transport.calls)
        assert not any("/Assets/USD/CY2024.json" in url for url in recorded_transport.calls)

    def test_both_balance_sheet_ratios_actually_resolve(self, built):
        for metric in ("return_on_capital_pct", "debt_to_equity"):
            assert built.provenance["coverage_by_metric"][metric]["resolved"] > 0, metric
            assert built.table["_default"][metric] > 0, metric


class TestDeterminismAndRequestDiscipline:
    def test_two_builds_from_the_same_cache_agree_exactly(self, edgar_client):
        first = build_benchmark_table(
            edgar_client, period="CY2024", min_sector_n=10, sic_lookup_limit=100
        )
        second = build_benchmark_table(
            edgar_client, period="CY2024", min_sector_n=10, sic_lookup_limit=100
        )
        assert first.table == second.table

    def test_revenue_frames_are_fetched_once_not_once_per_ratio(
        self, edgar_client, recorded_transport
    ):
        build_benchmark_table(
            edgar_client, period="CY2024", min_sector_n=10, sic_lookup_limit=0
        )
        revenue_calls = [
            url for url in recorded_transport.calls if "/Revenues/USD/CY2024" in url
        ]
        assert len(revenue_calls) == 1, (
            "revenue is the denominator of four ratios; fetching it per ratio is "
            "both slow and rude to a public API"
        )

    def test_the_sic_sample_is_capped(self, edgar_client, recorded_transport):
        build_benchmark_table(
            edgar_client, period="CY2024", min_sector_n=10, sic_lookup_limit=5
        )
        submissions = [url for url in recorded_transport.calls if "/submissions/" in url]
        assert len(submissions) == 5

    def test_a_zero_sic_limit_still_produces_the_all_filer_row(self, edgar_client):
        result = build_benchmark_table(
            edgar_client, period="CY2024", min_sector_n=10, sic_lookup_limit=0
        )
        assert result.table["_default"]["gross_margin_pct"] > 0
        assert result.provenance["sectors_published"] == []


class TestEmptyBuildIsRefused:
    """A build that resolves nothing must fail, not write an empty table."""

    def test_an_offline_build_with_a_cold_cache_fails_loudly(self, tmp_path):
        from app.services.edgar.benchmark_builder import BenchmarkBuildError
        from app.services.edgar.client import EdgarClient

        cold = EdgarClient(user_agent=None, cache_dir=tmp_path / "empty", offline=True)
        with pytest.raises(BenchmarkBuildError) as exc:
            build_benchmark_table(cold, period="CY2024", min_sector_n=10, sic_lookup_limit=0)
        assert "nothing to take a median of" in str(exc.value)

    def test_a_period_with_no_frames_fails_rather_than_publishing_zero(self, edgar_client):
        from app.services.edgar.benchmark_builder import BenchmarkBuildError

        with pytest.raises(BenchmarkBuildError):
            build_benchmark_table(
                edgar_client, period="CY1990", min_sector_n=10, sic_lookup_limit=0
            )
