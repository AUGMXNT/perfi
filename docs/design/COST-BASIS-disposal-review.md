# Disposal Review

## Status (2025)

- The current costbasis implementation lives in `perfi/costbasis.py` and uses a `receipt` flag (`costbasis_lot.receipt`) rather than the older `no_disposal` naming used in these notes.
- Line numbers and some details below refer to older versions of the code; treat this doc as historical context and debugging rationale.

# Pre Mar 21 Behavior

This is a review of our INCORRECT pre-Mar 21 “disposal” handling and how to fix it.

## is_disposal

Our current costbasis code uses an `CostbasisGenerator.is_disposal`

- `CostbasisGenerator.process()`
    - L#236: Set by matching an `tx_logical_type`in `is_disposal[]`
- `CostbasisGenerator.create_lots()`
    - L#385 set `no_disposal` flag on costbasis lot creation
        - THIS BEHAVIOR IS CURRENTLY LIKELY INCORRECT
        - More on `no_disposal` soon...
- `CostbasisGenerator.drawdown_from_lots()`
    - L#803: if `is_disposal` is True, then we run the disposal code
        - Note: if not `is_disposal`, we still run the subtraction since we still need to account for `costbasis_lot``current_amount` subtraction/accounting for certain cases, but no `costbasis_disposal` - eg a gift or a non-disposal transfer
        - Note 2: a deposit or an internal account should *not* drawdown a lot (except for a deposit receipt), because we still want to retain the original lots, costbasis
        - THIS BEHAVIOR IS CURRENTLY LIKELY INCORRECT
    - L:#925: if `is_disposal=True`and we need to create a reconciled lot, then we immediately drawdown/dispose from it after it’s created

## no_disposal

`no_disposal` is actually a bit of a misnomer. This is stored with a new `costbasis_lot` entry and was originally intended to specify that a lot is a deposit receipt (and intermediate lot) that generally should be ignored.

It should be renamed to something more clear, like `intermediate_lot` or `is_receipt` or `unwind`

- L#148: defined as part of `CostbasisLot` namedtuple
- `CostbasisGenerator.create_lots()`
    - L#355-386: We outline in comments how we use `no_disposal` specifically for making sure we are appropriately tracking unwinds, but we INCORRECTLY set `no_disposal` based on the `CostbasisGenerator.is_disposal` value - this doesn’t always map and would be clarified if we appropriately name what this flag means...
    - L#394: We call `CostbasisGenerator.create_costbasis_lot()` and pass a `no_disposal` and related `history[]` (required for unwinding)
        - THIS CAN BE WRONG since `no_disposal` is determined by `is_disposal`
- `CostbasisGenerator.deposit()`
    - L#482: We CORRECTLY create a `no_disposal` lot for a beefy deposit (mooReceipt), history points to the deposited (`self.outs[]`) transactions. Note that in this case we need to determine which lot is actually a disposal since it gives you a deposit receipt...
    - Note: We assume that create_lots() correctly handles our deposit_receipts propery, but it’s doing so based on the `is_disposal` flag, not on whether it’s a receipt or not...
- `CostbasisGenerator.repay()`
    - L#608: We are again CORRECTLY using `no_disposal` - trying to find a loan_receipt that we need to zero out
- `CostbasisGenerator.create_cost_basis_lot()`
    - L#753: we simply process the `no_disposal` that we’re passed
- `CostbasisGenerator.drawdown_from_lots()`
    - L#804: HAIRY AND I BELIEVE CURRENTLY INCORRECT: we look at `is_disposal`, `no_disposal`, and `lot_history` to see what we need to do. This will be easier to understand if once we rename
    - We need to separate out
        - drawing down from lots
        - generating a disposal
        - whether we need to zero out a `receipt` lot
        - whether we should be unwinding the history or not
- `LotMatcher`
    - L#1070: Functions as expected, which is that it gets lots to match irrespective of `no_disposal` flag
    - However `CostbasisGenereator.drawdown_from_lots()` is might be falling down on us...
        - FIX we are always unwinding, but we don’t need to be unwinding since we usually since we don’t subtract from a lot if we do a deposit...
        - We only need to unwind in the special case that we **release ownership** (this includes either a disposal, or a non-disposal 3rd party transfer) of a `receipt` asset...

# Fixing Behavior

## Summary

- Let’s rename `no_disposal` to something less confusing. For now I’m using `receipt`, which is descriptive and easier to spell than `intermediate` and lets us know we’re not treating it as a swapped asset lot
- We need to **drawdown** a lot based on whether we transfer ownership:
    - **Keep Ownership (no drawdown)**
        - Self Transfer (we assume transfers to be self unless otherwise specified)
            - maybe we should specifically require adding account list to see if it is assigned to the entity?
            - we need to do tx_logical mutations to reclassify... as payment/spend gift
        - Deposit
        - Withdraw
    - **Lose Ownership**
        - any disposal (`is_disposal`)
            - swap
            - trade
            - disposal
            - spend
        - non-disposal
            - loan repayment
            - gift
    - **Gain Ownership**
        - income
            - income
            - yield
            - receive (from 3rd party)
        - non-income
            - loan
- Only in the case where we **Lose Ownership** of a `receipt` do we also have to **drawdown** the original history amount (LIFO like repay loan for tax efficiency)
- We only **dispose** (create a `costbasis_disposal`) for an `is_disposal` type

## Implementation

- For each tx type we do up to 4 operations
    - `create_lots()`
        - skip if ownership does not change
        - create a receipt based on whether is_receipt()
    - `drawdown_lots()`
        - any time we lose ownership
        - if `is_disposal` we also `create_disposal()`
        - if is `receipt`, then we then we look at `history[]` and may have to drawdown from the `history[].lot` (note this is only with an ownership change, otherwise we only need to draw down the receipt amount itself)
    - `create_disposal()`
        - see above
    - `create_income()`
        - if it’s income, we need to create income
            - NOTE: a loan would create a new asset lot (with a cost basis) and potentially also a receipt, but wouldn’t be counted as income
- A tx_type could have disposal and income flags for different tax treatment preferences
    - we should assign these flags in `process()`

`drawndown_lots()` doing a lot of heavy lifting...

If a lot has a receipt:

- `test_costbasis_deposit_and_withdrawal_earns_interest()`
    - zero the receipt lot?
    - drawndown receipt properly
- `test_costbasis_changing_ownership_of_deposit_receipt()`
    - changing ownership or a receipt → sell

mapping...

test_dispose_of_wrapped_asset

## Controlled Vocabulary

### Receipt

A `receipt` is a boolean for a `CostbasisLot` (stored as `costbasis_lot.receipt` in our DB) that specifies that we’ve receipted a token that acts a receipt for a deposit. Examples include avAVAX for AVAX (Avalanche Aave), moo* tokens for Beefy deposits, sSPELL for a SPELL deposit, etc.

### Disposal

We refer to a disposal specifically how the IRS does - as a taxable event for sale, exchange, or (third party) transfer. All disposals are changes in ownership, but not all changes in ownership is a taxable disposal (eg):

- gift
- donation
- loan repayment

### Ownership

This is the concept of whether you retain control of your funds or not.  As long as you retain ownership of your funds, then we do not reset costbasis/generate a new lot.

## Transfers

Because obviously ownership changes depend on the transfer parties and act differently, we will standardize to 3 separate types of transfers:

- self_transfer = from/to one of your accounts where ownership doesn’t change
- receive = assumed from a 3rd party
- send = assumed from a 3rd party
