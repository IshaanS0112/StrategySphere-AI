#!/usr/bin/env python3
"""Load a case-study JSON file into a running StrategySphere instance.

    python backend/scripts/load_case_study.py data/case_studies/premium_saas.json \
        --api http://localhost:8000 --run-all

Uses only the standard library so it runs against a deployed instance without
installing the backend's dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def call(api: str, path: str, payload: dict | None = None, method: str = "GET") -> Any:
    url = f"{api.rstrip('/')}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"{method} {path} failed with {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach {url} ({exc.reason}). Is the backend running?"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_file", type=Path)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Run SWOT, matrix, pricing, and the report after loading.",
    )
    args = parser.parse_args()

    if not args.case_file.is_file():
        raise SystemExit(f"No such file: {args.case_file}")

    case = json.loads(args.case_file.read_text())
    company_payload = case["company"]

    company = call(args.api, "/companies", company_payload, method="POST")
    company_id = company["id"]
    print(f"Created company {company['name']} ({company_id})")

    for competitor in case.get("competitors", []):
        created = call(
            args.api, f"/companies/{company_id}/competitors", competitor, method="POST"
        )
        print(f"  + competitor {created['competitor_name']}")

    if not args.run_all:
        print(f"\nLoaded. Open {args.api}/docs or the dashboard to run the analysis.")
        return 0

    swot = call(args.api, f"/companies/{company_id}/swot-analysis", {}, method="POST")
    counts = swot["calculation_basis"]["factor_counts"]
    print(
        f"\nSWOT: {counts['strengths']}S / {counts['weaknesses']}W / "
        f"{counts['opportunities']}O / {counts['threats']}T"
    )

    matrix = call(args.api, f"/companies/{company_id}/market-attractiveness", {}, method="POST")
    print(
        f"Matrix: attractiveness {matrix['overall_attractiveness_score']}, "
        f"strength {matrix['competitive_strength_score']} -> {matrix['quadrant']}"
        + (" (BORDERLINE)" if matrix["borderline"] else "")
    )

    scenario = case.get("pricing_scenario")
    if scenario:
        pricing = call(
            args.api, f"/companies/{company_id}/pricing-recommendation", scenario, method="POST"
        )
        band = pricing["recommended_price_range"]
        print(
            f"Pricing: {band['min']} / {band['optimal']} / {band['max']} "
            f"(implied margin {pricing['calculation_basis']['implied_margin_pct']}%, "
            f"confidence {pricing['reasoning']['confidence']})"
        )

    report = call(
        args.api, f"/companies/{company_id}/generate-strategy-report", {}, method="POST"
    )
    print(f"Report: narrated by {report['narrative_source']}")
    print("\n" + report["ai_narrative"]["executive_summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
