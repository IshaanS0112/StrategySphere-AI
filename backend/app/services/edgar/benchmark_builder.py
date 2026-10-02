"""Frames + SIC -> sector medians + the provenance block that makes them readable."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import Any, Callable

from app.enums import BenchmarkBasis, MetricDerivation
from app.services.edgar import concepts as concept_mod
from app.services.edgar import sic as sic_mod
from app.services.edgar.client import EdgarClient
from app.services.edgar.frames import ResolvedConcept, resolve_candidates

logger = logging.getLogger(__name__)

SOURCE_STATEMENT = "SEC EDGAR XBRL frames API, data.sec.gov"


class BenchmarkBuildError(RuntimeError):
    """The build cannot produce a table worth publishing."""


@dataclass
class MetricCoverage:
    """Resolution outcome for one metric across the whole filer universe."""

    key: str
    resolved: int = 0
    dropped: int = 0
    drop_reasons: dict[str, int] = field(default_factory=dict)
    tag_resolution: dict[str, int] = field(default_factory=dict)

    def drop(self, reason: str) -> None:
        self.dropped += 1
        self.drop_reasons[reason] = self.drop_reasons.get(reason, 0) + 1

    @property
    def considered(self) -> int:
        return self.resolved + self.dropped

    @property
    def coverage_pct(self) -> float:
        return round(100.0 * self.resolved / self.considered, 2) if self.considered else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolved": self.resolved,
            "dropped": self.dropped,
            "coverage_pct": self.coverage_pct,
            "drop_reasons": dict(sorted(self.drop_reasons.items(), key=lambda kv: -kv[1])),
        }


@dataclass
class BuildResult:
    table: dict[str, Any]
    provenance: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        """The file as written: sectors plus the provenance block."""
        return {"_provenance": self.provenance, **self.table}


class ConceptCache:
    """One frames request per candidate tag per period, never two."""

    def __init__(self, client: EdgarClient) -> None:
        self._client = client
        self._store: dict[tuple[tuple[str, ...], str, str], ResolvedConcept] = {}

    def get(self, candidates: tuple[str, ...], *, unit: str, period: str) -> ResolvedConcept:
        key = (candidates, unit, period)
        if key not in self._store:
            self._store[key] = resolve_candidates(
                self._client, candidates, unit=unit, period=period
            )
        return self._store[key]

    @property
    def frames_fetched(self) -> int:
        return sum(len(resolved.frames) for resolved in self._store.values())


def instant_period(period: str) -> str:
    """Duration period -> the instantaneous key for the same period end."""
    body = period.removeprefix("CY")
    if len(body) == 4 and body.isdigit():
        return f"CY{body}Q4I"
    if period.endswith("I"):
        return period
    raise ValueError(
        f"cannot derive an instantaneous period key from {period!r}; expected CYyyyy"
    )


def company_values_for_metric(
    spec: concept_mod.MetricSpec,
    cache: ConceptCache,
    *,
    period: str,
    prior_period: str,
) -> tuple[dict[int, float], MetricCoverage, dict[int, str]]:
    """Per-company value for one metric, with coverage and the resolved tag."""
    coverage = MetricCoverage(key=spec.key)
    values: dict[int, float] = {}
    tags: dict[int, str] = {}

    if spec.derivation is MetricDerivation.GROWTH:
        current = cache.get(spec.numerator, unit="USD", period=period)
        prior = cache.get(spec.numerator, unit="USD", period=prior_period)
        universe = set(current.values) | set(prior.values)
        for cik in universe:
            now = current.values.get(cik)
            before = prior.values.get(cik)
            if now is None:
                coverage.drop(f"no revenue tag resolved for {period}")
                continue
            if before is None:
                coverage.drop(f"no revenue tag resolved for {prior_period}")
                continue
            if current.tag_by_cik.get(cik) != prior.tag_by_cik.get(cik):
                # Post-606 tag in one year and the legacy tag in the other are two
                # different definitions of revenue.
                coverage.drop("revenue tag differs between the two periods")
                continue
            if before <= 0:
                coverage.drop("non-positive prior-period revenue")
                continue
            growth = (now / before - 1.0) * 100.0
            low, high = spec.plausible_range
            if not low <= growth <= high:
                coverage.drop("outside plausible range")
                continue
            values[cik] = growth
            tags[cik] = current.tag_by_cik[cik]
            coverage.resolved += 1
            tag = current.tag_by_cik[cik]
            coverage.tag_resolution[tag] = coverage.tag_resolution.get(tag, 0) + 1
        return values, coverage, tags

    # RATIO
    instant = instant_period(period)
    numerator = cache.get(
        spec.numerator, unit="USD", period=instant if spec.numerator_instant else period
    )
    denominator = cache.get(
        spec.denominator, unit="USD", period=instant if spec.denominator_instant else period
    )
    universe = set(numerator.values) | set(denominator.values)
    for cik in universe:
        top = numerator.values.get(cik)
        bottom = denominator.values.get(cik)
        if top is None:
            coverage.drop(f"no {spec.numerator[0]} candidate resolved")
            continue
        if bottom is None:
            coverage.drop(f"no {spec.denominator[0]} candidate resolved")
            continue
        if bottom <= 0:
            # Negative book equity or negative revenue produces a ratio whose
            # sign reads as the opposite of what it means.
            coverage.drop("non-positive denominator")
            continue
        value = (top / bottom) * spec.scale
        low, high = spec.plausible_range
        if not low <= value <= high:
            coverage.drop("outside plausible range")
            continue
        values[cik] = value
        tag = f"{numerator.tag_by_cik[cik]}/{denominator.tag_by_cik[cik]}"
        tags[cik] = tag
        coverage.resolved += 1
        coverage.tag_resolution[tag] = coverage.tag_resolution.get(tag, 0) + 1

    return values, coverage, tags


def _classify_sample(
    client: EdgarClient,
    ciks: list[int],
    *,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[int, str], dict[str, Any]]:
    """One submissions request per company, to get a SIC code and a sector."""
    sectors: dict[int, str] = {}
    failures = 0
    unclassified = 0

    # One request per company, so this is the longest phase of a build by an order
    # of magnitude.
    done = {"n": 0}

    def report(_url: str, _payload: object, error: Exception | None) -> None:
        done["n"] += 1
        if progress and done["n"] % 50 == 0:
            progress(f"  classified {done['n']}/{len(ciks)} companies")

    payloads = client.submissions_many(ciks, on_result=report)
    failures = len(ciks) - len(payloads)

    for cik in ciks:
        payload = payloads.get(cik)
        if payload is None:
            continue
        raw_sic, _ = sic_mod.sic_from_submissions(payload)
        sector = sic_mod.sector_for_sic(raw_sic)
        if sector == sic_mod.UNCLASSIFIED:
            unclassified += 1
        sectors[cik] = sector

    lookups = len(payloads)
    return sectors, {
        "companies_requested": len(ciks),
        "lookups_succeeded": lookups,
        "lookups_failed": failures,
        "unclassified": unclassified,
    }


def build_benchmark_table(
    client: EdgarClient,
    *,
    period: str = "CY2024",
    prior_period: str | None = None,
    min_sector_n: int = 20,
    sic_lookup_limit: int = 600,
    specs: tuple[concept_mod.MetricSpec, ...] = concept_mod.METRIC_SPECS,
    progress: Callable[[str], None] | None = None,
) -> BuildResult:
    """Build sector medians for ``period`` and the provenance to read them with."""
    if prior_period is None:
        prior_period = f"CY{int(period.removeprefix('CY')) - 1}"

    say = progress or (lambda _msg: None)
    cache = ConceptCache(client)

    metric_values: dict[str, dict[int, float]] = {}
    coverage_by_metric: dict[str, MetricCoverage] = {}
    tag_resolution: dict[str, dict[str, int]] = {}

    for spec in specs:
        say(f"resolving {spec.key} ...")
        values, coverage, _tags = company_values_for_metric(
            spec, cache, period=period, prior_period=prior_period
        )
        metric_values[spec.key] = values
        coverage_by_metric[spec.key] = coverage
        tag_resolution[spec.key] = dict(
            sorted(coverage.tag_resolution.items(), key=lambda kv: -kv[1])
        )
        say(f"  {spec.key}: {coverage.resolved} resolved, {coverage.dropped} dropped")

    universe = sorted({cik for values in metric_values.values() for cik in values})

    # A table with no companies behind it is not a benchmark table, and writing one
    # is worse than failing: it would be a well-formed file of nothing that the SWOT
    # engine then loads and scores against.
    if not universe:
        unavailable = [
            frame.error or "no data"
            for resolved in cache._store.values()          # noqa: SLF001
            for frame in resolved.frames
            if not frame.available
        ]
        raise BenchmarkBuildError(
            f"No company resolved any metric for {period}. Every frame request came "
            f"back empty or unavailable, so there is nothing to take a median of. "
            f"First reason: {unavailable[0] if unavailable else 'unknown'}"
        )

    # --- the SIC sample ----------------------------------------------------
    # Ranked by revenue descending so the sample is deterministic and its bias is a
    # stated one.
    revenue = cache.get(concept_mod.REVENUE_TAGS, unit="USD", period=period).values
    ranked = sorted(universe, key=lambda cik: (-revenue.get(cik, 0.0), cik))
    sample = ranked[: max(0, int(sic_lookup_limit))]
    say(f"classifying {len(sample)} of {len(universe)} companies by SIC ...")
    sector_by_cik, sic_stats = _classify_sample(client, sample, progress=progress)

    # --- medians -----------------------------------------------------------
    table: dict[str, Any] = {}

    default_row: dict[str, Any] = {}
    default_meta: dict[str, Any] = {}
    for spec in specs:
        values = list(metric_values[spec.key].values())
        if not values:
            continue
        default_row[spec.key] = round(float(median(values)), 4)
        default_meta[spec.key] = {
            "n": len(values),
            "basis": BenchmarkBasis.EDGAR_ALL_FILER_MEDIAN.value,
        }
    default_row["_n"] = len(universe)
    default_row["_basis"] = BenchmarkBasis.EDGAR_ALL_FILER_MEDIAN.value
    default_row["_meta"] = default_meta
    table["_default"] = default_row

    by_sector: dict[str, list[int]] = {}
    for cik, sector in sector_by_cik.items():
        if sector == sic_mod.UNCLASSIFIED:
            continue
        by_sector.setdefault(sector, []).append(cik)

    sectors_below_min_n: dict[str, dict[str, int]] = {}
    for sector, members in sorted(by_sector.items()):
        row: dict[str, Any] = {}
        meta: dict[str, Any] = {}
        best_metric_n = 0
        for spec in specs:
            values = [
                metric_values[spec.key][cik]
                for cik in members
                if cik in metric_values[spec.key]
            ]
            best_metric_n = max(best_metric_n, len(values))
            if len(values) < min_sector_n:
                continue
            row[spec.key] = round(float(median(values)), 4)
            meta[spec.key] = {
                "n": len(values),
                "basis": BenchmarkBasis.EDGAR_SECTOR_MEDIAN.value,
            }
        if not row:
            # Every metric in this sector fell short of min_sector_n.
            sectors_below_min_n[sector] = {
                "classified_members": len(members),
                "best_metric_n": best_metric_n,
            }
            continue
        row["_n"] = len(members)
        row["_basis"] = BenchmarkBasis.EDGAR_SECTOR_MEDIAN.value
        row["_meta"] = meta
        table[sector] = row

    built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    provenance = {
        "source": SOURCE_STATEMENT,
        "period": period,
        "prior_period_for_growth": prior_period,
        "built_at": built_at,
        "companies_considered": len(universe),
        "coverage_by_metric": {
            key: cov.to_dict() for key, cov in coverage_by_metric.items()
        },
        "tag_resolution": tag_resolution,
        "min_sector_n": min_sector_n,
        "sectors_published": sorted(k for k in table if k != "_default"),
        "sectors_below_min_n": sectors_below_min_n,
        "sic_sample": {
            "rule": (
                "the largest filers by reported revenue that resolved at least one "
                "metric, capped at sic_lookup_limit"
            ),
            "limit": sic_lookup_limit,
            "bias": (
                "Sector medians therefore describe LARGE filers in that sector, not "
                "all of them. The all-filer median in _default uses the entire "
                "resolved universe, because it needs no SIC lookup. This is the "
                "trade the published rate limit forces: SIC classification is one "
                "request per company."
            ),
            **sic_stats,
        },
        "metrics_not_derivable": concept_mod.NOT_DERIVABLE,
        "how_to_read_the_default_row": (
            "The _default row is the median across EVERY filer that resolved the "
            "metric, which is a very different population from a sector: it "
            "includes pre-revenue, shell and micro-cap registrants in numbers "
            "that a sector median of large filers does not. That is why the "
            "all-filer net margin sits near zero and the all-filer return on "
            "capital is negative - the median SEC registrant is roughly "
            "breakeven, which is true and surprising rather than a defect. A "
            "company benchmarked against _default will therefore look stronger "
            "than one benchmarked against its own sector. Supplying competitor "
            "financials, so the engine uses a peer-set median, remains the "
            "intended path and overrides this table entirely."
        ),
        "derivation_notes": {
            spec.key: spec.note for spec in specs if spec.note
        },
        "method": (
            "One frames request per candidate tag per period. Ratios take both legs "
            "from the same unit and period, so a numerator can never be divided by "
            "a denominator from a different year. Companies where no candidate tag "
            "resolves are dropped and counted, never imputed. Medians, not means: "
            "one filer with a unit error should not move a benchmark."
        ),
        "frames_requests": cache.frames_fetched,
        "fetch_stats": client.stats.to_dict(),
    }

    return BuildResult(table=table, provenance=provenance)
