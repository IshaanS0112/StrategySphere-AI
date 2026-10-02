#!/usr/bin/env python3
"""Assemble a real validation panel from SEC filings, and score it for real."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MIN_SECTOR_PEERS = 8
# Cap on peers passed into one company's scoring run.
MAX_PEERS_PER_COMPANY = 60


def main() -> int:  # noqa: C901 - a linear pipeline, read top to bottom
    from app.config import get_settings
    from app.services.edgar import concepts as concept_mod
    from app.services.edgar import sic as sic_mod
    from app.services.edgar.benchmark_builder import ConceptCache, company_values_for_metric
    from app.services.edgar.client import (
        EdgarClient,
        EdgarConfigError,
        EdgarFetchError,
        EdgarOfflineError,
    )
    from app.services.attractiveness_matrix import run_attractiveness_matrix
    from app.services.market_structure import assess_market_structure
    from app.services.swot_engine import run_swot_analysis

    settings = get_settings()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scoring-period", default="CY2020")
    parser.add_argument("--horizon", type=int, default=3, help="Years to the outcome")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--cache-dir", default=settings.edgar_cache_dir)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--sic-limit", type=int, default=1500)
    parser.add_argument(
        "--min-metrics",
        type=int,
        default=4,
        help="Companies resolving fewer financial metrics than this are dropped.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    scoring_year = int(args.scoring_period.removeprefix("CY"))
    outcome_period = f"CY{scoring_year + args.horizon}"
    out_path = args.out or Path(
        f"data/validation/edgar_panel_{args.scoring_period}_{outcome_period}.json"
    )

    def say(message: str) -> None:
        if not args.quiet:
            print(message, flush=True)

    try:
        client = EdgarClient(
            user_agent=settings.edgar_user_agent,
            cache_dir=args.cache_dir,
            requests_per_second=settings.edgar_requests_per_second,
            timeout_seconds=settings.edgar_timeout_seconds,
            offline=args.offline,
        )
    except EdgarConfigError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 2

    cache = ConceptCache(client)
    drops: dict[str, int] = {}

    def drop(reason: str) -> None:
        drops[reason] = drops.get(reason, 0) + 1

    # --- 1. financial metrics at T ----------------------------------------
    say(f"resolving financials for {args.scoring_period} ...")
    metric_values: dict[str, dict[int, float]] = {}
    for spec in concept_mod.METRIC_SPECS:
        values, coverage, _tags = company_values_for_metric(
            spec, cache, period=args.scoring_period, prior_period=f"CY{scoring_year - 1}"
        )
        metric_values[spec.key] = values
        say(f"  {spec.key}: {coverage.resolved} resolved")

    # --- 2. the outcome: revenue CAGR from T to T+n ------------------------
    say(f"resolving revenue for {outcome_period} (the outcome) ...")
    revenue_t = cache.get(concept_mod.REVENUE_TAGS, unit="USD", period=args.scoring_period)
    revenue_tn = cache.get(concept_mod.REVENUE_TAGS, unit="USD", period=outcome_period)

    outcomes: dict[int, float] = {}
    for cik, start in revenue_t.values.items():
        end = revenue_tn.values.get(cik)
        if end is None:
            drop(f"no revenue reported for {outcome_period}")
            continue
        if revenue_t.tag_by_cik.get(cik) != revenue_tn.tag_by_cik.get(cik):
            # Same discipline as the growth metric: a post-606 tag at one end
            # and a legacy tag at the other measures the taxonomy change.
            drop("revenue tag differs between the scoring and outcome periods")
            continue
        if start <= 0 or end <= 0:
            drop("non-positive revenue at one end of the window")
            continue
        outcomes[cik] = (end / start) ** (1.0 / args.horizon) - 1.0

    say(f"  {len(outcomes)} companies have a {args.horizon}-year outcome")

    # --- 3. sector classification -----------------------------------------
    eligible = [
        cik
        for cik in outcomes
        if sum(1 for values in metric_values.values() if cik in values) >= args.min_metrics
    ]
    ranked = sorted(eligible, key=lambda c: (-revenue_t.values.get(c, 0.0), c))
    sample = ranked[: max(0, args.sic_limit)]
    say(f"classifying {len(sample)} of {len(eligible)} eligible companies by SIC ...")

    sector_by_cik: dict[int, str] = {}
    for index, cik in enumerate(sample, start=1):
        try:
            payload = client.submissions(cik)
        except (EdgarFetchError, EdgarOfflineError):
            drop("submissions lookup failed")
            continue
        raw_sic, _ = sic_mod.sic_from_submissions(payload)
        sector = sic_mod.sector_for_sic(raw_sic)
        if sector == sic_mod.UNCLASSIFIED:
            drop("no usable SIC code")
            continue
        sector_by_cik[cik] = sector
        if index % 100 == 0:
            say(f"  classified {index}/{len(sample)}")

    members_by_sector: dict[str, list[int]] = {}
    for cik, sector in sector_by_cik.items():
        members_by_sector.setdefault(sector, []).append(cik)

    # --- 4. sector-level market inputs, computed not guessed ---------------
    sector_market: dict[str, dict] = {}
    for sector, members in members_by_sector.items():
        if len(members) < MIN_SECTOR_PEERS:
            continue
        growths = [
            metric_values["revenue_growth_pct"][c]
            for c in members
            if c in metric_values["revenue_growth_pct"]
        ]
        margins = [
            metric_values["operating_margin_pct"][c]
            for c in members
            if c in metric_values["operating_margin_pct"]
        ]
        total_revenue = sum(revenue_t.values.get(c, 0.0) for c in members)
        sector_market[sector] = {
            "market_growth_pct": round(median(growths), 4) if growths else None,
            "market_size_usd_bn": round(total_revenue / 1e9, 4) if total_revenue else None,
            "industry_operating_margin_pct": round(median(margins), 4) if margins else None,
            "members": len(members),
        }

    # --- 5. score every company through the real pipeline ------------------
    say("scoring companies through the real pipeline ...")
    rows: list[dict] = []
    for cik, sector in sorted(sector_by_cik.items()):
        market = sector_market.get(sector)
        if market is None:
            drop(f"sector below {MIN_SECTOR_PEERS} filers, no market inputs")
            continue

        financial_data = {
            key: values[cik] for key, values in metric_values.items() if cik in values
        }
        peers = [c for c in members_by_sector[sector] if c != cik]
        peers.sort(key=lambda c: -revenue_t.values.get(c, 0.0))
        peers = peers[:MAX_PEERS_PER_COMPANY]
        sector_revenue = sum(revenue_t.values.get(c, 0.0) for c in members_by_sector[sector])

        def share(target: int) -> float | None:
            if not sector_revenue:
                return None
            return round(100.0 * revenue_t.values.get(target, 0.0) / sector_revenue, 6)

        competitors = [
            {
                "competitor_name": f"CIK{peer:010d}",
                "market_share_pct": share(peer),
                "financial_data": {
                    key: values[peer] for key, values in metric_values.items() if peer in values
                },
            }
            for peer in peers
        ]
        company_share = share(cik)
        financial_data = {**financial_data, "market_share_pct": company_share}

        market_data = {
            key: value
            for key, value in market.items()
            if key != "members" and value is not None
        }

        concentration = assess_market_structure(
            company_market_share_pct=company_share,
            competitors=competitors,
            analyst_intensity_override=None,
            settings=settings,
        )
        swot = run_swot_analysis(
            financial_data=financial_data,
            market_data=market_data,
            qualitative_inputs=[],
            competitors=competitors,
            industry=sector,
            concentration=concentration,
            settings=settings,
        )
        matrix = run_attractiveness_matrix(
            market_data=market_data,
            swot=swot,
            competitive_intensity_score=concentration.competitive_intensity_score,
            settings=settings,
        )
        rows.append(
            {
                "label": f"{revenue_t.names.get(cik, f'CIK{cik}')} {args.scoring_period}",
                "cik": cik,
                "sector": sector,
                "quadrant": matrix.quadrant.value,
                "attractiveness": matrix.overall_attractiveness_score,
                "strength": matrix.competitive_strength_score,
                "outcome": round(outcomes[cik], 6),
                # Carried for the single-variable baseline model, which has to
                # run on exactly the same rows to be a fair comparison.
                "revenue_growth_pct_at_T": metric_values["revenue_growth_pct"].get(cik),
                "borderline": matrix.borderline,
            }
        )

    by_quadrant: dict[str, int] = {}
    for row in rows:
        by_quadrant[row["quadrant"]] = by_quadrant.get(row["quadrant"], 0) + 1

    payload = {
        "_provenance": {
            "source": "SEC EDGAR XBRL frames API, data.sec.gov",
            "scoring_period": args.scoring_period,
            "outcome_period": outcome_period,
            "horizon_years": args.horizon,
            "n": len(rows),
            "by_quadrant": by_quadrant,
            "sectors": {
                sector: entry for sector, entry in sorted(sector_market.items())
            },
            "drops": dict(sorted(drops.items(), key=lambda kv: -kv[1])),
            "scoring_method": (
                "Every row is scored through the real pipeline: the SWOT engine "
                "against the median of its own sector peers, HHI-derived competitive "
                "intensity over sector revenue shares, and the GE-McKinsey weighted "
                "sum. No figure here is typed in by hand."
            ),
            "market_inputs": (
                "Market growth is the sector's median revenue growth; market size is "
                "the sum of its filers' revenue; industry margin is the sector's "
                "median operating margin. All computed from this dataset."
            ),
            "LOOK_AHEAD_BIAS": (
                f"Facts for {args.scoring_period} are filed in early "
                f"{scoring_year + 1}, so a score 'as at {scoring_year}' uses "
                "information that was not public until months later. This biases the "
                "result TOWARD the model looking good. Filing-date-aware assembly is "
                "the fix and is scoped as V4, not pretended away."
            ),
            "SHARES_ARE_OF_FILERS_NOT_MARKETS": (
                "Market share and HHI are computed over SEC filers in the SIC sector. "
                "Private and foreign competitors are absent, so concentration is "
                "overstated and every share is an overestimate."
            ),
            "outcome_definition": (
                f"{args.horizon}-year revenue CAGR from {args.scoring_period} to "
                f"{outcome_period}, expressed as a fraction. Both ends must resolve "
                "through the SAME revenue tag or the company is dropped."
            ),
            "fetch_stats": client.stats.to_dict(),
        },
        "outcome_definition": f"{args.horizon}-year revenue CAGR, expressed as a fraction",
        "panel": rows,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))

    say("")
    say(f"Wrote {out_path}")
    say(f"  n = {len(rows)}   {by_quadrant}")
    say(f"  sectors: {len(sector_market)}")
    say("  drops:")
    for reason, count in sorted(drops.items(), key=lambda kv: -kv[1]):
        say(f"    {count:>6}  {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
