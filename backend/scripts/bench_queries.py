#!/usr/bin/env python3
"""Measure the read layer: queries issued and ORM rows built, old path vs new.

    python backend/scripts/bench_queries.py --runs 20 --companies 12

Both paths are exercised against the same seeded database in the same process,
so the comparison is not one machine against another or a warm cache against a
cold one. Queries are counted with a SQLAlchemy ``before_cursor_execute`` hook,
which counts what the database was actually asked to do rather than what the
code looks like it asks for - the whole point being that
``company.swot_analyses[-1]`` does not look like a full table read.

This stays in the repository as a regression guard. A refactor that quietly
reintroduces a lazy collection load will show up here as the query count
going back up.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@contextmanager
def counted(engine):
    """Count statements and rows for everything inside the block."""
    from sqlalchemy import event

    stats = {"queries": 0, "rows": 0}

    def before(conn, cursor, statement, parameters, context, executemany):
        stats["queries"] += 1

    def after(conn, cursor, statement, parameters, context, executemany):
        # SQLite reports rowcount -1 for SELECT, so counting rows means
        # counting what the ORM actually materialised. That is the cost being
        # measured anyway: the expensive part of a collection load is building
        # an object per row and decoding a JSON blob into each one.
        result = getattr(context, "cursor_fetch_strategy", None)
        stats["rows"] += getattr(result, "_rowbuffer_len", 0) or 0

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        yield stats
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20, help="Stored analyses per company")
    parser.add_argument("--companies", type=int, default=12, help="Companies in the timeline")
    args = parser.parse_args()

    import os

    tmp = Path(tempfile.mkdtemp(prefix="ss-bench-")) / "bench.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp}"

    from app.config import get_settings
    from app.db import queries
    from app.db.session import Base, SessionLocal, engine
    from app.models import Company, MarketAttractiveness, SwotAnalysis

    Base.metadata.create_all(bind=engine)
    settings = get_settings()
    entity = "bench-entity"

    # --- seed -------------------------------------------------------------
    company_ids: list[uuid.UUID] = []
    with SessionLocal() as db:
        for index in range(args.companies):
            company = Company(
                name=f"Bench {index}",
                industry="saas",
                financial_data={"gross_margin_pct": 70.0},
                market_data={"market_growth_pct": 12.0},
                feature_scores={},
                qualitative_inputs=[],
                data_source="benchmark fixture",
                entity_key=entity,
                period_label=f"FY20{index:02d}",
            )
            db.add(company)
            db.flush()
            company_ids.append(company.id)
            for run in range(args.runs):
                db.add(
                    SwotAnalysis(
                        company_id=company.id,
                        strengths=[{"factor": f"f{run}", "evidence": "x" * 400}],
                        weaknesses=[],
                        opportunities=[],
                        threats=[],
                        calculation_basis={"trace": ["x" * 200] * 20},
                    )
                )
                db.add(
                    MarketAttractiveness(
                        company_id=company.id,
                        market_growth_score=4.0,
                        market_size_score=4.0,
                        profitability_score=4.0,
                        competitive_intensity_score=3.0,
                        overall_attractiveness_score=3.8,
                        competitive_strength_score=3.4,
                        quadrant="SELECTIVE_INVEST",
                        borderline=False,
                        calculation_basis={"trace": ["x" * 200] * 20},
                    )
                )
        db.commit()

    print(
        f"seeded {args.companies} companies x {args.runs} runs "
        f"= {args.companies * args.runs * 2} result rows\n"
    )

    def report(label: str, stats: dict, seconds: float, rows: int) -> None:
        print(
            f"  {label:<34} {stats['queries']:>4} queries  "
            f"{rows:>6} ORM rows  {seconds * 1000:>7.1f} ms"
        )

    # --- single company: latest SWOT --------------------------------------
    print("Latest result for ONE company")
    target = company_ids[0]

    with SessionLocal() as db:
        company = db.get(Company, target)
        with counted(engine) as stats:
            started = time.perf_counter()
            _ = company.swot_analyses[-1]
            elapsed = time.perf_counter() - started
            materialised = len(company.swot_analyses)
        report("V3  collection[-1]", stats, elapsed, materialised)

    with SessionLocal() as db:
        with counted(engine) as stats:
            started = time.perf_counter()
            _ = queries.latest_swot(db, target)
            elapsed = time.perf_counter() - started
        report("V3.1 latest_swot (LIMIT 1)", stats, elapsed, 1)

    # --- timeline: the N+1 ------------------------------------------------
    print(f"\nTimeline across {args.companies} periods")

    with SessionLocal() as db:
        from sqlalchemy import select

        with counted(engine) as stats:
            started = time.perf_counter()
            companies = list(db.scalars(select(Company).where(Company.entity_key == entity)))
            materialised = 0
            for company in companies:
                materialised += len(company.attractiveness_results)
                _ = company.attractiveness_results[-1] if company.attractiveness_results else None
            elapsed = time.perf_counter() - started
        report("V3  loop + collection[-1]", stats, elapsed, materialised)

    with SessionLocal() as db:
        with counted(engine) as stats:
            started = time.perf_counter()
            companies = queries.companies_for_entity(db, entity)
            latest = queries.latest_for_many(
                db, MarketAttractiveness, [c.id for c in companies]
            )
            elapsed = time.perf_counter() - started
        report("V3.1 latest_for_many (windowed)", stats, elapsed, len(latest))

    # --- the benchmark table cache ----------------------------------------
    print("\nBenchmark table load")
    from app.services import benchmarks as bench
    from app.services import cache

    path = settings.industry_benchmarks_path or str(
        Path(__file__).resolve().parents[2] / "data" / "benchmarks" / "edgar_CY2024.json"
    )
    iterations = 200

    started = time.perf_counter()
    for _ in range(iterations):
        bench.load_benchmark_table(path)
    uncached = time.perf_counter() - started

    cache.invalidate_benchmark_table()
    started = time.perf_counter()
    for _ in range(iterations):
        cache.benchmark_table(path)
    cached = time.perf_counter() - started

    print(f"  V3   parse every call ({iterations}x)    {uncached * 1000:>7.1f} ms")
    print(f"  V3.1 cached on (path, mtime, size)   {cached * 1000:>7.1f} ms")
    if cached > 0:
        print(f"  speedup                              {uncached / cached:>7.1f}x")

    # --- EDGAR fetch concurrency -----------------------------------------
    # Simulated latency rather than live requests: the point is a reproducible
    # number, and it would be rude to hammer a public API to produce one for a
    # README. 150 ms is the middle of what data.sec.gov actually returns.
    # Two latency regimes, because the honest answer depends on which one you
    # are in and the first measurement of this contradicted the justification
    # written above it.
    #
    # Serial wall time per request is (latency + gap), where gap is whatever
    # the limiter still owes after the request returned: max(0, 1/rate -
    # latency). So concurrency only buys anything when LATENCY EXCEEDS the
    # limiter's spacing. At the default 5 req/s that spacing is 200 ms, and
    # data.sec.gov usually answers faster than that - so the default
    # configuration is already limiter-bound and concurrency is worth nothing.
    from app.services.edgar.client import EdgarClient

    urls = [f"https://data.sec.gov/submissions/CIK{i:010d}.json" for i in range(1, 101)]

    def run(latency: float, rate: float, concurrency: int) -> float:
        def transport(_url, _headers, _timeout):
            time.sleep(latency)
            return b'{"data": []}'

        with tempfile.TemporaryDirectory() as cache_dir:
            client = EdgarClient(
                user_agent="Bench bench@example.com",
                cache_dir=cache_dir,
                requests_per_second=rate,
                concurrency=concurrency,
                transport=transport,
            )
            started = time.perf_counter()
            client.get_many(urls)
            return time.perf_counter() - started

    for latency, rate, note in (
        (0.15, 5.0, "limiter-bound: 150 ms latency under a 200 ms gap"),
        (0.60, 5.0, "latency-bound: 600 ms latency over a 200 ms gap"),
    ):
        print(f"\nEDGAR fetch: 100 requests at {rate:g}/s, {latency * 1000:.0f} ms latency")
        print(f"  ({note})")
        baseline = None
        for concurrency in (1, 4, 8):
            elapsed = run(latency, rate, concurrency)
            baseline = baseline or elapsed
            label = "V3  serial" if concurrency == 1 else f"V3.1 concurrency={concurrency}"
            print(
                f"  {label:<34} {elapsed:>6.1f} s   {baseline / elapsed:>4.2f}x   "
                f"{100 / elapsed:>5.2f} req/s outbound"
            )
    print("\n  The outbound rate never exceeds the configured limit in any row above.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
