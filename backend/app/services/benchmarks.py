"""Metric definitions and industry reference bands for the SWOT engine.

Two things live here.

**Metric rules** — the closed set of financial line items the engine knows how
to compare, each with its direction (is more of this good?) and its unit. A
company that does not supply a metric is not penalised for it; the metric is
skipped and the omission is recorded.

**Industry reference bands** — the fallback benchmark used when the supplied
peer set is too small to produce a meaningful median.

⚠️ THE SHIPPED REFERENCE BANDS ARE ILLUSTRATIVE ROUND NUMBERS, NOT SOURCED
INDUSTRY DATA. They are plausible orders of magnitude chosen so the engine has
something to compare against out of the box. They are deliberately not
attributed to any data provider, because inventing an attribution would be
worse than admitting the numbers are placeholders.

For real analysis, do one of two things — both supported, neither requiring a
code change:

1. Supply ``financial_data`` on at least ``swot_min_peers_for_benchmark``
   competitors. The engine then benchmarks against the **peer-set median**, and
   the reference table is never consulted. This is the intended path and the
   result records ``benchmark_basis = "PEER_SET"``.
2. Point ``INDUSTRY_BENCHMARKS_PATH`` at a JSON file of your own figures, keyed
   by industry, sourced from filings or a data provider you actually have.

Every scored factor carries the benchmark value and its basis in its evidence
string, so a reader can always see which of the three paths produced a number.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricRule:
    """One comparable financial line item."""

    key: str
    label: str
    unit: str
    higher_is_better: bool
    note: str = ""


# The order here is the order factors appear in the SWOT output.
METRIC_RULES: tuple[MetricRule, ...] = (
    MetricRule("revenue_growth_pct", "Revenue growth", "%", True),
    MetricRule("gross_margin_pct", "Gross margin", "%", True),
    MetricRule("operating_margin_pct", "Operating margin", "%", True),
    MetricRule("net_margin_pct", "Net margin", "%", True),
    MetricRule("return_on_capital_pct", "Return on capital employed", "%", True),
    MetricRule("market_share_pct", "Market share", "%", True),
    MetricRule("customer_retention_pct", "Customer retention", "%", True),
    MetricRule(
        "rnd_intensity_pct",
        "R&D intensity",
        "% of revenue",
        True,
        note=(
            "Treated as higher-is-better, which is a defensible default in "
            "technology and pharma and a contestable one in commodity or "
            "distribution businesses, where high R&D spend is cost without a "
            "moat. Flip the direction in METRIC_RULES for those industries."
        ),
    ),
    MetricRule(
        "debt_to_equity",
        "Debt-to-equity",
        "x",
        False,
        note="Lower is better as a solvency signal; it is not a growth signal.",
    ),
)

METRIC_BY_KEY: dict[str, MetricRule] = {rule.key: rule for rule in METRIC_RULES}


# ⚠️ Illustrative placeholders. See the module docstring.
_DEFAULT_INDUSTRY_BENCHMARKS: dict[str, dict[str, float]] = {
    "_default": {
        "revenue_growth_pct": 8.0,
        "gross_margin_pct": 40.0,
        "operating_margin_pct": 12.0,
        "net_margin_pct": 8.0,
        "return_on_capital_pct": 12.0,
        "market_share_pct": 10.0,
        "customer_retention_pct": 80.0,
        "rnd_intensity_pct": 4.0,
        "debt_to_equity": 1.0,
    },
    "saas": {
        "revenue_growth_pct": 25.0,
        "gross_margin_pct": 75.0,
        "operating_margin_pct": 5.0,
        "net_margin_pct": 2.0,
        "return_on_capital_pct": 8.0,
        "market_share_pct": 8.0,
        "customer_retention_pct": 90.0,
        "rnd_intensity_pct": 20.0,
        "debt_to_equity": 0.4,
    },
    "retail": {
        "revenue_growth_pct": 6.0,
        "gross_margin_pct": 28.0,
        "operating_margin_pct": 6.0,
        "net_margin_pct": 3.0,
        "return_on_capital_pct": 11.0,
        "market_share_pct": 10.0,
        "customer_retention_pct": 60.0,
        "rnd_intensity_pct": 1.0,
        "debt_to_equity": 1.2,
    },
    "manufacturing": {
        "revenue_growth_pct": 5.0,
        "gross_margin_pct": 30.0,
        "operating_margin_pct": 10.0,
        "net_margin_pct": 6.0,
        "return_on_capital_pct": 12.0,
        "market_share_pct": 10.0,
        "customer_retention_pct": 75.0,
        "rnd_intensity_pct": 3.0,
        "debt_to_equity": 1.1,
    },
}

BENCHMARK_PROVENANCE = (
    "ILLUSTRATIVE PLACEHOLDER BANDS - not sourced industry data. Supply "
    "competitor financial_data to benchmark against the peer-set median, or "
    "set INDUSTRY_BENCHMARKS_PATH to your own sourced table."
)


def load_industry_benchmarks(path: str | None = None) -> tuple[dict[str, dict[str, float]], str]:
    """Return ``(table, provenance)``.

    A malformed or missing override file falls back to the built-in table with
    a warning rather than raising: a benchmark table is an input to the
    analysis, not a hard dependency of the service starting.
    """
    if not path:
        return _DEFAULT_INDUSTRY_BENCHMARKS, BENCHMARK_PROVENANCE

    file_path = Path(path)
    if not file_path.is_file():
        logger.warning("INDUSTRY_BENCHMARKS_PATH=%s does not exist; using built-in table", path)
        return _DEFAULT_INDUSTRY_BENCHMARKS, BENCHMARK_PROVENANCE

    try:
        payload: dict[str, Any] = json.loads(file_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read %s (%s); using built-in table", path, exc)
        return _DEFAULT_INDUSTRY_BENCHMARKS, BENCHMARK_PROVENANCE

    provenance = str(payload.pop("_provenance", f"user-supplied table: {file_path.name}"))
    table = {
        str(industry): {str(k): float(v) for k, v in metrics.items()}
        for industry, metrics in payload.items()
        if isinstance(metrics, dict)
    }
    if "_default" not in table:
        table["_default"] = _DEFAULT_INDUSTRY_BENCHMARKS["_default"]
    return table, provenance


def industry_benchmark(
    table: dict[str, dict[str, float]], industry: str | None, metric_key: str
) -> float | None:
    """Industry-specific band, falling back to the generic row."""
    key = (industry or "").strip().lower()
    for candidate in (key, "_default"):
        row = table.get(candidate)
        if row and metric_key in row:
            return float(row[metric_key])
    return None


def peer_median(peer_financials: list[dict], metric_key: str, minimum: int) -> float | None:
    """Median of the peers that actually reported ``metric_key``.

    Median rather than mean: peer sets are small and one outlier competitor
    should not drag the comparison point. Returns ``None`` when fewer than
    ``minimum`` peers reported the metric, which is the signal to fall back to
    the industry table.
    """
    values = [
        float(financials[metric_key])
        for financials in peer_financials
        if isinstance(financials, dict)
        and isinstance(financials.get(metric_key), (int, float))
        and not isinstance(financials.get(metric_key), bool)
    ]
    if len(values) < minimum:
        return None
    return float(median(values))
