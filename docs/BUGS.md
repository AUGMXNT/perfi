# Bugs / Known issues

## Nonsense numbers when pricing is missing (2022-04-08)

For swaps/trades with unknown pricing, costbasis can sometimes produce unintuitive results.

Current behavior (2025):

- Missing prices are usually surfaced via flags like `zero_price` / `auto_reconciled`.
- A manual `tx_ledger` price override (CLI/API) + costbasis regeneration is the intended workflow for fixing specific cases.

Follow-up:

- Capture a concrete repro and add a regression test case if this shows up again.
