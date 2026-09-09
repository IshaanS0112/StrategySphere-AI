"""StrategySphere API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import inspect

from app.config import get_settings
from app.db.session import engine
from app.routers import analysis, companies, strategy_v2
from app.services.benchmarks import load_industry_benchmarks

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("strategysphere")


EXPECTED_TABLES = {
    "companies",
    "competitors",
    "swot_analyses",
    "market_attractiveness",
    "pricing_recommendations",
    "strategy_reports",
    "porters_analyses",
    "scenarios",
}


def _assert_schema_present() -> None:
    """Fail fast on an unmigrated database rather than at the first query."""
    present = set(inspect(engine).get_table_names())
    missing = EXPECTED_TABLES - present
    if missing:
        raise RuntimeError(
            "Database schema is missing "
            f"{sorted(missing)}. Run migrations before starting the API:\n"
            "    cd backend && alembic upgrade head\n"
            "If this is an existing V1 database created by create_all, first "
            "record the baseline:\n"
            "    alembic stamp 0001_v1_baseline && alembic upgrade head"
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    # V1 called Base.metadata.create_all here. That works while a schema is
    # append-only and stops working the moment a column changes shape, which
    # V2 needed. The app no longer creates its own schema: Alembic owns it, the
    # container entrypoint runs `alembic upgrade head` before uvicorn starts,
    # and a mismatch is now a loud startup error instead of a table that
    # silently lacks the column the code expects.
    _assert_schema_present()

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
    version="2.0.0",
    description=(
        "Executive decision intelligence. A SWOT scoring engine benchmarked against "
        "peer financials, a GE-McKinsey market attractiveness matrix, Porter's Five "
        "Forces, a cost-plus/competitor-benchmarked pricing model, analytic "
        "sensitivity analysis, what-if scenarios, multi-period tracking, and a "
        "backtest harness. Every strategic figure is computed deterministically; "
        "the LLM only narrates the computed output."
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

for module in (companies, analysis, strategy_v2):
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
            "Porter's Five Forces (Porter, HBR 1979)",
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
        "porters": {
            "scale_direction": (
                "1-5, higher = stronger force = worse for incumbents. This is the "
                "OPPOSITE direction to the GE-McKinsey attractiveness axis."
            ),
            "attractive_below": settings.porter_attractive_below,
            "unattractive_above": settings.porter_unattractive_above,
            "min_input_coverage": settings.porter_min_input_coverage,
            "composite_status": (
                "PROJECT-DEFINED COMPOSITE, not part of Porter's framework"
            ),
        },
        "sensitivity": {
            "method": "analytic - the attractiveness score is linear in its axes",
            "fragile_at_or_below": settings.sensitivity_fragile_threshold,
            "knife_edge_at_or_below": settings.sensitivity_knife_edge_threshold,
        },
        "multi_period": {
            "trend_material_delta": settings.trend_material_delta,
            "ordering": "by period_end; period_label is never used to sort",
        },
        "validation": {
            "permutations": settings.validation_permutations,
            "seed": settings.validation_random_seed,
            "null_model": "outcomes shuffled across companies, quadrant labels fixed",
        },
        "benchmark_provenance": provenance,
        "llm_role": (
            "Narration only. Every figure in a strategy report exists in "
            "structured_context before the model is called, and cited factor names "
            "not present in that context are dropped."
        ),
    }
