"""Floors, harvest contribution, greedy order, and the marginal unit.

The allocation rule is project-defined, so these tests are not checking it
against a published standard - there is no published standard, which is the
whole point. They check that the rule implemented is the rule documented, that
it fails loudly where it says it will, and that it is deterministic.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.enums import AllocationOutcome, Quadrant
from app.services.portfolio import (
    ALLOCATION_RULE_STATUS,
    PortfolioInputError,
    PortfolioUnit,
    allocate_capital,
    entropy_discount,
    priority_score,
)


def unit(key: str, **overrides) -> PortfolioUnit:
    payload = {
        "entity_key": key,
        "company_id": f"id-{key}",
        "name": key.title(),
        "attractiveness": 3.5,
        "strength": 3.5,
        "quadrant": Quadrant.SELECTIVE_INVEST.value,
        "capital_requested": 100.0,
        "capital_floor": 0.0,
        "revenue": 1000.0,
        "entropy_bits": 0.0,
    }
    payload.update(overrides)
    return PortfolioUnit(**payload)


class TestPriorityScore:
    def test_it_is_conjunctive(self, settings):
        # Strong-and-weak must not equal middling-and-middling. A sum cannot
        # tell those apart, which is why the matrix's own rule is a product.
        lopsided = unit("a", attractiveness=5.0, strength=1.0)
        balanced = unit("b", attractiveness=3.0, strength=3.0)
        assert priority_score(lopsided, settings) < priority_score(balanced, settings)

    def test_entropy_discounts_priority(self, settings):
        decisive = unit("a", entropy_bits=0.0)
        contested = unit("b", entropy_bits=1.5)
        assert priority_score(contested, settings) < priority_score(decisive, settings)

    def test_maximum_entropy_discounts_to_nothing(self, settings):
        assert entropy_discount(settings.max_entropy_bits, settings) == pytest.approx(0.0)

    def test_an_unmeasured_unit_is_not_discounted(self, settings):
        # "Unmeasured" is not "decisive", but penalising a unit for a run
        # nobody performed would punish the wrong thing.
        assert entropy_discount(None, settings) == 1.0
        assert priority_score(unit("a", entropy_bits=None), settings) == pytest.approx(
            3.5 * 3.5
        )

    def test_the_discount_is_clamped(self, settings):
        assert entropy_discount(99.0, settings) == 0.0
        assert entropy_discount(-1.0, settings) == 1.0


class TestFloorsFirst:
    def test_floors_are_funded_before_any_discretionary_capital(self, settings):
        result = allocate_capital(
            [
                unit("high", attractiveness=5.0, strength=5.0, capital_requested=100.0),
                unit("low", attractiveness=1.5, strength=1.5, capital_requested=60.0,
                     capital_floor=60.0),
            ],
            budget=100.0,
            settings=settings,
        )
        by_key = {a.entity_key: a for a in result.allocations}
        assert by_key["low"].allocated == 60.0
        assert by_key["high"].allocated == 40.0

    def test_floors_exceeding_the_pool_is_an_error_not_a_partial_plan(self, settings):
        with pytest.raises(PortfolioInputError) as exc:
            allocate_capital(
                [unit("a", capital_floor=100.0), unit("b", capital_floor=100.0)],
                budget=150.0,
                settings=settings,
            )
        message = str(exc.value)
        assert "Shortfall" in message
        assert "50.00" in message

    def test_a_floor_above_its_own_request_is_rejected(self, settings):
        with pytest.raises(PortfolioInputError) as exc:
            allocate_capital(
                [unit("a", capital_requested=50.0, capital_floor=80.0)],
                budget=1000.0,
                settings=settings,
            )
        assert "non-discretionary part of the request" in str(exc.value)

    def test_the_floor_counts_towards_the_request_not_on_top_of_it(self, settings):
        result = allocate_capital(
            [unit("a", capital_requested=100.0, capital_floor=40.0)],
            budget=1000.0,
            settings=settings,
        )
        assert result.allocations[0].allocated == 100.0
        assert result.allocations[0].outcome is AllocationOutcome.FUNDED


class TestHarvestContribution:
    def test_a_harvest_unit_contributes_instead_of_drawing(self, settings):
        result = allocate_capital(
            [
                unit("grow", quadrant=Quadrant.INVEST_GROW.value, capital_requested=200.0),
                unit(
                    "old",
                    quadrant=Quadrant.HARVEST_DIVEST.value,
                    capital_requested=0.0,
                    revenue=1000.0,
                ),
            ],
            budget=100.0,
            settings=settings,
        )
        assert result.harvest_contribution == pytest.approx(100.0)   # 10% of 1000
        assert result.pool == pytest.approx(200.0)
        by_key = {a.entity_key: a for a in result.allocations}
        assert by_key["old"].outcome is AllocationOutcome.CONTRIBUTOR
        assert by_key["grow"].allocated == 200.0

    def test_a_harvest_units_floor_is_still_funded(self, settings):
        result = allocate_capital(
            [
                unit("old", quadrant=Quadrant.HARVEST_DIVEST.value,
                     capital_requested=30.0, capital_floor=30.0, revenue=1000.0),
                unit("grow", quadrant=Quadrant.INVEST_GROW.value, capital_requested=100.0),
            ],
            budget=100.0,
            settings=settings,
        )
        by_key = {a.entity_key: a for a in result.allocations}
        assert by_key["old"].allocated == 30.0
        assert by_key["old"].net_capital == pytest.approx(30.0 - 100.0)

    def test_a_harvest_unit_with_no_revenue_contributes_nothing_and_warns(self, settings):
        result = allocate_capital(
            [
                unit("old", quadrant=Quadrant.HARVEST_DIVEST.value, capital_requested=0.0,
                     revenue=None),
                unit("grow", capital_requested=50.0),
            ],
            budget=100.0,
            settings=settings,
        )
        assert result.harvest_contribution == 0.0
        assert any("no revenue" in w for w in result.warnings)

    def test_a_portfolio_with_no_harvest_unit_says_so(self, settings):
        result = allocate_capital([unit("a")], budget=100.0, settings=settings)
        assert any("No unit is in HARVEST_DIVEST" in w for w in result.warnings)

    def test_the_rate_is_configurable(self):
        settings = Settings(_env_file=None, harvest_contribution_rate=0.25)
        result = allocate_capital(
            [
                unit("old", quadrant=Quadrant.HARVEST_DIVEST.value, capital_requested=0.0,
                     revenue=400.0),
                unit("grow", capital_requested=500.0),
            ],
            budget=0.0,
            settings=settings,
        )
        assert result.harvest_contribution == pytest.approx(100.0)


class TestGreedyOrderAndTheMarginalUnit:
    def test_units_are_funded_in_priority_order(self, settings):
        result = allocate_capital(
            [
                unit("weak", attractiveness=2.0, strength=2.0, capital_requested=100.0),
                unit("strong", attractiveness=4.5, strength=4.5, capital_requested=100.0),
                unit("middle", attractiveness=3.5, strength=3.5, capital_requested=100.0),
            ],
            budget=250.0,
            settings=settings,
        )
        assert [a.entity_key for a in result.allocations] == ["strong", "middle", "weak"]
        assert [a.allocated for a in result.allocations] == [100.0, 100.0, 50.0]

    def test_the_marginal_unit_is_the_first_to_miss_out(self, settings):
        result = allocate_capital(
            [
                unit("strong", attractiveness=4.5, strength=4.5, capital_requested=100.0),
                unit("middle", attractiveness=3.5, strength=3.5, capital_requested=100.0),
                unit("weak", attractiveness=2.0, strength=2.0, capital_requested=100.0),
            ],
            budget=150.0,
            settings=settings,
        )
        assert result.marginal_unit["entity_key"] == "middle"
        assert result.marginal_unit["discretionary_granted"] == 50.0
        assert result.marginal_unit["shortfall"] == 50.0

    def test_unfunded_units_are_all_reported(self, settings):
        result = allocate_capital(
            [
                unit("a", attractiveness=4.5, strength=4.5, capital_requested=100.0),
                unit("b", attractiveness=3.0, strength=3.0, capital_requested=100.0),
                unit("c", attractiveness=2.0, strength=2.0, capital_requested=100.0),
            ],
            budget=100.0,
            settings=settings,
        )
        assert {u["entity_key"] for u in result.unfunded} == {"b", "c"}
        assert all(u["shortfall"] == 100.0 for u in result.unfunded)

    def test_an_exactly_funded_portfolio_has_no_marginal_unit(self, settings):
        result = allocate_capital(
            [unit("a", capital_requested=100.0), unit("b", capital_requested=100.0)],
            budget=200.0,
            settings=settings,
        )
        assert result.marginal_unit is None
        assert result.unfunded == []
        assert result.unallocated == 0.0

    def test_surplus_budget_is_reported_rather_than_spread(self, settings):
        result = allocate_capital(
            [unit("a", capital_requested=50.0)], budget=500.0, settings=settings
        )
        assert result.unallocated == 450.0

    def test_a_zero_budget_still_funds_nothing_and_says_so(self, settings):
        result = allocate_capital(
            [unit("a", capital_requested=100.0)], budget=0.0, settings=settings
        )
        assert result.allocations[0].outcome is AllocationOutcome.UNFUNDED
        assert result.marginal_unit["entity_key"] == "a"


class TestDeterminism:
    def test_ties_break_on_entity_key(self, settings):
        first = allocate_capital(
            [unit("zulu"), unit("alpha"), unit("mike")], budget=150.0, settings=settings
        )
        second = allocate_capital(
            [unit("mike"), unit("zulu"), unit("alpha")], budget=150.0, settings=settings
        )
        assert [a.entity_key for a in first.allocations] == ["alpha", "mike", "zulu"]
        assert [a.entity_key for a in first.allocations] == [
            a.entity_key for a in second.allocations
        ]
        assert [a.allocated for a in first.allocations] == [
            a.allocated for a in second.allocations
        ]


class TestValidation:
    def test_an_empty_portfolio_is_refused(self, settings):
        with pytest.raises(PortfolioInputError) as exc:
            allocate_capital([], budget=100.0, settings=settings)
        assert "no members" in str(exc.value)

    def test_a_duplicate_member_is_refused(self, settings):
        with pytest.raises(PortfolioInputError) as exc:
            allocate_capital([unit("a"), unit("a")], budget=100.0, settings=settings)
        assert "compete against itself" in str(exc.value)

    def test_a_negative_budget_is_refused(self, settings):
        with pytest.raises(PortfolioInputError):
            allocate_capital([unit("a")], budget=-1.0, settings=settings)

    def test_negative_capital_is_refused(self, settings):
        with pytest.raises(PortfolioInputError):
            allocate_capital([unit("a", capital_requested=-5.0)], budget=10.0, settings=settings)


class TestTheLabel:
    def test_the_payload_says_the_rule_is_project_defined(self, settings):
        basis = allocate_capital([unit("a")], budget=100.0, settings=settings).calculation_basis
        assert basis["status"] == ALLOCATION_RULE_STATUS
        assert "not part of the GE-McKinsey framework" in basis["status"]

    def test_it_states_that_the_framework_supplies_no_arithmetic(self, settings):
        basis = allocate_capital([unit("a")], budget=100.0, settings=settings).calculation_basis
        assert "does NOT supply is any allocation arithmetic" in basis["framework_note"]
        assert "General Electric" in basis["framework_note"]

    def test_the_greedy_limitation_is_admitted(self, settings):
        basis = allocate_capital([unit("a")], budget=100.0, settings=settings).calculation_basis
        assert "knapsack" in basis["greedy_note"]

    def test_every_allocation_carries_a_reason(self, settings):
        result = allocate_capital(
            [unit("a", entropy_bits=0.5), unit("b", entropy_bits=None)],
            budget=100.0,
            settings=settings,
        )
        assert all(len(a.reason) > 20 for a in result.allocations)
        by_key = {a.entity_key: a for a in result.allocations}
        assert "not discounted" in by_key["b"].reason
