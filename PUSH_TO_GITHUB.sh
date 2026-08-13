#!/usr/bin/env bash
# Initialise StrategySphere as a git repo with a readable commit history and
# push it to GitHub.
#
#   cd ~/BASE/02-projects/StrategySphere
#   ./PUSH_TO_GITHUB.sh
#
# Prereqs: GitHub CLI installed and authenticated (`brew install gh && gh auth login`).
# Without gh, the script still builds the commits and prints the two manual
# commands to finish the push.
#
# Full walkthrough, including auth troubleshooting: docs/GITHUB.md
set -euo pipefail

REMOTE_URL="https://github.com/IshaanS0112/StrategySphere-AI.git"

# --- Guard rails ------------------------------------------------------------

if [ -d .git ]; then
  echo "This folder is already a git repo. Refusing to re-initialise."
  echo "If you meant to start over:  rm -rf .git  (this deletes local history)"
  exit 1
fi

if ! git config user.email > /dev/null 2>&1 || ! git config user.name > /dev/null 2>&1; then
  cat <<'MSG'
Git does not know who you are yet. Set this first, using the SAME email that is
verified on your GitHub account - otherwise your commits are attributed to a
stranger and never appear on your contribution graph:

  git config --global user.name  "Ishaan Singh"
  git config --global user.email "your-github-email@example.com"

Then run this script again.
MSG
  exit 1
fi

echo "Committing as: $(git config user.name) <$(git config user.email)>"
echo

# --- Do not push a broken repo ---------------------------------------------

echo "Running the test suite before committing anything..."
if [ -d backend/.venv ]; then
  (cd backend && ./.venv/bin/python -m pytest -q)
else
  (cd backend && python3 -m pytest -q)
fi
echo

# --- Build a history that reads like the project was built, not dumped ------

git init -q -b main

commit() {
  local message="$1"; shift
  git add "$@"
  git commit -qm "$message"
  echo "  ✓ $message"
}

commit "chore: project scaffold, Docker setup, and tooling config" \
  .gitignore docker-compose.yml \
  backend/Dockerfile backend/requirements.txt backend/requirements-dev.txt \
  backend/pytest.ini backend/.env.example \
  frontend/Dockerfile frontend/nginx.conf frontend/package.json \
  frontend/tsconfig.json frontend/vite.config.ts frontend/tailwind.config.js \
  frontend/postcss.config.js frontend/index.html

commit "feat(db): schema for companies, competitors, and the four analysis stages" \
  backend/app/__init__.py backend/app/config.py backend/app/enums.py \
  backend/app/db/ backend/app/models/

commit "feat(swot): benchmark-scored SWOT engine with peer-median comparison" \
  backend/app/services/__init__.py backend/app/services/benchmarks.py \
  backend/app/services/swot_engine.py

commit "feat(market): HHI-derived competitive intensity on DOJ/FTC bands" \
  backend/app/services/market_structure.py

commit "feat(matrix): GE-McKinsey market attractiveness matrix" \
  backend/app/services/attractiveness_matrix.py

commit "feat(pricing): cost-plus and competitor-benchmarked pricing engine" \
  backend/app/services/pricing_engine.py

commit "feat(report): frozen structured context, constrained LLM narration, template fallback" \
  backend/app/services/report_generator.py

commit "feat(api): FastAPI routers, request validation, and stage-ordering guards" \
  backend/app/services/analysis_pipeline.py backend/app/schemas/ \
  backend/app/routers/ backend/app/main.py

commit "test: 137 tests covering every engine and the HTTP contract" backend/tests/

commit "feat(ui): React dashboard with SWOT grid, matrix plot, pricing, and report views" \
  frontend/src/

commit "docs: README, architecture notes, runbook, and illustrative case studies" .

echo
echo "History built:"
git log --oneline
echo

# --- Push -------------------------------------------------------------------

git remote add origin "$REMOTE_URL"
echo "Remote set to $REMOTE_URL"
echo

if git push -u origin main; then
  echo
  echo "Done -> ${REMOTE_URL%.git}"
  echo
  echo "Now set the About panel on the repo page (gear icon, top right):"
  echo "  Description and topics are in docs/GITHUB.md section 7."
else
  cat <<'MSG'

The commits are all built and the remote is set - only the push failed.
Nothing is lost; fix the cause and re-run just:

    git push -u origin main

Most likely causes:
  * It asked for a password -> GitHub removed password auth in 2021.
    Run `brew install gh && gh auth login`, or use a personal access token.
  * "Updates were rejected" -> the GitHub repo is not empty (you ticked
    "Add a README"). Run: git pull --rebase origin main, then push again.
  * "Repository not found" -> check the URL with `git remote -v`, and that
    you are authenticated as the account that owns it.

Full walkthrough: docs/GITHUB.md
MSG
  exit 1
fi
