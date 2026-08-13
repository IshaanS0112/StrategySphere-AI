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
        assert client.get("/health").json() == {"status": "ok"}

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
