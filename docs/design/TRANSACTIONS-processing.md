# Transactions

## TODOs

- [x]  Pull coingecko token list into `asset_price`
    - [x]  Pull prices
- [x]  Generate `asset_tx` table
- [x]  Compressed cache, DB compacting
- [x]  fix normalize_asset() for LedgerTx
- [x]  Investigate why raw_data doesn't exist for some txns in updateledger script run
    - [x]  put LedgerTxs() into tx_ledger

---

we should always be able to replay the 

- regenerate chain reimport
- chain impmort

# How to update Transactions

t**x_chain** is going to be UNIQUE(”chain”, “address”, “hash”) so we can regenerate or update that at  will

**tx_ledger** and **tx_logical** have auto increment ids that are arbitrary so we have to be careful about regeneration because a **tx_logical** can be manually updated and then can no longer be automatically regenerated, and neither can the **tx_ledger** transactions referenced by that **tx_logical**

**tx_ledger** can be manually

- Before a **tx_ledger** record is inserted, we look to see if we have an existing record for chain, address, hash, direction, amount, perfi_asset_id (make an asset id for fee?)
    - If found, we write this record to a queue for review/editing and then another script processes that queue to do any needed updates (e.g. bug fixes for mis-categorized things or whatever)

# Notes from 2021-02-16 call

1. Why do we want to see the internal transactions (which have parent_hash) as a top level item inside the transactions list? Why not just see them as nested inside their associated parent transaction?
Our current thinking was to store tx_chain records keyed on (chain, hash, address) which means we would conflict when we insert the internal transaction and use its parent_hash as the 'hash' value for it.
    1. Answer: nest the internals under their parent transaction in an attribute named something like child transactions (done I think)
2. LOL - Polygonscan html is really similar but inconsistent in some ways from Snowscan. Not big differences, but not drop in with no code replacement either. Probably worth spending an hour to port it, and similar for polygonscan and ftmscan. Agree?
    1. yes, worth it if will be less time now than later
3. Added cookies support to cache.py. When cookies come in from a request for a domain, we save them and hand them back to subsequent requests for that domain. This seems to help prevent 302 redirects to busy from etherscan so why not? (may be placebo, IDK). Cache also allows you manually to pass any cookies in for a given hostname to be used on subsequent requests.
4. While adding NFT support for snowtrace I discovered inconsistent responses in the txdetails page for snowscan for how it shows tokens transfered for ERC721 tokens vs ERC20 (no amount for ERC721). Updated scraper to be more robust in erc20/erc721 token transfers for snowtrace and etherscan.
5. **Question: do any of the Avalanche transactions on snowtrace have labels (similar to etherscan, like ‘Flashbots’ etc) that I can test snowtrace scraper with?**
6. Found bug in Etherscan scrapper for mint transaction actions parsing for ERC-1155 tokens.  Do we care about these? It looks like these are a new standard use for contracts that mint many token types in one contract. I updated the etherscan scraper to handle it. 
    1. Yes we care. Scraping is done for Etherscan.
    2. **Can we find an example from snowscan?**

### 

## Interesting examples for scraper tests in future

Etherscan - ERC-1155 minting - `https://etherscan.io/tx/0xEXAMPLE_TX_HASH`

Etherscan - ERC721 list of tokens in a wallet address - `https://etherscan.io/address/0xEXAMPLE_ADDRESS#tokentxnsErc721`

Etherscan - Token transfer with truncated token symbol - `https://etherscan.io/tx/0xEXAMPLE_TX_HASH`

Snowtrace - Standard ERC 20 token transfers - `https://snowtrace.io/tx/0xEXAMPLE_TX_HASH`

Snowtrace - ERC20 and ERC721 tokens in same transaction - `https://snowtrace.io/tx/0xEXAMPLE_TX_HASH`

Snowtrace - Mint and burn of tokens in same transaction - `https://snowtrace.io/tx/0xEXAMPLE_TX_HASH`

 

# 2022-02-14 Review

- tx_chain
    - store by **UNIQUE(chain, hash, address)**
    - chain  e.g. ethereum or avalanche, etc...
    - hash
    - address (relates to our wallet)
    - time
    - type (internal, normal, token, nft)
    - **raw_data**
        - [x]  etherscan HTML SCRAPED DATA
        - [x]  etherscan RAW HTML
        - [ ]  etherscan API JSON
        - [x]  covalent API JSON
        - [x]  unmarshall API JSON
        - [x]  DeBank API JSON
        - [ ]  alchemy API JSON

- price
- costbasis

Generate from tx_chain(address) ordered by time

- tx_ledger
    - generate a double-entry booking set of transactions
    - also generate fees as a separate tx
    - we generate all tx_ledgers and then do a separate loop to generate tx_logical to be able to handle crosschain txs, etc.
    - we need to at this point get price, usd_value
        - map token_id to perfi_asset_id and then get the price_asset_id from the perfi_asset_id
        - and get the price nearest the time
- tx_logical
    - name
    - tags
    - approvals or multistep tx_chain or tx_ledger can be a single logical transaction
    - does tx_ledger.ids in tx_logical need to be relational? TBD

# How to Get Transactions

Account: [https://etherscan.io/address/0xEXAMPLE_ADDRESS](https://etherscan.io/address/0xEXAMPLE_ADDRESS)

Scrape TX lists:

- Full TX List
    - [https://etherscan.io/txs?a=0xEXAMPLE_ADDRESS](https://etherscan.io/txs?a=0xEXAMPLE_ADDRESS)
- Internal (simple view is fine)
    - [https://etherscan.io/address/0xEXAMPLE_ADDRESS/advanced#internaltx](https://etherscan.io/address/0xEXAMPLE_ADDRESS/advanced#internaltx)
- ERC20
    - [https://etherscan.io/address/0xEXAMPLE_ADDRESS/advanced#tokentxns](https://etherscan.io/address/0xEXAMPLE_ADDRESS/advanced#tokentxns)
- ERC721
    - [https://etherscan.io/address/0xEXAMPLE_ADDRESS/advanced#tokentxnsErc721](https://etherscan.io/address/0xEXAMPLE_ADDRESS/advanced#tokentxnsErc721)
- Debank API
    - [https://api.debank.com/history/list?chain=avax&page_count=100&start_time=0&token_id=&user_addr=0xEXAMPLE_ADDRESS](https://api.debank.com/history/list?chain=avax&page_count=100&start_time=0&token_id=&user_addr=0xEXAMPLE_ADDRESS)

Merging all transaction types by Transaction Hash

- Similar to Debank, we want to be able to get all the IN and OUT (Send and Receive)

In the ERC20 (token) transactions, look to see if it’s a contract in the API response, scrape if we cant tell by poking the web view for it

**Construct a PerFi Transaction record from all our data sources**

for inspiration see [https://docs.open.debank.com/en/reference/api-models/portfolioitemobject](https://docs.open.debank.com/en/reference/api-models/portfolioitemobject)

- type: deposit | loan | send etc
- protocol name: aave, cowswap, etc
- cost basis in USD
- datestamp

CowSwap Transaction:

- `https://etherscan.io/tx/0xEXAMPLE_TX_HASH`
- `https://dashboard.tenderly.co/tx/mainnet/0xEXAMPLE_TX_HASH`

Read the 3rd party

- CoW Protocol: GPv2Settlement
- Contract
- [https://etherscan.io/address/0x9008d19f58aabd9ed0d60971565aa8510560ab41](https://etherscan.io/address/0x9008d19f58aabd9ed0d60971565aa8510560ab41)
    - Contract Overview
    
- Etherscan
- Snowtrace
- Debank

Store Addresses into Address Book

- address
- chain
- name
- type
    - account
    - contract OR account

chain_transcation - blockchain transactions

ledger_entry

- single chain transaction would typically yield multiple ledger_entry items like:
    - cowswap
        - (separate chain_tx if a wrap or approval is needed might be grouped in a logical tx)
        - swap out: 200K USDC
        - swap in: 50 ETH
        - fee paid - no fee paid b/c cowswap does it
    - aave deposit
        - deposit out: 4.5 AVAX
        - fee paid: 0.001 AVAX

[Better Chain Transaction Data](Transactions/Better%20Chain%20Transaction%20Data%20b223787e619941669d4dc0b5161a02ae.md)

Old version of tx_ledger (before we moved to event stream model)

```sql
CREATE TABLE IF NOT EXISTS "tx_ledger" (
  "uuid" TEXT,
	"chain"	TEXT,
	"address"	TEXT,
	"hash"	TEXT,
	"timestamp"	INTEGER,
	"to_address"	TEXT,
	"from_address"	TEXT,
	"direction"	TEXT,
  "perfi_transaction_type" TEXT,
  "amount" REAL,
  "perfi_asset_id" TEXT,
  "price_asset_id" TEXT,
  "price" REAL,
  "ignore" INTEGER default 0,
	PRIMARY KEY("uuid")
);
COMMIT;
```

# tx_chain refactor

This table should store everything we need to regenerate tx_ledger...

- first pass, for an address, get a canonical list of all the tx hashes in the most reliable ways possible, store in db
    - blockscanner api
    - covalent
    - debank
- get details for each tx if necessary
    - blockscanner scrape

We should be focused on being able to generate tx_ledger

- token_id (address) in and out
- fees
- methods called

If are missing, details should we fetch 

covalent

- supported:
    - eth
    - matic
    - avalanche
    - arbitrum
    - fantom
    - moonriver
- need
    - optimism (alchemy)
    - harmony
    - metis

- supported but don’t need
    - binance
    - near/aurora
    - celo
    - moonbeam
    - xdai/gnosis
    - rsk
    - palm
    - klayton
    - heco
    - axii
    - astarshydon
    - iotex
    - boba
    
- unmarshal
    - solana
    - cosmos
    - osmosis

- PK (chain, address, hash)
- arrays?
    - from_addresses
    - to_addresses
- values
    - in and out of tokens
- actions
    - method
- fee_cost

## tx_chain_raw

This m:n table should include the raw parsed data that we can look at if we ever need to extract more data

- PK (chain, address, hash)
- source
    - blockscanner_scrape_html
    - blockscanner_scrape_parsed_json
    - blockscanner_api
    - debank
- raw_data_lzma