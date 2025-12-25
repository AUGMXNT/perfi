# PLAN (2025)

This is the current working roadmap for perfi.
For a time-ordered change log, see `docs/IMPLEMENTATION.md`.

## Current baseline (as of 2025-12-25)

- Python packaging: `uv` + `uv.lock` (no Poetry); `requires-python = >=3.11,<3.15`
- CI: GitHub Actions uses `uv sync --frozen --all-groups` + `uv run pytest`; release builds use Python 3.14
- Browser automation: DeBank history ingest uses DeBank Cloud OpenAPI when `DEBANK_KEY` is configured; otherwise Playwright scraping fallback
- Security: critical + high Dependabot alerts cleared for Python + frontend + electron (see `docs/IMPLEMENTATION.md`)

## Near-term priorities

1. Docs refresh pass
   - Make `docs/design/*`, `docs/integrations/*`, `docs/architecture/*` match current code + tests.
   - Preserve historical decision context; mark outdated sections explicitly instead of deleting.
2. Tax-year locking / “freeze submitted years”
   - Clarify desired semantics (what is frozen, when) vs current implementation (`lock_costbasis_lots`).
   - Add a feature-specific implementation doc when ready.
3. Tax years + coverage
   - 2021 migration + lock-down
   - 2022–2025 transaction coverage (GMX, escrow, interest/yield rules)

## Longer-term / ideas

- Daily yield tracking + reporting
- Tracking tax prepayments
- Protocol-specific parsing / plugin system beyond DeBank `name` heuristics
