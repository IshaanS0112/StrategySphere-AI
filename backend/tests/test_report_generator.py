"""Report generation."""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.enums import MarginBasis, NarrativeSource, Quadrant, SwotCategory
from app.services import report_generator
from app.services.attractiveness_matrix import AttractivenessResult
from app.services.pricing_engine import PricingResult
from app.services.swot_engine import SwotFactor, SwotResult


@pytest.fixture
def swot() -> SwotResult:
    result = SwotResult(
        calculation_basis={
            "factor_counts": {"strengths": 1, "weaknesses": 1, "opportunities": 0, "threats": 1},
            "benchmark_provenance": "test fixture",
        }
    )
    result.strengths.append(
        SwotFactor(
            factor="Operating margin",
            category=SwotCategory.STRENGTH,
            evidence="Operating margin 21% vs peer-set median 11%",
            impact_score=4,
            source="computed_financial",
            metric="operating_margin_pct",
        )
    )
    result.weaknesses.append(
        SwotFactor(
            factor="Debt-to-equity",
            category=SwotCategory.WEAKNESS,
            evidence="Debt-to-equity 2.6x vs industry benchmark 1.0x",
            impact_score=5,
            source="computed_financial",
            metric="debt_to_equity",
        )
    )
    result.threats.append(
        SwotFactor(
            factor="Intense competitive rivalry",
            category=SwotCategory.THREAT,
            evidence="HHI of 820 places this market in the UNCONCENTRATED band",
            impact_score=4,
            source="computed_market",
            metric="competitive_intensity_score",
        )
    )
    return result


@pytest.fixture
def attractiveness() -> AttractivenessResult:
    return AttractivenessResult(
        market_growth_score=5.0,
        market_size_score=4.0,
        profitability_score=4.0,
        competitive_intensity_score=4.5,
        overall_attractiveness_score=3.9,
        competitive_strength_score=3.0,
        quadrant=Quadrant.SELECTIVE_INVEST,
        borderline=False,
        calculation_basis={"weights": {"market_growth": 0.3}, "imputed_axes": []},
    )


@pytest.fixture
def pricing() -> PricingResult:
    return PricingResult(
        cost_base=60.0,
        target_margin_pct=0.4,
        margin_basis=MarginBasis.MARGIN,
        cost_plus_price=100.0,
        competitor_avg_price=102.5,
        value_adjustment_factor=1.0,
        recommended_price=101.25,
        recommended_price_range={"min": 91.13, "optimal": 101.25, "max": 111.38},
        implied_margin_pct=40.74,
        confidence="HIGH",
        reasoning={"warnings": [], "confidence": "HIGH"},
        calculation_basis={},
    )


@pytest.fixture
def context(swot, attractiveness, pricing) -> dict:
    return report_generator.build_structured_context(
        company_id="00000000-0000-0000-0000-000000000001",
        company_name="Testco",
        industry="saas",
        data_source="unit test fixture",
        swot=swot,
        attractiveness=attractiveness,
        pricing=pricing,
    )


class TestStructuredContext:
    def test_contains_every_computed_figure(self, context):
        assert context["market_position"]["market_attractiveness_score"] == 3.9
        assert context["market_position"]["competitive_strength_score"] == 3.0
        assert context["market_position"]["quadrant"] == "SELECTIVE_INVEST"
        assert context["pricing"]["recommended_price"] == 101.25
        assert context["pricing"]["implied_margin_pct"] == 40.74

    def test_is_json_serialisable(self, context):
        """It is sent to the model and stored in JSONB; it has to round-trip."""
        assert json.loads(json.dumps(context, default=str))

    def test_works_without_a_pricing_stage(self, swot, attractiveness):
        context = report_generator.build_structured_context(
            company_id="x",
            company_name="Testco",
            industry=None,
            data_source=None,
            swot=swot,
            attractiveness=attractiveness,
            pricing=None,
        )
        assert context["pricing"] is None


class TestValidation:
    def test_valid_citations_survive(self, context):
        raw = json.dumps(
            {
                "executive_summary": "Attractiveness 3.9, strength 3.0.",
                "strategic_position": "Selective investment.",
                "key_factors": [{"factor": "Operating margin", "implication": "Pricing power."}],
                "pricing_rationale": "Blended anchors.",
                "recommendation": "Invest selectively.",
            }
        )
        result = report_generator._validate_narrative(raw, context)
        assert [f["factor"] for f in result["key_factors"]] == ["Operating margin"]
        assert result["dropped_citations"] == 0

    def test_invented_factors_are_dropped(self, context):
        raw = json.dumps(
            {
                "executive_summary": "...",
                "strategic_position": "...",
                "key_factors": [
                    {"factor": "Operating margin", "implication": "real"},
                    {"factor": "Exclusive government contract", "implication": "invented"},
                    {"factor": "Best-in-class NPS", "implication": "also invented"},
                ],
                "pricing_rationale": "...",
                "recommendation": "...",
            }
        )
        result = report_generator._validate_narrative(raw, context)
        assert [f["factor"] for f in result["key_factors"]] == ["Operating margin"]
        assert result["dropped_citations"] == 2

    def test_code_fences_are_tolerated(self, context):
        raw = (
            '```json\n{"executive_summary": "a", "strategic_position": "b", '
            '"key_factors": [], "recommendation": "c"}\n```'
        )
        result = report_generator._validate_narrative(raw, context)
        assert result["executive_summary"] == "a"

    def test_missing_required_key_raises(self, context):
        raw = json.dumps({"executive_summary": "a"})
        with pytest.raises(ValueError, match="missing required key"):
            report_generator._validate_narrative(raw, context)

    def test_non_object_json_raises(self, context):
        with pytest.raises(ValueError, match="not an object"):
            report_generator._validate_narrative("[1, 2, 3]", context)


class TestFallback:
    def test_no_api_key_produces_a_complete_report(self, context):
        narrative = report_generator.generate_narrative(context, Settings(_env_file=None))
        assert narrative["generated_by"] == NarrativeSource.TEMPLATE_FALLBACK.value
        assert narrative["fallback_reason"] == "no ANTHROPIC_API_KEY configured"
        for key in (
            "executive_summary",
            "strategic_position",
            "key_factors",
            "pricing_rationale",
            "recommendation",
        ):
            assert narrative[key] or narrative[key] == []

    def test_fallback_cites_the_same_numbers(self, context):
        narrative = report_generator._fallback_narrative(context, "test")
        summary = narrative["executive_summary"]
        assert "3.9" in summary
        assert "3.0" in summary
        assert "SELECTIVE_INVEST" in summary
        assert "101.25" in summary

    def test_fallback_only_cites_real_factors(self, context):
        narrative = report_generator._fallback_narrative(context, "test")
        allowed = report_generator._valid_factor_names(context)
        assert all(f["factor"] in allowed for f in narrative["key_factors"])

    def test_borderline_placement_is_stated(self, context):
        context["market_position"]["borderline"] = True
        narrative = report_generator._fallback_narrative(context, "test")
        assert "borderline" in narrative["executive_summary"].lower()
        assert "boundary" in narrative["recommendation"].lower()

    def test_low_pricing_confidence_is_stated(self, context):
        context["pricing"]["confidence"] = "LOW"
        narrative = report_generator._fallback_narrative(context, "test")
        assert "LOW" in narrative["recommendation"]

    def test_model_failure_falls_back_rather_than_raising(self, context, monkeypatch):
        settings = Settings(_env_file=None, anthropic_api_key="sk-test-not-real")

        class ExplodingAnthropic:
            def __init__(self, **_kwargs):
                raise RuntimeError("connection refused")

        import anthropic

        monkeypatch.setattr(anthropic, "Anthropic", ExplodingAnthropic)
        narrative = report_generator.generate_narrative(context, settings)
        assert narrative["generated_by"] == NarrativeSource.TEMPLATE_FALLBACK.value
        assert "connection refused" in narrative["fallback_reason"]

    def test_unparseable_model_output_falls_back(self, context, monkeypatch):
        settings = Settings(_env_file=None, anthropic_api_key="sk-test-not-real")

        class Block:
            text = 'this is not json at all", }'

        class Response:
            content = [Block()]

        class FakeMessages:
            def create(self, **_kwargs):
                return Response()

        class FakeAnthropic:
            def __init__(self, **_kwargs):
                self.messages = FakeMessages()

        import anthropic

        monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
        narrative = report_generator.generate_narrative(context, settings)
        assert narrative["generated_by"] == NarrativeSource.TEMPLATE_FALLBACK.value
        assert "unparseable" in narrative["fallback_reason"]

    def test_successful_model_call_is_used_and_validated(self, context, monkeypatch):
        settings = Settings(_env_file=None, anthropic_api_key="sk-test-not-real")

        payload = json.dumps(
            {
                "executive_summary": "Attractiveness 3.9 against strength 3.0.",
                "strategic_position": "Selective investment.",
                "key_factors": [
                    {"factor": "Operating margin", "implication": "real"},
                    {"factor": "Fictional moat", "implication": "invented"},
                ],
                "pricing_rationale": "Blended anchors.",
                "recommendation": "Invest selectively.",
            }
        )[1:]  # the client prefills the opening brace

        class Block:
            text = payload

        class Response:
            content = [Block()]

        class FakeMessages:
            def create(self, **_kwargs):
                return Response()

        class FakeAnthropic:
            def __init__(self, **_kwargs):
                self.messages = FakeMessages()

        import anthropic

        monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
        narrative = report_generator.generate_narrative(context, settings)
        assert narrative["generated_by"] == NarrativeSource.LLM.value
        assert [f["factor"] for f in narrative["key_factors"]] == ["Operating margin"]
        assert narrative["dropped_citations"] == 1
