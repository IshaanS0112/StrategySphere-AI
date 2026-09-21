"""Portfolio capital allocation across business units.

**GE-McKinsey was built for exactly this.** McKinsey developed the nine-box for
General Electric in the early 1970s to allocate capital across GE's business
units — which of the roughly forty of them should be fed, held or wound down.
Scoring a single company, which is what V1 and V2 do, is the degenerate case of
the framework. This module uses it for its actual purpose.

**And GE-McKinsey prescribes no allocation arithmetic.** It is a positioning
framework: it tells you where a unit sits, and what you then do with the budget
is management judgement. So the rule implemented here is mine, it is labelled
``PROJECT-DEFINED ALLOCATION RULE`` in every payload it touches, and it gets
exactly the same treatment as the Porter composite — a number the UI can sort
by, with a statement attached that the framework did not supply it.

    priority_score = attractiveness x strength x (1 - entropy_bits / log2(3))

Conjunctive, matching the matrix: a product, not a sum, because being strong on
one axis and weak on the other is not the same as middling on both. Discounted
by entropy so a contested position competes for capital on worse terms than a
decisive one at the same coordinates — which is the entire reason Pillar B
computes an entropy at all.

**The allocation, in order.**

1. **Every floor is funded first.** A unit's ``capital_floor`` is what keeps it
   operating and is not discretionary. If the floors exceed the available pool
   the result is an error naming the shortfall, not a silent partial
   allocation — a committee that asked "can we fund this portfolio" needs to
   hear "no", not receive a plan that quietly starves two units.
2. **Harvest units contribute rather than draw.** A unit in ``HARVEST_DIVEST``
   adds ``harvest_contribution_rate x revenue`` to the pool. This is the one
   rule here with real provenance: funding growth out of the cash thrown off by
   declining units is what GE used the matrix for.
3. **The remainder is allocated greedily by priority**, capped at each unit's
   own request.
4. **What did not get funded is reported, including the marginal unit** — the
   first one in priority order that did not fit. An allocator that returns only
   winners hides the decision it actually made.

Ties break on ``(priority_score, entity_key)`` so two identical units always
come out in the same order.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.config import Settings
from app.enums import AllocationOutcome, Quadrant

ALLOCATION_RULE_STATUS = (
    "PROJECT-DEFINED ALLOCATION RULE, not part of the GE-McKinsey framework"
)


class PortfolioInputError(ValueError):
    """A portfolio that cannot be allocated as stated."""


@dataclass(frozen=True)
class PortfolioUnit:
    """One business unit: an existing scored company-period, plus capital terms.

    ``entity_key`` and ``period_label`` are the V2 period identity, reused
    rather than duplicated. A portfolio member is a pointer at a company-period
    row that has already been through the matrix, which is what keeps one
    unit's position on the grid identical to the one its own page shows.
    """

    entity_key: str
    company_id: str
    name: str
    attractiveness: float
    strength: float
    quadrant: str
    capital_requested: float
    capital_floor: float = 0.0
    revenue: float | None = None
    period_label: str | None = None
    # None means no uncertainty analysis has been run for this unit, which is
    # not the same as an entropy of zero and must not be scored as one.
    entropy_bits: float | None = None

    @property
    def is_harvest(self) -> bool:
        return self.quadrant == Quadrant.HARVEST_DIVEST.value


@dataclass
class Allocation:
    entity_key: str
    company_id: str
    name: str
    quadrant: str
    attractiveness: float
    strength: float
    entropy_bits: float | None
    entropy_discount: float
    priority_score: float
    revenue: float | None
    capital_requested: float
    capital_floor: float
    allocated: float
    contributed: float
    net_capital: float
    outcome: AllocationOutcome
    reason: str
    rank: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["outcome"] = self.outcome.value
        return payload


@dataclass
class AllocationResult:
    budget: float
    harvest_contribution: float
    pool: float
    floors_total: float
    discretionary_available: float
    discretionary_allocated: float
    unallocated: float
    allocations: list[Allocation] = field(default_factory=list)
    unfunded: list[dict[str, Any]] = field(default_factory=list)
    marginal_unit: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    calculation_basis: dict[str, Any] = field(default_factory=dict)


def entropy_discount(entropy_bits: float | None, settings: Settings) -> float:
    """``1 - entropy/log2(3)``, clamped to [0, 1]. Missing entropy does not discount.

    A unit with no uncertainty analysis is not penalised, because "unmeasured"
    is not "contested". It is recorded in the allocation's reason so the
    asymmetry is visible: a unit that never ran the Monte Carlo competes at
    full priority against one that ran it and came back contested.
    """
    if entropy_bits is None:
        return 1.0
    ratio = entropy_bits / settings.max_entropy_bits if settings.max_entropy_bits else 0.0
    return max(0.0, min(1.0, 1.0 - ratio))


def priority_score(unit: PortfolioUnit, settings: Settings) -> float:
    """Conjunctive position score, discounted for stated uncertainty."""
    return round(
        unit.attractiveness * unit.strength * entropy_discount(unit.entropy_bits, settings), 6
    )


def _validate(units: list[PortfolioUnit], budget: float) -> None:
    if budget < 0:
        raise PortfolioInputError("budget cannot be negative")
    if not units:
        raise PortfolioInputError(
            "A portfolio with no members has nothing to allocate. GE-McKinsey is a "
            "comparison across units; one unit in isolation is the single-company "
            "view the rest of this application already provides."
        )
    seen: set[str] = set()
    for unit in units:
        if unit.capital_requested < 0 or unit.capital_floor < 0:
            raise PortfolioInputError(f"{unit.entity_key}: capital amounts cannot be negative")
        if unit.capital_floor > unit.capital_requested:
            raise PortfolioInputError(
                f"{unit.entity_key}: capital_floor {unit.capital_floor:,.0f} exceeds "
                f"capital_requested {unit.capital_requested:,.0f}. The floor is the "
                "non-discretionary part of the request, not an amount on top of it."
            )
        if unit.entity_key in seen:
            raise PortfolioInputError(
                f"duplicate member {unit.entity_key}: a unit cannot compete against itself"
            )
        seen.add(unit.entity_key)


def allocate_capital(
    units: list[PortfolioUnit], *, budget: float, settings: Settings
) -> AllocationResult:
    """Fund floors, take the harvest contribution, then greedily fund priority."""
    _validate(units, budget)
    warnings: list[str] = []

    # --- step 2 first, arithmetically: the pool is what floors are paid from --
    harvest_contribution = 0.0
    contribution_by_unit: dict[str, float] = {}
    for unit in units:
        if not unit.is_harvest:
            continue
        if unit.revenue is None:
            warnings.append(
                f"{unit.entity_key} is in HARVEST_DIVEST but reported no revenue, so it "
                "contributes nothing to the pool. The contribution is a fraction of "
                "revenue and cannot be computed without one."
            )
            contribution_by_unit[unit.entity_key] = 0.0
            continue
        contribution = settings.harvest_contribution_rate * float(unit.revenue)
        contribution_by_unit[unit.entity_key] = contribution
        harvest_contribution += contribution

    pool = budget + harvest_contribution

    # --- step 1: floors are not discretionary -------------------------------
    floors_total = sum(unit.capital_floor for unit in units)
    if floors_total > pool + 1e-9:
        raise PortfolioInputError(
            f"The floors total {floors_total:,.2f} against an available pool of "
            f"{pool:,.2f} (budget {budget:,.2f} plus {harvest_contribution:,.2f} of "
            f"harvest contribution). Shortfall {floors_total - pool:,.2f}. A floor is "
            "the minimum to keep a unit operating, so this portfolio cannot be funded "
            "as stated: either the budget rises or a unit closes. Allocating what "
            "fits and staying silent would present a plan that starves units without "
            "saying which."
        )

    remaining = pool - floors_total

    ranked = sorted(units, key=lambda u: (-priority_score(u, settings), u.entity_key))

    allocations: list[Allocation] = []
    unfunded: list[dict[str, Any]] = []
    marginal: dict[str, Any] | None = None
    discretionary_allocated = 0.0

    for rank, unit in enumerate(ranked, start=1):
        score = priority_score(unit, settings)
        discount = entropy_discount(unit.entropy_bits, settings)
        contributed = contribution_by_unit.get(unit.entity_key, 0.0)
        allocated = unit.capital_floor
        reason_parts: list[str] = []

        if unit.is_harvest:
            outcome = AllocationOutcome.CONTRIBUTOR
            reason_parts.append(
                f"HARVEST_DIVEST: contributes {settings.harvest_contribution_rate:.0%} of "
                f"revenue ({contributed:,.2f}) to the pool and draws no discretionary "
                "capital. Funding growth out of the cash thrown off by declining units "
                "is what GE used this matrix for."
            )
            if unit.capital_floor > 0:
                reason_parts.append(
                    f"Its floor of {unit.capital_floor:,.2f} is still funded: a unit being "
                    "harvested is still operating."
                )
        else:
            discretionary_request = unit.capital_requested - unit.capital_floor
            grant = min(discretionary_request, max(0.0, remaining))
            allocated += grant
            remaining -= grant
            discretionary_allocated += grant

            if grant >= discretionary_request - 1e-9 and discretionary_request > 0:
                outcome = AllocationOutcome.FUNDED
                reason_parts.append(f"Funded in full at priority rank {rank}.")
            elif discretionary_request <= 1e-9:
                outcome = AllocationOutcome.FUNDED
                reason_parts.append(
                    "Requested nothing above its floor, so it is fully funded by "
                    "definition."
                )
            elif grant > 1e-9:
                outcome = AllocationOutcome.PARTIALLY_FUNDED
                reason_parts.append(
                    f"The budget ran out inside this unit: {grant:,.2f} of a "
                    f"{discretionary_request:,.2f} discretionary request."
                )
                marginal = marginal or _marginal_entry(unit, score, rank, grant)
            elif unit.capital_floor > 0:
                outcome = AllocationOutcome.FLOOR_ONLY
                reason_parts.append(
                    f"Floor funded, discretionary request of {discretionary_request:,.2f} "
                    "not reached."
                )
                marginal = marginal or _marginal_entry(unit, score, rank, 0.0)
            else:
                outcome = AllocationOutcome.UNFUNDED
                reason_parts.append("Nothing available by the time priority reached it.")
                marginal = marginal or _marginal_entry(unit, score, rank, 0.0)

            if outcome is not AllocationOutcome.FUNDED:
                unfunded.append(
                    {
                        "entity_key": unit.entity_key,
                        "name": unit.name,
                        "rank": rank,
                        "priority_score": score,
                        "quadrant": unit.quadrant,
                        "capital_requested": unit.capital_requested,
                        "allocated": round(allocated, 2),
                        "shortfall": round(unit.capital_requested - allocated, 2),
                        "outcome": outcome.value,
                    }
                )

        if unit.entropy_bits is None:
            reason_parts.append(
                "No uncertainty analysis has been run for this unit, so its priority is "
                "not discounted. Unmeasured is not the same as decisive."
            )
        else:
            reason_parts.append(
                f"Priority {score:,.3f} = {unit.attractiveness:.2f} x {unit.strength:.2f} "
                f"x {discount:.3f} (entropy {unit.entropy_bits:.3f} bits)."
            )

        allocations.append(
            Allocation(
                entity_key=unit.entity_key,
                company_id=unit.company_id,
                name=unit.name,
                quadrant=unit.quadrant,
                attractiveness=unit.attractiveness,
                strength=unit.strength,
                entropy_bits=unit.entropy_bits,
                entropy_discount=round(discount, 4),
                priority_score=score,
                revenue=unit.revenue,
                capital_requested=unit.capital_requested,
                capital_floor=unit.capital_floor,
                allocated=round(allocated, 2),
                contributed=round(contributed, 2),
                net_capital=round(allocated - contributed, 2),
                outcome=outcome,
                reason=" ".join(reason_parts),
                rank=rank,
            )
        )

    if not any(unit.is_harvest for unit in units):
        warnings.append(
            "No unit is in HARVEST_DIVEST, so nothing contributes to the pool. The "
            "allocation is funded entirely from the stated budget."
        )

    return AllocationResult(
        budget=round(budget, 2),
        harvest_contribution=round(harvest_contribution, 2),
        pool=round(pool, 2),
        floors_total=round(floors_total, 2),
        discretionary_available=round(pool - floors_total, 2),
        discretionary_allocated=round(discretionary_allocated, 2),
        unallocated=round(max(0.0, remaining), 2),
        allocations=allocations,
        unfunded=unfunded,
        marginal_unit=marginal,
        warnings=warnings,
        calculation_basis=_basis_block(units, settings, marginal),
    )


def _marginal_entry(
    unit: PortfolioUnit, score: float, rank: int, granted: float
) -> dict[str, Any]:
    return {
        "entity_key": unit.entity_key,
        "name": unit.name,
        "rank": rank,
        "priority_score": score,
        "capital_requested": unit.capital_requested,
        "discretionary_granted": round(granted, 2),
        "shortfall": round(unit.capital_requested - unit.capital_floor - granted, 2),
        "note": (
            "The marginal unit: the highest-priority unit that did not get its full "
            "request. This is the decision the allocation actually made, and it is "
            "the line a committee argues about. Reporting only the funded units "
            "would hide it."
        ),
    }


def _basis_block(
    units: list[PortfolioUnit], settings: Settings, marginal: dict[str, Any] | None
) -> dict[str, Any]:
    scored = sum(1 for unit in units if unit.entropy_bits is not None)
    return {
        "status": ALLOCATION_RULE_STATUS,
        "framework_note": (
            "GE-McKinsey was developed by McKinsey for General Electric in the early "
            "1970s to allocate capital across GE's business units, so using it on a "
            "portfolio is the framework's original purpose rather than an extension "
            "of it. What the framework does NOT supply is any allocation arithmetic: "
            "it positions units and leaves the capital decision to management. The "
            "rule below is therefore mine, and is labelled as mine wherever it "
            "appears - the same treatment the Porter composite gets."
        ),
        "priority_formula": (
            "priority_score = attractiveness x strength x (1 - entropy_bits / log2(3))"
        ),
        "priority_components": {
            "conjunctive": (
                "A product, not a sum, matching the matrix's own rule: strong on one "
                "axis and weak on the other is not the same as middling on both, and "
                "a sum cannot tell them apart."
            ),
            "entropy_discount": (
                "A contested position competes for capital on worse terms than a "
                "decisive one at the same coordinates. This is the reason the "
                "uncertainty analysis computes an entropy at all."
            ),
            "unmeasured_units": (
                f"{len(units) - scored} of {len(units)} units have no uncertainty "
                "analysis and are not discounted. Unmeasured is not decisive, and "
                "discounting them would penalise a unit for a missing run rather "
                "than for a contested position."
            ),
        },
        "allocation_order": [
            "1. Fund every capital_floor. Floors are not discretionary; if they exceed "
            "the pool the allocation fails loudly rather than silently starving units.",
            f"2. HARVEST_DIVEST units contribute "
            f"{settings.harvest_contribution_rate:.0%} of revenue to the pool instead "
            "of drawing from it. This is the one rule here with real provenance: "
            "funding growth out of declining units is what GE used the matrix for.",
            "3. Allocate the remainder greedily by priority, capped at each unit's own "
            "capital_requested.",
            "4. Report the unfunded units and the marginal one.",
        ],
        "harvest_contribution_rate": settings.harvest_contribution_rate,
        "max_entropy_bits": settings.max_entropy_bits,
        "tie_break": (
            "(priority_score descending, entity_key ascending). Deterministic, so two "
            "identical units always come out in the same order and a rerun of the "
            "same portfolio is quotable."
        ),
        "greedy_note": (
            "Greedy by priority is not the allocation that maximises total priority "
            "under the budget - that is a knapsack problem, and its optimum can fund "
            "two mid-priority units instead of one top-priority one. Greedy is used "
            "because a capital committee has to be able to follow the ordering, and "
            "'we funded them in priority order until the money ran out' is a defence "
            "an optimiser's answer cannot offer."
        ),
        "marginal_unit_reported": marginal is not None,
    }
