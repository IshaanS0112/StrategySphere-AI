"""The XBRL frames API, reduced to ``{cik: fact}``.

    https://data.sec.gov/api/xbrl/frames/us-gaap/{Concept}/{Unit}/CY{YYYY}.json

One request returns one fact for every entity that reported that concept for
that period — which is what makes a sector median affordable. The alternative,
``companyfacts`` per company, is one request each and would take hours at a
compliant rate.

Two frame-specific hazards are handled here rather than left to the caller.

**Duplicate CIKs.** A frame can carry more than one row for the same entity
(restatements, amended filings). The last row wins, deterministically, and the
collision is counted rather than silently resolved.

**Unit and period must match across a ratio's legs.** The frames endpoint is
already scoped to one unit and one period, so requesting both legs of a ratio
from the same ``(unit, period)`` is what guarantees a FY2023 numerator is never
divided by a FY2022 denominator. That guarantee is a property of *how* the data
is fetched, which is why the fetch layer owns it and ``benchmark_builder``
never accepts two frames from different periods for one ratio.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.services.edgar.client import EdgarClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrameFact:
    cik: int
    entity_name: str
    value: float
    end: str
    accn: str = ""
    form: str = ""
    fy: int | None = None
    fp: str = ""


@dataclass
class FrameResult:
    """One concept, one unit, one period, indexed by CIK."""

    concept: str
    unit: str
    period: str
    facts: dict[int, FrameFact]
    rows_returned: int = 0
    duplicate_ciks: int = 0
    rows_rejected: int = 0
    available: bool = True
    error: str = ""

    def values(self) -> dict[int, float]:
        return {cik: fact.value for cik, fact in self.facts.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "unit": self.unit,
            "period": self.period,
            "available": self.available,
            "companies": len(self.facts),
            "rows_returned": self.rows_returned,
            "duplicate_ciks": self.duplicate_ciks,
            "rows_rejected": self.rows_rejected,
            "error": self.error,
        }


def parse_frame(payload: dict[str, Any], *, concept: str, unit: str, period: str) -> FrameResult:
    """Turn a frames response into ``{cik: FrameFact}``.

    Rows missing a CIK or a numeric value are rejected and counted. A frames
    payload is data from an external service, so nothing in it is trusted to be
    the shape the documentation promises.
    """
    data = payload.get("data")
    if not isinstance(data, list):
        return FrameResult(
            concept=concept,
            unit=unit,
            period=period,
            facts={},
            available=False,
            error="response carried no 'data' array",
        )

    facts: dict[int, FrameFact] = {}
    duplicates = 0
    rejected = 0
    for row in data:
        if not isinstance(row, dict):
            rejected += 1
            continue
        raw_cik = row.get("cik")
        raw_value = row.get("val")
        if not isinstance(raw_cik, int) or isinstance(raw_cik, bool):
            rejected += 1
            continue
        if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
            rejected += 1
            continue
        if raw_cik in facts:
            duplicates += 1
        facts[raw_cik] = FrameFact(
            cik=raw_cik,
            entity_name=str(row.get("entityName", "")).strip(),
            value=float(raw_value),
            end=str(row.get("end", "")),
            accn=str(row.get("accn", "")),
            form=str(row.get("form", "")),
            fy=row.get("fy") if isinstance(row.get("fy"), int) else None,
            fp=str(row.get("fp", "")),
        )

    return FrameResult(
        concept=concept,
        unit=unit,
        period=period,
        facts=facts,
        rows_returned=len(data),
        duplicate_ciks=duplicates,
        rows_rejected=rejected,
    )


def fetch_frame(
    client: EdgarClient, concept: str, *, unit: str = "USD", period: str = "CY2024"
) -> FrameResult:
    """Fetch and parse one frame.

    A concept that 404s is a *fact about the data*, not a crash: plenty of
    us-gaap tags have no frame for a given period. It comes back
    ``available=False`` with the reason, and the candidate resolver moves to
    the next tag in the list.
    """
    from app.services.edgar.client import EdgarFetchError, EdgarOfflineError

    try:
        payload = client.frames(concept, unit=unit, period=period)
    except (EdgarFetchError, EdgarOfflineError) as exc:
        logger.info("frame %s/%s/%s unavailable: %s", concept, unit, period, exc)
        return FrameResult(
            concept=concept,
            unit=unit,
            period=period,
            facts={},
            available=False,
            error=str(exc),
        )
    return parse_frame(payload, concept=concept, unit=unit, period=period)


@dataclass
class ResolvedConcept:
    """A candidate list collapsed into one value per company.

    ``tag_by_cik`` is the part that matters for provenance: it records which of
    the candidate tags each company was actually read through, which is what
    lets the built table say "4,102 companies, 3,410 of them through GrossProfit".
    """

    values: dict[int, float]
    tag_by_cik: dict[int, str]
    names: dict[int, str]
    frames: list[FrameResult]

    def tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for tag in self.tag_by_cik.values():
            counts[tag] = counts.get(tag, 0) + 1
        return counts


def resolve_candidates(
    client: EdgarClient,
    candidates: tuple[str, ...],
    *,
    unit: str = "USD",
    period: str = "CY2024",
) -> ResolvedConcept:
    """Try each candidate tag in order; first one to carry a company wins.

    One frame request per candidate tag, not per company. A company already
    resolved by an earlier tag is never overwritten by a later one, which is
    what makes the candidate list a preference ranking rather than a merge.
    """
    values: dict[int, float] = {}
    tag_by_cik: dict[int, str] = {}
    names: dict[int, str] = {}
    frames: list[FrameResult] = []

    for tag in candidates:
        frame = fetch_frame(client, tag, unit=unit, period=period)
        frames.append(frame)
        for cik, fact in frame.facts.items():
            if cik in values:
                continue
            values[cik] = fact.value
            tag_by_cik[cik] = tag
            if fact.entity_name:
                names[cik] = fact.entity_name

    return ResolvedConcept(values=values, tag_by_cik=tag_by_cik, names=names, frames=frames)
