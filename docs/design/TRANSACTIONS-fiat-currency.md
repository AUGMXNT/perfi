# Fiat Currency Handling

Status (2025): implemented and covered by tests.

Fiat currencies:

- have an `asset_tx_id` of `FIAT:[CUR]` where `CUR` is a currency code like USD, SGD
- are emitted by exchange importers (see `perfi/ingest/exchange.py`)
- are priced/converted during ledger generation for imported transactions (see `perfi/transaction/chain_to_ledger.py`)

## Swap vs trade (why we care)

For tracking buys/sells on exchanges, we need to model FIAT legs explicitly; however, perfi does not currently create costbasis lots for FIAT assets (it treats FIAT as a settlement/pricing currency).

QUESTION: Do we track them the same way (mechanically) that we track all assets (e.g. asset_tx_id / asset_price_id — probably with a special leading character like ‘FIAT_SGD’ or ‘FIAT_RMB’ etc to let us know it’s not a token but is actually a fiat currency symbol?

IMPORTANT: We definitely want to make a distinction between a “swap” (token to token) vs a “trade” (”buy”/”sell”) that is fiat

We actually want this because in many tax regimes, the former is not necessarily taxed, but the latter is

In code today:

- `TxLogical.refresh_type()` marks 1-in/1-out transactions as `trade` if either side is `FIAT:*`, otherwise `swap`.
- Costbasis treats `trade` as a disposal when you are selling crypto for FIAT (OUT is not FIAT), but not a disposal when you are buying crypto with FIAT (OUT is FIAT).

## Pricing / FX

- For imported transactions, `chain_to_ledger` converts FIAT amounts to USD using `price_feed.convert_fiat(...)`.
- Costbasis does not create/track lots for FIAT assets (it skips them).

## Tests

- `tests/integration/test_imports_from_exchanges.py` covers FIAT imports (Gemini USD/SGD, etc).
- `tests/e2e/test_e2e_costbasis.py` exercises disposal logic for swaps/trades.

**Implementation checklist (now done):**

- [x] Importers emit `FIAT:*` assets
- [x] `TxLogical.refresh_type()` marks FIAT-involved swaps as `trade`
- [x] `chain_to_ledger` converts FIAT to USD for pricing
- [x] Costbasis includes `trade` handling (buy vs sell behavior)

LATER: 8949 output could optionally convert USD values into a local currency at report time.
