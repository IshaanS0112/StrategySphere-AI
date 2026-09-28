"""SWOT scoring engine.

A SWOT that an LLM brainstorms is a paragraph of vibes. This one is arithmetic.

**Strengths and weaknesses** come from comparing the company's reported
financial metrics against a benchmark — the median of the supplied peer set
where there are enough peers, otherwise a configured industry band. The signed
relative deviation from that benchmark is bucketed into an impact score of 1-5.
A metric within the neutral band of its benchmark produces no factor at all,
which is the point: if every metric always yields a factor, the grid fills with
noise and the strength average becomes meaningless.

**Opportunities and threats** come from market-level inputs — growth, size, and
the competitive intensity derived from the competitor set's HHI — bucketed
through the same band logic.

**Analyst-supplied qualitative factors** (brand, distribution, talent) pass
through untouched but are tagged ``source = "analyst_input"``, so a reader can
always separate a computed comparison from a human judgement. They are not
laundered into looking like measurements.

Every factor carries the benchmark it was scored against inside its evidence
string. Nothing here calls a language model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import Settings
from app.enums import BenchmarkBasis, SwotCategory
from app.services import benchmarks as bench
from app.services import cache
from app.services.market_structure import ConcentrationResult

# Band edges for market-level inputs, ascending. A value below the first edge
# scores 1; at or above the last edge scores 5.
MARKET_GROWTH_BANDS = (3.0, 6.0, 10.0, 15.0)          # annual %, higher better
MARKET_SIZE_BANDS = (1.0, 5.0, 20.0, 75.0)            # USD bn, higher better

_REGULATORY_OUTLOOK = {
    "FAVOURABLE": (SwotCategory.OPPORTUNITY, "Regulatory outlook assessed as favourable"),
    "FAVORABLE": (SwotCategory.OPPORTUNITY, "Regulatory outlook assessed as favourable"),
    "ADVERSE": (SwotCategory.THREAT, "Regulatory outlook assessed as adverse"),
    "NEUTRAL": (None, "Regulatory outlook assessed as neutral"),
}


@dataclass(frozen=True)
class SwotFactor:
    factor: str
    category: SwotCategory
    evidence: str
    impact_score: int
    source: str                       # computed_financial | computed_market | analyst_input
    metric: str | None = None
    benchmark_basis: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["category"] = self.category.value
        return payload


@dataclass
class SwotResult:
    strengths: list[SwotFactor] = field(default_factory=list)
    weaknesses: list[SwotFactor] = field(default_factory=list)
    opportunities: list[SwotFactor] = field(default_factory=list)
    threats: list[SwotFactor] = field(default_factory=list)
    calculation_basis: dict[str, Any] = field(default_factory=dict)

    @property
    def all_factors(self) -> list[SwotFactor]:
        return self.strengths + self.weaknesses + self.opportunities + self.threats

    def bucket(self, category: SwotCategory) -> list[SwotFactor]:
        return {
            SwotCategory.STRENGTH: self.strengths,
            SwotCategory.WEAKNESS: self.weaknesses,
            SwotCategory.OPPORTUNITY: self.opportunities,
            SwotCategory.THREAT: self.threats,
        }[category]


# --------------------------------------------------------------------------
# Scoring primitives
# --------------------------------------------------------------------------

def favourable_deviation_pct(value: float, benchmark: float, higher_is_better: bool) -> float | None:
    """Signed deviation from benchmark, in percent, positive = good for the firm.

    Returns ``None`` when the benchmark is zero — a relative comparison against
    zero is undefined, and returning a huge number instead would manufacture a
    5-impact factor out of a missing benchmark.
    """
    if benchmark == 0:
        return None
    deviation = (value - benchmark) / abs(benchmark) * 100.0
    return deviation if higher_is_better else -deviation


def impact_from_deviation(abs_deviation_pct: float, settings: Settings) -> int:
    """Bucket an absolute relative deviation into a 1-5 impact score."""
    if abs_deviation_pct >= settings.swot_score_5_pct:
        return 5
    if abs_deviation_pct >= settings.swot_score_4_pct:
        return 4
    if abs_deviation_pct >= settings.swot_score_3_pct:
        return 3
    if abs_deviation_pct >= settings.swot_score_2_pct:
        return 2
    return 1


def band_score(value: float, bands: tuple[float, ...]) -> int:
    """Map a raw value onto 1-5 using ascending band edges."""
    score = 1
    for edge in bands:
        if value >= edge:
            score += 1
        else:
            break
    return min(score, 5)


def _coerce_number(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


# --------------------------------------------------------------------------
# Strengths / weaknesses from financial metrics
# --------------------------------------------------------------------------

def _score_financial_metrics(
    *,
    financial_data: dict,
    peer_financials: list[dict],
    industry: str | None,
    benchmark_table: bench.BenchmarkTable,
    settings: Settings,
) -> tuple[list[SwotFactor], list[dict[str, Any]]]:
    factors: list[SwotFactor] = []
    trace: list[dict[str, Any]] = []

    for rule in bench.METRIC_RULES:
        value = _coerce_number(financial_data.get(rule.key))
        if value is None:
            trace.append({"metric": rule.key, "status": "skipped", "reason": "not reported"})
            continue

        # V3: the table lookup returns a point carrying its own basis and the
        # sample size behind it, so an EDGAR sector median can say n=148 in the
        # evidence string while a placeholder band still says "industry
        # benchmark". The peer-set path is untouched.
        benchmark = bench.peer_median(
            peer_financials, rule.key, settings.swot_min_peers_for_benchmark
        )
        basis = BenchmarkBasis.PEER_SET.value
        basis_label = "peer-set median"
        benchmark_n: int | None = None
        if benchmark is None:
            point = benchmark_table.lookup(industry, rule.key)
            if point is not None:
                benchmark, basis, basis_label = point.value, point.basis, point.label()
                benchmark_n = point.n
        if benchmark is None:
            trace.append(
                {"metric": rule.key, "status": "skipped", "reason": "no benchmark available"}
            )
            continue

        deviation = favourable_deviation_pct(value, benchmark, rule.higher_is_better)
        if deviation is None:
            trace.append({"metric": rule.key, "status": "skipped", "reason": "zero benchmark"})
            continue

        entry = {
            "metric": rule.key,
            "value": value,
            "benchmark": benchmark,
            "benchmark_basis": basis,
            "benchmark_n": benchmark_n,
            "favourable_deviation_pct": round(deviation, 3),
            "higher_is_better": rule.higher_is_better,
        }

        if abs(deviation) < settings.swot_neutral_band_pct:
            entry["status"] = "neutral"
            entry["reason"] = (
                f"within +/-{settings.swot_neutral_band_pct}% of benchmark; not a factor"
            )
            trace.append(entry)
            continue

        impact = impact_from_deviation(abs(deviation), settings)
        category = SwotCategory.STRENGTH if deviation > 0 else SwotCategory.WEAKNESS
        direction = "above" if deviation > 0 else "below"

        evidence = (
            f"{rule.label} {value:g}{rule.unit} vs {basis_label} {benchmark:g}{rule.unit} "
            f"({deviation:+.1f}% favourable deviation, {abs(deviation):.1f}% {direction} on the "
            f"{'higher-is-better' if rule.higher_is_better else 'lower-is-better'} axis)"
        )

        entry["status"] = category.value
        entry["impact_score"] = impact
        trace.append(entry)

        factors.append(
            SwotFactor(
                factor=rule.label,
                category=category,
                evidence=evidence,
                impact_score=impact,
                source="computed_financial",
                metric=rule.key,
                benchmark_basis=basis,
            )
        )

    return factors, trace


# --------------------------------------------------------------------------
# Opportunities / threats from market inputs
# --------------------------------------------------------------------------

def _score_market_inputs(
    *,
    market_data: dict,
    concentration: ConcentrationResult,
) -> tuple[list[SwotFactor], dict[str, Any]]:
    factors: list[SwotFactor] = []
    trace: dict[str, Any] = {}

    growth = _coerce_number(market_data.get("market_growth_pct"))
    if growth is not None:
        score = band_score(growth, MARKET_GROWTH_BANDS)
        trace["market_growth"] = {"value": growth, "score": score, "bands": MARKET_GROWTH_BANDS}
        if score >= 4:
            factors.append(
                SwotFactor(
                    factor="Expanding market",
                    category=SwotCategory.OPPORTUNITY,
                    evidence=(
                        f"Market growing at {growth:g}% annually, scoring {score}/5 on the "
                        f"growth band scale {list(MARKET_GROWTH_BANDS)}"
                    ),
                    impact_score=score,
                    source="computed_market",
                    metric="market_growth_pct",
                )
            )
        elif score <= 2:
            factors.append(
                SwotFactor(
                    factor="Stagnant market growth",
                    category=SwotCategory.THREAT,
                    evidence=(
                        f"Market growing at only {growth:g}% annually, scoring {score}/5 on the "
                        f"growth band scale {list(MARKET_GROWTH_BANDS)}"
                    ),
                    # A low growth score is a HIGH-impact threat, so the scale
                    # is inverted here rather than passed through.
                    impact_score=6 - score,
                    source="computed_market",
                    metric="market_growth_pct",
                )
            )

    size = _coerce_number(market_data.get("market_size_usd_bn"))
    if size is not None:
        score = band_score(size, MARKET_SIZE_BANDS)
        trace["market_size"] = {"value": size, "score": score, "bands": MARKET_SIZE_BANDS}
        if score >= 4:
            factors.append(
                SwotFactor(
                    factor="Large addressable market",
                    category=SwotCategory.OPPORTUNITY,
                    evidence=(
                        f"Addressable market of ${size:g}bn, scoring {score}/5 on the size band "
                        f"scale {list(MARKET_SIZE_BANDS)} (USD bn)"
                    ),
                    impact_score=score,
                    source="computed_market",
                    metric="market_size_usd_bn",
                )
            )

    intensity = concentration.competitive_intensity_score
    trace["competitive_intensity"] = {
        "score": intensity,
        "hhi": concentration.hhi,
        "band": concentration.concentration.value if concentration.concentration else None,
        "source": concentration.basis.get("intensity_source"),
    }
    if intensity >= 4.0 and concentration.hhi is not None:
        factors.append(
            SwotFactor(
                factor="Intense competitive rivalry",
                category=SwotCategory.THREAT,
                evidence=(
                    f"HHI of {concentration.hhi:g} places this market in the "
                    f"{concentration.concentration.value} band (DOJ/FTC 2023 Merger Guidelines); "
                    f"derived competitive intensity {intensity:g}/5"
                ),
                impact_score=int(round(intensity)),
                source="computed_market",
                metric="competitive_intensity_score",
            )
        )
    elif intensity <= 2.0 and concentration.hhi is not None:
        factors.append(
            SwotFactor(
                factor="Concentrated market with limited rivalry",
                category=SwotCategory.OPPORTUNITY,
                evidence=(
                    f"HHI of {concentration.hhi:g} places this market in the "
                    f"{concentration.concentration.value} band (DOJ/FTC 2023 Merger Guidelines); "
                    f"derived competitive intensity {intensity:g}/5"
                ),
                impact_score=int(round(6 - intensity)),
                source="computed_market",
                metric="competitive_intensity_score",
            )
        )

    outlook_raw = market_data.get("regulatory_outlook")
    if isinstance(outlook_raw, str):
        key = outlook_raw.strip().upper()
        mapped = _REGULATORY_OUTLOOK.get(key)
        trace["regulatory_outlook"] = {"value": key, "recognised": mapped is not None}
        if mapped and mapped[0] is not None:
            category, label = mapped
            impact = _coerce_number(market_data.get("regulatory_impact_score")) or 3.0
            impact_int = max(1, min(5, int(round(impact))))
            factors.append(
                SwotFactor(
                    factor=label,
                    category=category,
                    evidence=(
                        f"Analyst-supplied regulatory outlook '{key}' with impact "
                        f"{impact_int}/5. This is a judgement, not a measurement."
                    ),
                    impact_score=impact_int,
                    source="analyst_input",
                    metric="regulatory_outlook",
                )
            )

    return factors, trace


# --------------------------------------------------------------------------
# Analyst qualitative pass-through
# --------------------------------------------------------------------------

def _normalise_qualitative(raw_inputs: list) -> tuple[list[SwotFactor], list[dict[str, Any]]]:
    factors: list[SwotFactor] = []
    rejected: list[dict[str, Any]] = []

    for item in raw_inputs or []:
        if not isinstance(item, dict):
            rejected.append({"input": item, "reason": "not an object"})
            continue
        try:
            category = SwotCategory(str(item["category"]).strip().upper())
        except (KeyError, ValueError):
            rejected.append({"input": item, "reason": "missing or unrecognised category"})
            continue

        factor_name = str(item.get("factor", "")).strip()
        if not factor_name:
            rejected.append({"input": item, "reason": "missing factor name"})
            continue

        score = _coerce_number(item.get("impact_score"))
        if score is None:
            rejected.append({"input": item, "reason": "missing or non-numeric impact_score"})
            continue

        factors.append(
            SwotFactor(
                factor=factor_name,
                category=category,
                evidence=str(item.get("evidence", "")).strip()
                or "Analyst assertion with no evidence supplied.",
                impact_score=max(1, min(5, int(round(score)))),
                source="analyst_input",
            )
        )

    return factors, rejected


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def run_swot_analysis(
    *,
    financial_data: dict,
    market_data: dict,
    qualitative_inputs: list,
    competitors: list[dict],
    industry: str | None,
    concentration: ConcentrationResult,
    settings: Settings,
) -> SwotResult:
    """Score a full SWOT grid. Deterministic: same inputs, same output, no LLM."""
    # Cached on (path, mtime, size): the table is parsed once per version of
    # the file rather than once per scoring run, and a rebuilt table is picked
    # up on the next call with no restart.
    benchmark_table = cache.benchmark_table(settings.industry_benchmarks_path)
    peer_financials = [
        c.get("financial_data") or {} for c in competitors if isinstance(c, dict)
    ]

    financial_factors, financial_trace = _score_financial_metrics(
        financial_data=financial_data,
        peer_financials=peer_financials,
        industry=industry,
        benchmark_table=benchmark_table,
        settings=settings,
    )
    market_factors, market_trace = _score_market_inputs(
        market_data=market_data, concentration=concentration
    )
    qualitative_factors, rejected = _normalise_qualitative(qualitative_inputs)

    result = SwotResult()
    for factor in financial_factors + market_factors + qualitative_factors:
        result.bucket(factor.category).append(factor)

    # Highest impact first inside each quadrant: an executive reading the grid
    # top-down should hit the material factors before the marginal ones.
    for category in SwotCategory:
        result.bucket(category).sort(key=lambda f: (-f.impact_score, f.factor))

    peers_with_financials = sum(1 for f in peer_financials if f)

    result.calculation_basis = {
        "benchmark_provenance": benchmark_table.provenance,
        "peer_count": len(competitors),
        "peers_reporting_financials": peers_with_financials,
        "min_peers_for_peer_benchmark": settings.swot_min_peers_for_benchmark,
        "scoring_thresholds_pct": {
            "neutral_band": settings.swot_neutral_band_pct,
            "impact_2": settings.swot_score_2_pct,
            "impact_3": settings.swot_score_3_pct,
            "impact_4": settings.swot_score_4_pct,
            "impact_5": settings.swot_score_5_pct,
        },
        "financial_metric_trace": financial_trace,
        "market_input_trace": market_trace,
        "market_structure": concentration.basis,
        "qualitative_inputs_accepted": len(qualitative_factors),
        "qualitative_inputs_rejected": rejected,
        "factor_counts": {
            "strengths": len(result.strengths),
            "weaknesses": len(result.weaknesses),
            "opportunities": len(result.opportunities),
            "threats": len(result.threats),
        },
    }
    return result
