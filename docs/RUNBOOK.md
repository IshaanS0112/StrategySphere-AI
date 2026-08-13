# StrategySphere — how to run it

Written for macOS. Every command below has been executed against this exact
codebase; the expected output is shown so you can tell a working step from a
broken one without guessing.

---

## 0. Where the project lives

```
/Users/ishaansingh/BASE/02-projects/StrategySphere
```

Open **Terminal** (Cmd+Space → type `Terminal` → Enter) and go there:

```bash
cd ~/BASE/02-projects/StrategySphere
ls
```

You should see:

```
PUSH_TO_GITHUB.sh  README.md  backend  data  docker-compose.yml  docs  frontend
```

If `ls` shows something else, you are in the wrong folder — `pwd` tells you where
you actually are.

---

## 1. Check what you have installed

```bash
python3 --version     # need 3.10 or newer
node --version        # need 18 or newer
docker --version      # optional, but it is the easy path
```

**Python 3.10 is a hard floor**, not a preference. The SQLAlchemy models use
`Mapped[str | None]`, which is evaluated at runtime and does not exist before
3.10. macOS ships an older Python on some versions — if `python3 --version`
says 3.9 or lower, either use the Docker path in §2 or install a newer Python
(`brew install python@3.12`).

---

## 2. The easy path — Docker (one command)

This runs Postgres, the API, and the dashboard together. Docker Desktop must be
**running** (whale icon in the menu bar), not just installed.

```bash
cd ~/BASE/02-projects/StrategySphere
docker compose up --build
```

First build takes a few minutes. You are ready when the log settles on:

```
backend-1   | INFO:     Application startup complete.
backend-1   | INFO:     Uvicorn running on http://0.0.0.0:8000
```

Then open **<http://localhost:5173>** in your browser.

To stop: `Ctrl+C` in that terminal. To wipe the database and start clean:

```bash
docker compose down -v
```

**Skip to §5 to verify it works.**

---

## 3. The manual path — two terminals, no Docker

Use this when you want `--reload` while editing, or when Docker is not running.
It uses SQLite instead of Postgres, so there is nothing else to install.

### Terminal 1 — backend

```bash
cd ~/BASE/02-projects/StrategySphere/backend

# Create an isolated environment (once). Without this, modern macOS Python
# refuses to install packages with an "externally-managed-environment" error.
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements-dev.txt

# Run it. SQLite means no database server to start.
DATABASE_URL="sqlite:///./local.db" uvicorn app.main:app --reload
```

Expected tail of the output:

```
INFO: Industry benchmark table: ILLUSTRATIVE PLACEHOLDER BANDS - not sourced industry data...
INFO: No ANTHROPIC_API_KEY configured. Strategy reports will use the deterministic template fallback...
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Both INFO lines are correct behaviour, not warnings you need to fix. Leave this
terminal running.

> Every new terminal session needs `source .venv/bin/activate` again. If a
> command fails with `ModuleNotFoundError: fastapi`, you forgot it.

### Terminal 2 — frontend

Open a **second** terminal window (Cmd+N in Terminal):

```bash
cd ~/BASE/02-projects/StrategySphere/frontend
npm install          # once, takes ~35 seconds
npm run dev
```

Expected:

```
VITE v6.4.3  ready in 84 ms
➜  Local:   http://localhost:5173/
```

Open **<http://localhost:5173>**.

The dev server proxies `/api` to `http://localhost:8000`, so the browser only
ever talks to one origin and CORS never comes up. That means **the backend in
Terminal 1 must be running** or every page will show a fetch error.

---

## 4. Optional — turn on the AI narrative

The project works completely without an API key; reports come out through the
deterministic template instead. To get the LLM-written version:

```bash
cd ~/BASE/02-projects/StrategySphere/backend
cp .env.example .env
```

Open `.env`, put your key on the `ANTHROPIC_API_KEY=` line, save, and restart
the backend. For Docker, export it before `docker compose up` instead:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
docker compose up --build
```

You can tell which path ran from the badge at the top of the report:
`LLM narrated` vs `template fallback`.

---

## 5. Verifying it actually works

Five checks, in order. Each one isolates a different layer, so the first one
that fails tells you where the problem is.

### Check 1 — the test suite (no server needed)

```bash
cd ~/BASE/02-projects/StrategySphere/backend
source .venv/bin/activate        # skip if using Docker only
pytest
```

**Expected: `137 passed`.** This proves the scoring engines are correct without
a database, a network connection, or an API key. If this passes and nothing
else does, your problem is configuration, not code.

### Check 2 — the API is up

```bash
curl http://localhost:8000/health
```

**Expected:** `{"status":"ok"}`

Nothing back, or `Connection refused` → the backend is not running. Go back to
§2 or §3 Terminal 1.

### Check 3 — the engines are exposed and honest

```bash
curl http://localhost:8000/methodology
```

**Expected:** JSON containing the weights actually in force —
`"market_growth": 0.3`, `"quadrant_thresholds": {"high": 3.5, "low": 2.5, ...}`,
and a `benchmark_provenance` string saying the shipped bands are placeholders.

This endpoint exists so the claim "the scores are computed, not generated" is
checkable without reading source. It is also the single best thing to show an
interviewer.

### Check 4 — the whole pipeline, one command

```bash
cd ~/BASE/02-projects/StrategySphere
python3 backend/scripts/load_case_study.py \
    data/case_studies/premium_saas.json \
    --api http://localhost:8000 --run-all
```

**Expected, exactly:**

```
Created company Northwind Analytics (illustrative) (…)
  + competitor Meridian Data
  + competitor Corvus Insights
  + competitor Halcyon BI
  + competitor Tessera Cloud

SWOT: 9S / 1W / 2O / 1T
Matrix: attractiveness 3.8, strength 3.6667 -> INVEST_GROW
Pricing: 1002.1065 / 1113.4517 / 1224.7969 (implied margin 56.8908%, confidence HIGH)
Report: narrated by template_fallback
```

Those numbers are deterministic. If yours differ, something is genuinely wrong —
that is the point of quoting them here.

Run the other two cases to confirm all three quadrants are reachable:

```bash
python3 backend/scripts/load_case_study.py data/case_studies/contested_retail.json --api http://localhost:8000 --run-all
python3 backend/scripts/load_case_study.py data/case_studies/commodity_manufacturer.json --api http://localhost:8000 --run-all
```

**Expected:** `SELECTIVE_INVEST (BORDERLINE)` and `HARVEST_DIVEST` respectively.

### Check 5 — the dashboard

Open <http://localhost:5173>. You should see the three case cards, and any
company loaded in Check 4 listed below them.

Click a company and walk the four stages top to bottom:

1. **Run SWOT** → the grid fills. Each factor shows an impact bar and an
   evidence line naming the benchmark it was scored against. Badges read
   `computed` or `analyst`.
2. **Run matrix** → the plotted point appears at its real coordinates on the
   2.5 / 3.5 grid, not in the middle of a labelled box.
3. **Run pricing** → price, range, implied margin, and an expandable
   **Derivation** showing every intermediate step.
4. **Generate report** → the narrative, then click
   **"Show structured context (pre-LLM)"**. Every number in the prose above is
   in that JSON. That is the demo.

The **Run matrix** button is disabled until SWOT has run, and **Generate
report** until the matrix has. That is intentional — a 409 rather than a silent
recompute, so the quadrant on screen always matches the grid above it.

---

## 6. When something breaks

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: fastapi` | venv not activated in this terminal | `source .venv/bin/activate` |
| `error: externally-managed-environment` on pip | installing into system Python | create the venv (§3) |
| `TypeError: unsupported operand type(s) for \|` | Python 3.9 or older | `brew install python@3.12`, recreate the venv |
| `Address already in use` on 8000 | an old backend is still running | `lsof -ti:8000 \| xargs kill` |
| `Address already in use` on 5173 | an old vite is still running | `lsof -ti:5173 \| xargs kill` |
| Dashboard loads, every action errors | backend not running | check `curl localhost:8000/health` |
| `Cannot connect to the Docker daemon` | Docker Desktop not started | open Docker Desktop, wait for the whale |
| `409 Run the SWOT analysis first` | stages run out of order | that is the guard working — run stage 1 first |
| Report says `template fallback` | no API key | expected; see §4 if you want the LLM version |
| Want a clean slate (manual path) | | `rm backend/local.db` and restart |
| Want a clean slate (Docker) | | `docker compose down -v` |

---

## 7. Cheat sheet

```bash
# Docker, everything
cd ~/BASE/02-projects/StrategySphere && docker compose up --build

# Manual, terminal 1
cd ~/BASE/02-projects/StrategySphere/backend && source .venv/bin/activate
DATABASE_URL="sqlite:///./local.db" uvicorn app.main:app --reload

# Manual, terminal 2
cd ~/BASE/02-projects/StrategySphere/frontend && npm run dev

# Prove it works
cd ~/BASE/02-projects/StrategySphere/backend && pytest          # 137 passed
curl http://localhost:8000/health                                # {"status":"ok"}
cd ~/BASE/02-projects/StrategySphere && python3 backend/scripts/load_case_study.py \
    data/case_studies/premium_saas.json --api http://localhost:8000 --run-all
```

| URL | What it is |
|---|---|
| <http://localhost:5173> | Dashboard |
| <http://localhost:8000/docs> | Interactive API docs (Swagger) |
| <http://localhost:8000/methodology> | Every weight and threshold in force |
| <http://localhost:8000/health> | Liveness check |
