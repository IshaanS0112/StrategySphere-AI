# Pushing StrategySphere to GitHub

Written for macOS. The fast path is one command (§3). Everything else here is
for when that command hits a wall — and the wall is almost always
authentication (§5).

---

## 1. Set your git identity first

Do this **before** committing anything. Git stamps every commit with whatever
name and email are configured at the time, and it cannot be changed afterwards
without rewriting history.

```bash
git config --global user.name  "Ishaan Singh"
git config --global user.email "ishu2004.ind@gmail.com"
```

The email must be one that is **verified on your GitHub account**. This is not
cosmetic: if it doesn't match, GitHub attributes your commits to a stranger,
your avatar doesn't appear next to them, and **they never show up on your
contribution graph**. For a placement profile that is the whole point of
pushing.

Check what GitHub knows about you at
<https://github.com/settings/emails>. Confirm what git will use:

```bash
git config --global user.name
git config --global user.email
```

---

## 2. Confirm nothing private is about to be committed

```bash
cd ~/BASE/02-projects/StrategySphere
cat .gitignore
```

`.gitignore` already excludes `.env`, `*.db`, `node_modules/`, `__pycache__/`,
`.pytest_cache/`, `dist/`, and `.venv/`. Nothing sensitive exists in this
project today, but the one rule worth internalising is:

> **Never commit `.env`.** `backend/.env.example` is the file that belongs in
> the repo — it documents the variable names with empty values. `.env` holds
> your actual API key.

If you ever do commit a key by accident, rotating the key is the fix. Deleting
the file in a later commit does **not** remove it from history.

---

## 3. The fast path

```bash
cd ~/BASE/02-projects/StrategySphere
./PUSH_TO_GITHUB.sh
```

The script:

1. refuses to run if your git identity isn't set,
2. runs the test suite and aborts if anything fails,
3. builds **11 logical commits** instead of one "initial commit" blob,
4. creates the GitHub repo, pushes, and adds topics — if GitHub CLI is
   installed and logged in.

To get GitHub CLI:

```bash
brew install gh
gh auth login          # choose GitHub.com → HTTPS → login with a browser
```

If `gh` isn't available the script still builds the commits and prints the two
commands you need to finish by hand. Skip to §4.

---

## 4. The manual path

### 4a. Create an empty repo on GitHub

Go to <https://github.com/new> and set:

| Field | Value |
|---|---|
| Repository name | `strategysphere` |
| Description | Executive decision intelligence: benchmark-scored SWOT, GE-McKinsey market attractiveness matrix, and a cost-plus/competitor-benchmarked pricing engine. |
| Visibility | **Public** (a private repo is invisible to recruiters) |
| Add a README | ❌ **leave unticked** |
| Add .gitignore | ❌ **leave unticked** |
| Choose a licence | ❌ **leave unticked** |

Those three must stay unticked. Ticking any of them puts a commit on the remote
that your local history doesn't share, and your first `git push` is then
rejected with `Updates were rejected because the remote contains work that you
do not have locally`.

### 4b. Commit locally

If you ran `PUSH_TO_GITHUB.sh` the commits already exist — skip to 4c. Otherwise,
the minimum viable version:

```bash
cd ~/BASE/02-projects/StrategySphere
git init -b main
git add .
git commit -m "StrategySphere: SWOT scoring, GE-McKinsey matrix, pricing engine, LLM narration over computed scores"
```

Before pushing, check that only what you expect is tracked:

```bash
git status --porcelain     # expect: nothing
git ls-files | wc -l       # expect: 72
git ls-files | grep -E "__pycache__|\.env$|\.db$|node_modules"   # expect: nothing
```

### 4c. Connect and push

```bash
git remote add origin https://github.com/<your-username>/strategysphere.git
git push -u origin main
```

Replace `<your-username>` with your actual GitHub username. If this asks for a
password, read §5 before typing anything.

---

## 5. Authentication — the part that actually breaks

**GitHub stopped accepting account passwords for git operations in August 2021.**
If a push prompts for "Password for https://…", your GitHub password will be
rejected no matter how many times you retype it. Pick one of these instead.

### Option A — GitHub CLI (easiest)

```bash
brew install gh
gh auth login
```

Choose *GitHub.com* → *HTTPS* → *Yes* (authenticate git) → *Login with a web
browser*. It configures the git credential helper for you; pushes just work
afterwards.

### Option B — Personal access token

1. <https://github.com/settings/personal-access-tokens> → **Generate new token**
   (fine-grained).
2. Set an expiry, choose *Only select repositories* → `strategysphere`, and
   under **Repository permissions** set **Contents: Read and write**.
3. Generate, then **copy the token immediately** — GitHub shows it once.
4. Push. When prompted, your username is your GitHub username and **the
   password is the token**.

To avoid retyping it each push:

```bash
git config --global credential.helper osxkeychain
```

macOS then stores it in Keychain after the first successful push.

### Option C — SSH keys

```bash
ssh-keygen -t ed25519 -C "ishu2004.ind@gmail.com"      # Enter through the prompts
pbcopy < ~/.ssh/id_ed25519.pub                          # public key now on your clipboard
```

Paste it at <https://github.com/settings/ssh/new>, then use the SSH remote:

```bash
git remote set-url origin git@github.com:<your-username>/strategysphere.git
ssh -T git@github.com          # expect: "Hi <username>! You've successfully authenticated"
git push -u origin main
```

---

## 6. Verify the push actually landed

A push that prints no error can still leave you out of sync. Check all four:

```bash
git status                 # "Your branch is up to date with 'origin/main'"
git log --oneline -3       # your latest commits
git ls-remote origin main  # hash here must match your local HEAD
```

```bash
git rev-parse main         # these two hashes
git rev-parse origin/main  # must be identical
```

Then open `https://github.com/<your-username>/strategysphere` and confirm:

- [ ] the README renders, with the results table intact
- [ ] the commit count reads **11**, not 1
- [ ] your avatar appears next to the commits (if not, §1 — wrong email)
- [ ] `backend/` and `frontend/` are browsable; `node_modules/` is absent
- [ ] no `.env` anywhere

> This is the exact check that would have caught the HPC-Vision problem, where
> two local commits were never on GitHub because a 225 MB file silently blocked
> every push.

---

## 7. Make the repo page worth landing on

A recruiter spends about twenty seconds on a repo. Almost all of it is the
top-right **About** panel and the README's first screen.

On the repo page, click the **⚙️ gear** beside *About*:

- **Description** — Executive decision intelligence: benchmark-scored SWOT, GE-McKinsey market attractiveness matrix, and a cost-plus/competitor-benchmarked pricing engine.
- **Topics** — `fastapi` `react` `typescript` `postgresql` `docker` `swot-analysis` `business-intelligence` `strategy-analysis`
- ✅ tick **Releases** and **Packages** off; they're empty and add noise.

Then pin it: your profile → **Customize your pins** → select `strategysphere`.

Optional but cheap: **Settings → General → Features → Issues**, and file three
issues from the V2 list in `docs/architecture.md` (Porter's Five Forces,
multi-period tracking, scenario simulation). A repo with an open roadmap reads
as maintained rather than abandoned.

---

## 8. Pushing changes after the first time

```bash
cd ~/BASE/02-projects/StrategySphere
git add .
git commit -m "fix(pricing): describe what changed and why"
git push
```

Keep commits small and the messages specific. `update` and `changes` tell a
reviewer nothing; `fix(pricing): floor the recommended range at cost base` tells
them you knew what you were doing.

---

## 9. Troubleshooting

| Message | Cause | Fix |
|---|---|---|
| `Support for password authentication was removed` | using an account password | §5 — use gh, a token, or SSH |
| `remote: Repository not found` | typo in the URL, or the repo is private and you're unauthenticated | `git remote -v`, then `git remote set-url origin <correct>` |
| `Updates were rejected because the remote contains work…` | you ticked "Add a README" when creating the repo | `git pull --rebase origin main` then push again |
| `refusing to merge unrelated histories` | same cause as above | `git pull --rebase --allow-unrelated-histories origin main` |
| `src refspec main does not match any` | nothing committed yet, or your branch is `master` | `git log` to check; `git branch -M main` to rename |
| `fatal: not a git repository` | wrong folder | `cd ~/BASE/02-projects/StrategySphere` |
| `file is 225.00 MB; exceeds GitHub's file size limit of 100.00 MB` | a large file is in a commit | remove it, gitignore it, and rewrite that commit — deleting it in a *new* commit does not help |
| Commits show a generic avatar, not yours | `user.email` isn't verified on GitHub | §1, then re-commit; past commits need a history rewrite |
| Committed a secret | | rotate the key immediately; removing the file later does not remove it from history |

---

## 10. Cheat sheet

```bash
# one-time identity
git config --global user.name  "Ishaan Singh"
git config --global user.email "ishu2004.ind@gmail.com"

# push this project
cd ~/BASE/02-projects/StrategySphere
./PUSH_TO_GITHUB.sh

# or by hand, after creating an EMPTY repo at github.com/new
git init -b main && git add . && git commit -m "StrategySphere"
git remote add origin https://github.com/<you>/strategysphere.git
git push -u origin main

# confirm it landed
git rev-parse main && git rev-parse origin/main    # must match
```
