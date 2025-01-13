"""
LATER: we should run the an update anytime we can't find a mapping

This script We need to run this to get the latest assets; depends on looking at the asset referenced by the ledger_tx's and mapping; requires updates if there are new unrecognized tokens

We also generate a new constants file from coingecko token info plus our own fixups
"""

import json
import logging
import sys

from perfi.asset import update_assets_from_txchain
from perfi.constants.paths import ROOT
from perfi.db import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

if sys.stdout.isatty():
    logger.setLevel(logging.DEBUG)


def main():
    update_assets_from_txchain()
    print("Generating Constants...")
    generate_constants()


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
    "AUD",
    "BGN",
    "BRL",
    "CAD",
    "CHF",
    "CNY",
    "CZK",
    "DKK",
    "EUR",
    "GBP",
    "HKD",
    "HRK",
    "HUF",
    "IDR",
    "INR",
    "ISK",
    "JPY",
    "KRW",
    "MXN",
    "MYR",
    "NOK",
    "NZD",
    "PHP",
    "PLN",
    "RON",
    "SEK",
    "SGD",
    "THB",
    "TRY",
    "USD",
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
    "avalanche-bridged-dai-avalanche": "dai",  # DAI.e
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
    # DAI
    "avalanche:0xd586e7f844cea2f87f50152665bcbc2c279d8d70": "dai",  # Avalanche DAI
}

CHAIN_FEE_ASSETS = {
    "ethereum": "eth",
    "avalanche": "avax",
    "polygon": "matic",
    "fantom": "ftm",
    "arbitrum": "eth",
    "optimism": "eth",
    "xdai": "xdai",
    "metis": "metis",
    "binancesc": "bnb",
    "harmony": "one",
    "aurora": "eth",
    "zksync-era": "eth",
    "polygon-zkevm": "eth",
    "evmos": "evmos",
    "base": "eth",
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
    f.write("# Instead, see bin/map_assets.py    #\n")
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
        # Split the key if it contains a description in parentheses
        key_parts = k.split(" (", 1)
        key = key_parts[0]
        description = f"  # {key_parts[1][:-1]}" if len(key_parts) > 1 else ""
        f.write(f'    "{key}": "{COSTBASIS_LIKEKIND[k]}",{description}\n')
    f.write("}\n")

    f.write("\n")

    f.write("CHAIN_FEE_ASSETS = {\n")
    for k in CHAIN_FEE_ASSETS:
        f.write(f'    "{k}": "{CHAIN_FEE_ASSETS[k]}",\n')
    f.write("}\n")


if __name__ == "__main__":
    main()
