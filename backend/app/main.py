"""StrategySphere API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.session import Base, engine
from app.routers import analysis, companies
from app.services.benchmarks import load_industry_benchmarks

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("strategysphere")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # create_all is adequate here because the schema is append-only for V1.
    # A migration tool (Alembic) is the correct answer the moment a column
    # needs to change shape - noted in docs/architecture.md.
    Base.metadata.create_all(bind=engine)

    settings = get_settings()
    _, provenance = load_industry_benchmarks(settings.industry_benchmarks_path)
    logger.info("Industry benchmark table: %s", provenance)
    if not settings.anthropic_api_key:
        logger.info(
            "No ANTHROPIC_API_KEY configured. Strategy reports will use the deterministic "
            "template fallback - every number is identical, only the prose is missing."
        )
    yield


settings = get_settings()

app = FastAPI(
    title="StrategySphere API",
    version="1.0.0",
    description=(
        "Executive decision intelligence. A SWOT scoring engine benchmarked against "
        "peer financials, a GE-McKinsey market attractiveness matrix, and a "
        "cost-plus/competitor-benchmarked pricing model. Every strategic figure is "
        "computed deterministically; the LLM only narrates the computed output."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (companies, analysis):
    app.include_router(module.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/methodology", tags=["meta"])
def methodology() -> dict[str, object]:
    """The parameter set currently in force.

    Exposed as an endpoint because the honest claim this project makes - that
    the scores are computed, not generated - is only checkable if the weights
    and thresholds behind them are visible without reading the source.
    """
    _, provenance = load_industry_benchmarks(settings.industry_benchmarks_path)
    return {
        "frameworks": [
            "GE-McKinsey market attractiveness matrix (GE / McKinsey, c. 1971)",
            "Herfindahl-Hirschman Index, DOJ/FTC 2023 Merger Guidelines bands",
            "Cost-plus and competitor-benchmark pricing with a value adjustment",
        ],
        "attractiveness_weights": settings.attractiveness_weights,
        "quadrant_thresholds": {
            "high": settings.quadrant_high_threshold,
            "low": settings.quadrant_low_threshold,
            "borderline_margin": settings.quadrant_borderline_margin,
        },
        "swot_thresholds_pct": {
            "neutral_band": settings.swot_neutral_band_pct,
            "impact_2": settings.swot_score_2_pct,
            "impact_3": settings.swot_score_3_pct,
            "impact_4": settings.swot_score_4_pct,
            "impact_5": settings.swot_score_5_pct,
        },
        "swot_weakness_penalty": settings.swot_weakness_penalty,
        "hhi_bands": {
            "unconcentrated_below": settings.hhi_unconcentrated_max,
            "highly_concentrated_above": settings.hhi_highly_concentrated_min,
        },
        "pricing": {
            "default_margin_basis": settings.pricing_default_margin_basis,
            "weights": {
                "cost_plus": settings.pricing_w_cost_plus,
                "competitor_benchmark": settings.pricing_w_competitor,
            },
            "value_coefficient_k": settings.pricing_value_coefficient,
            "value_adjustment_cap": settings.pricing_value_adjustment_cap,
            "range_spread": settings.pricing_range_spread,
        },
        "benchmark_provenance": provenance,
        "llm_role": (
            "Narration only. Every figure in a strategy report exists in "
            "structured_context before the model is called, and cited factor names "
            "not present in that context are dropped."
        ),
    }
