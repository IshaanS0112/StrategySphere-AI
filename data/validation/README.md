# Validation panels

The backtest harness answers one question: **does the quadrant verdict predict
anything?** V1 could not answer it, and said so. V2 makes it computable — but
only once someone supplies a panel, because the answer depends entirely on real
data this repository does not ship.

## What is here

`synthetic_demo_panel.json` — 36 **generated** rows with a deliberate signal
plus gaussian noise. It exists so the harness can be run end to end and so the
tests have something to bite on.

> **Any result computed from it says something about the harness and nothing
> about whether GE-McKinsey predicts business performance.** It is generated
> data with a signal I put there myself. Reporting it as validation would be
> circular.

## Building a real panel

A row is one company, scored at time **T**, with a realised outcome measured at
**T+n**:

```json
{
  "label": "Company plc FY2021",
  "quadrant": "INVEST_GROW",
  "attractiveness": 4.1,
  "strength": 3.8,
  "outcome": 0.164
}
```

The honest procedure, and the order matters:

1. **Pick the scoring date first, and freeze it.** Score every company from
   filings available at T and nothing later. Reading a FY2024 annual report to
   score a company "as at 2021" is look-ahead bias, and it will manufacture a
   result.
2. **Score them through this system.** Load each company with its T-period
   financials and competitor set, run SWOT and the matrix, and record the
   quadrant and both axes.
3. **Measure the outcome at T+n** from a source independent of the scoring
   inputs — 3-year revenue CAGR, total shareholder return, or margin change.
   Whatever you choose, use the same definition for every row.
4. **Aim for n ≥ 30.** Below that the permutation test cannot separate a real
   effect from noise, and a non-significant result tells you about your sample
   size rather than about the framework.

Sources: SEC EDGAR full-text search (<https://www.sec.gov/edgar/search/>) for US
filers; NSE/BSE-hosted annual reports for Indian listed companies.

## Running it

```bash
curl -X POST http://localhost:8000/validation/backtest \
     -H 'Content-Type: application/json' \
     -d @data/validation/synthetic_demo_panel.json
```

Or in Python, against any panel file:

```bash
python backend/scripts/run_validation.py data/validation/synthetic_demo_panel.json
```

## Reading the output

Three numbers, and the third is the one that matters.

| Field | What it means |
|---|---|
| `separation` | mean outcome of `INVEST_GROW` minus mean outcome of `HARVEST_DIVEST` |
| `spearman_rho` | rank correlation between `attractiveness × strength` and the outcome |
| `permutation_p_value` | how often shuffled outcomes produce a separation at least this large |

A separation without a p-value is not evidence. On a panel of twenty companies
across three quadrants, a gap of several percentage points between group means
arises constantly by chance — the permutation test is the only thing standing
between "the framework works" and "I found a pattern in noise".

And even a significant result is association, not causation. The quadrant may
simply be reading the same underlying growth that drives the outcome. A fair
comparison needs a baseline model using revenue growth alone; if the quadrant
does not beat that, it is adding nothing.
