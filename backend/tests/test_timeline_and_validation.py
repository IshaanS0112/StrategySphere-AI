"""Multi-period timelines and the validation harness.

The validation tests are the ones with teeth. A backtest that reports a
separation without a null is how a model that is indistinguishable from noise
gets called validated, so the permutation test is checked against data
constructed to have no signal at all.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.config import Settings
from app.enums import TrendDirection
from app.services.timeline import build_timeline, classify_trend
from app.services.validation import (
    PanelRow,
    ValidationInputError,
    parse_panel,
    run_validation,
    spearman,
)


def period(label, end, attractiveness, strength, quadrant, borderline=False):
    return {
        "company_id": f"id-{label}",
        "period_label": label,
        "period_end": end,
        "attractiveness": attractiveness,
        "strength": strength,
        "quadrant": quadrant,
        "borderline": borderline,
        "data_source": "test",
    }


class TestTrendClassification:
    def test_movement_below_the_floor_is_stable(self, settings: Settings):
        direction, delta = classify_trend(3.00, 3.20, settings)
        assert direction is TrendDirection.STABLE
        assert delta == pytest.approx(0.20)

    def test_material_rise_is_improving(self, settings: Settings):
        assert classify_trend(3.0, 3.6, settings)[0] is TrendDirection.IMPROVING

    def test_material_fall_is_deteriorating(self, settings: Settings):
        assert classify_trend(3.6, 3.0, settings)[0] is TrendDirection.DETERIORATING


class TestTimeline:
    def test_ordering_is_by_date_not_label(self, settings: Settings):
        rows = [
            period("Q11-2025", date(2025, 11, 30), 3.0, 3.0, "SELECTIVE_INVEST"),
            period("Q3-2025", date(2025, 3, 31), 2.0, 2.0, "HARVEST_DIVEST"),
        ]
        result = build_timeline(entity_key="acme", rows=rows, settings=settings)
        assert [p.period_label for p in result.points] == ["Q3-2025", "Q11-2025"], (
            "string ordering would put Q11 before Q3"
        )

    def test_period_without_a_date_is_excluded_with_a_reason(self, settings: Settings):
        rows = [
            period("FY2024", date(2024, 3, 31), 3.0, 3.0, "SELECTIVE_INVEST"),
            period("FY2025", None, 4.0, 4.0, "INVEST_GROW"),
        ]
        result = build_timeline(entity_key="acme", rows=rows, settings=settings)
        assert len(result.points) == 1
        assert len(result.excluded) == 1
        assert "cannot be ordered" in result.excluded[0]["reason"]

    def test_period_without_a_matrix_result_is_excluded(self, settings: Settings):
        rows = [
            period("FY2024", date(2024, 3, 31), 3.0, 3.0, "SELECTIVE_INVEST"),
            {
                "company_id": "x",
                "period_label": "FY2025",
                "period_end": date(2025, 3, 31),
                "attractiveness": None,
                "strength": None,
                "quadrant": None,
                "borderline": False,
                "data_source": None,
            },
        ]
        result = build_timeline(entity_key="acme", rows=rows, settings=settings)
        assert "no market attractiveness result" in result.excluded[0]["reason"]

    def test_single_period_gives_no_trend(self, settings: Settings):
        rows = [period("FY2024", date(2024, 3, 31), 3.0, 3.0, "SELECTIVE_INVEST")]
        result = build_timeline(entity_key="acme", rows=rows, settings=settings)
        assert result.attractiveness_trend is TrendDirection.INSUFFICIENT_DATA
        assert "needs at least two" in result.summary

    def test_quadrant_changes_are_listed_pairwise(self, settings: Settings):
        rows = [
            period("FY2023", date(2023, 3, 31), 4.0, 4.0, "INVEST_GROW"),
            period("FY2024", date(2024, 3, 31), 3.0, 3.0, "SELECTIVE_INVEST"),
            period("FY2025", date(2025, 3, 31), 2.0, 2.0, "HARVEST_DIVEST"),
        ]
        result = build_timeline(entity_key="acme", rows=rows, settings=settings)
        assert len(result.quadrant_changes) == 2
        assert result.quadrant_changes[0]["from_quadrant"] == "INVEST_GROW"
        assert result.attractiveness_trend is TrendDirection.DETERIORATING

    def test_borderline_periods_are_caveated(self, settings: Settings):
        rows = [
            period("FY2024", date(2024, 3, 31), 3.55, 3.55, "INVEST_GROW", borderline=True),
            period("FY2025", date(2025, 3, 31), 3.45, 3.45, "SELECTIVE_INVEST"),
        ]
        result = build_timeline(entity_key="acme", rows=rows, settings=settings)
        assert "borderline" in result.calculation_basis["borderline_caveat"]
        assert result.quadrant_changes[0]["either_side_borderline"] is True

    def test_trend_method_is_disclosed(self, settings: Settings):
        rows = [
            period("FY2024", date(2024, 3, 31), 3.0, 3.0, "SELECTIVE_INVEST"),
            period("FY2025", date(2025, 3, 31), 4.0, 4.0, "INVEST_GROW"),
        ]
        result = build_timeline(entity_key="acme", rows=rows, settings=settings)
        assert "first-to-last" in result.calculation_basis["trend_method"]


class TestSpearman:
    def test_perfect_positive_rank_correlation(self):
        assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)

    def test_perfect_negative(self):
        assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)

    def test_constant_input_is_undefined_not_zero(self):
        assert spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None

    def test_ties_are_averaged(self):
        # Monotone but with a tie: still strongly positive, not exactly 1.
        rho = spearman([1, 2, 2, 3], [10, 20, 20, 30])
        assert rho is not None and rho == pytest.approx(1.0)


class TestValidation:
    def test_tiny_panel_is_rejected(self, settings: Settings):
        with pytest.raises(ValidationInputError, match="at least 3"):
            run_validation(
                [PanelRow("a", "INVEST_GROW", 4, 4, 0.1)], settings
            )

    def test_position_score_is_the_product(self):
        assert PanelRow("a", "INVEST_GROW", 4.0, 3.0, 0.1).position_score == 12.0

    def test_clear_signal_is_detected(self, settings: Settings):
        rows = [PanelRow(f"g{i}", "INVEST_GROW", 4.5, 4.5, 0.30 + i * 0.01) for i in range(8)]
        rows += [
            PanelRow(f"d{i}", "HARVEST_DIVEST", 1.5, 1.5, -0.20 + i * 0.01) for i in range(8)
        ]
        result = run_validation(rows, settings)
        assert result.separation > 0
        assert result.permutation_p_value <= 0.05
        assert "Distinguishable from chance" in result.verdict

    def test_pure_noise_is_not_called_significant(self, settings: Settings):
        """Outcomes deliberately unrelated to quadrant. The harness must not
        report this as validation."""
        outcomes = [0.1, -0.2, 0.3, -0.1, 0.05, 0.2, -0.3, 0.15, -0.05, 0.25]
        quadrants = [
            "INVEST_GROW",
            "HARVEST_DIVEST",
            "SELECTIVE_INVEST",
        ] * 4
        rows = [
            PanelRow(f"r{i}", quadrants[i], 3.0, 3.0, outcomes[i % len(outcomes)])
            for i in range(10)
        ]
        result = run_validation(rows, settings)
        assert result.permutation_p_value > 0.05
        assert "NOT distinguishable from chance" in result.verdict

    def test_p_value_is_never_exactly_zero(self, settings: Settings):
        rows = [PanelRow(f"g{i}", "INVEST_GROW", 5, 5, 10.0) for i in range(6)]
        rows += [PanelRow(f"d{i}", "HARVEST_DIVEST", 1, 1, -10.0) for i in range(6)]
        result = run_validation(rows, settings)
        assert result.permutation_p_value > 0, (
            "a finite permutation test cannot establish p = 0"
        )

    def test_no_verdict_without_both_extreme_quadrants(self, settings: Settings):
        rows = [PanelRow(f"s{i}", "SELECTIVE_INVEST", 3, 3, 0.1 * i) for i in range(5)]
        result = run_validation(rows, settings)
        assert result.separation is None
        assert "nothing to separate" in result.verdict

    def test_reversed_separation_is_called_out(self, settings: Settings):
        rows = [PanelRow(f"g{i}", "INVEST_GROW", 4.5, 4.5, -0.2) for i in range(6)]
        rows += [PanelRow(f"d{i}", "HARVEST_DIVEST", 1.5, 1.5, 0.3) for i in range(6)]
        result = run_validation(rows, settings)
        assert result.separation < 0
        assert "REVERSED" in result.verdict

    def test_deterministic_given_the_seed(self, settings: Settings):
        rows = [PanelRow(f"g{i}", "INVEST_GROW", 4.5, 4.5, 0.3 + i * 0.01) for i in range(6)]
        rows += [PanelRow(f"d{i}", "HARVEST_DIVEST", 1.5, 1.5, -0.1) for i in range(6)]
        first = run_validation(rows, settings)
        second = run_validation(rows, settings)
        assert first.permutation_p_value == second.permutation_p_value

    def test_power_warning_is_always_present(self, settings: Settings):
        rows = [PanelRow(f"r{i}", "INVEST_GROW", 4, 4, 0.1) for i in range(3)]
        result = run_validation(rows, settings)
        assert "cannot distinguish a real" in result.calculation_basis["power_warning"]

    def test_causation_caveat_is_present(self, settings: Settings):
        rows = [PanelRow(f"r{i}", "INVEST_GROW", 4, 4, 0.1 * i) for i in range(4)]
        result = run_validation(rows, settings)
        assert "not causation" in result.calculation_basis["what_this_does_not_prove"]


class TestPanelParsing:
    def test_unknown_quadrant_is_rejected(self):
        with pytest.raises(ValidationInputError, match="unknown quadrant"):
            parse_panel([{"quadrant": "INVEST", "attractiveness": 4, "strength": 4, "outcome": 1}])

    def test_missing_field_is_rejected(self):
        with pytest.raises(ValidationInputError):
            parse_panel([{"quadrant": "INVEST_GROW", "attractiveness": 4}])

    def test_valid_records_parse(self):
        rows = parse_panel(
            [
                {
                    "label": "Acme",
                    "quadrant": "invest_grow",
                    "attractiveness": 4.2,
                    "strength": 3.9,
                    "outcome": 0.18,
                }
            ]
        )
        assert rows[0].quadrant == "INVEST_GROW"
        assert rows[0].label == "Acme"
