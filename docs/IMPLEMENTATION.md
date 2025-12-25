# Implementation Log

This is the shared implementation log per `AGENTS.md`. For the 2025 migration roadmap/audit, see `docs/IMPLEMENTATION-2025-update.md`.

## 2025-12-25 — Round 2: uv scaffolding + CI migration

### Done

- Added `uv.lock` and validated `uv sync --frozen --all-groups`
- Migrated GitHub Actions off Poetry:
  - `.github/workflows/python-app.yml` now uses `uv sync --frozen` + `uv run pytest`
  - `.github/workflows/build_releases.yml` now uses `uv sync --frozen` + `uv run pyinstaller`
- Removed/updated remaining Poetry references in the active repo entrypoints:
  - `setup-example.sh` uses `uv run`
  - `electron/src/index.js` spawns `uv run python …` for local dev
  - `frontend/README.md` uses `uv run python perfi/api.py`
  - `bin/cli.py` user messages reference `uv run python …`
  - `perfi/balance/exposure.py` no longer shells out to `poetry run …`
  - `perfi/farming/farm_helper.py` comment updated
- Aligned Python support to `>=3.10,<3.12`:
  - Updated `pyproject.toml` and corresponding `README.md` instructions
  - (Superseded by the Python 3.14 upgrade below)

### Test/validation notes

- `uv sync --frozen --all-groups`
- `uv run pytest --verbose`
- Added a small test-only stub in `tests/conftest.py` to keep the test suite deterministic (no Coingecko network dependency).

### Follow-ups

- Consider replacing/removing unmaintained runtime deps (`delegator.py`, `rootpath`, `sttable`) per the 2025 audit doc.
- (Done) Migrated the DeBank browser scraper to Playwright (see below).

## 2025-12-25 — Python 3.14 upgrade

### Done

- Updated `pyproject.toml` `requires-python` to `>=3.11,<3.15`
- Bumped `lxml` to `>=6.0.2,<7` (required for CPython 3.14 wheels)
- Regenerated lockfile with `uv lock --python 3.14`
- Updated GitHub Actions:
  - `.github/workflows/python-app.yml` runs a Python 3.11 + 3.14 test matrix (no Coingecko network step)
  - `.github/workflows/build_releases.yml` builds with Python 3.14
- Fixed test side-effects: `pytest` no longer rewrites `perfi/constants/assets.py` via `bin/map_assets.py`

### Test/validation notes

- `uv sync --frozen --all-groups --python 3.14`
- `uv run pytest --verbose` (66 passed on Python 3.14.2)

### Local env notes

- `mamba install -n perfi python=3.14 -y` (conda env `perfi` now Python 3.14.2)

### Follow-ups

- Address new/visible warnings on 3.14 (invalid escape sequences, `datetime.utcfromtimestamp()` deprecation, `pkg_resources` deprecation from transitive deps).

## 2025-12-25 — DeBank browser scraper: Selenium-wire -> Playwright

### Done

- Replaced selenium-wire-based DeBank history scraping with Playwright (`perfi/ingest/chain.py`)
- Removed `selenium-wire` / `chromedriver-binary-auto` deps; added `playwright` (`pyproject.toml`, `uv.lock`)

### Notes

- Playwright requires installing browser binaries once (example): `uv run playwright install chromium`

## 2025-12-25 — Security: clear critical Dependabot alerts

### Done

- Python: bumped `h11` (and `httpcore`) to address the Dependabot alert; updated `uv.lock`
- Frontend: upgraded `siwe` to v3 and removed stale webpack-era deps; added npm `overrides` to clear remaining criticals; updated `frontend/package-lock.json`
- Electron: upgraded `electron`, `electron-builder`, and `axios`; upgraded Electron Forge deps to eliminate the `request` chain; updated `electron/package-lock.json`

### Test/validation notes

- `uv run pytest --verbose`
- `pushd frontend && npx vite build && popd`
- `pushd frontend && npm audit` (0 critical)
- `pushd electron && npm audit` (0 critical)

### Notes

- `frontend` still fails `npm run build` due to existing `vue-tsc` type errors; release workflow uses `npx vite build`, which passes.
