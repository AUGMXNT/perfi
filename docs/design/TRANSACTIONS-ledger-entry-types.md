# Ledger Entry Types

[https://github.com/AUGMXNT/perfi-poc/blob/2bed1398bb1152e8af4486f58630524c4043a8a2/_old/poc/txtypes.txt](https://github.com/AUGMXNT/perfi-poc/blob/2bed1398bb1152e8af4486f58630524c4043a8a2/_old/poc/txtypes.txt)

## Transaction Types

### From existing services

| Rotki | Cointracking | TokenTax | Koinly | Accointing | CryptoTaxCalculator | CoinTracker.io | TaxBit |
|-------|--------------|----------|--------|------------|---------------------|----------------|--------|
| | Income | Deposit | Deposit | Buy | Fee | Xfr In-Out | Transfer In |
| **TAXABLE ACTIONS** | Deposit | Withdrawl | Withdrawl | Transfer | Incoming | Trade | Trade |
| Income | Withdrawl | Trade | Internal | | Outgoing | Bought | Transfer Out |
| Trade | Other Fee | Transfer | ICO | | Receive | Sold | Expense |
| AssetMovement | Trade | | OTC | | Sell | Received | |
| EthereumTransaction | | **LABELS** | | | Send | Sent | **FLAGS** |
| MarginPosition | | Airdrop | **CLASSIFICATIONS** | | Zero Cost Buy | Mint | Missing Cost Basis |
| Loan | | Fork | Fee | | | | Missing Price |
| DefiEvent | | Mining | Gambling used | | **CATEGORIES** | | Need Review |
| AMMTrade | | Reward | Gift sent | | Need Review | | Manual |
| LedgerAction | | Loan Interest | ICO | | Manual | | Imported |
| | | Income | OTC | | Imported | | Ignored |
| **TRADE TYPES** | | Gift | Ignored | | Ignored | | |
| Buy | | Lost | Interest Paid | | | **TAGS** | |
| Sell | | Cost | Internal | | | Gift | |
| Settlement Buy | | Interest Payment | Lending | | | Lost | |
| Settlement Sell | | Margin Fee | Lost | | | Mined | |
| | | Realized P&L | Margin fee | | | Airdrop | |
| | | Liquidity In | Margin loss | | | Payment | |
| | | Liquidity Out | Payment | | | Fork | |
| | | | Remove funds | | | Donation | |
| | | | Swap | | | Staked | |
| | | | | | | Interest | |

### Our Format 
tx_logical_type

- id (slug version)
- name - english version
- tx_ledger_type_map

tx_perfi_type→tx_ledger_type

- id - slug version
- direction
- name - english version
- tags

we’ll store tax treatment rules in a separate table simply as a relational mapping

- perfi_tx_type, tax treament, tax_ruleset_id

tax_rule_set will just have

- description - US, UK, whatever
- but also any customizations, will be stored as a tax_rule_set
- if there changes, it will create a new rule_set, because all tax generation needs to be redone

```json
tx_logical_type

bridge
borrow
repay
deposit
withdraw
lp
swap
send (transfer)
  payment
  gift
receive (transfer)
stake
yield
```

```
tx_ledger_type

IN
  bridge_in: Bridge In
  borrow: Borrow
  buy_from_fiat: Buy from Fiat
  loan_borrow: Loan Borrow
  receive_gift: Receive Gift
  swap_in: Swap In
  withdraw: Withdraw Deposit

  Earned Income (Taxable)
    airdrop: Airdrop
    claimed_reward: Claimed Reward
    income: Income
    interest_earned: Interest Earned
    mining: Mining
    fork: Fork
    staking_reward: Staking Reward

OUT
  bridge_out: Bridge out
  give_gift: Give Gift
  lost: Lost
  loan_deposit: Loan Deposit
  loan_repay: Loan Repay
  migration: Migration
  staking: Staking
  stolen: Stolen
  
  Disposal (Taxable)
    swap_out: Swap Out
    sell_to_fiat: Sell to Fiat
    spend: Spend

  Tax Deductible
    donation: Donation
    fee: Fee
    interest_paid: Interest Paid
    margin_fee: Margin Fee
    margin_loss: Margin Loss

OTHER
  failed_tx: Failed TX
  ignored: Ignored
  invalid: Invalid
  lock: Lock
  unlock: Unlock
  remove_funds: Remove Funds
  wrap: Wrap
  unwrap: Unwrap
  internal: Internal (Contract Call, Checkpoints, etc)
  other: Other

?? Margin Postion
?? Liquidity In/Out, LP Funding?
?? Mint?
ICO
OTC
Gambling

Tags:
  Need Review
  Imported
  Manual
  0-Cost Basis
```

```python
# Heuristics
We want to be able to go from a less specific default (eg, Deposit based on debank.name) to more specific overrides (debank.protocol).

We want matching to be something like udev, where we can give it a combination of selectors like: protocol, (function) name, tokens we interact with, contract addresses 

have it do a bunch of matches.

QUESTION: do we prioritize by specificity or just by some sort of order
Might be simple order:
* just token or a function name, is most general
* protocol overrides
* contract address overrides
* to/from address

QUESTION: will we ever want to change a tx_ledger.tx_perfi_type based on the tx_logicial that it belongs to?
* maybe for a bridge transaction?
* but a bridge tx send will always be either a send to an EOA bridge address or a contract interaction with a bridge address
* the matching receive will sometimes be from a contract, sometimes generated from null by a contract, sometimes from an account... j

```

**BridgeIn**

`‘bridge’ in from_address_name.lower()`

**BridgeOut**

`‘bridge’ in to_address_name.lower()`

**SwapIn/Out**

`debank.receives and debank.sends both have tokens?` 

**FailedTX**

`Status == failed`

**Staking**

asset type = ‘vault’ and not type borrow or loan (see below)

**Borrow**

asset type = loan

**Deposit**

asset type = vault and assert tag =’aave’
