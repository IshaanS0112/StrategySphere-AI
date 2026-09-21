#!/usr/bin/env python3
"""Run the backtest on a real panel, against a revenue-growth-only baseline.

    python backend/scripts/run_edgar_validation.py \
        data/validation/edgar_panel_CY2020_CY2023.json

Two models on the same rows:

* **GE-McKinsey** — position score = attractiveness x strength, as the V2
  harness defines it, plus the quadrant separation the harness reports.
* **Baseline** — revenue growth at T alone. One number the analyst already had
  before any of this was built.

If the framework does not beat the baseline it is adding nothing over a figure
that was already on the first page of the filing, and that is the result worth
publishing. Both models get a permutation p-value; neither gets tuned.

Prints a report and, with --markdown, writes docs/validation_results.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from app.config import get_settings
    from app.services.validation import (
        PanelRow,
        group_separation,
        run_validation,
        separation_permutation_p,
        spearman,
        spearman_permutation_p,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel_file", type=Path)
    parser.add_argument("--markdown", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    payload = json.loads(args.panel_file.read_text())
    panel = payload["panel"]
    provenance = payload.get("_provenance", {})

    rows = [
        PanelRow(
            label=r["label"],
            quadrant=r["quadrant"],
            attractiveness=r["attractiveness"],
            strength=r["strength"],
            outcome=r["outcome"],
        )
        for r in panel
    ]
    outcomes = [r.outcome for r in rows]
    labels = [r.quadrant for r in rows]

    # --- model A: the framework -------------------------------------------
    harness = run_validation(rows, settings)
    position = [r.position_score for r in rows]
    model_rho = spearman(position, outcomes)
    model_p = spearman_permutation_p(position, outcomes, settings)

    # The harness's separation is specifically INVEST_GROW minus
    # HARVEST_DIVEST. When a panel contains only two of the three quadrants it
    # is undefined, and the generalised version is reported alongside rather
    # than instead - swapping the definition to whatever the data supports is
    # how a backtest gets tuned into significance.
    present = sorted({r.quadrant for r in rows})
    pairs = [
        ("INVEST_GROW", "HARVEST_DIVEST"),
        ("INVEST_GROW", "SELECTIVE_INVEST"),
        ("SELECTIVE_INVEST", "HARVEST_DIVEST"),
    ]
    group_tests = []
    for high, low in pairs:
        separation = group_separation(labels, outcomes, high, low)
        if separation is None:
            group_tests.append({"high": high, "low": low, "separation": None, "p": None})
            continue
        group_tests.append(
            {
                "high": high,
                "low": low,
                "separation": round(separation, 4),
                "p": separation_permutation_p(labels, outcomes, high, low, settings),
            }
        )

    # --- model B: revenue growth alone ------------------------------------
    growth_rows = [
        (r, panel[i].get("revenue_growth_pct_at_T"))
        for i, r in enumerate(rows)
        if panel[i].get("revenue_growth_pct_at_T") is not None
    ]
    baseline_rho = baseline_p = None
    baseline_groups: list[dict] = []
    if len(growth_rows) >= 30:
        growth_values = [g for _row, g in growth_rows]
        growth_outcomes = [row.outcome for row, _g in growth_rows]
        baseline_rho = spearman(growth_values, growth_outcomes)
        baseline_p = spearman_permutation_p(growth_values, growth_outcomes, settings)

        # Terciles of growth, so the baseline gets a group comparison shaped
        # exactly like the framework's rather than only a correlation.
        ordered = sorted(growth_values)
        low_cut = ordered[len(ordered) // 3]
        high_cut = ordered[2 * len(ordered) // 3]
        tercile_labels = [
            "TOP_THIRD" if g >= high_cut else ("BOTTOM_THIRD" if g <= low_cut else "MIDDLE")
            for g in growth_values
        ]
        separation = group_separation(
            tercile_labels, growth_outcomes, "TOP_THIRD", "BOTTOM_THIRD"
        )
        baseline_groups.append(
            {
                "high": "TOP_THIRD",
                "low": "BOTTOM_THIRD",
                "separation": round(separation, 4) if separation is not None else None,
                "p": separation_permutation_p(
                    tercile_labels, growth_outcomes, "TOP_THIRD", "BOTTOM_THIRD", settings
                ),
            }
        )

    report = {
        "panel_file": str(args.panel_file),
        "n": len(rows),
        "quadrants_present": present,
        "by_quadrant": harness.by_quadrant,
        "outcome_mean": round(mean(outcomes), 4),
        "outcome_median": round(median(outcomes), 4),
        "model": {
            "name": "GE-McKinsey position (attractiveness x strength)",
            "spearman_rho": model_rho,
            "permutation_p": model_p,
            "harness_separation": harness.separation,
            "harness_p": harness.permutation_p_value,
            "harness_verdict": harness.verdict,
            "group_tests": group_tests,
        },
        "baseline": {
            "name": "revenue growth at T, alone",
            "n": len(growth_rows),
            "spearman_rho": baseline_rho,
            "permutation_p": baseline_p,
            "group_tests": baseline_groups,
        },
        "permutations": settings.validation_permutations,
        "seed": settings.validation_random_seed,
        "provenance": provenance,
    }

    print(json.dumps({k: v for k, v in report.items() if k != "provenance"}, indent=2))

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(_render_markdown(report))
        print(f"\nwrote {args.markdown}")
    return 0


def _fmt(value, digits: int = 4, dash: str = "—") -> str:
    return dash if value is None else f"{value:.{digits}f}"


def _render_markdown(report: dict) -> str:
    """The numeric skeleton of docs/validation_results.md.

    Only the figures are generated. The reading of them is written by hand
    underneath, because a script that also writes the conclusion is a script
    that can be pointed at a different panel until the conclusion changes.
    """
    provenance = report["provenance"]
    lines = [
        "<!-- Numbers in this section are generated by",
        "     backend/scripts/run_edgar_validation.py --markdown.",
        "     The reading of them below is written by hand. -->",
        "",
        f"- **Panel**: `{report['panel_file']}`, n = {report['n']}",
        f"- **Scored at**: {provenance.get('scoring_period')}  →  "
        f"**outcome at**: {provenance.get('outcome_period')} "
        f"({provenance.get('horizon_years')}-year revenue CAGR)",
        f"- **Quadrants present**: {', '.join(report['quadrants_present'])}",
        f"- **Permutations**: {report['permutations']}, seed {report['seed']}",
        "",
        "| Quadrant | n | mean outcome | median outcome |",
        "|---|---:|---:|---:|",
    ]
    for quadrant, entry in report["by_quadrant"].items():
        lines.append(
            f"| `{quadrant}` | {entry['n']} | {_fmt(entry['mean_outcome'])} | "
            f"{_fmt(entry['median_outcome'])} |"
        )

    lines += [
        "",
        "| Model | Spearman rho | permutation p | group separation | p |",
        "|---|---:|---:|---:|---:|",
    ]
    model = report["model"]
    usable = [t for t in model["group_tests"] if t["separation"] is not None]
    best = usable[0] if usable else {"separation": None, "p": None, "high": "", "low": ""}
    lines.append(
        f"| GE-McKinsey position | {_fmt(model['spearman_rho'])} | "
        f"{_fmt(model['permutation_p'])} | {_fmt(best['separation'])} | {_fmt(best['p'])} |"
    )
    baseline = report["baseline"]
    b_group = baseline["group_tests"][0] if baseline["group_tests"] else {}
    lines.append(
        f"| Revenue growth alone | {_fmt(baseline['spearman_rho'])} | "
        f"{_fmt(baseline['permutation_p'])} | {_fmt(b_group.get('separation'))} | "
        f"{_fmt(b_group.get('p'))} |"
    )

    lines += ["", "**Every group comparison attempted:**", ""]
    lines += ["| High group | Low group | separation | p |", "|---|---|---:|---:|"]
    for test in model["group_tests"]:
        lines.append(
            f"| `{test['high']}` | `{test['low']}` | {_fmt(test['separation'])} | "
            f"{_fmt(test['p'])} |"
        )
    lines += [
        "",
        f"**The V2 harness's own verdict, verbatim:** {model['harness_verdict']}",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
