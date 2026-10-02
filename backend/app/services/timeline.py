"""Multi-period tracking: quadrant migration across reporting periods."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.config import Settings
from app.enums import TrendDirection


@dataclass(frozen=True)
class PeriodPoint:
    company_id: str
    period_label: str | None
    period_end: date | None
    attractiveness: float
    strength: float
    quadrant: str
    borderline: bool
    data_source: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "period_label": self.period_label,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "attractiveness": self.attractiveness,
            "strength": self.strength,
            "quadrant": self.quadrant,
            "borderline": self.borderline,
            "data_source": self.data_source,
        }


@dataclass
class TimelineResult:
    entity_key: str
    points: list[PeriodPoint] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    attractiveness_trend: TrendDirection = TrendDirection.INSUFFICIENT_DATA
    strength_trend: TrendDirection = TrendDirection.INSUFFICIENT_DATA
    quadrant_changes: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def classify_trend(
    first: float, last: float, settings: Settings
) -> tuple[TrendDirection, float]:
    """Direction of travel between the first and last period, with the delta."""
    delta = round(last - first, 4)
    if abs(delta) < settings.trend_material_delta:
        return TrendDirection.STABLE, delta
    return (
        TrendDirection.IMPROVING if delta > 0 else TrendDirection.DETERIORATING
    ), delta


def build_timeline(
    *,
    entity_key: str,
    rows: list[dict[str, Any]],
    settings: Settings,
) -> TimelineResult:
    """Order the periods, classify the trend, and list every quadrant change."""
    usable: list[PeriodPoint] = []
    excluded: list[dict[str, Any]] = []

    for row in rows:
        if row.get("period_end") is None:
            excluded.append(
                {
                    "company_id": row.get("company_id"),
                    "period_label": row.get("period_label"),
                    "reason": (
                        "no period_end date, so it cannot be ordered against the "
                        "other periods; excluded from the trend rather than "
                        "appended in arbitrary position"
                    ),
                }
            )
            continue
        if row.get("attractiveness") is None or row.get("strength") is None:
            excluded.append(
                {
                    "company_id": row.get("company_id"),
                    "period_label": row.get("period_label"),
                    "reason": "no market attractiveness result has been computed for this period",
                }
            )
            continue
        usable.append(
            PeriodPoint(
                company_id=str(row["company_id"]),
                period_label=row.get("period_label"),
                period_end=row["period_end"],
                attractiveness=float(row["attractiveness"]),
                strength=float(row["strength"]),
                quadrant=str(row["quadrant"]),
                borderline=bool(row.get("borderline", False)),
                data_source=row.get("data_source"),
            )
        )

    usable.sort(key=lambda p: p.period_end)  # type: ignore[arg-type,return-value]

    result = TimelineResult(entity_key=entity_key, points=usable, excluded=excluded)

    if len(usable) < 2:
        result.summary = (
            f"Only {len(usable)} scored period available for '{entity_key}'. "
            "A trend needs at least two."
        )
        result.calculation_basis = {
            "ordering": "by period_end ascending",
            "periods_usable": len(usable),
            "periods_excluded": len(excluded),
            "material_delta_threshold": settings.trend_material_delta,
        }
        return result

    a_trend, a_delta = classify_trend(
        usable[0].attractiveness, usable[-1].attractiveness, settings
    )
    s_trend, s_delta = classify_trend(usable[0].strength, usable[-1].strength, settings)
    result.attractiveness_trend = a_trend
    result.strength_trend = s_trend

    for previous, current in zip(usable, usable[1:]):
        if previous.quadrant != current.quadrant:
            result.quadrant_changes.append(
                {
                    "from_period": previous.period_label,
                    "to_period": current.period_label,
                    "from_quadrant": previous.quadrant,
                    "to_quadrant": current.quadrant,
                    "attractiveness_delta": round(
                        current.attractiveness - previous.attractiveness, 4
                    ),
                    "strength_delta": round(current.strength - previous.strength, 4),
                    "either_side_borderline": previous.borderline or current.borderline,
                }
            )

    first, last = usable[0], usable[-1]
    move = (
        f"quadrant moved {first.quadrant} -> {last.quadrant}"
        if first.quadrant != last.quadrant
        else f"quadrant held at {last.quadrant}"
    )
    result.summary = (
        f"{len(usable)} periods from {first.period_label} to {last.period_label}: "
        f"attractiveness {a_trend.value.lower()} ({a_delta:+.2f}), "
        f"strength {s_trend.value.lower()} ({s_delta:+.2f}), {move}."
    )

    borderline_changes = [c for c in result.quadrant_changes if c["either_side_borderline"]]
    result.calculation_basis = {
        "ordering": "by period_end ascending; period_label is never used to sort",
        "periods_usable": len(usable),
        "periods_excluded": len(excluded),
        "material_delta_threshold": settings.trend_material_delta,
        "attractiveness_delta": a_delta,
        "strength_delta": s_delta,
        "trend_method": (
            "first-to-last difference, not a fitted slope. With the two-to-five "
            "periods a filing history realistically provides, a regression slope "
            "would carry a standard error wider than the effect it measures."
        ),
        "quadrant_change_count": len(result.quadrant_changes),
        "borderline_caveat": (
            f"{len(borderline_changes)} of {len(result.quadrant_changes)} quadrant "
            "changes involve a period that was flagged borderline. A move across a "
            "boundary that was already knife-edge is not evidence of a real shift."
            if borderline_changes
            else "No quadrant change involved a borderline period."
        ),
    }
    return result
