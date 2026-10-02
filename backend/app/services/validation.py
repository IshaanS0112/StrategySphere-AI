"""Validation harness: does the quadrant verdict predict anything?"""

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
        """Composite position: the product of the two axes."""
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


# --------------------------------------------------------------------------
# V3: the comparison that makes a positive result mean anything V2's README already
# said it: "even a significant result would be association, not causation, until it
# beats a baseline model using revenue growth alone." Running the framework against
# a baseline needs a permutation p-value for a rank correlation, not just for the
# quadrant separation, because a panel can fail to contain both extreme quadrants
# while its continuous position score still predicts perfectly well.


def spearman_permutation_p(
    xs: list[float], ys: list[float], settings: Settings
) -> float | None:
    """Empirical p-value for Spearman's rho under label shuffling."""
    observed = spearman(xs, ys)
    if observed is None:
        return None

    rank_x = _rank(xs)
    rank_y = _rank(ys)
    mean_x, mean_y = mean(rank_x), mean(rank_y)
    dev_x = [value - mean_x for value in rank_x]
    dev_y = [value - mean_y for value in rank_y]
    norm_x = sum(value * value for value in dev_x) ** 0.5
    norm_y = sum(value * value for value in dev_y) ** 0.5
    if norm_x == 0 or norm_y == 0:
        return None

    rng = random.Random(settings.validation_random_seed)
    target = abs(observed)
    at_least_as_extreme = 0
    shuffled = dev_y[:]
    for _ in range(settings.validation_permutations):
        rng.shuffle(shuffled)
        candidate = sum(a * b for a, b in zip(dev_x, shuffled)) / (norm_x * norm_y)
        if abs(candidate) >= target - 1e-12:
            at_least_as_extreme += 1
    # Add-one smoothing: a finite permutation test cannot establish p = 0.
    return round(
        (at_least_as_extreme + 1) / (settings.validation_permutations + 1), 4
    )


def group_separation(
    labels: list[str], outcomes: list[float], high: str, low: str
) -> float | None:
    """``mean(outcome | high) - mean(outcome | low)`` for any two labels."""
    top = [o for label, o in zip(labels, outcomes) if label == high]
    bottom = [o for label, o in zip(labels, outcomes) if label == low]
    if not top or not bottom:
        return None
    return mean(top) - mean(bottom)


def separation_permutation_p(
    labels: list[str], outcomes: list[float], high: str, low: str, settings: Settings
) -> float | None:
    """Permutation p-value for ``group_separation`` under outcome shuffling."""
    observed = group_separation(labels, outcomes, high, low)
    if observed is None:
        return None
    rng = random.Random(settings.validation_random_seed)
    pool = outcomes[:]
    target = abs(observed)
    at_least_as_extreme = 0
    for _ in range(settings.validation_permutations):
        rng.shuffle(pool)
        candidate = group_separation(labels, pool, high, low)
        if candidate is not None and abs(candidate) >= target - 1e-12:
            at_least_as_extreme += 1
    return round(
        (at_least_as_extreme + 1) / (settings.validation_permutations + 1), 4
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
