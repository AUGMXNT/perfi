import json
import logging
import lzma
from tqdm import tqdm

from perfi.db import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


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
        "arbitrum:arb": "ethereum",
        "binancesc:bsc": "binancecoin",
        "ethereum:eth": "ethereum",
        "fantom:ftm": "fantom",
        "metis:metis": "metis-token",
        "optimism:op": "ethereum",
        "polygon:matic": "matic-network",
        "xdai:xdai": "xdai",
        # Tokens
        "fantom:0x8d11ec38a3eb5e956b052f67da8bdc9bef8abf3e": "dai",  # dai
        "fantom:0x328a7b4d538a2b3942653a9983fda3c12c571141": "usd-coin",  # crUSDC/ibUSDC
    }

    for tx_chain in tqdm(results, desc="Scanning Assets from TxChain", disable=None):
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

    for asset in tqdm(results, desc="Updating Assets from TxChain", disable=None):
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

    # Extra Fixups
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
    db.cur.executescript(fixups_sql)
