# Cost Basis Accounting

- Cost Basis Accounting
    - [Beancount - Proposal - Inventory Booking Improvements](https://docs.google.com/document/d/1F8IJ_7fMHZ75XFPocMokLxVZczAhrBRBVN9uMhQFCZ4/edit#heading=h.slkego4axqdp)
    - [https://github.com/simonmichael/hledger/issues/1022](https://github.com/simonmichael/hledger/issues/1022)
    
    Import Cost Basis from:
    
    - Bitcoin.tax
    - Exchange Buys
        - Coinbase
        - Gemini
        - Kraken
    - CSV format lets people arbitrarily import cost basis
    
    settings to check which tx are taxable by default
    
- tx_chain
    - everything based on a chain tx, all the data we can get
- tx_ledger
    - take the chain transactions and split into ins/outs
        - fee
        - in
        - out
- tx_logical
    - group those ins and outs
    - need to allow adding other transactions (eg, approvals)

- we need to generate a new costbasis_lot for any transactions where we acquire more assets
- we regenerate costbasis and gains continually based on different imports, etc

- costbasis_lot
    - tracking lots
    - record balance of lot as
- costbasis_disposal
    - track which lot is used
    - track price sold
- disposal_lot
    - gains - calced from cost lot
    
    Cost Basis
    
    - Price feed
    - Asset INPUT / Asset OUTPUT * Price Feed Price
        - Calculate your INPUT price
    
    Trade 2 ETH (price is 3k at time of trade) for 10 AVAX
    
    valuing the input, we get:   2eth * 3,000usd_per_eth  / 10avax = 600 USD is how much that AVAX cost you to buy
    
    Cost Basis is always determined by the Price Feed
    
    Capital Gain/Loss is calculated from the value of the Cost Basis of the output + any fees
    
    Tax bins
    
    SpecID 1 = 0.5 ETH at 1000
    
    SpecID 2 = 1 ETH at 500
    
    PF = 1 ETH = 3000
    
    PF = 1 AVAX = 300
    
    Actual Transaction
    
    - Sell 1 ETH
    - Buy 9 AVAX = 2700 based PF
    - $100 gas fee
    - Means we actually netted $2600 for our ETH
    - Gains = $2600 minus
        - 0.5eth at $1000 from SpecID 1
        - 0.5eth at $500 from SpecID 2
        - Cost basis for 1.0 ETH in this trade is $1500
        - Total spent of $2600 minus total cost basis $1500 is a $1100 Gain
        - SpecID 1 is zeroed out
        - We have 0.5 ETH remaining in SpecID 2
    
    lot
    
    - id
    - asset_id = AVAX
    - price_per_asset = 300
    - original_asset_amount = 9
        - we want this because these will be attached to plays, and let us know whether we’re in profit or not for any entry/position
    - current_asset_amount = 9
        - this is a state optimization so we know how much is left in this lot when we need to calculate capital gains/losses
    
    lot_tx_log
    
    - txhash
    - lot_id
    - amount
