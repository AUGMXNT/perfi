# IMPLEMENTATION 2025 Update (Poetry -> uv, dependency audit)

This document is a **roadmap + audit** for bringing this repo back to a maintainable “working” state in 2025.
It started as a checklist of what needed doing next; “Round 2” work items below are now being executed and checked off.

## Goals

1. **Standardize on `uv`** for local dev + CI (no Poetry dependency).
2. **Make installs reproducible** (lockfile + “frozen” CI installs).
3. **Audit dependencies** for maintenance risk and modern compatibility.
4. **De-risk browser automation** (historically problematic Selenium stack).

## Status (Round 2 progress)

- ✅ Added `uv.lock` and switched CI to `uv sync --frozen` + `uv run`
- ✅ Removed Poetry references from CI and core scripts/docs (electron dev spawn, setup script, CLI messages, frontend README)
- ✅ Aligned supported Python to `>=3.11,<3.15` (CI runs 3.11 + 3.14)

## Current State (what we found)

### Packaging & environment

- `pyproject.toml` is already **PEP 621** (`[project]` + `[dependency-groups]`) and uses **`hatchling`** as build backend.
- `pyproject.toml` also already has **`[tool.uv.sources]`** for `pyinstaller` (git source), which Poetry will ignore.
- ✅ `uv.lock` is now present, enabling reproducible installs with `uv sync --frozen`.
- ✅ Poetry is no longer required for CI or the primary developer workflows in this repo.

### Python version support (important)

`pyproject.toml` now declares:

- `requires-python = ">=3.11,<3.15"`

Practical implication:
- The project targets Python **3.11–3.14**
- ✅ CI runs tests on Python 3.11 + 3.14

### CI/workflows are now `uv`-only

✅ CI/workflows are now `uv`-only:

- `.github/workflows/python-app.yml` uses `uv sync --frozen --all-groups` and `uv run pytest`.
- `.github/workflows/build_releases.yml` uses `uv sync --frozen --all-groups` and `uv run pyinstaller` (Python 3.14).

### Where Poetry used to be referenced (now removed)

These were the main “actionable” Poetry references during the migration:

- ✅ `.github/workflows/python-app.yml`
- ✅ `.github/workflows/build_releases.yml`
- ✅ `electron/src/index.js` (local dev spawn now uses `uv run python …`)
- ✅ `setup-example.sh`
- ✅ `bin/cli.py` (user messages now reference `uv run …`)
- ✅ `perfi/balance/exposure.py` (no longer shells out to `poetry run …`)
- ✅ `frontend/README.md`

## Dependency Audit (Python)

### “Works today” vs “maintainable”

`uv` can resolve the dependency set on modern Python, but the current constraints have some **high maintenance risk** items:

#### 1) Unmaintained / long-stale packages (recommend replacing)

Evidence below is from PyPI “last upload” timestamps.

| Package | Used? | Last PyPI release | Risk | Recommendation |
|---|---:|---:|---|---|
| `delegator.py` | Yes (`perfi/balance/exposure.py`, `perfi/farming/farm_helper.py`) | 2018-09-17 | Abandoned | Replace with `subprocess.run` / `asyncio.create_subprocess_exec` / `anyio.run_process` |
| `rootpath` | Yes (`perfi/constants/paths.py`) | 2019-03-10 | Abandoned | Replace with `pathlib.Path(__file__).resolve()` patterns or `importlib.resources` |
| `sttable` | Tests (`tests/integration/test_imports_from_exchanges.py`) | 2019-11-23 | Abandoned | Replace with a small local parser or a maintained table parser |

#### 2) Selenium stack risk (recommend re-evaluating)

| Package | Used? | Last PyPI release | Notes |
|---|---:|---:|---|
| `selenium-wire` | Yes (`perfi/ingest/chain.py`) | 2022-10-15 | Appears unmaintained; also pins older transitive deps (e.g. `blinker==1.7.0`) |
| `chromedriver-binary-auto` | Yes (via `import chromedriver_binary`) | 2023-07-25 | Driver-management fragility; may not keep pace with Chrome/Selenium changes |

#### 3) “Transitive pins” increasing upgrade friction

`pyproject.toml` lists several packages that are commonly transitive dependencies (examples: `httpcore`, `h11`, `anyio`, `starlette`, `click`, `asttokens`, `executing`, `blinker`).

This is not inherently wrong, but it tends to:
- increase the chance of resolver conflicts,
- make upgrades harder (more pins to coordinate),
- lock you into old transitive versions (e.g. `blinker==1.7.0` due to selenium-wire).

**Follow-up task:** Decide which of these can be removed from direct dependencies safely.

#### 4) Dev/test tooling included as runtime dependencies

`codecov` is in `[project.dependencies]` but is typically CI-only.
If not imported at runtime, move it to a dev/test group or remove and use a GitHub Action instead.

### Python version decision (resolved)

- Supported Python range is now:

- `requires-python = ">=3.11,<3.15"` (Python 3.11–3.14)
- ✅ `uv sync --frozen --all-groups --python 3.14` + `pytest` pass on Python 3.14.2
- ⚠️ `selenium-wire` still appears unmaintained and remains a long-term risk

Note: Python 3.14 required bumping `lxml` to `>=6.0.2` to avoid source builds (no `cp314` wheels in `lxml<6`).

## Browser Automation: Selenium -> Playwright / Stagehand / Vibium

### What Selenium is doing today

Only one major usage was found:

- `perfi/ingest/chain.py` uses `selenium-wire` to open `https://debank.com/profile/{address}/history`, repeatedly click “Load More”, and capture XHR responses from `https://api.debank.com/history/list`.

This exists because DeBank’s free OpenAPI was discontinued (see the in-file comment), and the paid API requires `DEBANK_KEY`.

### Options (tradeoffs)

1. **Keep Selenium-wire (short term)**
   - Pros: no rewrite
   - Cons: unmaintained package, fragile driver story, pins old deps, Python-version constraints

2. **Switch to Playwright (recommended if browser scraping remains needed)**
   - Pros: actively maintained; better headless reliability; built-in network capture; avoids chromedriver management
   - Cons: requires installing browser binaries (`playwright install`); some refactor effort

3. **Stagehand**
   - Stagehand (Python SDK) is actively updated, but it pulls in **LLM + Browserbase** dependencies (`openai`, `anthropic`, `browserbase`, etc).
   - Likely overkill unless we explicitly want AI-driven browsing and are OK with that dependency surface.

4. **Vibium**
   - Exists on PyPI but appears extremely early-stage (`0.0.1`). Risky as a foundation dependency right now.

### Recommendation for Round 2

- If we still need the DeBank “browser scrape fallback”, implement it with **Playwright** (keep the logic the same: click “Load More”, capture responses).
- If we can accept requiring `DEBANK_KEY`, consider **removing browser scraping entirely** and treating DeBank as a configured integration.

## Proposed Round 2 Execution Plan (actual changes)

### A) Standardize on `uv` (remove Poetry)

- Add `uv.lock` and commit it.
- Update CI to use:
  - `uv sync --frozen` (or equivalent) instead of ad-hoc installs.
  - `uv run pytest` instead of `poetry run pytest`.
- Update `electron/src/index.js` dev spawn to use `uv run python …` (or document a non-`uv` fallback if desired).
- Update scripts/docs:
  - `setup-example.sh`, `frontend/README.md`, `bin/cli.py` messages, any other user-facing Poetry strings.

### B) Fix Python version policy

- ✅ Set supported Python range to `>=3.11,<3.15` (Python 3.11–3.14).
- Update:
  - `pyproject.toml` `requires-python`
  - `.github/workflows/python-app.yml` Python versions (matrix)
  - `.github/workflows/build_releases.yml` Python version
  - `README.md` Python environment snippets

### C) Dependency modernization (incremental)

Recommended order:

1. Remove/replace unmaintained packages:
   - `delegator.py`, `rootpath`, `sttable`
2. Move CI-only tooling out of runtime deps:
   - `codecov`
3. Reduce direct transitive pins where safe:
   - start with `httpcore`, `h11`, `anyio`, `click`, `asttokens`, `executing`, `blinker`, `starlette` (evaluate carefully)
4. Revisit `pyinstaller` sourcing:
   - stop pinning to moving git branch (`rev="develop"`); pin to a commit hash or a released version

### D) Selenium replacement decision

- Choose one:
  - **Playwright-based DeBank browser scraper**, or
  - **Require `DEBANK_KEY`**, remove browser scraping and associated dependencies.

## Notes / Open Questions

- Should the “analytics/plotting” stack (`numpy`, `pandas`, `scipy`, `matplotlib`, `plotly`, `kaleido`) be required for all users, or moved into an optional extra/group?
- Is Python `siwe` needed on the backend? (No backend usage found; frontend does include `siwe` in JS.)
- Should we add a small `Makefile` / `justfile` / `scripts/` entrypoints for common `uv` commands (install, test, run)?
