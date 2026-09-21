#!/usr/bin/env python3
"""Regenerate the EDGAR fixture files.

    python backend/tests/fixtures/edgar/make_fixtures.py

These files are **hand-constructed to the recorded shape of real data.sec.gov
responses**, not copies of real SEC data. That distinction matters and is the
reason this generator is committed next to them:

* A real frames response for a common concept is several megabytes and roughly
  seven thousand rows. Committing one would add tens of megabytes to a repo for
  a test that needs sixty companies.
* Every edge case the builder has to handle — a company on the legacy revenue
  tag, a company whose tag changes between periods, a negative denominator, a
  sector one company short of the minimum — has to be *present* for the
  drop-and-count paths to be tested. Waiting for them to turn up in a real
  sample is not testing, it is hoping.

The field names, nesting and types are taken from the live API. Nothing in the
test suite ever opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 60 companies laid out so every branch in the builder is reachable:
#   1000-1024  post-606 revenue tag, full financials          (25)
#   1025-1039  legacy Revenues tag, full financials           (15)
#   1040-1044  revenue but no gross profit                    (5)
#   1045-1047  gross profit but no revenue at all             (3)
#   1048-1049  zero / negative revenue -> non-positive denominator (2)
#   1050-1052  revenue tag differs between CY2023 and CY2024  (3)
#   1053-1055  present in CY2024 only -> no prior period      (3)
#   1056-1059  negative book equity -> debt_to_equity dropped (4)
POST_606 = "RevenueFromContractWithCustomerExcludingAssessedTax"
LEGACY = "Revenues"

SECTORS = {
    # 7372 prepackaged software -> saas, 5331 variety stores -> retail,
    # 3714 motor vehicle parts -> manufacturing, 6022 state banks -> financials
    "saas": (7372, range(1000, 1012)),
    "retail": (5331, range(1012, 1024)),
    "manufacturing": (3714, range(1024, 1036)),
    "financials": (6022, range(1036, 1040)),   # deliberately short of min n
}


def row(cik: int, value: float, end: str = "2024-12-31", fy: int = 2024) -> dict:
    return {
        "accn": f"0000{cik}-{fy}-000001",
        "cik": cik,
        "entityName": f"FIXTURE COMPANY {cik}",
        "loc": "US-CA",
        "start": f"{fy}-01-01",
        "end": end,
        "val": value,
        "fy": fy,
        "fp": "FY",
        "form": "10-K",
        "filed": f"{fy + 1}-02-14",
        "frame": f"CY{fy}",
    }


def frame(concept: str, period: str, rows: list[dict]) -> dict:
    return {
        "taxonomy": "us-gaap",
        "tag": concept,
        "ccp": f"{period}I",
        "uom": "USD",
        "label": concept,
        "description": f"Fixture frame for {concept}",
        "pts": len(rows),
        "data": rows,
    }


def build() -> dict[str, dict]:
    files: dict[str, dict] = {}

    revenue_2024_606: list[dict] = []
    revenue_2024_legacy: list[dict] = []
    revenue_2023_606: list[dict] = []
    revenue_2023_legacy: list[dict] = []
    gross_profit: list[dict] = []
    operating_income: list[dict] = []
    net_income: list[dict] = []
    assets: list[dict] = []
    liabilities: list[dict] = []
    equity: list[dict] = []
    rnd: list[dict] = []

    for cik in range(1000, 1060):
        index = cik - 1000
        base_revenue = 1_000_000.0 * (index + 1)
        # Margin varies by sector block so sector medians differ from each other
        # and from the all-filer median - a test that cannot tell them apart
        # cannot prove the sector logic works.
        if cik < 1012:
            margin = 0.70 + (index % 5) * 0.01        # saas: ~70-74%
        elif cik < 1024:
            margin = 0.30 + (index % 5) * 0.01        # retail: ~30-34%
        elif cik < 1036:
            margin = 0.38 + (index % 5) * 0.01        # manufacturing: ~38-42%
        else:
            margin = 0.50 + (index % 5) * 0.01

        if cik in (1045, 1046, 1047):
            gross_profit.append(row(cik, base_revenue * margin))
            continue

        if cik == 1048:
            revenue_2024_606.append(row(cik, 0.0))
            gross_profit.append(row(cik, 100.0))
            continue
        if cik == 1049:
            revenue_2024_606.append(row(cik, -50_000.0))
            gross_profit.append(row(cik, 100.0))
            continue

        if cik in (1050, 1051, 1052):
            # Tag changes between periods: post-606 in 2024, legacy in 2023.
            revenue_2024_606.append(row(cik, base_revenue))
            revenue_2023_legacy.append(row(cik, base_revenue * 0.9, "2023-12-31", 2023))
        elif cik in (1053, 1054, 1055):
            revenue_2024_606.append(row(cik, base_revenue))   # no 2023 row at all
        elif cik < 1025:
            revenue_2024_606.append(row(cik, base_revenue))
            revenue_2023_606.append(row(cik, base_revenue * 0.9, "2023-12-31", 2023))
        else:
            revenue_2024_legacy.append(row(cik, base_revenue))
            revenue_2023_legacy.append(row(cik, base_revenue * 0.95, "2023-12-31", 2023))

        if cik not in (1040, 1041, 1042, 1043, 1044):
            gross_profit.append(row(cik, base_revenue * margin))
        operating_income.append(row(cik, base_revenue * margin * 0.3))
        net_income.append(row(cik, base_revenue * margin * 0.2))
        assets.append(row(cik, base_revenue * 2.0))
        liabilities.append(row(cik, base_revenue * 1.0))
        equity.append(
            row(cik, -base_revenue * 0.2 if cik >= 1056 else base_revenue * 1.0)
        )
        if index % 3 == 0:
            rnd.append(row(cik, base_revenue * 0.12))

    files["frames-RevenueFromContractWithCustomerExcludingAssessedTax-CY2024"] = frame(
        POST_606, "CY2024", revenue_2024_606
    )
    files["frames-Revenues-CY2024"] = frame(LEGACY, "CY2024", revenue_2024_legacy)
    files["frames-RevenueFromContractWithCustomerExcludingAssessedTax-CY2023"] = frame(
        POST_606, "CY2023", revenue_2023_606
    )
    files["frames-Revenues-CY2023"] = frame(LEGACY, "CY2023", revenue_2023_legacy)
    files["frames-SalesRevenueNet-CY2024"] = frame("SalesRevenueNet", "CY2024", [])
    files["frames-SalesRevenueNet-CY2023"] = frame("SalesRevenueNet", "CY2023", [])
    files["frames-GrossProfit-CY2024"] = frame("GrossProfit", "CY2024", gross_profit)
    files["frames-OperatingIncomeLoss-CY2024"] = frame(
        "OperatingIncomeLoss", "CY2024", operating_income
    )
    files["frames-NetIncomeLoss-CY2024"] = frame("NetIncomeLoss", "CY2024", net_income)
    # Balance-sheet concepts are INSTANTANEOUS and live under CY2024Q4I, not
    # CY2024. Filing them here under the duration key would make the fixtures
    # disagree with the live API in exactly the way that cost the first real
    # build two whole metrics.
    files["frames-Assets-CY2024Q4I"] = frame("Assets", "CY2024Q4I", assets)
    files["frames-Liabilities-CY2024Q4I"] = frame("Liabilities", "CY2024Q4I", liabilities)
    files["frames-StockholdersEquity-CY2024Q4I"] = frame(
        "StockholdersEquity", "CY2024Q4I", equity
    )
    files[
        "frames-StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest-CY2024Q4I"
    ] = frame(
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "CY2024Q4I",
        [],
    )
    files["frames-ResearchAndDevelopmentExpense-CY2024"] = frame(
        "ResearchAndDevelopmentExpense", "CY2024", rnd
    )

    sic_by_cik: dict[int, tuple[int, str]] = {}
    for sector, (code, ciks) in SECTORS.items():
        for cik in ciks:
            sic_by_cik[cik] = (code, sector)

    submissions: dict[str, dict] = {}
    for cik in range(1000, 1060):
        code, _sector = sic_by_cik.get(cik, (0, ""))
        submissions[f"submissions-CIK{cik:010d}"] = {
            "cik": str(cik),
            "entityType": "operating",
            "sic": str(code) if code else "",
            "sicDescription": "Fixture industry" if code else "",
            "name": f"FIXTURE COMPANY {cik}",
            "tickers": [f"FIX{cik}"],
            "exchanges": ["Nasdaq"],
            "filings": {"recent": {"form": ["10-K"], "accessionNumber": [f"0000{cik}-24-000001"]}},
        }
    files.update(submissions)
    return files


def main() -> None:
    for name, payload in build().items():
        (HERE / f"{name}.json").write_text(json.dumps(payload, indent=1))
    print(f"wrote fixtures to {HERE}")


if __name__ == "__main__":
    main()
