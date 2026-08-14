# StrategySphere

[![CI](https://github.com/IshaanS0112/StrategySphere-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/IshaanS0112/StrategySphere-AI/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Executive decision intelligence — a scored SWOT engine, a GE-McKinsey market attractiveness matrix, and a cost-plus/competitor-benchmarked pricing model. The AI writes the summary; it does not decide the strategy.**

FastAPI · PostgreSQL · React + TypeScript · Docker

---

## Why I built this

I kept running into the same thing while reading consulting case books: SWOT, competitive positioning, and pricing are taught as *frameworks*, but they get applied as *opinions*. Someone puts "strong brand" in the strengths box and nobody asks what that was measured against.

So I built the version where the boxes are computed. Every strength and weakness in the grid comes from a specific financial metric compared against a specific benchmark — the median of the peer set you supplied, or a configured industry band when there aren't enough peers — and the evidence string tells you exactly which. If a metric sits inside the neutral band, it produces nothing. Four empty quadrants is a valid output.

I also wanted the project to survive one specific question, which is the question I would ask: *is the AI actually doing the analysis, or is your code doing it and the model just describing the result?* Here it's the second, deliberately, and the system is built so you can check rather than take my word for it.

---

## What it does

1. **SWOT scoring** — financial metrics compared against a peer-set median (or an industry band), with the signed relative deviation bucketed into a 1-5 impact score. Market growth, size, and competitive intensity feed opportunities and threats through the same band logic. Analyst-supplied qualitative factors pass through but stay tagged as judgements.
2. **Market structure** — competitive intensity is *derived*, not typed in: the Herfindahl-Hirschman Index over the competitor set, classified against the US DOJ/FTC 2023 Merger Guidelines bands, then nudged by competitor price dispersion.
3. **GE-McKinsey matrix** — the two axes computed from the above, placed against the documented 2.5 / 3.5 thresholds, with a `borderline` flag when the point sits within 0.15 of a boundary.
4. **Pricing** — a cost-plus anchor blended with the competitor benchmark, adjusted for the shared-feature quality gap, clamped, and floored at cost.
5. **Executive report** — every figure above is frozen into a structured JSON context *first*; the LLM then narrates that context under a JSON-only contract, and any factor it cites that isn't in the context is discarded.

---

## The line between computed and narrated

This is the design decision the rest of the project hangs off.

| Stage | Who computes it |
|---|---|
| Strength / weakness factors and their impact scores | Benchmark arithmetic — `swot_engine.py` |
| HHI, concentration band, competitive intensity | `market_structure.py` |
| Attractiveness score, strength score, quadrant | Weighted sum — `attractiveness_matrix.py` |
| Recommended price, range, implied margin | `pricing_engine.py` |
| Readable narrative | LLM — `report_generator.py` |

Every number in a generated report exists in `structured_context` before any model is called. That context is stored in the database, returned by `GET /companies/{id}/strategy-report`, and rendered in the UI behind a **"show structured context (pre-LLM)"** toggle. Any factor name the model cites that isn't in the grid is dropped and counted. If the model call fails, times out, or returns malformed JSON, a template produces the same report from the same numbers.

**With no `ANTHROPIC_API_KEY` configured at all, the system still produces complete strategy reports.**

`GET /methodology` returns every weight and threshold currently in force, so the claim that the scores are computed is checkable without reading the source.

---

## Measured results

The three shipped case files, run end to end (`--run-all`), no API key configured:

| Case | SWOT (S/W/O/T) | Attractiveness | Strength | Quadrant | Price (min/opt/max) | Implied margin |
|---|---|---|---|---|---|---|
| `premium_saas` | 9 / 1 / 2 / 1 | 3.80 | 3.67 | `INVEST_GROW` | 1002.11 / 1113.45 / 1224.80 | 56.9% |
| `contested_retail` | 4 / 3 / 1 / 2 | 2.50 | 2.67 | `SELECTIVE_INVEST` ⚠ borderline | 62.41 / 69.35 / 76.28 | 25.0% |
| `commodity_manufacturer` | 0 / 9 / 0 / 3 | 1.50 | 1.00 | `HARVEST_DIVEST` | 39.00 / 42.10 / 46.31 | 7.4% |

All three quadrants are reachable, and the borderline flag fires on the case built to sit on a boundary. **This is self-consistency against inputs I designed to produce those verdicts — not validation against real business outcomes**, which this repo does not have and does not claim.

Two of those rows show the guard rails doing their job rather than the happy path:

- `premium_saas` returns a **56.9% implied margin against a 45% target**. That is correct, not a bug: rivals price well above this company's cost-plus anchor, so the blended price lands above it. The engine reports the realised margin precisely so the gap is visible.
- `commodity_manufacturer` has its **range floored at the cost base** (39.00) — the raw band bottom was 37.89, below cost — which drops the recommendation to `MEDIUM` confidence with the reason attached.

`pytest`: **137 tests**, no database and no network required for the engine tests.

---

## Scope

**This is an analysis tool over data you supply. It does not ingest live market feeds, does not scrape competitor pricing, and has not been validated against real strategic outcomes.**

The three case files in `data/case_studies/` are **illustrative composites, not real companies** — they exist so the pipeline can be exercised in one click, and every one of them says so in its own `data_source` field, which the UI displays on every downstream result. The built-in industry benchmark table is likewise **placeholder round numbers, not sourced data**; supplying competitor financials so the engine uses a peer-set median is the intended path, and `data/case_studies/SOURCES.md` explains how to swap in real figures from filings.

`docs/architecture.md` has the full "what's real vs simulated" breakdown, the bugs found while building it, and the two places the implementation deliberately departs from my original design note.

---

## Quick start

Requires Docker, or Python 3.10+ and Node 18+.

```bash
git clone https://github.com/IshaanS0112/StrategySphere-AI.git
cd StrategySphere-AI

export ANTHROPIC_API_KEY=sk-...      # optional; without it, reports use the fallback
docker compose up --build
```

Dashboard on <http://localhost:5173>, API docs on <http://localhost:8000/docs>.

Load a case and run the whole pipeline from the command line:

```bash
python backend/scripts/load_case_study.py data/case_studies/premium_saas.json \
    --api http://localhost:8000 --run-all
```

### Running the backend without Docker

```bash
cd backend
pip install -r requirements-dev.txt
cp .env.example .env          # set DATABASE_URL, or use SQLite for a quick look
pytest                        # 137 tests, no database needed
DATABASE_URL="sqlite:///./local.db" uvicorn app.main:app --reload
```

The models declare JSONB and UUID as dialect *variants*, so the whole app runs on SQLite for local work and on Postgres in deployment.

### Frontend

```bash
cd frontend && npm ci && npm run dev     # proxies /api to :8000
```

### Verifying an install

```bash
cd backend && pytest                              # 137 passed
curl localhost:8000/health                        # {"status":"ok"}
python backend/scripts/load_case_study.py \
    data/case_studies/premium_saas.json --api http://localhost:8000 --run-all
```

The last command should print `attractiveness 3.8, strength 3.6667 -> INVEST_GROW`.
Those figures are deterministic, so a mismatch means something is genuinely wrong.

---

## API

```
GET    /health
GET    /methodology                              Weights and thresholds in force

POST   /companies                                Create company (data_source required)
GET    /companies  ·  GET /companies/{id}  ·  DELETE /companies/{id}
POST   /companies/{id}/competitors  ·  GET /companies/{id}/competitors

POST   /companies/{id}/swot-analysis             Run the SWOT scoring engine
POST   /companies/{id}/market-attractiveness     Run the GE-McKinsey matrix
POST   /companies/{id}/pricing-recommendation    Run the pricing engine
POST   /companies/{id}/generate-strategy-report  Narrate the structured context
```

Each `POST` has a matching `GET` returning the latest stored result. Stage ordering is enforced with `409` rather than a silent recompute — the matrix must be built on the SWOT grid the user actually saw.

---

## Questions this project should survive

**"Is your SWOT a real methodology or LLM brainstorming?"**
Arithmetic. Each factor is a named metric, a benchmark, and a signed relative deviation bucketed into 1-5. The evidence string carries all three, and `calculation_basis` carries the trace for every metric — including the ones that were skipped and why.

**"Walk me through the GE-McKinsey matrix."**
`0.3·growth + 0.2·size + 0.3·profitability + 0.2·(6 − intensity)`, weights validated to sum to 1.0 at config load so the output stays on the 1-5 axis. Competitive strength comes from the scored SWOT grid. Quadrants at 2.5 / 3.5, with anything within 0.15 of a boundary flagged borderline.

**"Where does competitive intensity come from?"**
HHI over the competitor set, classified on DOJ/FTC 2023 bands, adjusted by price dispersion. Two assumptions are stated in the code and in the stored basis: the unnamed residual share is treated as an atomistic fringe (which biases HHI down), and concentration is mapped to rivalry in the antitrust direction.

**"How does the pricing engine derive its number?"**
Cost-plus anchor blended 50/50 with the competitor mean, multiplied by a value-adjustment factor from the shared-feature gap, capped at ±30%, floored at cost. The realised margin is reported alongside, because the blended price frequently does *not* deliver the target margin and hiding that would be the whole problem.

**"Where does the data come from?"**
Whatever you supply, recorded in a required `data_source` field. The shipped cases are labelled composites. No scraping — see `docs/architecture.md`.

**"How would you validate the attractiveness score against real outcomes?"**
I haven't, and the README says so. The honest test is a retrospective: score a set of business units at time T from their filings, then check whether the `HARVEST_DIVEST` set actually underperformed the `INVEST_GROW` set over the following three years. That needs a labelled panel I don't have.

---

## Repository layout

```
backend/app/services/    swot_engine · market_structure · attractiveness_matrix
                         pricing_engine · report_generator · analysis_pipeline
backend/app/{models,schemas,routers,db}/
backend/tests/           137 tests, engine tests need no database
backend/scripts/         load_case_study.py
frontend/src/            SWOTGrid · AttractivenessMatrix · PricingView · ReportView
data/case_studies/       illustrative composites + SOURCES.md
docs/architecture.md     what's real vs simulated, bugs found, design deviations
```

---

## Licence

MIT — see [LICENSE](LICENSE).
