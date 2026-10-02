#!/usr/bin/env python3
"""Run the backtest harness over a panel file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel_file", type=Path)
    parser.add_argument(
        "--api",
        default=None,
        help="Post to a running instance instead of computing locally.",
    )
    args = parser.parse_args()

    if not args.panel_file.is_file():
        raise SystemExit(f"No such file: {args.panel_file}")

    payload = json.loads(args.panel_file.read_text())
    records = payload["panel"] if isinstance(payload, dict) else payload
    note = payload.get("_note") if isinstance(payload, dict) else None

    if args.api:
        import urllib.request

        request = urllib.request.Request(
            f"{args.api.rstrip('/')}/validation/backtest",
            data=json.dumps({"panel": records}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read())
    else:
        from app.config import get_settings
        from app.services.validation import parse_panel, run_validation

        outcome = run_validation(parse_panel(records), get_settings())
        result = {
            "n": outcome.n,
            "by_quadrant": outcome.by_quadrant,
            "separation": outcome.separation,
            "spearman_rho": outcome.spearman_rho,
            "permutation_p_value": outcome.permutation_p_value,
            "permutations_run": outcome.permutations_run,
            "verdict": outcome.verdict,
            "calculation_basis": outcome.calculation_basis,
        }

    if note:
        print(f"!! {note}\n")

    print(f"Panel size: {result['n']}\n")
    print(f"{'Quadrant':<20} {'n':>4} {'mean':>9} {'median':>9}")
    for quadrant, stats in result["by_quadrant"].items():
        mean = stats["mean_outcome"]
        median = stats["median_outcome"]
        print(
            f"{quadrant:<20} {stats['n']:>4} "
            f"{('—' if mean is None else f'{mean:>9.4f}')} "
            f"{('—' if median is None else f'{median:>9.4f}')}"
        )

    print(f"\nSeparation (grow − divest): {result['separation']}")
    print(f"Spearman rho:               {result['spearman_rho']}")
    print(
        f"Permutation p-value:        {result['permutation_p_value']} "
        f"({result['permutations_run']} shuffles)"
    )
    print(f"\n{result['verdict']}")
    print(f"\n{result['calculation_basis']['power_warning']}")
    print(f"\n{result['calculation_basis']['what_this_does_not_prove']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
