#!/usr/bin/env python3
"""Build the industry benchmark table from SEC EDGAR XBRL filings.

    export EDGAR_USER_AGENT="Your Name you@example.com"
    python backend/scripts/build_benchmarks.py --period CY2024 \
        --out data/benchmarks/edgar_CY2024.json

Then point the app at it:

    export INDUSTRY_BENCHMARKS_PATH=data/benchmarks/edgar_CY2024.json

The SEC requires automated access to declare a User-Agent with contact details
and rate-limits it. There is no default User-Agent; the client refuses to be
constructed without one. Every response is cached under --cache-dir, so a
second run of the same period costs no requests at all, and --offline serves
the cache only and fails loudly on a miss.

This is a long-running job the first time: one frames request per candidate tag
per period, then one submissions request per company in the SIC sample. At the
default 5 requests/second a 600-company sample takes about two minutes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from app.config import get_settings
    from app.services.edgar.benchmark_builder import build_benchmark_table
    from app.services.edgar.client import (
        EdgarClient,
        EdgarConfigError,
        EdgarOfflineError,
    )

    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--period", default="CY2024", help="Calendar period, e.g. CY2024")
    parser.add_argument(
        "--prior-period",
        default=None,
        help="Period for the revenue-growth denominator. Defaults to period minus one year.",
    )
    parser.add_argument("--out", type=Path, default=None, help="Where to write the table")
    parser.add_argument("--cache-dir", default=settings.edgar_cache_dir)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Serve from cache only. A missing key is an error, never a fetch.",
    )
    parser.add_argument("--min-sector-n", type=int, default=settings.edgar_min_sector_n)
    parser.add_argument("--sic-limit", type=int, default=settings.edgar_sic_lookup_limit)
    parser.add_argument(
        "--requests-per-second", type=float, default=settings.edgar_requests_per_second
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    out_path = args.out or Path(f"data/benchmarks/edgar_{args.period}.json")

    def say(message: str) -> None:
        if not args.quiet:
            print(message, flush=True)

    try:
        client = EdgarClient(
            user_agent=settings.edgar_user_agent,
            cache_dir=args.cache_dir,
            requests_per_second=args.requests_per_second,
            timeout_seconds=settings.edgar_timeout_seconds,
            offline=args.offline,
        )
    except EdgarConfigError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 2

    say(f"Building {args.period} benchmarks (cache: {args.cache_dir}, offline={args.offline})")
    try:
        result = build_benchmark_table(
            client,
            period=args.period,
            prior_period=args.prior_period,
            min_sector_n=args.min_sector_n,
            sic_lookup_limit=args.sic_limit,
            progress=say,
        )
    except EdgarOfflineError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 3

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result.payload(), indent=2, sort_keys=True))

    provenance = result.provenance
    say("")
    say(f"Wrote {out_path}")
    say(f"  companies considered : {provenance['companies_considered']}")
    say(f"  sectors published    : {', '.join(provenance['sectors_published']) or 'none'}")
    if provenance["sectors_below_min_n"]:
        say(
            f"  below min n={args.min_sector_n}     : "
            + ", ".join(
                f"{sector} ({n})" for sector, n in provenance["sectors_below_min_n"].items()
            )
        )
    say("  coverage:")
    for metric, coverage in provenance["coverage_by_metric"].items():
        say(
            f"    {metric:<24} {coverage['resolved']:>6} resolved  "
            f"{coverage['dropped']:>6} dropped  ({coverage['coverage_pct']}%)"
        )
    say(f"  fetch: {json.dumps(provenance['fetch_stats'])}")
    say("")
    say(f"Point the app at it:  export INDUSTRY_BENCHMARKS_PATH={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
