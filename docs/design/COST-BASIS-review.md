# 2022-03-02 Cost Basis Review

## Status (2025)

- Implemented in `perfi/costbasis.py` and exercised by `tests/e2e/test_e2e_costbasis.py`.
- Lots are keyed by `asset_tx_id` (fiat assets use `FIAT:*` and are treated specially).
- Receipt-style assets are tracked via `costbasis_lot.receipt=1` and optional `history` for unwind logic.
- Tax-year “locking” exists at the costbasis lot level (`costbasis_lot.locked_for_year`), but broader “freeze submitted years” semantics are still evolving.

We are using `asset_tx_id` to uniquely identify what asset a cost basis lot is tracking

# Cost Basis Price Generation

We will generate the costbasis price based on a combination

- `asset_price_id` from `asset_tx_id`
- inheriting the price from a previous cost basis lot (eg, AVAX to avAVAX)
- maybe tx_logical_type or some other algorithm, mapping, etc at some point

**Historical TODO (2022):** implement swap-aware price derivation (this is now implemented in `perfi/costbasis.py`; keep the notes below as design context).

NOTE: based on this discussion: [COST-BASIS-accounting.md](COST-BASIS-accounting.md)

When we have a swap, we are going to try to use the OUTPUT * PriceFeed for the cost basis, and generate our DISPOSAL price from that.

We will need to think about how to calculate these differently if we don’t have a Price for the OUTPUT

- eg: we do a swap from SPELL to sSPELL on Trader Joe. If we had deposited the SPELL to sSPELL in Abracadabra, it would be a deposit, but if we’re trading for it, then it would be a disposal. sSPELL does not have a coingecko price so the only way to generate a price would be from the reverse (we shouldn’t consider using the exposure mapping because of slippage)
- If we don’t have price for either, then they’re just 0 value swaps (Notpaying Fuckin Taxes)

# Transaction Types

We currently seed `tx_ledger.tx_ledger_type` from DeBank’s `tx.name` (with a small mapping layer) and then derive `tx_logical.tx_logical_type` from grouped ledger entries (`TxLogical.refresh_type()`).

But, we need **TODO** create logic for using are appropriate [Ledger Entry Types](TRANSACTIONS-ledger-entry-types.md) 

- We have a list of `tx_ledger_type` already
    - currently mostly DeBank-derived values (plus `fee`); future work could normalize into more explicit values like swap_in/swap_out
- We need to derive a list of `tx_logical_type`
    - eg swap

# Refactor to Processing on TxLogical vs TxLedger

We have a number of operations that depend on interactions at the TxLogical level vs individual TxLedger (eg, cost basis from swaps, assignments from bridging) 

# Disposal

We currently decide disposals based on `tx_logical_type` heuristics in `perfi/costbasis.py`. Long-term this should be ruleset-driven (per entity / tax regime) and mapped to a standardized vocabulary.

# Original Cost Basis Tracking for Multiple Inputs

If a swap, deposit, etc is not a disposal

can we simply not track the original_lot_id but also not consume (subtract) the lot balance at all?

this potentially gets us into trouble if we’re over-subtracting before we turn this back...

we also need to make sure that we know that it was a nondisposal

can we skip original_lot_id if we simply store prices, so we can restore the price if we generate a new IN

- cons: regeneration? doesn’t matter if we completely regenerate? reparenting to lot id might not work anyway?

This only applies if you treat an LP as a non-disposal

```
> How did you get koinly to keep your cost basis when staking Lps.

Cllick the settings button at the top & then turn off the Realize gains on liquidity transactions? switch
```

[https://www.youtube.com/watch?v=jVCJ1Zddd4Y](https://www.youtube.com/watch?v=jVCJ1Zddd4Y) - Cointracking step through video

In that case we need to to track:

10 ETH + 10 AVAX → LP

we need multiple original cost basis so when we go

LP → 20 ETH + 20 AVAX we can match the original cost basis?

If swap, no problem

If not swap...

10 ETH → generate an OUT event (subtract using HIFO matcher)

- mark as disposal=False

10 AVAX → generate an OUT event (subtract using HIFO matcher)

- mark as disposal=False

LP will generate a lot when we receive it

- LP price should be current price of 10 ETH + 10 AVAX
- our data model does not handle list of related original lots

LP back

- our LP price OUT price is 15 ETH * 15 AVAX
- 15 ETH
    
    15 AVAX
    
- Even if you stored the original 10 ETH + 10 AVAX, you now have a new 5 ETH and 5 AVAX that has a new basis (current)
    - We still need the original 10 ETH + 10 AVAX price... so need the original lots, unless we store this somehow
    - does original_lot simply need to be a list? `original_lot_list`
    

costbasis → token vs exposure, like kind asset

bridge - same

we need to not consumer, or our matcher needs to select like kind items

## Approach 1 - everything is a costbasis

- costbasis lot generated for every single asset_tx_id exchange
    - we subtract against costbasis_lot
- we store a chain of provenance
- we calculate the price/amount
- we store a like_kind_asset_id and ratio
- hifo_matcher needs to querie against a like_kind_asset_id for consumption, this becomes maybe intractable when dealing with variable/floating value/amount conversions like an LP or an ibAsset?
    - makes my head hurt a bit, you’d need to calculate the exact value and amount at the time of consumption to be able to unwind? Impossible to do w/o a very accurate price oracle or a full archive node
    - ABANDONED... let’s see how approach 2 works

## Approach 2 - conserved costbasis tx

For costbasis, we actually don’t care about asset_tx_id? If we need to store a like_kind_id, why don’t we leave the mapping to begin with?

- we have an symbol and costbasis_asset_price_id mapping and extend that mapping whenever we detect a type deposit, etc, extend our protocol parsing knowledge
- we should use a single symbol for our mapping of assets, regardless of chain
- we don’t consume/subtract except for non-like kind exchange
    - this gives us the flexibility of actually calculating the actual hifo
        - eg if you deposit 50 AVAX in Aave, and then you sell 50 AVAX, you wouldn’t be able to get the actual HIFO if we had already consumed it (unless we map the original anway)
        - we would still generate a costbasis lot for the avAVAX in case you ended up disposing of it... then you would also need to follow the chain back and subtract from the 50 AVAX

## Costbasis Model Conclusions

Thinking through all our corner cases, a combined model which mostly uses a “conserved” cost basis approach, but adds some things as well. This handles everything we’ve thought of so far.

- We should be applying our cost basis rules based at the `tx_logical` and `tx_logical.tx_logical_type` level, which we will use to primarily determine if tx_logical is a disposal (taxable event) or not
    - Every `tx_ledger` **IN** should generate a `costbasis_lot`
        - `costbasis_lot.price` should be established by
            - PriceFeed `asset_price_id` from `asset_tx_id`
            - If not available, we should derive pricing from `tx_logical.tx_logical_type` and the **OUT** value (depending on if it’s a deposit, swap, LP, etc)
            - If both are 0, we should assign a 0 cost basis and flag for `review` JSON
            - ??? We should store `price_source`: as “price_feed”, `[tx_logical_type]` (derived), or “manual”
        - Store a`no_disposal` flag for the `costbasis_lot` of the **IN** tx if not a disposal type
            - “bridge”, “borrow”, “repay”, “deposit”, “withdraw”, “stake”, potentially “lp”
            - We need to do this because we want to be able to ignore this intermediary `costbasis_lot` in most of our calculations (eg, listing ou all our cost basis) but we need it if we transfer the the intermediary for some reason, we still need a `costbasis_lot` entry (see below for more detailed example, reasoning)
        - Store `history` as JSON data structure for referencing the source of the funds
            - We need this in the case that we sell a “receipt” asset like avAVAX, yvBOOST, xSDT, sSTAKE that is normally not transferred, then we will need to look at the history to make sure we run our **LOT MATCHER** to consume the appropriate source `costbasis_lot` into a `costbasis_disposal`
            - One thing to keep in mind is that there can be multiple levels of stake/farm deposits. These need chained references in `history` and we need to be able to unwind in the code to the base asset (likely we’ll store the chain and the original reference in `history` as QoL implementation detail)
                - yvBOOST is an autocompounding/ib version of yveCRV which locks CRV. This is an interesting example b/c there is a market for yveCRV *and* yvBOOST (and they can be arbitraged)
                - Mai Finance (Qi Dao) allows you to deposit camWMATIC, which is the amWMATIC Aave desposit of MATIC
                - Frax, StakeDao, and autocompounders may be other examples
            - This data structure will also let us handle LPs, where there are multiple sources.
                - There is a corner case where you can LP LPs in which case you would need to make sure that you store `original_lots{}` in the the `ancestry[]` but we leave that as an exercise to future degens
            - We need to track the original input `amount`  and `costbasis_mapped_asset` because in the case of an ib or staked asset or an LP, we need to track how much additional yield/value we have received when we withdraw and generate new `costbasis_lot`s for the earned income
                - This might be derived from value_usd/price_usd but that seems jankier
            - UNWINDING is_disposal=False costbasis_lots: In the case of disposal, we also need the `amount` and `costbasis_mapped_asset` so we can run our **LOT MATCHER** on the appropriate amounts (again, this may be different than the deposit for ib, staked, or LP assets)
- For costbasis, we can’t get around mapping to a `costbasis_mapped_asset` for running our calculations at some point. We should do this automatically on import, and then allow manual (and mass) updates
    - We will still want to track the `asset_tx_id` for a `costbasis_lot` to help us to mass replaces or update our default rules, having a `costbasis_mapped_asset` (which = `asset_price_id` (coinbase_slug)) is *actually* what we need/care about for our **LOT MATCHER**
        - Regardless of whether our ETH is on Ethereum or Arbitrum or Avalanche our **LOT MATCHER** should be picking the best `costbasis_lot` to consume from for disposal
        - When we generate our 8949, we will be printing out a single SYMBOL (eg ETH) and we don’t want to print WETH, WETH.e, etc
        - We also want an english description (like “SELL Uniswap V3 FRAX/USDC LP”) for disposals
- We will only create a `costbasis_disposal` for an OUT that is a disposal - if we “subtracted” cost basis every time, we would have a much harder, potentially impossible time trying to write a **LOT MATCHER** to consume properly (mainly due to ib/floating LP conversions). Let’s not deal with that can of worms
    - The `value_usd` should be generated when possible based on the IN price for a “swap”, and if not, fallback to a PriceFeed
    - We should similarly store `price_source` for how this is generated
    - We should store a `tx_ledger_type` for future fine-grained retyping
    - We should also store a `matcher` (”hifo”, “manual”) and a `lots` JSON that contains a list of `costbasis_lot` and `starting_amount` `consumed_amount`
        - If we switch a `tx_logical` from disposal to a non-disposal, we can look at `costbasis_disposal.lots` and reverse the consumption (and then delete the `costbasis_disposal` )
    - If for some reason we have an overrun with LOT MATCHER, it should create a 0-cost-basis  `costbasis_lot` with a `review` JSON that links also to this `costbasis_disposal`
- We can keep a `costbasis_log` if we want, but we really don’t need it and probably won’t ever use it...

`get_costbasis_price_and_source()`

- [x]  we need to create a `costbasis_asset_mapper()` to generate our `costbasis_asset_price_id`
    - [x]  `costbasis_asset_mapper()`
        - [x]  manually generated dict of chain:asset_tx_id → asset_price_id
        - [ ]  future:
            - [ ]  We should allow mapping preferences for wrapped, bridged funds if you want to treat those as disposal
            - [ ]  we can automatically generate additional mappings if we know a protocol, eg aave deposit as it will always have mapped tokens (eg, AVAX to avAVAX)
            - [ ]  if a user does certain mappings, like connects a bridge in and out in a tx_logical “bridge” tx, or makes a deposit then we can also do this mapping, ask if they want to mass apply a mapping
            - [ ]  this is a way we can very efficiently build out a comprehensive or user specific list of mappings

`is_disposal`, `non_disposal`

`costbasis_handleasset_receive()`

~~create zero cost basis~~

root_lot_by_asset_tx_id: dict<asset_tx_id, CostbasisLot>

ancestors_by_asset_tx_id: dict<asset_tx_id, list<CostbasisLot>>

‘lp’

1 ETH OUT

1 AVAX OUT

1 ETH-AVAX LP IN

**Important note:** We don’t want to generate costbasis subtractions for OUTs that occur on logical txs that are not disposals because doing so would consume some of a open costbasis lot for an asset that isn’t really a disposal, thereby harming us later when we wanted to drawdown form the highest cost lot and couldn’t because it was consumed by a nondisposal event. e.g deposit AVAX for avAVAX, this is not a disposal, so dont’ make a subtraction to consume from any AVAX cb lots.

**Here’s when we would definitely use the ancestry array and why we sort of care about the ordering:**

For a “deposit” where we generate costbasis_lots for:

- receive CRV = original asset
- deposit yveCRV = first vault
- deposit yvBOOST = second (ib) vault

For the yvBOOST costbasis lot, its history attr looks like:

- root_lots: { CRV: CostbasisLot }
- ancestors[]
    - yveCRV, costbasis_lot.is_disposal=False
    - CRV

If we withdraw yvBOOST (this withdraw is a nondisposal event)

- If we withdraw yvBOOST, it’s a simple unwind, you just invalidate yvBOOST (delete, or mark done)

If we sell yvBOOST (this sell IS A DISPOSAL)

- we create a costbasis_disposal and LOT MATCHER against yvBOOST
- Then collect each yvBOOST where is_disposal=False until we have enough to cover the amount of yvBOOST we are selling, then we need to invalidate those lots’ intermediaries and then look at the root_lots to see what to consume
    - How many CRV do we consume from the yvBOOST sale? This would depend on us being able to separate out, how many CRV is in each yveCRV and how many yveCRV is in yvBOOST, because we still need to separate out the yield, from the non-disposal original deposit amount
    - For simplicity and tax efficiency, we should always try to consume the original deposit first, and if we overrun, that’s fine too because we generate a zero cost basis lot (same as calculating the yield)
    - So the only question is how to get the ratio. We should get this from the market price for CRV and price for yvBOOST (that we sold it for) and use that to generate the ratio of consumption.
        - There is a blockchain way to get ratios which is contract dependent is to look at the ABI and pull the ratio mapping to the currency for each vault deposit contract - this is brittle, needs to be done on a per contract basis, and actually might not be as correct since you’re selling including slippage (eg, yveCurve and yvBOOST both can be traded on the market, and often there *is* an arbitrage between it’s direct unwrap value and market price)
