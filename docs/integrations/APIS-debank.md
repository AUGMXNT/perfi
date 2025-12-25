# DeBank integration

## Official docs

- Chain: https://docs.open.debank.com/en/reference/api-reference/chain
- Protocol: https://docs.open.debank.com/en/reference/api-reference/protocol
- Token: https://docs.open.debank.com/en/reference/api-reference/token

## How perfi uses DeBank

We primarily use DeBank transaction history as an ingest source for `tx_chain`.

Implementation lives in `perfi/ingest/chain.py`:

- `DeBankTransactionsFetcher` uses DeBank Cloud OpenAPI (paid) when `DEBANK_KEY` is present in settings.
- `DeBankBrowserTransactionsFetcher` uses Playwright to load the DeBank web UI and captures XHR responses from `https://api.debank.com/history/list` as a fallback when no key is configured.

The unifier chooses based on whether `setting(db).get("DEBANK_KEY")` is set.

## Configuration

- Configure `DEBANK_KEY` in the `setting` table (see `perfi/settings.py`), or via CLI/API tooling.
- If using the Playwright fallback, install browser binaries once:
  - `uv run playwright install chromium`

## Endpoints used

- OpenAPI (paid): `https://pro-openapi.debank.com/v1/user/all_history_list?...`
- Browser-captured: `https://api.debank.com/history/list`

## Notes / limitations

- The browser scraper depends on DeBank's UI and can break; prefer the paid API if reliability matters.
- The current unifier is effectively “ethereum-only” (see `TransactionsUnifier.all_transactions` in `perfi/ingest/chain.py`).
