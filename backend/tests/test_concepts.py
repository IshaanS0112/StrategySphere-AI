"""Tag resolution order, and the promise that nothing is ever imputed."""

from __future__ import annotations

import pytest

from app.enums import MetricDerivation
from app.services import benchmarks as bench
from app.services.edgar import concepts
from app.services.edgar.frames import parse_frame, resolve_candidates


class TestSpecsMatchTheBenchmarkTable:
    def test_every_spec_key_is_a_metric_the_swot_engine_reads(self):
        # A spec whose key is not in METRIC_RULES builds a column nothing reads.
        known = set(bench.METRIC_BY_KEY)
        assert {spec.key for spec in concepts.METRIC_SPECS} <= known

    def test_not_derivable_metrics_are_real_metrics_that_are_declared_absent(self):
        known = set(bench.METRIC_BY_KEY)
        assert set(concepts.NOT_DERIVABLE) <= known
        # ... and they must not also be built, or the declaration is a lie.
        assert not set(concepts.NOT_DERIVABLE) & {s.key for s in concepts.METRIC_SPECS}

    def test_the_two_sets_together_account_for_every_metric_rule(self):
        covered = {s.key for s in concepts.METRIC_SPECS} | set(concepts.NOT_DERIVABLE)
        assert covered == set(bench.METRIC_BY_KEY), (
            "A metric that is neither built nor declared not-derivable is one "
            "nobody made a decision about."
        )

    def test_every_not_derivable_entry_carries_a_reason(self):
        assert all(len(reason) > 40 for reason in concepts.NOT_DERIVABLE.values())

    def test_ratio_specs_declare_both_legs(self):
        for spec in concepts.METRIC_SPECS:
            if spec.derivation is MetricDerivation.RATIO:
                assert spec.numerator and spec.denominator, spec.key

    def test_debt_to_equity_is_not_scaled_to_percent(self):
        # It is a multiple. Multiplying it by 100 would produce a benchmark of
        # 100x that every company beats by two orders of magnitude.
        assert concepts.METRIC_SPEC_BY_KEY["debt_to_equity"].scale == 1.0


class TestResolutionOrder:
    def test_the_first_candidate_present_wins(self):
        facts = {"Revenues": 50.0, "RevenueFromContractWithCustomerExcludingAssessedTax": 80.0}
        tag, value = concepts.resolve_first(facts, concepts.REVENUE_TAGS)
        assert (tag, value) == ("RevenueFromContractWithCustomerExcludingAssessedTax", 80.0)

    def test_it_falls_through_to_the_legacy_tag(self):
        assert concepts.resolve_first({"Revenues": 50.0}, concepts.REVENUE_TAGS) == (
            "Revenues",
            50.0,
        )

    def test_nothing_resolves_returns_none_rather_than_a_default(self):
        assert concepts.resolve_first({"Assets": 10.0}, concepts.REVENUE_TAGS) is None

    def test_booleans_are_not_numbers(self):
        assert concepts.resolve_first({"Revenues": True}, concepts.REVENUE_TAGS) is None

    def test_candidate_lists_have_no_duplicates(self):
        for spec in concepts.METRIC_SPECS:
            tags = spec.all_tags()
            assert len(tags) == len(set(tags)), spec.key


class TestFrameParsing:
    def test_rows_without_a_numeric_value_are_rejected_and_counted(self):
        payload = {
            "data": [
                {"cik": 1, "val": 10.0, "entityName": "A"},
                {"cik": 2, "val": None, "entityName": "B"},
                {"cik": 3, "entityName": "C"},
                {"val": 4.0, "entityName": "D"},
                "not a row",
            ]
        }
        result = parse_frame(payload, concept="X", unit="USD", period="CY2024")
        assert set(result.facts) == {1}
        assert result.rows_rejected == 4
        assert result.rows_returned == 5

    def test_duplicate_ciks_are_counted_and_resolved_last_wins(self):
        payload = {
            "data": [
                {"cik": 1, "val": 10.0, "entityName": "A"},
                {"cik": 1, "val": 20.0, "entityName": "A restated"},
            ]
        }
        result = parse_frame(payload, concept="X", unit="USD", period="CY2024")
        assert result.duplicate_ciks == 1
        assert result.facts[1].value == 20.0

    def test_a_payload_with_no_data_array_is_unavailable_not_a_crash(self):
        result = parse_frame({"error": "not found"}, concept="X", unit="USD", period="CY2024")
        assert result.available is False
        assert result.facts == {}

    def test_a_missing_frame_is_unavailable_and_the_next_candidate_is_tried(
        self, edgar_client, recorded_transport
    ):
        # SalesRevenueNet has an empty fixture frame and NoSuchTag has none at all -
        # both have to be survivable, because plenty of us-gaap tags have no frame
        # for a given period.
        resolved = resolve_candidates(
            edgar_client,
            ("NoSuchTag", "Revenues"),
            period="CY2024",
        )
        assert resolved.values, "the second candidate should still have resolved"
        assert all(tag == "Revenues" for tag in resolved.tag_by_cik.values())
        assert resolved.frames[0].available is False


class TestCandidateResolutionAcrossCompanies:
    def test_each_company_is_read_through_exactly_one_tag(self, edgar_client):
        resolved = resolve_candidates(edgar_client, concepts.REVENUE_TAGS, period="CY2024")
        counts = resolved.tag_counts()
        # The fixture universe deliberately mixes post-606 and legacy filers.
        assert counts["RevenueFromContractWithCustomerExcludingAssessedTax"] > 0
        assert counts["Revenues"] > 0
        assert sum(counts.values()) == len(resolved.values)

    def test_an_earlier_tag_is_never_overwritten_by_a_later_one(self, edgar_client):
        resolved = resolve_candidates(edgar_client, concepts.REVENUE_TAGS, period="CY2024")
        post_606 = {
            cik
            for cik, tag in resolved.tag_by_cik.items()
            if tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
        }
        legacy = {cik for cik, tag in resolved.tag_by_cik.items() if tag == "Revenues"}
        assert not post_606 & legacy

    def test_one_request_per_candidate_tag_not_per_company(
        self, edgar_client, recorded_transport
    ):
        resolve_candidates(edgar_client, concepts.REVENUE_TAGS, period="CY2024")
        # Three candidate tags, three requests, sixty companies.
        assert len(recorded_transport.calls) == len(concepts.REVENUE_TAGS)

    @pytest.mark.parametrize("cik", [1045, 1046, 1047])
    def test_companies_with_no_revenue_tag_at_all_are_absent(self, edgar_client, cik):
        resolved = resolve_candidates(edgar_client, concepts.REVENUE_TAGS, period="CY2024")
        assert cik not in resolved.values
