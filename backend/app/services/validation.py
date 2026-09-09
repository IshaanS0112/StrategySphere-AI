"""Validation harness: does the quadrant verdict predict anything?

V1's README carried an admission — the attractiveness score had never been
checked against real business outcomes, and the honest test would be a
retrospective panel. This module is that test. It does not manufacture the
answer; it makes the answer computable once someone supplies the data.

**The design.** Give it a panel of companies scored at time T plus a realised
outcome measured at T+n (revenue CAGR, TSR, margin change — anything ordinal).
It reports:

1. **Separation.** Mean and median outcome per quadrant. If the framework has
   any predictive content, `INVEST_GROW` should beat `HARVEST_DIVEST`.
2. **Rank correlation.** Spearman's rho between the composite position score
   and the outcome, which is robust to the outcome's distribution and does not
   assume linearity.
3. **A permutation null.** The separation statistic recomputed thousands of
   times against shuffled outcomes, giving an empirical p-value.

**Point 3 is the one that matters and the one usually missing.** With a panel of
twenty companies split across three quadrants, a gap between group means of
several percentage points arises constantly by chance. Reporting the gap without
the null is how a backtest "validates" a model that is indistinguishable from
noise. The permutation test asks the only useful question: how often would
shuffled outcomes produce a gap at least this large?

**No data ships with this.** A synthetic panel is included for testing the
harness itself and is labelled as such. Real validation needs filings, and
`data/validation/README.md` documents how to assemble a panel from EDGAR.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any

from app.config import Settings
from app.enums import Quadrant

QUADRANT_RANK = {
    Quadrant.HARVEST_DIVEST.value: 0,
    Quadrant.SELECTIVE_INVEST.value: 1,
    Quadrant.INVEST_GROW.value: 2,
}


class ValidationInputError(ValueError):
    """Raised when a panel cannot support a meaningful test."""


@dataclass
class PanelRow:
    label: str
    quadrant: str
    attractiveness: float
    strength: float
    outcome: float

    @property
    def position_score(self) -> float:
        """Composite position: the product of the two axes.

        Product rather than sum because GE-McKinsey's rule is conjunctive —
        being strong on one axis and weak on the other is not the same as being
        middling on both, and a sum cannot tell those apart.
        """
        return self.attractiveness * self.strength


@dataclass
class ValidationResult:
    n: int
    by_quadrant: dict[str, dict[str, Any]] = field(default_factory=dict)
    separation: float | None = None
    spearman_rho: float | None = None
    permutation_p_value: float | None = None
    permutations_run: int = 0
    verdict: str = ""
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def _rank(values: list[float]) -> list[float]:
    """Ranks with ties averaged, which is what Spearman requires."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of the ranks. ``None`` when either side is constant."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy) ** 0.5, 4)


def _separation(rows: list[PanelRow]) -> float | None:
    """Mean outcome of INVEST_GROW minus mean outcome of HARVEST_DIVEST."""
    grow = [r.outcome for r in rows if r.quadrant == Quadrant.INVEST_GROW.value]
    divest = [r.outcome for r in rows if r.quadrant == Quadrant.HARVEST_DIVEST.value]
    if not grow or not divest:
        return None
    return mean(grow) - mean(divest)


def run_validation(
    rows: list[PanelRow], settings: Settings
) -> ValidationResult:
    """Score a labelled panel. Deterministic given ``validation_random_seed``."""
    if len(rows) < 3:
        raise ValidationInputError(
            f"A panel of {len(rows)} cannot support a test. Supply at least 3 rows, "
            f"and understand that anything under ~30 has very little power."
        )

    result = ValidationResult(n=len(rows))

    for quadrant in QUADRANT_RANK:
        subset = [r.outcome for r in rows if r.quadrant == quadrant]
        result.by_quadrant[quadrant] = {
            "n": len(subset),
            "mean_outcome": round(mean(subset), 4) if subset else None,
            "median_outcome": round(median(subset), 4) if subset else None,
        }

    result.separation = (
        round(s, 4) if (s := _separation(rows)) is not None else None
    )
    result.spearman_rho = spearman(
        [r.position_score for r in rows], [r.outcome for r in rows]
    )

    # --- permutation null ---------------------------------------------------
    if result.separation is not None:
        rng = random.Random(settings.validation_random_seed)
        outcomes = [r.outcome for r in rows]
        observed = abs(result.separation)
        at_least_as_extreme = 0
        for _ in range(settings.validation_permutations):
            shuffled = outcomes[:]
            rng.shuffle(shuffled)
            permuted = [
                PanelRow(r.label, r.quadrant, r.attractiveness, r.strength, o)
                for r, o in zip(rows, shuffled)
            ]
            candidate = _separation(permuted)
            if candidate is not None and abs(candidate) >= observed:
                at_least_as_extreme += 1
        result.permutations_run = settings.validation_permutations
        # Add-one smoothing: a p-value of exactly 0 is not something a finite
        # permutation test can establish.
        result.permutation_p_value = round(
            (at_least_as_extreme + 1) / (settings.validation_permutations + 1), 4
        )

    result.verdict = _verdict(result)
    result.calculation_basis = {
        "separation_definition": (
            "mean(outcome | INVEST_GROW) - mean(outcome | HARVEST_DIVEST)"
        ),
        "position_score_definition": (
            "attractiveness x strength. Product not sum, because the GE-McKinsey "
            "rule is conjunctive and a sum cannot distinguish 'strong on one axis, "
            "weak on the other' from 'middling on both'."
        ),
        "rank_correlation": "Spearman's rho, ties averaged",
        "null_model": (
            "Outcomes are shuffled across companies while quadrant labels stay "
            "fixed, so the null is 'quadrant carries no information about outcome'. "
            "The p-value is the fraction of shuffles producing a separation at "
            "least as extreme as observed, with add-one smoothing."
        ),
        "permutations": settings.validation_permutations,
        "seed": settings.validation_random_seed,
        "power_warning": (
            f"n = {len(rows)}. Below roughly 30 this test cannot distinguish a real "
            f"effect from noise; a non-significant result at this size is not "
            f"evidence the framework fails, only that the panel is too small."
        ),
        "what_this_does_not_prove": (
            "Association, not causation. A quadrant that predicts outcome may be "
            "reading the same underlying growth that drives the outcome, rather "
            "than adding anything to it. A fair comparison needs a baseline model "
            "using revenue growth alone."
        ),
    }
    return result


def _verdict(result: ValidationResult) -> str:
    if result.separation is None:
        return (
            "No verdict: the panel does not contain both INVEST_GROW and "
            "HARVEST_DIVEST companies, so there is nothing to separate."
        )
    p = result.permutation_p_value
    direction = "in the expected direction" if result.separation > 0 else "REVERSED"
    if p is not None and p <= 0.05:
        return (
            f"Separation of {result.separation:+.3f} {direction}, permutation "
            f"p = {p:.3f}. Distinguishable from chance on this panel."
        )
    return (
        f"Separation of {result.separation:+.3f} {direction}, permutation "
        f"p = {p:.3f}. NOT distinguishable from chance on this panel."
        if p is not None
        else f"Separation of {result.separation:+.3f} {direction}; no null computed."
    )


def parse_panel(records: list[dict[str, Any]]) -> list[PanelRow]:
    """Build panel rows from CSV/JSON records, rejecting unusable ones loudly."""
    rows: list[PanelRow] = []
    for index, record in enumerate(records):
        try:
            quadrant = str(record["quadrant"]).strip().upper()
            if quadrant not in QUADRANT_RANK:
                raise ValidationInputError(
                    f"row {index}: unknown quadrant '{quadrant}'"
                )
            rows.append(
                PanelRow(
                    label=str(record.get("label", f"row-{index}")),
                    quadrant=quadrant,
                    attractiveness=float(record["attractiveness"]),
                    strength=float(record["strength"]),
                    outcome=float(record["outcome"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationInputError(f"row {index}: {exc}") from exc
    return rows
