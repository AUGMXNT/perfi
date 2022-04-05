"""
LATER: we should run the an update anytime we can't find a mapping

This script We need to run this to get the latest assets; depends on looking at the asset referenced by the ledger_tx's and mapping; requires updates if there are new unrecognized tokens

We also generate a new constants file from coingecko token info plus our own fixups
"""


from perfi.cache import cache
from perfi.db import db
from perfi.constants.paths import ROOT


import json
import logging
import lzma
from pprint import pprint, pformat
import sys
import time


logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

if sys.stdout.isatty():
    logger.setLevel(logging.DEBUG)


def main():
    update_assets_from_txchain()
    generate_constants()


def update_assets_from_txchain():
    sql = """SELECT chain, address, hash, timestamp, raw_data_lzma
           FROM tx_chain
           ORDER BY timestamp ASC
        """
    results = db.query(sql)

    # Manual Overrides
    manual_type_map = {
        # LPs
        "JLP": "lp",  # Trader Joe LP
        "SLP": "lp",  # Sushiswap LP
        "UNI-V2": "lp",  # Uniswap v2 LP
        "UNI-V3-POS": "lp",  # Uniswap v3 LP
        "spLP": "lp",  # Spookyswap LP
        "PGL": "lp",  # Pangolin LP
        "am3CRV": "lp",  # Curve Aave Matic 3CRV
        "AC4D": "lp",  # Axial
        "G-UNI": "lp",
        # Vaults
        "YRT": "vault",  # Yield Yak Vault
        "fsGLP": "vault",  # GLP Deposit
        "sbfGMX": "vault",  # GMX Deposit
        "sAVAX": "vault",  # Benqi AVAX Deposit
        "sSPELL": "vault",  # Spell Deposit
        "xSDT": "vault",  # Stake DAO SDT Deposit
        "stkMTA": "vault",  # Staked MTA
        "imxB": "vault",  # Impermax Deposit
        "pSLP": "vault",  # Pickled Sushi LP
        # Deposit
        ### TODO: dynamic matches...
        # vIron[A-Z] : Iron Bank
        # sd*
        # [a-z]CRV : Curve
        # [a-z]CRV-gauge
        # t*
        # variableDebt*
        # yv* : Yearn yVault
        # B-[A-Z] : Balancer
        # v[A-Z] - Kogefarm
        # ZPR_NFT - Zapper NFT
        # CROWDFUND_EDITIONS - NFT
        # LOOT - NFTs
        # POETS - NFT
        # Tag - bridge, wrapped
        # hMatic
        # FTMB
        # imxC - Impermax Collateral, hmm
    }

    manual_price_map = {
        # L1s
        "avalanche:avax": "avalanche-2",
        "ethereum:eth": "ethereum",
        "fantom:ftm": "fantom",
        "polygon:matic": "matic-network",
        "xdai:xdai": "xdai",
        # Tokens
        "fantom:0x8d11ec38a3eb5e956b052f67da8bdc9bef8abf3e": "dai",  # dai
        "fantom:0x328a7b4d538a2b3942653a9983fda3c12c571141": "usd-coin",  # crUSDC/ibUSDC
    }

    for tx_chain in results:
        chain = tx_chain[0]
        address = tx_chain[1]
        hash = tx_chain[2]
        timestamp = tx_chain[3]
        lzmad = lzma.LZMADecompressor()
        raw_data_str = lzmad.decompress(tx_chain[4])
        raw_data = json.loads(raw_data_str)

        # First lets update tokens...

        if "debank" in raw_data:
            # NOTE: debank time_at seems to be _very_ old. Don't use!
            txs = raw_data["debank"]["receives"] + raw_data["debank"]["sends"]
            for tx in txs:
                try:
                    logger.debug(
                        f"{tx['_token']['chain']:8} | {tx['_token']['symbol']:20} | {tx['_token']['id']}"
                    )
                except:
                    logger.debug(
                        f"INVALID TOKEN? (skipping): {raw_data['chain']}:{raw_data['hash']}"
                    )
                    continue

                sql = """REPLACE INTO asset_tx
                 (chain, id, symbol, name, type)
                 VALUES
                 (?, ?, ?, ?, ?)
              """
                if tx["_token"]["chain"] == tx["_token"]["id"]:
                    type = "coin"
                elif tx["_token"]["symbol"] in manual_type_map:
                    type = manual_type_map[tx["_token"]["symbol"]]
                else:
                    type = "token"
                params = [
                    chain,
                    tx["_token"]["id"],
                    tx["_token"]["symbol"],
                    tx["_token"]["name"],
                    type,
                ]
                db.execute(sql, params)

    # OK, now time to update asset_price_id mappings...
    sql = """SELECT chain, id, symbol, name, type, raw_data
           FROM asset_tx
           WHERE asset_price_id IS NULL"""
    results = db.query(sql)

    for asset in results:
        chain = asset[0]
        id = asset[1]
        symbol = asset[2]
        name = asset[3]
        type = asset[4]
        raw_data = asset[5]

        # first manual override
        if f"{chain}:{id}" in manual_price_map:
            sql = """UPDATE asset_tx 
               SET asset_price_id = ? 
               WHERE chain = ? AND id = ?
            """
            params = [manual_price_map[f"{chain}:{id}"], chain, id]
            db.execute(sql, params)
        elif type == "token":
            sql = """SELECT id FROM asset_price WHERE raw_data LIKE ?"""
            results = db.query(sql, f"%{id}%")
            # No dupe contract ids, great
            if len(results) <= 1:
                for ap in results:
                    sql = """UPDATE asset_tx 
                   SET asset_price_id = ? 
                   WHERE chain = ? AND id = ?
                """
                    params = [ap[0], chain, id]
                    db.execute(sql, params)
            logger.debug(f"{chain}:{symbol} - {len(results)}")

        # TODO: cleanup...
        fixups_sql = """
            -- VAULTS
            -- Yield Yak Vault
            UPDATE asset_tx SET type='vault' WHERE symbol = 'YRT';
            -- Beefy Finance Vault
            UPDATE asset_tx SET type='vault' WHERE symbol GLOB 'moo*';
            -- Yearn Finance Vault
            UPDATE asset_tx SET type='vault' WHERE symbol GLOB 'yv*';
            -- Stake DAO Vault
            UPDATE asset_tx SET type='vault' WHERE symbol GLOB 'sd*';
            -- Kogefarm 
            UPDATE asset_tx SET type='vault' WHERE symbol GLOB 'v*' AND name LIKE '%vault%';
            -- Qi Compounding
            UPDATE asset_tx SET type='vault' WHERE symbol GLOB 'cam*';
            -- Tokemak
            UPDATE asset_tx SET type='vault' WHERE symbol GLOB 't*' AND name GLOB 'Tokemak*';
            -- Curve Gauges
            UPDATE asset_tx 
            SET type='vault', tag='curve'
            WHERE asset_price_id IS NULL 
            AND symbol GLOB '*-gauge'
            AND name GLOB 'Curve.fi *';
            -- Aave Deposits
            UPDATE asset_tx 
            SET type='vault', tag='aave'
            WHERE symbol GLOB 'a*'
            AND name GLOB 'Aave *';
            -- Aave Loans
            UPDATE asset_tx 
            SET type='loan', tag='aave' 
            WHERE symbol GLOB 'variableDebt*';

            -- LPs
            UPDATE asset_tx 
            SET type='lp', tag='balancer' 
            WHERE asset_price_id IS NULL 
            AND symbol GLOB 'B*'
            AND name GLOB 'Balancer *';
            -- Lots of random LP tokens... (checked that they are all LP tokens in DB...)
            UPDATE asset_tx 
            SET type='lp'
            WHERE asset_price_id IS NULL 
            AND type = 'token'
            AND symbol GLOB '*LP*'
            AND name GLOB '*LP*';
        """
        db.cur.executescript(schema_sql)

"""
LATER:
    * should we store these in the DB so they can be updated by the user easily?
    * maybe we need a table of different mapping types...

    mapping
        type, key, value

???
# we need to store tx_logical_types with is_disposal treatment
"""

### MAPPINGS USED INTERNALLY

# We use forex-python and these are the currencies we currently support getting price quotes for.
# via https://github.com/MicroPyramid/forex-python
FIAT_SYMBOLS = [
    "USD",
    "JPY",
    "BGN",
    "CZK",
    "DKK",
    "GBP",
    "HUF",
    "PLN",
    "RON",
    "SEK",
    "CHF",
    "ISK",
    "NOK",
    "HRK",
    "TRY",
    "AUD",
    "BRL",
    "CAD",
    "CNY",
    "HKD",
    "IDR",
    "INR",
    "KRW",
    "MXN",
    "MYR",
    "NZD",
    "PHP",
    "SGD",
    "THB",
    "ZAR",
]


# Mapping of Coingecko to Perfi platform names
COINGECKO_PLATFORM_MAP = {
    "arbitrum-one": "arbitrum",
    "binance-smart-chain": "bsc",
    "harmony-shard-0": "harmony",
    "huobi-token": "heco",
    "kucoin-community-chain": "kcc",
    "metis-andromeda": "metis",
    "okex-chain": "okex",
    "optimistic-ethereum": "optimism",
    "polygon-pos": "polygon",
    "shiden network": "shiden",
}

# generate wrapped tokens
COINGECKO_WRAPPED_TOKEN_MAP = {}

COINGECKO_LIKEKIND_MAP = {
    # AVAX
    "wrapped-avax": "avalanche-2",
    # BTC
    "aave-amm-wbtc": "bitcoin",
    "aave-polygon-wbtc": "bitcoin",
    "aave-wbtc": "bitcoin",
    "aave-wbtc-v1": "bitcoin",
    "compound-wrapped-btc": "bitcoin",
    "compound-wrapped-btc-legacy": "bitcoin",
    "renbtc": "bitcoin",
    "wrapped-bitcoin": "bitcoin",
    "wrapped-btc-wormhole": "bitcoin",
    # DAI
    "wrapped-xdai": "dai",
    "xdai": "dai",
    # ETH
    "weth": "ethereum",
    # FTM
    "wrapped-fantom": "fantom",
    # USDC
    "usd-coin-avalanche-bridged-usdc-e": "usd-coin",  # USDC.e
    "aave-polygon-usdc": "usd-coin",  # amUSDC
    # USDT
    "tether-avalanche-bridged-usdt-e": "tether",
    ### UST
    "wrapped-ust": "terrausd",
    ### USDT
    "avalanche:0xc7198437980c041c805a1edcba50c1ce5db95118": "tether",  # USDT.e
    # Harmony WONE
    "harmony:0x21be370d5312f44cb42ce377bc9b8a0cef1a4c83": "one",
    "avalanche:0x50b7545627a5162f82a992c33b87adc75187b218": "bitcoin",  # WBTC.e
    # AAVE
    "ethereum:0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": "aave",
    "avalanche:0x63a72806098bd3d9520cc43356dd78afe5d386d9": "aave",
}

### MAPPINGS TO OUTPUT

# List of wrapped tokens that we know about
# chain:contract : asset_tx_id
# chain:wrapped_symbol : contract
WRAPPED_TOKENS = {
    # Ethereum WETH
    "ethereum:0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "eth",
    "ethereum:eth": "eth",
    # Avalanche WAVAX
    "avalanche:0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7": "avax",
    "avalanche:avax": "avax",
    # Fantom WFTM
    "fantom:0x21be370d5312f44cb42ce377bc9b8a0cef1a4c83": "ftm",
    "fantom:ftm": "ftm",
    # Harmony WONE
    "harmony:0x21be370d5312f44cb42ce377bc9b8a0cef1a4c83": "one",
    "harmony:one": "one",
    # Moonriver
    # Moonbeam
    # Aurora
    # Celo
    # Gnosis Chain
    # BSC
    # Arbitrum
    "arbitrum:0x82af49447d8a07e3bd95bd0d56f35241523fbab1": "aeth",
    # Optimism
    "optimism:0x82af49447d8a07e3bd95bd0d56f35241523fbab1": "oeth",
    # Boba
    # Metis
}

# These have fixed price, can be used for stablecoins, or worthless tokens that aren't listed...
# We need a better way of flagging tokens to see if they should use a derived price or 0 price
FIXED_PRICE_TOKENS = {
    # EBI
    "polygon:0x0e25f83f02aaa2c15ddd53d7197066659683a9b0": 0.0,
    # TMGO
    "polygon:0x034d706c3af9d11f0ba90d9967947abeda7a5758": 0.0,
}

# We always start with this list from our imports, then we add coingecko onto this...
# costbasis asset mapping
"""
This mapping defines like-kind assets
Depending on your tax regime, you might need to not map bridged or wrapped tokens as equivalent.

In the case of slippage from trading - eg, if there's a wormhole hack and you bought discounted USDC, you should manually edit your cost basis for the discount or actual you bought it for.
"""
COSTBASIS_LIKEKIND = {
    ### CEX Import maps
    "import:aave": "aave",
    "import:alcx": "alchemix",
    "import:algo": "algorand",
    "import:amp": "amp-token",
    "import:atom": "cosmos",
    "import:avax": "avalanche-2",
    "import:bal": "balancer",
    "import:bat": "basic-attention-token",
    "import:bch": "bitcoin-cash",
    "import:bsv": "bitcoin-cash-sv",
    "import:btc": "bitcoin",
    "import:cgld": "celo",
    "import:clv": "clover-finance",
    "import:crv": "curve-dao-token",
    "import:comp": "compound-coin",
    "import:dai": "dai",
    "import:dcr": "decred",
    "import:eth": "ethereum",
    "import:eth2": "ethereum",
    "import:fet": "fetch-ai",
    "import:forth": "ampleforth-governance-token",
    "import:ftm": "fantom",
    "import:glm": "golem",
    "import:grt": "the-graph",
    "import:icp": "internet-computer",
    "import:lrc": "loopring",
    "import:ltc": "litecoin",
    "import:matic": "matic-network",
    "import:metis": "metis-token",
    "import:mkr": "maker",
    "import:nu": "nucypher",
    "import:omg": "omisego",
    "import:skl": "skale",
    "import:sol": "solana",
    "import:sushi": "sushi",
    "import:usdc": "usd-coin",
    "import:ust": "terrausd",
    "import:xlm": "stellar",
    "import:xmr": "monero",
    "import:xtz": "tezos",
    "import:zec": "zcash",
    ### Missing mappings from Coingecko...
    # ETH
    "avalanche:0xd62eff4221f83f05843ab1f645f7c0b4e38a6b49": "ethereum",  # bWETH.e
    # FTM
    "fantom:0x6362496bef53458b20548a35a2101214ee2be3e0": "fantom",  # anyFTM
    # USDC
    "avalanche:0x46a51127c3ce23fb7ab1de06226147f446e4a857": "usd-coin",  # avUSDC
    "fantom:0x328a7b4d538a2b3942653a9983fda3c12c571141": "usd-coin",  # crUSDC
    # PolyFRAX
    "polygon:0x104592a158490a9228070e0a8e5343b499e125d0": "frax",
}


def generate_constants():
    # ORDER market_cap ASC: in case we missed some mapping, try to overwrite with canonical using (fixes some solana wormhole mappings)
    sql = """SELECT id, symbol, name, raw_data 
             FROM asset_price
             WHERE source = 'coingecko'
             ORDER BY market_cap ASC
          """
    results = db.query(sql)

    # Go through each
    for r in results:
        id = r[0]
        symbol = r[1]
        name = r[2]
        raw_data = json.loads(r[3])

        for p in raw_data["platforms"]:
            if p in COINGECKO_PLATFORM_MAP:
                platform = COINGECKO_PLATFORM_MAP[p]
            else:
                platform = p

            # Check if we're in the mapped id...
            if id in COINGECKO_LIKEKIND_MAP:
                mapped_id = COINGECKO_LIKEKIND_MAP[id]
            else:
                mapped_id = id
            # LATER: we could be smarter about making sure 'avalanche-bridged', '-wormhole' coingecko_id's with matching symbols map onto the native tokens...
            # Also 'any' bridge symbols potentially

            if platform and raw_data["platforms"][p]:
                key = f"{platform}:{raw_data['platforms'][p]}"
                COSTBASIS_LIKEKIND[key] = mapped_id

    # Let's output this to the file...
    # NOTE: we can't use pformat because it changes our dict ordering
    print("Updating perfi/constants/assets.py file")
    f = open(f"{ROOT}/perfi/constants/assets.py", "w")

    f.write("###############################################\n")
    f.write("# THIS FILE IS AUTOGENERATED. DO NOT MODIFY.  #\n")
    f.write("# Instead, see asset-constants-generate.py    #\n")
    f.write("###############################################\n")

    f.write("FIAT_SYMBOLS = [\n")
    for s in FIAT_SYMBOLS:
        f.write(f'    "{s}",\n')
    f.write("]\n")

    f.write("\n")

    f.write("WRAPPED_TOKENS = {\n")
    for k in WRAPPED_TOKENS:
        f.write(f'    "{k}": "{WRAPPED_TOKENS[k]}",\n')
    f.write("}\n")

    f.write("\n")

    f.write("FIXED_PRICE_TOKENS = {\n")
    for k in FIXED_PRICE_TOKENS:
        f.write(f'    "{k}": "{FIXED_PRICE_TOKENS[k]}",\n')
    f.write("}\n")

    f.write("\n")

    f.write("COSTBASIS_LIKEKIND = {\n")
    for k in COSTBASIS_LIKEKIND:
        f.write(f'    "{k}": "{COSTBASIS_LIKEKIND[k]}",\n')
    f.write("}\n")


if __name__ == "__main__":
    main()
