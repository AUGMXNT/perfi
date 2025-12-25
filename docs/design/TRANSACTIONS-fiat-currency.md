# Fiat Currency Handling

2022-03-20: This documentation is incomplete and needs verification

Fiat currencies:

- have an `asset_tx_id` of `FIAT:[CUR]` were `CUR` is a currency code like USD, SGD
- the PriceFeed will intelligently recognize and return the proper conversion
- we do the output in the final 8949

## Fiat Currency Discussion

For tracking buys/sells on exchanges, we’ll want to support tracking costbasis lots for fiats.

QUESTION: Do we track them the same way (mechanically) that we track all assets (e.g. asset_tx_id / asset_price_id — probably with a special leading character like ‘FIAT_SGD’ or ‘FIAT_RMB’ etc to let us know it’s not a token but is actually a fiat currency symbol?

IMPORTANT: We definitely want to make a distinction between a “swap” (token to token) vs a “trade” (”buy”/”sell”) that is fiat

We actually want this because in many tax regimes, the former is not necessarily taxed, but the latter is

QUESTION:  When should we convert from foreign FIAT_* to FIAT_USD prices? During costbasis somewhere?

**TODOs**

- In Importers, use FIAT:SYM for all symbols that represent fiat currencies
- In TxLogical typer, in swap, teach it to type it as `trade` if any of the ins/outs startswith `FIAT:`
- Update our PriceFeed.get_price  to understand that `Fiat:*`  coin_ids should actually use the CurrencyRate class to do a price lookup to USD instead.
- Treat the new tx_logical_type `trade` as a disposal in `costbasis.py` by adding a new if clause for `trade`
- LATER: costbasis 8949 script can do final conversion to local currency from our USD values if we ever want that
