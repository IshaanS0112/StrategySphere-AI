"""What-if scenarios: recompute the pipeline under a named set of overrides."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.enums import Quadrant
from app.services import market_structure
from app.services.attractiveness_matrix import AttractivenessResult, run_attractiveness_matrix
from app.services.swot_engine import run_swot_analysis


class ScenarioInputError(ValueError):
    """Raised when an override cannot be applied to the baseline."""


# Keys a scenario is allowed to touch.
ALLOWED_MARKET_KEYS = {
    "market_growth_pct",
    "market_size_usd_bn",
    "industry_operating_margin_pct",
    "regulatory_outlook",
    "regulatory_impact_score",
    "competitive_intensity_score",
    "buyer_concentration",
    "buyer_switching_cost",
    "substitute_availability",
    "substitute_price_performance",
    "capital_intensity",
    "regulatory_barrier",
    "supplier_concentration",
}
ALLOWED_FINANCIAL_KEYS = {
    "revenue_growth_pct",
    "gross_margin_pct",
    "operating_margin_pct",
    "net_margin_pct",
    "return_on_capital_pct",
    "market_share_pct",
    "customer_retention_pct",
    "rnd_intensity_pct",
    "debt_to_equity",
}


@dataclass
class ScenarioResult:
    attractiveness: AttractivenessResult
    applied_overrides: dict[str, Any]
    resulting_inputs: dict[str, Any]
    delta: dict[str, Any] = field(default_factory=dict)
    quadrant_changed: bool = False
    warnings: list[str] = field(default_factory=list)


def _validate_overrides(overrides: dict) -> tuple[dict, list[str]]:
    """Reject unknown keys loudly; return the cleaned override set."""
    cleaned: dict[str, Any] = {}
    warnings: list[str] = []

    market = overrides.get("market_data") or {}
    if not isinstance(market, dict):
        raise ScenarioInputError("market_data override must be an object")
    unknown = set(market) - ALLOWED_MARKET_KEYS
    if unknown:
        raise ScenarioInputError(
            f"Unknown market_data override key(s): {sorted(unknown)}. "
            f"A key that does not exist would apply silently and make the "
            f"scenario look like evidence of stability."
        )
    if market:
        cleaned["market_data"] = dict(market)

    financial = overrides.get("financial_data") or {}
    if not isinstance(financial, dict):
        raise ScenarioInputError("financial_data override must be an object")
    unknown = set(financial) - ALLOWED_FINANCIAL_KEYS
    if unknown:
        raise ScenarioInputError(
            f"Unknown financial_data override key(s): {sorted(unknown)}"
        )
    if financial:
        cleaned["financial_data"] = dict(financial)

    competitors = overrides.get("competitors") or []
    if not isinstance(competitors, list):
        raise ScenarioInputError("competitors override must be a list of operations")
    ops: list[dict] = []
    for entry in competitors:
        if not isinstance(entry, dict) or "op" not in entry:
            raise ScenarioInputError(
                "each competitor override needs an 'op' of add | remove | update"
            )
        op = str(entry["op"]).lower()
        if op not in {"add", "remove", "update"}:
            raise ScenarioInputError(f"unsupported competitor op: {entry['op']}")
        if op in {"remove", "update"} and not entry.get("competitor_name"):
            raise ScenarioInputError(f"'{op}' needs a competitor_name to target")
        ops.append({**entry, "op": op})
    if ops:
        cleaned["competitors"] = ops

    if not cleaned:
        raise ScenarioInputError(
            "A scenario with no overrides just re-runs the baseline. Supply at "
            "least one market_data, financial_data, or competitors change."
        )
    return cleaned, warnings


def _apply_competitor_ops(
    competitors: list[dict], ops: list[dict]
) -> tuple[list[dict], list[str]]:
    result = copy.deepcopy(competitors)
    warnings: list[str] = []

    for entry in ops:
        op = entry["op"]
        name = entry.get("competitor_name")

        if op == "add":
            result.append(
                {
                    "competitor_name": name or f"Scenario entrant {len(result) + 1}",
                    "price_point": entry.get("price_point"),
                    "market_share_pct": entry.get("market_share_pct"),
                    "feature_scores": entry.get("feature_scores") or {},
                    "financial_data": entry.get("financial_data") or {},
                }
            )
            continue

        matches = [c for c in result if c.get("competitor_name") == name]
        if not matches:
            warnings.append(
                f"Competitor '{name}' not found in the baseline, so the '{op}' "
                f"operation did nothing. The scenario result reflects the "
                f"baseline competitor set."
            )
            continue

        if op == "remove":
            result = [c for c in result if c.get("competitor_name") != name]
        else:  # update
            for competitor in matches:
                for key in ("price_point", "market_share_pct"):
                    if key in entry:
                        competitor[key] = entry[key]
                if "feature_scores" in entry:
                    competitor["feature_scores"] = {
                        **(competitor.get("feature_scores") or {}),
                        **(entry["feature_scores"] or {}),
                    }

    return result, warnings


def _diff(baseline: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    """Field-by-field delta, reporting only what actually moved."""
    out: dict[str, Any] = {}
    for key, base_value in baseline.items():
        new_value = scenario.get(key)
        numeric = (
            isinstance(base_value, (int, float))
            and isinstance(new_value, (int, float))
            and not isinstance(base_value, bool)
            and not isinstance(new_value, bool)
        )
        if numeric:
            delta = round(new_value - base_value, 4)
            if delta != 0:
                out[key] = {
                    "baseline": base_value,
                    "scenario": new_value,
                    "delta": delta,
                }
        elif base_value != new_value:
            out[key] = {"baseline": base_value, "scenario": new_value}
    return out


def result_snapshot(result: AttractivenessResult) -> dict[str, Any]:
    """The comparable fields of a matrix result, for baselines and diffs."""
    return {
        "market_growth_score": result.market_growth_score,
        "market_size_score": result.market_size_score,
        "profitability_score": result.profitability_score,
        "competitive_intensity_score": result.competitive_intensity_score,
        "overall_attractiveness_score": result.overall_attractiveness_score,
        "competitive_strength_score": result.competitive_strength_score,
        "quadrant": result.quadrant.value,
        "borderline": result.borderline,
    }


def run_scenario(
    *,
    baseline_financial_data: dict,
    baseline_market_data: dict,
    baseline_qualitative_inputs: list,
    baseline_competitors: list[dict],
    baseline_snapshot: dict[str, Any],
    industry: str | None,
    overrides: dict,
    settings: Settings,
) -> ScenarioResult:
    """Recompute SWOT + matrix under overrides, diffed against a stored baseline."""
    cleaned, warnings = _validate_overrides(overrides)

    # Deep copies: the caller's dicts are ORM-attached and must not be touched.
    financial = copy.deepcopy(baseline_financial_data or {})
    market = copy.deepcopy(baseline_market_data or {})
    competitors = copy.deepcopy(baseline_competitors or [])

    financial.update(cleaned.get("financial_data", {}))
    market.update(cleaned.get("market_data", {}))
    if "competitors" in cleaned:
        competitors, competitor_warnings = _apply_competitor_ops(
            competitors, cleaned["competitors"]
        )
        warnings += competitor_warnings

    concentration = market_structure.assess_market_structure(
        company_market_share_pct=financial.get("market_share_pct"),
        competitors=competitors,
        analyst_intensity_override=market.get("competitive_intensity_score"),
        settings=settings,
    )
    swot = run_swot_analysis(
        financial_data=financial,
        market_data=market,
        qualitative_inputs=baseline_qualitative_inputs or [],
        competitors=competitors,
        industry=industry,
        concentration=concentration,
        settings=settings,
    )
    attractiveness = run_attractiveness_matrix(
        market_data=market,
        swot=swot,
        competitive_intensity_score=concentration.competitive_intensity_score,
        settings=settings,
    )

    scenario_snapshot = result_snapshot(attractiveness)
    delta = _diff(baseline_snapshot, scenario_snapshot)
    quadrant_changed = baseline_snapshot.get("quadrant") != scenario_snapshot["quadrant"]

    if not delta:
        warnings.append(
            "The overrides produced no change in any scored output. Either they "
            "were within a neutral band, or they moved an input the matrix does "
            "not read."
        )

    return ScenarioResult(
        attractiveness=attractiveness,
        applied_overrides=cleaned,
        resulting_inputs={
            "financial_data": financial,
            "market_data": market,
            "competitor_count": len(competitors),
            "competitor_names": [c.get("competitor_name") for c in competitors],
        },
        delta=delta,
        quadrant_changed=quadrant_changed,
        warnings=warnings,
    )


def describe_move(baseline_quadrant: str, scenario_quadrant: str) -> str:
    """Plain-language reading of a quadrant migration."""
    if baseline_quadrant == scenario_quadrant:
        return f"Position holds in {scenario_quadrant} under this scenario."
    ordering = {
        Quadrant.HARVEST_DIVEST.value: 0,
        Quadrant.SELECTIVE_INVEST.value: 1,
        Quadrant.INVEST_GROW.value: 2,
    }
    direction = (
        "improves" if ordering.get(scenario_quadrant, 1) > ordering.get(baseline_quadrant, 1)
        else "deteriorates"
    )
    return (
        f"Position {direction}: {baseline_quadrant} -> {scenario_quadrant} under "
        f"this scenario."
    )
