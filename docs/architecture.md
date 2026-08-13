# StrategySphere — architecture

## System shape

```
React dashboard ◄──► FastAPI ──► PostgreSQL
                        │
        ┌───────────────┼──────────────┬───────────────┐
        ▼               ▼              ▼               ▼
  SWOT engine    GE-McKinsey      Pricing        Report generator
        │          matrix          engine       (structured → LLM)
        │               │              │               │
        └──── market_structure ────────┘          Claude API
                    (HHI)                     (narration only)
```

The engines are pure functions over plain dicts. They never touch a database
session, never call out to the network, and never import FastAPI.
`analysis_pipeline.py` is the only module that knows about both the ORM and the
engines. That boundary is what lets the entire engine test suite run on a fresh
clone with nothing installed but pytest.

## Data flow

1. `POST /companies` stores financials, market inputs, feature scores, analyst
   factors, and a **required** `data_source`.
2. `POST /companies/{id}/competitors` adds rivals. Their `financial_data` is
   what upgrades the SWOT benchmark from a static table to a peer median.
3. `POST .../swot-analysis` scores the grid and stores it with a full trace.
4. `POST .../market-attractiveness` reads the **stored** SWOT row — not a fresh
   recompute — and places the company on the matrix.
5. `POST .../pricing-recommendation` blends the anchors.
6. `POST .../generate-strategy-report` freezes a structured context from the
   stored rows, narrates it, validates the citations, and stores both.

Steps 4 and 6 read persisted rows rather than recomputing upstream stages. If
step 4 recomputed the SWOT, a dashboard could show a quadrant that no longer
matched the grid directly above it on the same page.

---

## What's real vs simulated

### Real

- **SWOT scoring.** Metric → benchmark → signed relative deviation → 1-5
  bucket. Reproducible, and the trace for every metric (including the skipped
  ones and the reason) is stored in `calculation_basis`.
- **Peer-median benchmarking.** When at least three competitors report a
  metric, the comparison point is their median. Median rather than mean because
  peer sets are small and one outlier should not move the benchmark.
- **HHI and concentration banding.** Standard sum-of-squared-percentage-shares,
  classified on the US DOJ/FTC 2023 Merger Guidelines bands (unconcentrated
  below 1,000; moderately concentrated 1,000–1,800; highly concentrated above
  1,800).
- **The GE-McKinsey weighted sum and quadrant placement.** Weights validated to
  sum to 1.0 at config load, so the score cannot silently drift off the 1-5
  axis.
- **The pricing arithmetic**, including the margin/markup distinction, the
  value-adjustment clamp, and the cost floor.
- **Citation validation.** A factor name the model returns that is not in the
  structured context is dropped before the response is built.

### Simulated / supplied

- **The shipped case studies are illustrative composites.** Not real companies,
  not extracted from filings. Every one carries that statement in its own
  `data_source`, which is displayed on every downstream result.
- **The built-in industry benchmark table is placeholder round numbers.** It is
  deliberately not attributed to any data provider, because inventing an
  attribution would be worse than admitting the numbers are placeholders.
  Supply competitor financials (peer median) or point
  `INDUSTRY_BENCHMARKS_PATH` at your own sourced table.
- **Analyst qualitative factors are judgements**, carried through untouched and
  tagged `source: analyst_input` so they are never confused with a measurement.
- **No live market data, no competitor-price scraping.** Out of scope on
  purpose: scraping rivals' pricing pages is a terms-of-service problem, and
  every verdict this tool can produce is reachable from disclosed figures.

### Not validated

The attractiveness score has never been checked against real business outcomes.
The honest test would be a retrospective panel — score business units at time T
from their filings, then measure whether the `HARVEST_DIVEST` set actually
underperformed the `INVEST_GROW` set over the following three years. That needs
labelled data this repo does not have.

---

## Where this implementation departs from its own spec

Both deviations are deliberate, both are switchable, and both are pinned by a
test so the claim is checkable.

### 1. `target_margin_pct` is a margin, not a markup

The spec defines the cost-plus anchor as `cost_base × (1 + target_margin_pct)`.
That is a **markup**. On a cost of 100 with a 40% target it returns 140, and the
margin actually realised on that price is `(140 − 100) / 140 = 28.6%` — not the
40% that was asked for. The correct cost-plus price for a target *margin* is
`cost / (1 − m)` = 166.67, which does deliver 40%.

`MarginBasis.MARGIN` is the default and `MarginBasis.MARKUP` is available
per-request. Every result reports `implied_margin_pct`, and the
`margin_basis_note` in the reasoning shows both numbers side by side, so the
distinction is surfaced rather than buried.

### 2. Competitive strength accounts for weaknesses

The spec defines the strength axis as the mean of SWOT strength impact scores.
That formula cannot see weaknesses at all: a company with one outstanding margin
and four structural problems scores as strong.

Implemented as:

```
competitive_strength = base − swot_weakness_penalty × (mean(weakness_impacts) − 3.0)
```

centred on 3.0 so a company with average weaknesses is unaffected. Setting
`SWOT_WEAKNESS_PENALTY=0` reproduces the spec formula exactly whenever at least
one strength was scored, and `test_penalty_zero_reproduces_the_spec_formula_exactly`
asserts it.

### 3. Additions the spec did not ask for

- **`borderline` flag.** A position within 0.15 of a quadrant boundary is
  reported as provisional. 3.51 and 3.49 are not meaningfully different, and
  presenting the first as a confident `INVEST_GROW` is how a model gets a
  committee to make a decision the arithmetic does not support.
- **HHI-derived competitive intensity.** The spec has intensity as a 1-5 input.
  Asking the analyst to type it in makes the matrix a re-display of an opinion.
- **`GET /methodology`.** The parameter set is only checkable if it is visible
  without reading source.
- **A neutral band in SWOT scoring.** Without it every metric always produces a
  factor and the grid fills with noise, which then contaminates the strength
  average feeding the matrix.

---

## Bugs found while building this

**A company with zero strengths and nine weaknesses scored 2.56 and landed in
`SELECTIVE_INVEST`.** Caught by the end-to-end smoke run on the
`commodity_manufacturer` case, not by a unit test — every unit test had at
least one strength in its fixture.

The cause: `mean([])` is undefined, so the empty-strengths case fell back to a
neutral 3.0 base. But two different situations produce `strengths == []` and
they are not alike. *Nothing was evaluated* (no financials supplied) is an
absence of evidence, and neutral is the honest answer. *Everything was evaluated
and none of it was a strength* is evidence — of a company behind its peers on
every axis it reported. Treating the second as neutral handed a failing
manufacturer a passing verdict.

Fixed by dropping the base to the floor of the axis when weaknesses exist and
strengths do not, with the reason recorded in `calculation_basis.base_reason`.
Two regression tests pin it, including one that asserts the case now reaches
`HARVEST_DIVEST`.

**Timestamp ties made "latest result" arbitrary.** Every lookup in the pipeline
uses `company.swot_analyses[-1]`, ordered by `generated_at`. With
`server_default=func.now()`, SQLite's `CURRENT_TIMESTAMP` has one-second
resolution — two analyses run in the same second tie, and the "latest" row
becomes whichever the database felt like returning. Fixed with a client-side
`utc_now()` default at microsecond precision; the server default is retained for
rows inserted outside the ORM.

**Feature-score comparison across disjoint key sets.** The first version of the
value adjustment compared the company's mean across *its* features to the
competitors' mean across *theirs*. Comparing an average over
`{speed, support, uptime}` to one over `{price, brand}` is meaningless and
produced a confident price premium out of nothing. Now only shared feature names
are scored, and the dropped ones are listed in the result.

**Unbounded value adjustment.** `1 + k·delta` with a 4-point feature gap and a
k of 0.5 returns a 3x price. Clamped to ±30% by default, with `clamped: true`
recorded when the cap fires.

---

## Deliberate limitations

- **`create_all` at startup, no Alembic.** Adequate while the schema is
  append-only for V1; the correct answer the moment a column needs to change
  shape.
- **No authentication.** Single-user analysis tool. Anything multi-tenant needs
  auth and a tenant column on every table before it leaves a laptop.
- **Latest-result semantics.** `GET` returns the most recent run. There is no
  history browser, though every run is retained.
- **Regulatory outlook is a three-valued analyst input.** It could be derived
  from something, but not from anything this project has access to.
- **No Porter's Five Forces and no scenario simulation.** Scoped out for V1 and
  listed here so the omission is a decision rather than a gap.

---

## Testing

137 tests. The engine tests use no database, no network, and no model.

- `test_swot_engine.py` — deviation signs (including lower-is-better and
  negative benchmarks), impact-bucket boundaries, the neutral band on both
  sides, peer-median vs industry-table selection, analyst-input rejection,
  determinism.
- `test_market_structure.py` — hand-computed HHI, the DOJ/FTC band edges,
  scale-invariance of the price-dispersion CV, every intensity fallback path.
- `test_attractiveness_matrix.py` — all-max gives exactly 5.0 and all-min
  exactly 1.0 (which only holds if the weights sum to 1), quadrant boundaries
  including the strict-inequality edges, the spec-equivalence proof, the
  zero-strengths regression, weight validation at config load.
- `test_pricing_engine.py` — margin vs markup arithmetic pinned numerically,
  the shared-feature intersection, the clamp, the cost floor, confidence
  downgrades.
- `test_report_generator.py` — context completeness, citation dropping, code
  fences, and every fallback path including a monkeypatched exploding client.
- `test_api.py` — the HTTP contract end to end against SQLite, including the
  stage-ordering 409s and input validation rejections.
