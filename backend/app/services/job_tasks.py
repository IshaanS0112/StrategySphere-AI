"""The jobs this application knows how to run."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services import cache
from app.services.jobs import JobContext, register

logger = logging.getLogger("strategysphere.jobs")

BENCHMARK_BUILD = "benchmarks.build"
PANEL_BUILD = "validation.panel"


@register(BENCHMARK_BUILD)
def build_benchmarks(context: JobContext, params: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Rebuild the industry benchmark table from SEC XBRL filings."""
    from app.services.edgar.benchmark_builder import build_benchmark_table
    from app.services.edgar.client import EdgarClient

    period = str(params.get("period", "CY2024"))
    out_path = Path(str(params.get("out") or f"data/benchmarks/edgar_{period}.json"))
    min_sector_n = int(params.get("min_sector_n", settings.edgar_min_sector_n))
    sic_limit = int(params.get("sic_limit", settings.edgar_sic_lookup_limit))

    context.log(f"building {period} benchmarks")
    client = EdgarClient(
        user_agent=settings.edgar_user_agent,
        cache_dir=settings.edgar_cache_dir,
        requests_per_second=settings.edgar_requests_per_second,
        timeout_seconds=settings.edgar_timeout_seconds,
        offline=bool(params.get("offline", settings.edgar_offline)),
        concurrency=settings.edgar_concurrency,
    )

    # The builder reports free-text progress; translate it to a fraction so the UI
    # has something to draw.
    state = {"step": 0}
    total_steps = 9

    def progress(message: str) -> None:
        if message.startswith("resolving") or message.startswith("classifying"):
            state["step"] = min(state["step"] + 1, total_steps - 1)
        context.progress(state["step"] / total_steps, message.strip())

    result = build_benchmark_table(
        client,
        period=period,
        prior_period=params.get("prior_period"),
        min_sector_n=min_sector_n,
        sic_lookup_limit=sic_limit,
        progress=progress,
    )

    context.check_cancelled()
    context.progress(0.95, f"writing {out_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = out_path.with_suffix(out_path.suffix + ".partial")
    temporary.write_text(json.dumps(result.payload(), indent=2, sort_keys=True))
    temporary.replace(out_path)

    # The live table is cached on (path, mtime, size), so a rebuild of a DIFFERENT
    # path needs no invalidation and a rebuild of the live one is picked up
    # automatically.
    cache.invalidate_benchmark_table()

    provenance = result.provenance
    return {
        "path": str(out_path),
        "period": period,
        "companies_considered": provenance["companies_considered"],
        "sectors_published": provenance["sectors_published"],
        "sectors_below_min_n": provenance["sectors_below_min_n"],
        "coverage_by_metric": {
            key: {"resolved": entry["resolved"], "coverage_pct": entry["coverage_pct"]}
            for key, entry in provenance["coverage_by_metric"].items()
        },
        "fetch_stats": provenance["fetch_stats"],
        "is_live_table": str(out_path) == settings.industry_benchmarks_path,
    }


@register(PANEL_BUILD)
def build_panel(context: JobContext, params: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Assemble a validation panel by scoring filings through the real pipeline."""
    import subprocess
    import sys

    period = str(params.get("scoring_period", "CY2020"))
    horizon = int(params.get("horizon", 3))
    out = params.get("out")

    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[2] / "scripts" / "build_edgar_panel.py"),
        "--scoring-period",
        period,
        "--horizon",
        str(horizon),
        "--quiet",
    ]
    if out:
        command += ["--out", str(out)]
    if params.get("offline"):
        command.append("--offline")

    context.log(f"assembling panel {period} +{horizon}y")
    completed = subprocess.run(command, capture_output=True, text=True, timeout=3600)
    context.check_cancelled()

    if completed.returncode != 0:
        raise RuntimeError(
            f"panel build exited {completed.returncode}: {completed.stderr[-2000:]}"
        )

    context.progress(1.0, "panel written")
    return {
        "scoring_period": period,
        "horizon": horizon,
        "stdout_tail": completed.stdout[-2000:],
    }
