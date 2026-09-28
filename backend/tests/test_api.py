"""HTTP contract, end to end, against a temporary SQLite database.

The stage-ordering 409s are the interesting part. The matrix must be built on
the SWOT grid the user actually saw, so requesting it first is an error rather
than a silent recompute.
"""

from __future__ import annotations

COMPANY = {
    "name": "Testco Ltd",
    "industry": "saas",
    "data_source": "Unit test fixture, not a real company",
    "financial_data": {
        "revenue_growth_pct": 30.0,
        "gross_margin_pct": 80.0,
        "operating_margin_pct": 18.0,
        "net_margin_pct": 12.0,
        "market_share_pct": 22.0,
        "debt_to_equity": 0.3,
    },
    "market_data": {
        "market_growth_pct": 16.0,
        "market_size_usd_bn": 30.0,
        "industry_operating_margin_pct": 18.0,
        "regulatory_outlook": "NEUTRAL",
    },
    "feature_scores": {"speed": 4, "support": 4, "uptime": 5},
    "qualitative_inputs": [
        {
            "factor": "Founder-led distribution",
            "category": "STRENGTH",
            "evidence": "Direct enterprise relationships",
            "impact_score": 4,
        }
    ],
}

COMPETITORS = [
    {
        "competitor_name": "Rival A",
        "price_point": 100.0,
        "market_share_pct": 18.0,
        "feature_scores": {"speed": 3, "support": 4, "uptime": 3},
        "financial_data": {"operating_margin_pct": 10.0, "gross_margin_pct": 70.0},
    },
    {
        "competitor_name": "Rival B",
        "price_point": 110.0,
        "market_share_pct": 14.0,
        "feature_scores": {"speed": 2, "support": 3, "uptime": 4},
        "financial_data": {"operating_margin_pct": 12.0, "gross_margin_pct": 74.0},
    },
    {
        "competitor_name": "Rival C",
        "price_point": 95.0,
        "market_share_pct": 11.0,
        "feature_scores": {"speed": 4, "support": 2, "uptime": 3},
        "financial_data": {"operating_margin_pct": 8.0, "gross_margin_pct": 66.0},
    },
]


def create_company(client, payload=None):
    response = client.post("/companies", json=payload or COMPANY)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def seed_full_company(client) -> str:
    company_id = create_company(client)
    for competitor in COMPETITORS:
        response = client.post(f"/companies/{company_id}/competitors", json=competitor)
        assert response.status_code == 201, response.text
    return company_id


class TestMeta:
    def test_health(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["version"] == "3.1.0"

    def test_methodology_exposes_the_parameter_set(self, client):
        body = client.get("/methodology").json()
        assert body["attractiveness_weights"]["market_growth"] == 0.3
        assert body["quadrant_thresholds"]["high"] == 3.5
        assert "PLACEHOLDER" in body["benchmark_provenance"]
        assert "Narration only" in body["llm_role"]


class TestCompanies:
    def test_create_and_fetch(self, client):
        company_id = create_company(client)
        body = client.get(f"/companies/{company_id}").json()
        assert body["name"] == "Testco Ltd"
        assert body["feature_scores"]["uptime"] == 5

    def test_missing_company_is_404(self, client):
        response = client.get("/companies/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_data_source_is_required(self, client):
        payload = {k: v for k, v in COMPANY.items() if k != "data_source"}
        assert client.post("/companies", json=payload).status_code == 422

    def test_feature_score_outside_the_scale_is_rejected(self, client):
        payload = dict(COMPANY, feature_scores={"speed": 11})
        response = client.post("/companies", json=payload)
        assert response.status_code == 422
        assert "1-5 scale" in response.text

    def test_impossible_market_share_is_rejected(self, client):
        payload = dict(COMPANY, financial_data={"market_share_pct": 140.0})
        assert client.post("/companies", json=payload).status_code == 422

    def test_competitor_market_share_is_bounded(self, client):
        company_id = create_company(client)
        response = client.post(
            f"/companies/{company_id}/competitors",
            json={"competitor_name": "Impossible", "market_share_pct": 250.0},
        )
        assert response.status_code == 422

    def test_deleting_a_company_cascades(self, client):
        company_id = seed_full_company(client)
        assert client.delete(f"/companies/{company_id}").status_code == 204
        assert client.get(f"/companies/{company_id}").status_code == 404


class TestStageOrdering:
    def test_matrix_before_swot_is_409(self, client):
        company_id = seed_full_company(client)
        response = client.post(f"/companies/{company_id}/market-attractiveness")
        assert response.status_code == 409
        assert "SWOT" in response.json()["detail"]

    def test_report_before_matrix_is_409(self, client):
        company_id = seed_full_company(client)
        assert client.post(f"/companies/{company_id}/swot-analysis").status_code == 200
        response = client.post(f"/companies/{company_id}/generate-strategy-report")
        assert response.status_code == 409

    def test_swot_on_an_empty_company_is_409(self, client):
        company_id = create_company(
            client, {"name": "Empty", "data_source": "nothing at all supplied"}
        )
        response = client.post(f"/companies/{company_id}/swot-analysis")
        assert response.status_code == 409
        assert "empty lists" in response.json()["detail"]

    def test_getting_a_stage_before_running_it_is_404(self, client):
        company_id = seed_full_company(client)
        for path in (
            "swot-analysis",
            "market-attractiveness",
            "pricing-recommendation",
            "strategy-report",
        ):
            assert client.get(f"/companies/{company_id}/{path}").status_code == 404


class TestFullPipeline:
    def test_end_to_end(self, client):
        company_id = seed_full_company(client)

        swot = client.post(f"/companies/{company_id}/swot-analysis").json()
        assert swot["strengths"], "a company ahead of its peers must score strengths"
        assert swot["calculation_basis"]["peers_reporting_financials"] == 3

        matrix = client.post(f"/companies/{company_id}/market-attractiveness").json()
        assert 1.0 <= matrix["overall_attractiveness_score"] <= 5.0
        assert 1.0 <= matrix["competitive_strength_score"] <= 5.0
        assert matrix["quadrant"] in {"INVEST_GROW", "SELECTIVE_INVEST", "HARVEST_DIVEST"}
        assert matrix["calculation_basis"]["market_structure"]["hhi"] > 0

        pricing = client.post(
            f"/companies/{company_id}/pricing-recommendation",
            json={"cost_base": 60.0, "target_margin_pct": 0.4},
        ).json()
        band = pricing["recommended_price_range"]
        assert band["min"] < band["optimal"] < band["max"]
        assert pricing["margin_basis"] == "MARGIN"

        report = client.post(f"/companies/{company_id}/generate-strategy-report").json()
        # No API key is configured in the test environment, so this must be the
        # template path - and it must still be a complete report.
        assert report["narrative_source"] == "template_fallback"
        assert report["ai_narrative"]["executive_summary"]
        assert report["structured_context"]["market_position"]["quadrant"] == matrix["quadrant"]
        assert (
            report["structured_context"]["pricing"]["recommended_price"] == band["optimal"]
        ), "the report must narrate the stored price, not a recomputed one"

        # And every stage is retrievable afterwards.
        for path in (
            "swot-analysis",
            "market-attractiveness",
            "pricing-recommendation",
            "strategy-report",
        ):
            assert client.get(f"/companies/{company_id}/{path}").status_code == 200

    def test_markup_basis_produces_a_lower_price_than_margin_basis(self, client):
        company_id = seed_full_company(client)
        client.post(f"/companies/{company_id}/swot-analysis")

        margin = client.post(
            f"/companies/{company_id}/pricing-recommendation",
            json={"cost_base": 100.0, "target_margin_pct": 0.4, "margin_basis": "MARGIN"},
        ).json()
        markup = client.post(
            f"/companies/{company_id}/pricing-recommendation",
            json={"cost_base": 100.0, "target_margin_pct": 0.4, "margin_basis": "MARKUP"},
        ).json()

        assert (
            markup["recommended_price_range"]["optimal"]
            < margin["recommended_price_range"]["optimal"]
        )

    def test_impossible_margin_is_rejected_by_validation(self, client):
        company_id = seed_full_company(client)
        response = client.post(
            f"/companies/{company_id}/pricing-recommendation",
            json={"cost_base": 100.0, "target_margin_pct": 1.5},
        )
        assert response.status_code == 422

    def test_negative_cost_is_rejected(self, client):
        company_id = seed_full_company(client)
        response = client.post(
            f"/companies/{company_id}/pricing-recommendation",
            json={"cost_base": -10.0, "target_margin_pct": 0.3},
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------
# V3
# --------------------------------------------------------------------------


class TestUncertaintyEndpoint:
    def test_it_needs_a_matrix_first(self, client):
        company_id = create_company(client)
        response = client.post(f"/companies/{company_id}/uncertainty", json={})
        assert response.status_code == 409
        assert "matrix" in response.json()["detail"].lower()

    def test_a_run_with_no_stated_uncertainty_is_decisive(self, client):
        company_id = create_company(client)
        client.post(f"/companies/{company_id}/swot-analysis")
        client.post(f"/companies/{company_id}/market-attractiveness")
        body = client.post(f"/companies/{company_id}/uncertainty", json={}).json()
        assert body["entropy_bits"] == 0.0
        assert body["verdict_stability"] == "DECISIVE"
        assert body["quadrant_probabilities"][body["point_quadrant"]] == 1.0

    def test_stated_ranges_produce_a_distribution(self, client):
        company_id = create_company(client)
        client.post(f"/companies/{company_id}/swot-analysis")
        client.post(f"/companies/{company_id}/market-attractiveness")
        response = client.post(
            f"/companies/{company_id}/uncertainty",
            json={
                "uncertainty_inputs": {
                    "market_growth_pct": {"low": 2.0, "mode": 16.0, "high": 22.0},
                    "competitive_strength_score": {"low": 2.0, "mode": 3.4, "high": 4.5},
                }
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert 0.0 < body["entropy_bits"] <= 1.585
        assert sum(body["quadrant_probabilities"].values()) == 1.0
        assert body["draws"] == 10000
        low, high = body["attractiveness_ci_90"]
        assert low <= high

    def test_the_payload_states_that_the_ranges_are_analyst_supplied(self, client):
        company_id = create_company(client)
        client.post(f"/companies/{company_id}/swot-analysis")
        client.post(f"/companies/{company_id}/market-attractiveness")
        body = client.post(f"/companies/{company_id}/uncertainty", json={}).json()
        assert "THE DISTRIBUTIONS ARE ANALYST-SUPPLIED" in body["calculation_basis"]

    def test_a_mode_outside_its_range_is_a_422(self, client):
        company_id = create_company(client)
        client.post(f"/companies/{company_id}/swot-analysis")
        client.post(f"/companies/{company_id}/market-attractiveness")
        response = client.post(
            f"/companies/{company_id}/uncertainty",
            json={"uncertainty_inputs": {"market_growth_pct": {"low": 1, "mode": 9, "high": 5}}},
        )
        assert response.status_code == 422

    def test_an_unsupported_input_is_a_422_not_a_silent_drop(self, client):
        company_id = create_company(client)
        client.post(f"/companies/{company_id}/swot-analysis")
        client.post(f"/companies/{company_id}/market-attractiveness")
        response = client.post(
            f"/companies/{company_id}/uncertainty",
            json={"uncertainty_inputs": {"gross_margin_pct": {"low": 1, "mode": 2, "high": 3}}},
        )
        assert response.status_code == 422

    def test_persisting_inputs_writes_them_onto_the_company(self, client):
        company_id = create_company(client)
        client.post(f"/companies/{company_id}/swot-analysis")
        client.post(f"/companies/{company_id}/market-attractiveness")
        client.post(
            f"/companies/{company_id}/uncertainty",
            json={
                "uncertainty_inputs": {
                    "market_growth_pct": {"low": 10.0, "mode": 16.0, "high": 20.0}
                },
                "persist_inputs": True,
            },
        )
        stored = client.get(f"/companies/{company_id}").json()["uncertainty_inputs"]
        assert stored["market_growth_pct"]["mode"] == 16.0

    def test_uncertainty_inputs_can_be_supplied_at_creation(self, client):
        payload = {
            **COMPANY,
            "uncertainty_inputs": {
                "market_growth_pct": {"low": 10.0, "mode": 16.0, "high": 24.0}
            },
        }
        company_id = create_company(client, payload)
        client.post(f"/companies/{company_id}/swot-analysis")
        client.post(f"/companies/{company_id}/market-attractiveness")
        body = client.post(f"/companies/{company_id}/uncertainty", json={}).json()
        assert "market_growth_pct" in body["calculation_basis"]["sampled_inputs"]

    def test_getting_it_before_running_it_is_404(self, client):
        company_id = create_company(client)
        assert client.get(f"/companies/{company_id}/uncertainty").status_code == 404


def _scored_company(client, name: str, payload_overrides: dict | None = None) -> str:
    payload = {**COMPANY, "name": name}
    payload.update(payload_overrides or {})
    company_id = create_company(client, payload)
    client.post(f"/companies/{company_id}/swot-analysis")
    client.post(f"/companies/{company_id}/market-attractiveness")
    return company_id


class TestPortfolioEndpoints:
    def test_create_and_allocate(self, client):
        first = _scored_company(client, "Alpha Unit")
        second = _scored_company(client, "Beta Unit")
        response = client.post(
            "/portfolios",
            json={
                "name": "FY26 capital plan",
                "budget": 150.0,
                "members": [
                    {"company_id": first, "revenue": 1000.0, "capital_requested": 100.0},
                    {
                        "company_id": second,
                        "revenue": 500.0,
                        "capital_requested": 100.0,
                        "capital_floor": 25.0,
                    },
                ],
            },
        )
        assert response.status_code == 201
        portfolio_id = response.json()["id"]

        run = client.post(f"/portfolios/{portfolio_id}/allocate", json={}).json()
        assert run["budget"] == 150.0
        assert len(run["allocations"]) == 2
        assert sum(a["allocated"] for a in run["allocations"]) <= 150.0 + 1e-6
        assert run["calculation_basis"]["status"].startswith("PROJECT-DEFINED")

    def test_a_portfolio_of_one_is_refused(self, client):
        only = _scored_company(client, "Solo Unit")
        response = client.post(
            "/portfolios",
            json={
                "name": "Solo",
                "budget": 10.0,
                "members": [{"company_id": only, "capital_requested": 10.0}],
            },
        )
        assert response.status_code == 422

    def test_an_unknown_company_is_404(self, client):
        known = _scored_company(client, "Known Unit")
        response = client.post(
            "/portfolios",
            json={
                "name": "Bad",
                "budget": 10.0,
                "members": [
                    {"company_id": known, "capital_requested": 5.0},
                    {
                        "company_id": "00000000-0000-0000-0000-000000000000",
                        "capital_requested": 5.0,
                    },
                ],
            },
        )
        assert response.status_code == 404

    def test_the_same_company_twice_is_refused(self, client):
        only = _scored_company(client, "Twice Unit")
        response = client.post(
            "/portfolios",
            json={
                "name": "Dupe",
                "budget": 10.0,
                "members": [
                    {"company_id": only, "capital_requested": 5.0},
                    {"company_id": only, "capital_requested": 5.0},
                ],
            },
        )
        assert response.status_code == 422
        assert "compete against itself" in response.json()["detail"]

    def test_an_unscored_member_is_a_409_naming_it(self, client):
        scored = _scored_company(client, "Scored Unit")
        unscored = create_company(client, {**COMPANY, "name": "Unscored Unit"})
        portfolio_id = client.post(
            "/portfolios",
            json={
                "name": "Half-scored",
                "budget": 100.0,
                "members": [
                    {"company_id": scored, "capital_requested": 50.0},
                    {"company_id": unscored, "capital_requested": 50.0},
                ],
            },
        ).json()["id"]
        response = client.post(f"/portfolios/{portfolio_id}/allocate", json={})
        assert response.status_code == 409
        assert "Unscored Unit" in response.json()["detail"]

    def test_floors_above_the_budget_are_a_409_not_a_partial_plan(self, client):
        first = _scored_company(client, "Floor A")
        second = _scored_company(client, "Floor B")
        portfolio_id = client.post(
            "/portfolios",
            json={
                "name": "Underfunded",
                "budget": 50.0,
                "members": [
                    {"company_id": first, "capital_requested": 100.0, "capital_floor": 100.0},
                    {"company_id": second, "capital_requested": 100.0, "capital_floor": 100.0},
                ],
            },
        ).json()["id"]
        response = client.post(f"/portfolios/{portfolio_id}/allocate", json={})
        assert response.status_code == 409
        assert "Shortfall" in response.json()["detail"]

    def test_a_floor_above_its_own_request_is_rejected_at_the_schema(self, client):
        first = _scored_company(client, "Schema A")
        second = _scored_company(client, "Schema B")
        response = client.post(
            "/portfolios",
            json={
                "name": "Bad floors",
                "budget": 500.0,
                "members": [
                    {"company_id": first, "capital_requested": 10.0, "capital_floor": 90.0},
                    {"company_id": second, "capital_requested": 10.0},
                ],
            },
        )
        assert response.status_code == 422

    def test_a_per_run_budget_overrides_the_stored_one(self, client):
        first = _scored_company(client, "Budget A")
        second = _scored_company(client, "Budget B")
        portfolio_id = client.post(
            "/portfolios",
            json={
                "name": "Override",
                "budget": 100.0,
                "members": [
                    {"company_id": first, "capital_requested": 100.0},
                    {"company_id": second, "capital_requested": 100.0},
                ],
            },
        ).json()["id"]
        run = client.post(f"/portfolios/{portfolio_id}/allocate", json={"budget": 200.0}).json()
        assert run["budget"] == 200.0
        assert all(a["outcome"] == "FUNDED" for a in run["allocations"])

    def test_runs_are_listed_and_the_portfolio_is_fetchable(self, client):
        first = _scored_company(client, "List A")
        second = _scored_company(client, "List B")
        portfolio_id = client.post(
            "/portfolios",
            json={
                "name": "Listable",
                "budget": 100.0,
                "members": [
                    {"company_id": first, "capital_requested": 60.0},
                    {"company_id": second, "capital_requested": 60.0},
                ],
            },
        ).json()["id"]
        client.post(f"/portfolios/{portfolio_id}/allocate", json={})
        client.post(f"/portfolios/{portfolio_id}/allocate", json={"budget": 120.0})
        runs = client.get(f"/portfolios/{portfolio_id}/allocations").json()
        assert len(runs) == 2
        assert client.get(f"/portfolios/{portfolio_id}").json()["name"] == "Listable"
        assert any(p["id"] == portfolio_id for p in client.get("/portfolios").json())

    def test_deleting_a_portfolio_does_not_delete_its_companies(self, client):
        first = _scored_company(client, "Keep A")
        second = _scored_company(client, "Keep B")
        portfolio_id = client.post(
            "/portfolios",
            json={
                "name": "Temporary",
                "budget": 10.0,
                "members": [
                    {"company_id": first, "capital_requested": 5.0},
                    {"company_id": second, "capital_requested": 5.0},
                ],
            },
        ).json()["id"]
        assert client.delete(f"/portfolios/{portfolio_id}").status_code == 204
        assert client.get(f"/companies/{first}").status_code == 200

    def test_an_unknown_portfolio_is_404(self, client):
        assert client.get("/portfolios/00000000-0000-0000-0000-000000000000").status_code == 404


class TestBenchmarkProvenanceEndpoint:
    def test_it_reports_the_live_table(self, client):
        body = client.get("/benchmarks/provenance").json()
        assert "provenance" in body
        assert "_default" in body["metrics_by_sector"]
        assert "how_to_rebuild" in body

    def test_it_admits_when_the_table_is_placeholders(self, client):
        # The test suite runs with no INDUSTRY_BENCHMARKS_PATH, so this is the
        # built-in table and the endpoint must say so rather than dressing it up.
        body = client.get("/benchmarks/provenance").json()
        assert body["is_edgar_sourced"] is False
        assert "PLACEHOLDER" in body["provenance"]

    def test_building_without_a_user_agent_is_refused_immediately(self, client):
        # The suite runs with no EDGAR_USER_AGENT. Failing now beats failing
        # two minutes into a job on a problem the server could see at once.
        response = client.post("/benchmarks/build", json={"period": "CY2024"})
        assert response.status_code == 503
        assert response.json()["code"] == "NOT_CONFIGURED"


class TestMethodologyV3:
    def test_it_publishes_the_uncertainty_parameters(self, client):
        body = client.get("/methodology").json()
        assert body["uncertainty"]["draws"] == 10000
        assert body["uncertainty"]["distribution"] == "PERT"
        assert "ANALYST-SUPPLIED" in body["uncertainty"]["status"]

    def test_it_publishes_the_allocation_rule_with_its_label(self, client):
        body = client.get("/methodology").json()
        assert body["portfolio_allocation"]["status"].startswith("PROJECT-DEFINED")
        assert "General Electric" in body["portfolio_allocation"]["framework_note"]

    def test_it_publishes_the_edgar_configuration(self, client):
        body = client.get("/methodology").json()
        assert body["edgar"]["min_sector_n"] == 20
        assert body["edgar"]["requests_per_second"] == 5.0


# --------------------------------------------------------------------------
# V3.1
# --------------------------------------------------------------------------


class TestPaginationEndpoint:
    def _seed(self, client, count: int) -> None:
        for index in range(count):
            create_company(
                client,
                {
                    **COMPANY,
                    "name": f"Paged {index:02d}",
                    "industry": "saas" if index % 2 else "retail",
                },
            )

    def test_a_page_carries_items_and_a_cursor(self, client):
        self._seed(client, 7)
        body = client.get("/companies", params={"limit": 3}).json()
        assert len(body["items"]) == 3
        assert body["next_cursor"]
        assert body["total"] is None

    def test_paging_through_visits_every_row_exactly_once(self, client):
        self._seed(client, 11)
        seen: list[str] = []
        cursor = None
        for _ in range(10):
            params = {"limit": 4}
            if cursor:
                params["cursor"] = cursor
            body = client.get("/companies", params=params).json()
            seen += [item["id"] for item in body["items"]]
            cursor = body["next_cursor"]
            if not cursor:
                break
        assert len(seen) == 11
        assert len(set(seen)) == 11, "a row appeared on two pages"

    def test_the_last_page_has_no_cursor(self, client):
        self._seed(client, 3)
        body = client.get("/companies", params={"limit": 50}).json()
        assert body["next_cursor"] is None

    def test_an_insert_mid_paging_does_not_duplicate_a_row(self, client):
        # The reason for keyset over offset: with OFFSET, inserting a newer row
        # shifts every later page by one, so a row is shown twice and another
        # is never shown at all.
        self._seed(client, 6)
        first = client.get("/companies", params={"limit": 3}).json()
        create_company(client, {**COMPANY, "name": "Inserted Later"})
        second = client.get(
            "/companies", params={"limit": 3, "cursor": first["next_cursor"]}
        ).json()
        assert not ({i["id"] for i in first["items"]} & {i["id"] for i in second["items"]})

    def test_total_is_opt_in(self, client):
        self._seed(client, 5)
        body = client.get("/companies", params={"limit": 2, "with_total": True}).json()
        assert body["total"] == 5

    def test_filtering_by_industry(self, client):
        self._seed(client, 6)
        body = client.get("/companies", params={"industry": "SaaS", "limit": 50}).json()
        assert body["items"]
        assert all(item["industry"] == "saas" for item in body["items"])

    def test_searching_by_name(self, client):
        self._seed(client, 4)
        body = client.get("/companies", params={"q": "paged 02"}).json()
        assert [item["name"] for item in body["items"]] == ["Paged 02"]

    def test_the_limit_is_clamped_to_the_configured_maximum(self, client):
        self._seed(client, 3)
        assert client.get("/companies", params={"limit": 500}).status_code == 200
        assert client.get("/companies", params={"limit": 5000}).status_code == 422

    def test_a_forged_cursor_is_a_422_with_advice(self, client):
        response = client.get("/companies", params={"cursor": "!!!not-a-cursor"})
        assert response.status_code == 422
        assert "start from the first page" in response.json()["detail"]


class TestJobsEndpoints:
    def test_listing_is_empty_to_begin_with(self, client):
        assert client.get("/jobs").json() == []

    def test_an_unknown_job_is_404(self, client):
        import uuid as _uuid

        response = client.get(f"/jobs/{_uuid.uuid4()}")
        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"

    def test_a_panel_build_without_a_user_agent_is_refused(self, client):
        response = client.post("/validation/panels", json={"scoring_period": "CY2020"})
        assert response.status_code == 503
        assert response.json()["code"] == "NOT_CONFIGURED"

    def test_the_build_request_refuses_a_path_outside_data(self, client):
        response = client.post(
            "/benchmarks/build", json={"period": "CY2024", "out": "/etc/passwd"}
        )
        assert response.status_code == 422

    def test_a_queued_job_can_be_cancelled_and_then_not_again(self, client, db_session):
        from app.config import Settings
        from app.services import jobs as jobs_service

        db, _engine = db_session

        @jobs_service.register("test.api")
        def _api(_context, _params, _settings):
            return {}

        jobs_service.shutdown_runner(wait=False)   # nothing will pick it up
        row = jobs_service.submit(
            db, "test.api", {}, settings=Settings(_env_file=None), dedupe=False
        )

        assert client.get(f"/jobs/{row.id}").json()["state"] == "QUEUED"
        assert client.post(f"/jobs/{row.id}/cancel").json()["state"] == "CANCELLED"

        again = client.post(f"/jobs/{row.id}/cancel")
        assert again.status_code == 409
        assert again.json()["code"] == "JOB_CONFLICT"

    def test_a_pending_job_tells_the_client_when_to_poll(self, client, db_session):
        from app.config import Settings
        from app.services import jobs as jobs_service

        db, _engine = db_session

        @jobs_service.register("test.retry")
        def _retry(_context, _params, _settings):
            return {}

        jobs_service.shutdown_runner(wait=False)
        row = jobs_service.submit(
            db, "test.retry", {}, settings=Settings(_env_file=None), dedupe=False
        )
        assert client.get(f"/jobs/{row.id}").headers["Retry-After"] == "2"


class TestReadiness:
    def test_ready_reports_each_dependency_separately(self, client):
        body = client.get("/ready").json()
        assert body["status"] in {"ready", "degraded"}
        assert body["checks"]["database"]["ok"] is True
        assert "latency_ms" in body["checks"]["database"]
        assert body["checks"]["schema"]["ok"] is True
        assert body["checks"]["benchmarks"]["sectors"] > 0
        assert "jobs" in body["checks"]

    def test_liveness_touches_nothing(self, client):
        # A liveness probe that checks the database restarts the API whenever
        # the database hiccups, turning a dependency blip into a self-inflicted
        # outage. This one only reports that the process is up.
        body = client.get("/health").json()
        assert set(body) == {"status", "version", "uptime_seconds"}


class TestConditionalRequests:
    def test_methodology_serves_an_etag_and_then_a_304(self, client):
        first = client.get("/methodology")
        etag = first.headers["ETag"]
        assert etag.startswith('W/"')
        second = client.get("/methodology", headers={"If-None-Match": etag})
        assert second.status_code == 304
        assert second.content == b""

    def test_a_stale_etag_gets_the_body(self, client):
        response = client.get("/methodology", headers={"If-None-Match": 'W/"stale"'})
        assert response.status_code == 200
        assert response.json()["attractiveness_weights"]
