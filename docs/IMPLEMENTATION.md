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

### Test/validation notes

- `uv sync --frozen --all-groups`
- `uv run pytest --verbose`
- Added a small test-only stub in `tests/conftest.py` to keep the test suite deterministic (no Coingecko network dependency).

### Follow-ups

- Consider replacing/removing unmaintained runtime deps (`delegator.py`, `rootpath`, `sttable`) per the 2025 audit doc.
- Decide whether to keep Selenium-wire or migrate the DeBank browser scraper to Playwright.

