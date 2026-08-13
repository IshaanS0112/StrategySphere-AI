# Case study data — provenance

## What is in this folder right now

Three **illustrative composites**. They are not real companies, and the figures
in them were not extracted from any filing, database, or published case. They
exist so the pipeline can be run end to end in one click, and so the test suite
has inputs that reliably land in each of the three GE-McKinsey quadrants.

Every one of them carries `ILLUSTRATIVE COMPOSITE` in its `data_source` field,
which the API stores and the UI displays on every downstream result. That is
deliberate: a strategy report built on invented numbers should say so on its
face, not in a footnote nobody reads.

**Do not present output built on these files as analysis of a real market.**

## Replacing them with real data

The two defensible sources for a project like this, in order of preference:

1. **Public company annual reports and 10-K/20-F filings.** The Business,
   Risk Factors, and MD&A sections give you exactly the inputs this engine
   consumes: revenue growth, margins, market position, and management's own
   statement of competitive pressure.
   - US: SEC EDGAR full-text search — <https://www.sec.gov/edgar/search/>
   - India: company investor-relations pages; NSE and BSE both host filed
     annual reports for listed companies.
2. **Published business case studies.** Harvard Business Publishing, Ivey, and
   ICMR sell teaching cases with the competitive and financial data already
   assembled. If you use one, cite the case ID in `data_source`.

**Do not scrape competitor pricing pages.** It is a terms-of-service problem
and, for a portfolio project, an entirely unnecessary one — every quadrant this
tool can produce is reachable from disclosed figures.

## File format

```jsonc
{
  "company":     { /* the CompanyCreate schema: name, industry, data_source,
                      financial_data, market_data, feature_scores,
                      qualitative_inputs */ },
  "competitors": [ /* the CompetitorCreate schema, one object per rival */ ],
  "pricing_scenario": { "cost_base": 0, "target_margin_pct": 0, "margin_basis": "MARGIN" }
}
```

`data_source` is required by the API. A case with no provenance is rejected at
the schema layer rather than quietly accepted.

## Loading a case

```bash
python backend/scripts/load_case_study.py data/case_studies/premium_saas.json \
    --api http://localhost:8000 --run-all
```

`--run-all` walks the full pipeline (SWOT → matrix → pricing → report) and
prints the resulting quadrant and price, which is the fastest way to confirm a
deployment is working.

## Keeping the UI presets in sync

`frontend/src/data/caseStudies.ts` mirrors these files so the dashboard can seed
a case without a round trip to the filesystem. If you edit one, edit the other.
