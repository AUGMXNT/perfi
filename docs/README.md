# perfi docs

Start here.

## Key docs

- `docs/PLAN.md` — current roadmap / priorities
- `docs/IMPLEMENTATION.md` — shared implementation log (append-only)
- `docs/IMPLEMENTATION-2025-update.md` — 2025 audit + migration checklist

## Architecture

- `docs/architecture/GUI-PACKAGING.md` — Vue/FastAPI/Electron/PyInstaller + CI build pipeline

## Integrations

- `docs/integrations/APIS-debank.md` — DeBank Cloud OpenAPI + Playwright fallback
- `docs/integrations/PROTOCOL-PARSING.md` — (mostly future/aspirational) protocol-specific parsing ideas

## Design docs

- Transactions
  - `docs/design/TRANSACTIONS-processing.md`
  - `docs/design/TRANSACTIONS-ledger-entry-types.md`
  - `docs/design/TRANSACTIONS-fiat-currency.md`
- Cost basis
  - `docs/design/COST-BASIS-review.md`
  - `docs/design/COST-BASIS-accounting.md`
  - `docs/design/COST-BASIS-disposal-review.md`

## Doc conventions

- When a doc contains older wiki material, add a short “Status (2025)” section near the top that reflects the current code + tests.
- Keep “why we decided X” context; mark outdated sections explicitly instead of deleting.
