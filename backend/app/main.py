"""StrategySphere API entrypoint."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from sqlalchemy import inspect, text

from app import errors, obs
from app.config import get_settings
from app.db.session import engine
from app.services import cache
from app.routers import analysis, companies, jobs as jobs_router, strategy_v2, strategy_v3
from app.services.portfolio import ALLOCATION_RULE_STATUS
from app.services.uncertainty import SUPPORTED_INPUTS as SUPPORTED_UNCERTAINTY_INPUTS

logger = logging.getLogger("strategysphere")
STARTED_AT = time.time()


EXPECTED_TABLES = {
    "companies",
    "competitors",
    "swot_analyses",
    "market_attractiveness",
    "pricing_recommendations",
    "strategy_reports",
    "porters_analyses",
    "scenarios",
    "uncertainty_analyses",
    "portfolios",
    "portfolio_members",
    "allocation_runs",
    "jobs",
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
    settings_at_boot = get_settings()
    obs.configure_logging(settings_at_boot.log_level, settings_at_boot.log_format)

    # V1 called Base.metadata.create_all here.
    _assert_schema_present()

    settings = get_settings()
    provenance = cache.benchmark_table(settings.industry_benchmarks_path).provenance
    logger.info("benchmark table loaded", extra={"ctx_provenance": provenance})
    if not settings.edgar_user_agent:
        logger.info(
            "No EDGAR_USER_AGENT configured. The API runs normally; rebuilding the "
            "benchmark table from data.sec.gov requires one and will refuse without it."
        )
    if not settings.anthropic_api_key:
        logger.info(
            "no ANTHROPIC_API_KEY configured; strategy reports use the deterministic "
            "template fallback - every number is identical, only the prose is missing"
        )

    from app.services import jobs

    jobs.start_runner(settings)
    try:
        yield
    finally:
        # Drain in-flight jobs on shutdown rather than killing them mid-write,
        # which would leave a RUNNING row nobody will ever finish.
        jobs.shutdown_runner()


settings = get_settings()

app = FastAPI(
    title="StrategySphere API",
    version="3.1.0",
    description=(
        "Executive decision intelligence. A SWOT scoring engine benchmarked against "
        "peer financials or sector medians built from SEC XBRL filings, a "
        "GE-McKinsey market attractiveness matrix, Porter's Five Forces, a "
        "cost-plus/competitor-benchmarked pricing model, analytic sensitivity "
        "analysis, Monte-Carlo uncertainty propagation, what-if scenarios, "
        "multi-period tracking, portfolio-level capital allocation, and a backtest "
        "harness. Every strategic figure is computed deterministically; the LLM "
        "only narrates the computed output."
    ),
    lifespan=lifespan,
)

# Order matters: the observability middleware is added last, so it sits OUTERMOST
# and therefore times and logs everything the others do - including the cost of
# compression and the CORS preflights.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Without this the browser cannot read the id it needs to quote in a bug
    # report, which makes the whole request-id scheme decorative.
    expose_headers=[obs.REQUEST_ID_HEADER, "Server-Timing", "ETag"],
)
app.add_middleware(
    obs.ObservabilityMiddleware, slow_request_seconds=settings.slow_request_seconds
)

errors.install_handlers(app)

for module in (companies, analysis, strategy_v2, strategy_v3, jobs_router):
    app.include_router(module.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, object]:
    """Liveness. Deliberately touches nothing."""
    return {"status": "ok", "version": app.version, "uptime_seconds": round(time.time() - STARTED_AT, 1)}


@app.get("/ready", tags=["meta"])
def ready() -> dict[str, object]:
    """Readiness: can this process actually serve a request right now?"""
    from app.services import jobs

    checks: dict[str, object] = {}
    healthy = True

    started = time.perf_counter()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = {
            "ok": True,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:  # noqa: BLE001 - the reason is the payload
        healthy = False
        checks["database"] = {"ok": False, "error": str(exc)}

    try:
        present = set(inspect(engine).get_table_names())
        missing = sorted(EXPECTED_TABLES - present)
        checks["schema"] = {"ok": not missing, "missing": missing}
        healthy = healthy and not missing
    except Exception as exc:  # noqa: BLE001
        healthy = False
        checks["schema"] = {"ok": False, "error": str(exc)}

    table = cache.benchmark_table(settings.industry_benchmarks_path)
    checks["benchmarks"] = {
        "ok": bool(table.rows),
        "sectors": len(table.rows),
        "sourced": table.provenance_detail is not None,
    }
    checks["jobs"] = jobs.runner_status()

    payload = {"status": "ready" if healthy else "degraded", "checks": checks}
    if not healthy:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/metrics", tags=["meta"], include_in_schema=False)
def metrics() -> Response:
    """Prometheus text exposition."""
    if not settings.metrics_enabled:
        raise errors.AppError(errors.NOT_CONFIGURED, "Metrics are disabled by configuration.")
    obs.METRICS.set_gauge("app_uptime_seconds", round(time.time() - STARTED_AT, 1))
    return Response(content=obs.METRICS.render(), media_type="text/plain; version=0.0.4")


@app.get("/methodology", tags=["meta"])
def methodology(request: Request, response: Response) -> object:
    """The parameter set currently in force."""
    provenance = cache.benchmark_table(settings.industry_benchmarks_path).provenance
    payload: dict[str, object] = {
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
        "uncertainty": {
            "draws": settings.uncertainty_draws,
            "seed": settings.uncertainty_seed,
            "distribution": settings.uncertainty_distribution,
            "pert_lambda": settings.uncertainty_pert_lambda,
            "credible_interval_pct": settings.uncertainty_credible_interval_pct,
            "stability_bands": {
                "DECISIVE_below": settings.uncertainty_decisive_below,
                "CONTESTED_at_or_above": settings.uncertainty_contested_at_or_above,
                "max_entropy_bits": round(settings.max_entropy_bits, 4),
            },
            "inputs_accepted": list(SUPPORTED_UNCERTAINTY_INPUTS),
            "status": (
                "THE DISTRIBUTIONS ARE ANALYST-SUPPLIED. Quadrant probabilities are "
                "conditional on ranges a human typed; they are not objective "
                "probabilities that a verdict is correct."
            ),
            "versus_sensitivity": (
                "Sensitivity asks how far ONE input must move to flip the verdict. "
                "Uncertainty asks how likely EACH verdict is given everything stated. "
                "They disagree often, and the disagreement is informative."
            ),
        },
        "portfolio_allocation": {
            "status": ALLOCATION_RULE_STATUS,
            "priority_formula": (
                "attractiveness x strength x (1 - entropy_bits / log2(3))"
            ),
            "harvest_contribution_rate": settings.harvest_contribution_rate,
            "allocation_order": [
                "fund every capital_floor, erroring if they exceed the pool",
                "HARVEST_DIVEST units contribute a fraction of revenue to the pool",
                "allocate the remainder greedily by priority, capped at each request",
                "report the unfunded units and the marginal one",
            ],
            "framework_note": (
                "GE-McKinsey was built by McKinsey for General Electric to allocate "
                "capital across business units, so portfolio use is its original "
                "purpose. It prescribes no allocation ARITHMETIC, which is why the "
                "rule above is labelled project-defined."
            ),
        },
        "edgar": {
            "source": "SEC EDGAR XBRL frames API, data.sec.gov",
            "user_agent_configured": bool(settings.edgar_user_agent),
            "requests_per_second": settings.edgar_requests_per_second,
            "min_sector_n": settings.edgar_min_sector_n,
            "sic_lookup_limit": settings.edgar_sic_lookup_limit,
            "note": (
                "EDGAR_USER_AGENT has no default; the client refuses to construct "
                "without one, so an anonymous request never reaches SEC "
                "infrastructure. Building the table is a CLI job, not an endpoint."
            ),
        },
        "benchmark_provenance": provenance,
        "benchmark_detail_endpoint": "GET /benchmarks/provenance",
        "llm_role": (
            "Narration only. Every figure in a strategy report exists in "
            "structured_context before the model is called, and cited factor names "
            "not present in that context are dropped."
        ),
    }

    # This payload changes only when configuration or the benchmark file does, and
    # the dashboard requests it on every page load.
    etag = cache.etag_for(payload)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=60"
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return payload
