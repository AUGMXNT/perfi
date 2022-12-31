import hashlib
import json
import logging
import lzma
import sys
from decimal import *
from pprint import pprint

import arrow
from tqdm import tqdm
from web3 import Web3

from perfi.constants.assets import CHAIN_FEE_ASSETS
from ..db import db
from ..models import TxLedgerStore, TxLedger
from ..price import price_feed

messages = (
    []
)  # We'll use this to collect things to show to the user at the end of the script run. Things that might require investigation.


logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


class TokenApproveForOtherAddressException(Exception):
    def __init__(self, message):
        self.message = message


class UnscrapedChainError(Exception):
    def __init__(self, message):
        self.message = message


def update_entity_transactions(entity_name):
    logger.debug(f"Entity: {entity_name}")
    logger.debug("---")
    # Get List of Accounts
    sql = """SELECT address.label, address.chain, address.address
           FROM address
           JOIN entity on entity.id = address.entity_id
           WHERE entity.name = ?
           ORDER BY ord, label
        """
    results = db.query(sql, entity_name)

    for wallet in results:
        label = wallet[0]
        chain = wallet[1]
        address = wallet[2]

        update_wallet_ledger_transactions(address)


def update_wallet_ledger_transactions(address):
    # Clear out old tx_ledger items
    sql = """DELETE FROM tx_rel_ledger_logical
           WHERE tx_ledger_id IN (
             SELECT id FROM tx_ledger WHERE address = ?
           )
        """
    results = db.execute(sql, address)
    sql = """DELETE FROM tx_ledger WHERE address = ?"""
    results = db.execute(sql, address)

    # Getting chain tx's to turn into ledger tx's
    sql = """SELECT chain, address, hash, timestamp, raw_data_lzma
           FROM tx_chain
           WHERE address = ?
           ORDER BY timestamp ASC
        """
    results = db.query(sql, address)

    ledger_txs = []

    for tx_chain in tqdm(results, desc="Generate Ledger TXs", disable=None):
        chain = tx_chain[0]
        hash = tx_chain[2]
        timestamp = tx_chain[3]

        lzmad = lzma.LZMADecompressor()
        raw_data_str = lzmad.decompress(tx_chain[4])
        raw_data = json.loads(raw_data_str)

        logger.debug(
            f'{arrow.get(timestamp).format("YYYY-MM-DD HH:mm:ss")} | {chain:10} | {hash}'
        )

        # First we'll see if this is a tx_chain imported from an exchange.
        # If it is, we'll handle it completely here and not do any of the debank/fee stuff after this section

        # Handle exchange imports
        if chain.startswith("import."):
            # Importers will give us sends and receives in the raw_data, so use it
            for t in raw_data["sends"]:
                tx = LedgerTx(
                    chain=chain,
                    address=address,
                    hash=hash,
                    timestamp=timestamp,
                )
                tx.asset_tx_id = t["asset_tx_id"]
                tx.amount = t["amount"]
                tx.direction = "OUT"
                tx.tx_ledger_type = t["tx_ledger_type"]
                tx.symbol = t["symbol"]
                tx.from_address = t["from_address"]
                tx.to_address = t["to_address"]
                tx.proceeds_after_fees_usd = t.get("proceeds_after_fees_usd", None)
                tx.price_usd = t.get("price_usd", None)
                tx.price_source = t.get("price_source", None)

                tx.isfee = 0
                try:
                    if t["isfee"] == 1:
                        tx.isfee = 1
                except:
                    tx.isfee = 0

                ledger_txs.append(tx)

            for t in raw_data["receives"]:
                tx = LedgerTx(
                    chain=chain,
                    address=address,
                    hash=hash,
                    timestamp=timestamp,
                )
                tx.asset_tx_id = t["asset_tx_id"]
                tx.amount = t["amount"]
                tx.direction = "IN"
                tx.tx_ledger_type = t["tx_ledger_type"]
                tx.symbol = t["symbol"]
                tx.from_address = t["from_address"]
                tx.to_address = t["to_address"]
                tx.price_usd = t.get("price_usd", None)
                tx.price_source = t.get("price_source", None)
                tx.costbasis_including_fees_usd = t.get(
                    "costbasis_including_fees_usd", None
                )

                ledger_txs.append(tx)

            continue

        # If we get this far, we aren't looking at an exchange import, so assume it's a real tx_chain
        # and pull sends/receives from DeBank then make a Fee TxLedger too...

        # Get Receives and Sends from DeBank
        if "debank" in raw_data:
            """
            LATER: If we are going to dissect a UniV3 multicall we may need to do it here and create the appropriate tx_ledgers
            in case we collect yield and unwrap an LP at the same time
            """
            # NOTE: debank time_at seems to be _very_ old. Don't use!
            debank_tx = raw_data["debank"]

            for debank_item in debank_tx["receives"]:
                tx = LedgerTx(
                    chain=chain, address=address, hash=hash, timestamp=timestamp
                )
                # HACK - if we have an invalid debank tx then we don't add it to the ledger_tx at all
                try:
                    tx.from_debank(debank_tx, debank_item, "receive")
                    tx.from_address_name = tx.get_attr_from_explorer(
                        "from_address_name", raw_data
                    )
                    tx.to_address_name = tx.get_attr_from_explorer(
                        "to_address_name", raw_data
                    )
                    ledger_txs.append(tx)
                except Exception as err:
                    raise Exception(f"Coudnt make ledger IN for {debank_item}")
                    pass

            for debank_item in debank_tx["sends"]:
                tx = LedgerTx(
                    chain=chain, address=address, hash=hash, timestamp=timestamp
                )
                try:
                    tx.from_debank(debank_tx, debank_item, "send")
                    tx.from_address_name = tx.get_attr_from_explorer(
                        "from_address_name", raw_data
                    )
                    tx.to_address_name = tx.get_attr_from_explorer(
                        "to_address_name", raw_data
                    )
                    ledger_txs.append(tx)
                except Exception as err:
                    raise Exception(f"Coudnt make ledger OUT for {debank_item}")
                    pass

            # Get the fee tx only if we are the sender (otherwise it's not something we paid for)
            tx = LedgerTx(chain=chain, address=address, hash=hash, timestamp=timestamp)
            if debank_tx["tx"] is not None:
                from_address = debank_tx["tx"]["from_addr"]
                if address.lower() == from_address.lower():
                    tx.fee_from_debank(raw_data)
                    ledger_txs.append(tx)

            # If this is an approval, create a  TxLedger for it
            if debank_tx["cate_id"] == "approve":
                tx = LedgerTx(
                    chain=chain, address=address, hash=hash, timestamp=timestamp
                )
                tx.tx_ledger_type = "approval"
                tx.to_address = debank_tx["other_addr"]
                if "_project" in debank_tx:
                    tx.to_address_name = debank_tx["_project"]["name"]
                tx.from_address = tx.address
                tx.direction = "APPROVE"
                tx.amount = debank_tx["token_approve"]["value"]
                tx.isfee = 0
                try:
                    tx.asset_tx_id = debank_tx["_token"]["id"]
                except:
                    try:
                        tx.asset_tx_id = debank_tx["token_approve"]["token_id"]
                    except:
                        tx_asset_tx_id = None
                [_, tx.symbol, tx.asset_price_id] = tx.normalize_asset(
                    tx.chain, tx.asset_tx_id
                )
                if (
                    tx.symbol is None or tx.symbol.strip() == ""
                ) and "_token" in debank_tx:
                    tx.symbol = debank_tx["_token"]["symbol"]
                ledger_txs.append(tx)

    # Now we have all our ledger_txs, so lets put them into the tx_ledger table in the DB
    tx_ledger_store = TxLedgerStore(db)
    for tx in tqdm(ledger_txs, desc="Saving Ledger TXs", disable=None):
        tx.generate_id()
        tx.assign_tx_ledger_type()
        tx.assign_price()
        tx_ledger_store.save(tx.as_tx_ledger())
        logger.debug(f"Inserted ledger_tx {tx.id}")


# This will look at a Boba transaction hash to determine if its fee was in Boba or ETH
def get_boba_fee_asset(hash: str):
    w3 = Web3(Web3.HTTPProvider("https://mainnet.boba.network"))
    receipt = w3.eth.getTransactionReceipt(hash)
    if receipt["l2BobaFee"] != "0x0":
        return "boba"
    else:
        return "eth"


# This is a helper class that is only used within this sub-module that takes chain data in and creates a proper TxLedger
# LATER: we may want to rename this to something less confusing like TxLedgerCreator, especially if we access this externally anywhere else (but we don't right now so we're leaving this)
class LedgerTx:
    def __init__(self, **kwargs):
        self.id = None
        self.chain = kwargs["chain"]
        self.address = kwargs["address"]
        self.hash = kwargs["hash"]
        self.from_address = None
        self.to_address = None
        self.from_address_name = None
        self.to_address_name = None
        self.asset_tx_id = None
        self.isfee = 0
        self.amount = None

        self.costbasis_including_fees_usd = None
        self.proceeds_after_fees_usd = None
        self.price_usd = None
        self.price_source = None
        self.timestamp = kwargs["timestamp"]
        self.direction = None
        self.tx_ledger_type = None
        self.asset_price_id = None
        self.symbol = None
        self.price_source = None
        self.debank_name = None

        self.TxTyper = TxTyper()

    def __str__(self):
        return f"""
             chain: {self.chain}
             address: {self.address}
             hash: {self.hash}
             from_address : {self.from_address }
             to_address : {self.to_address }
             asset_tx_id : {self.asset_tx_id }
             isfee : {self.isfee }
             amount : {self.amount }

             costbasis_including_fees: {self.costbasis_including_fees_usd}
             proceeds_after_fees_usd: {self.proceeds_after_fees_usd}
             price_usd : {self.price_usd }
             price_source : {self.price_source }

             timestamp: {self.timestamp}
             direction : {self.direction }
             tx_ledger_type : {self.tx_ledger_type }
             asset_price_id : {self.asset_price_id }
             symbol : {self.symbol }
             debank_name : {self.debank_name or '__None__'}
             """

    def generate_id(self):
        # Generate UUID
        try:
            id_to_hash = (
                self.chain
                + self.address
                + self.hash
                + self.from_address
                + self.to_address
                + self.asset_tx_id
                + str(self.isfee)
                + str(self.amount)
            )
            self.id = hashlib.sha256(id_to_hash.encode()).hexdigest()
        except Exception as err:
            logger.debug(f"Error generating ID for LedgerTx.  Attributes: \n {self}")
            logger.debug("Exception:")
            logger.debug(err)
            raise

        # TODO: We need to check the corner case if we have multiple identical tx's - eg, receiving 5 ETH to the same address in the same block
        # If this ever happens, then the tx_ledger is no longer idempotent and can't replay an event_stream deterministically
        # If this happens we can avoid this by summing txs with the same asset_tx_id
        sql = """SELECT COUNT(id) from tx_ledger WHERE id = ?"""
        params = [self.id]
        result = db.query(sql, params)
        if result[0][0] > 1:
            logger.debug(self)
            raise Exception(
                f"{result[0][0]} results- Duplicate ledger_tx: {self.id} hash: {self.hash}"
            )

        return id

    def normalize_asset(self, chain, token_id):
        sql = """SELECT symbol, asset_price_id
             FROM asset_tx
             WHERE chain = ? AND id = ?
          """
        params = [chain, token_id]
        results = db.query(sql, params)
        if len(results) != 1:
            return [None, None, None]
        else:
            symbol = results[0][0]
            asset_price_id = results[0][1]
            return [token_id, symbol, asset_price_id]

    def get_attr_from_explorer(self, attr, raw_data):
        explorer = self.explorer_name()
        try:
            return raw_data[explorer][attr]
        except:
            return None

    def from_debank(self, debank_tx, debank_item, debank_tx_type):
        if debank_tx["tx"] and "name" in debank_tx["tx"]:
            self.debank_name = debank_tx["tx"]["name"]
        if debank_tx_type == "receive":
            self.to_address = self.address
            self.from_address = debank_item["from_addr"]
            self.direction = "IN"
        elif debank_tx_type == "send":
            self.to_address = debank_item["to_addr"]
            self.from_address = self.address
            self.direction = "OUT"
        try:
            tok = debank_item["_token"]
        except:
            # Special case for Uniswap V3 positions
            # LATER: what if we dont have a token we know about? How can we handle this more robustly?
            # - NFT positions are going to be a big class, debank token id maybe not the right one vs from block explorer
            # TODO: this is chain specific contract address (refactor for DDL for protocol-specific overrides)
            if (
                debank_tx["tx"]
                and "to_addr" in debank_tx["tx"]
                and debank_tx["tx"]["to_addr"]
                == "0xc36442b4a4522e871399cd717abdd847ab11fe88"
            ):
                tok = {
                    "name": "Uniswap V3 Position NFT",
                    "symbol": "UNI-V3-POS",
                    "id": "0xc36442b4a4522e871399cd717abdd847ab11fe88",
                }
            else:
                tok = {"id": debank_item["token_id"]}
                # raise Exception(f'No debank token in {self.hash}')
        [self.asset_tx_id, self.symbol, self.asset_price_id] = self.normalize_asset(
            self.chain, tok["id"]
        )  # Is symbol the best key? can also use name or optimized_symbol

        if self.asset_tx_id is None:
            messages.append(
                f"No asset_tx_id found for token. Hash: {self.hash}  Chain: {self.chain}   Tok: {tok}"
            )
            self.asset_tx_id = tok["id"]

        self.amount = debank_item["amount"]

        # debug
        # print(f'{self.perfi_transaction_type:>19} | {self.amount:<10.3f} | {self.asset_id} ({self.symbol})')

    def explorer_name(self):
        explorer_mapping = {
            "ethereum": "etherscan",
            "avalanche": "snowtrace",
            "polygon": "polygonscan",
            "fantom": "ftmscan",
            # 'xdai': 'blockscout (xdai)',
        }
        return explorer_mapping.get(self.chain)

    def fee_from_debank(self, raw_data):
        debank_tx_data = raw_data["debank"]["tx"]
        self.direction = "OUT"
        self.tx_ledger_type = "fee"

        # Set asset_tx_id based on chain
        asset_mapping = {
            "ethereum": "eth",
            "avalanche": "avax",
            "polygon": "matic",
            "fantom": "ftm",
            "xdai": "xdai",
        }

        # Boba does fees in ETH or Boba so we need to inspect the transaction to know
        if self.chain == "boba":
            self.asset_tx_id = get_boba_fee_asset(self.hash)
        else:
            self.asset_tx_id = CHAIN_FEE_ASSETS[self.chain]

        # Assign addresses
        self.from_address = debank_tx_data["from_addr"]
        self.to_address = debank_tx_data["to_addr"]

        try:
            self.amount = Decimal(debank_tx_data["eth_gas_fee"])
            self.isfee = 1

            if self.amount > 0:
                # Use DeBank's USD price
                # Costbasis code downstream wants price_usd to represent the unit price, so we divide total gas fee by amount here
                self.price_usd = Decimal(debank_tx_data["usd_gas_fee"]) / Decimal(
                    self.amount
                )
                self.price_source = "debank"

                if self.price_usd is None:
                    raise Exception(
                        f"Unexpected none value for price_usd from debank\n {self}"
                    )
            else:
                self.price_usd = Decimal(0)
                self.price_source = "zero_fee_value"

            try:
                self.debank_name = (
                    raw_data["debank"]["tx"]["name"]
                    if raw_data["debank"]["tx"]
                    else None
                )
            except:
                self.debank_name = None

            # extra
            self.extra = {}
        except Exception as err:
            pprint(raw_data)
            raise Exception(
                f"Error when trying to create fee from debank data: {err} {raw_data}"
            )

    def assign_tx_ledger_type(self):
        if self.tx_ledger_type:
            return  # We already have a type set (probably due the auto created ledger entry for each fee)
        type = self.TxTyper.get_transaction_type(self)
        self.tx_ledger_type = type
        logger.debug(f'{self.hash} | {type or "__None__"}')

    def assign_price(self):
        if self.chain.startswith("import"):
            # If we have explicit price from an import (e.g. coinbasepro), we'll use what we have, and just set the price_source here and return early.
            if self.price_usd:
                self.price_source = (
                    self.price_source or "exchange_export_file_explicit_price"
                )
                return

            # If we have explicit costbasis info for this asset already (from coinbase import), derive price from that
            elif self.direction == "IN" and self.costbasis_including_fees_usd:
                if Decimal(self.costbasis_including_fees_usd) > 0:
                    self.price_usd = Decimal(
                        self.costbasis_including_fees_usd
                    ) / Decimal(self.amount)
                    self.price_source = "exchange_export_file_explicit_costbasis"
                    return

            # If we have explicit proceeds info for this asset already (from coinbase import), derive price from that
            elif self.direction == "OUT" and self.proceeds_after_fees_usd:
                self.price_usd = Decimal(self.proceeds_after_fees_usd) / Decimal(
                    self.amount
                )
                self.price_source = "exchange_export_file_explicit_proceeds"
                return

            # If this asset is for FIAT, try to convert it to USD
            elif self.asset_tx_id.startswith("FIAT:"):
                from_fiat_symbol = self.asset_tx_id.split(":")[1]
                to_fiat_symbol = "USD"
                if from_fiat_symbol == "USD":
                    price_usd = 1
                    price_source = "exchange_export_file"
                else:
                    price_usd, price_source = price_feed.convert_fiat(
                        from_fiat_symbol,
                        to_fiat_symbol,
                        Decimal(self.amount),
                        int(self.timestamp),
                    )
                self.price_usd = price_usd
                self.price_source = price_source
                return

            else:
                # If we get this far, we were an imported chain TX but didn't get pricing info.
                # Let downstream costbasis pricing handle this (in costbasis.py)
                return

        asset_map = price_feed.map_asset(self.chain, self.asset_tx_id)
        if asset_map:
            # Don't override existing symbol...
            if not self.symbol:
                self.symbol = asset_map["symbol"]
            self.asset_price_id = asset_map["asset_price_id"]
            coin_price = price_feed.get(self.asset_price_id, int(self.timestamp))
            if coin_price:
                self.price_usd = coin_price.price
                self.price_source = coin_price.source

    def as_tx_ledger(self):
        args = dict(
            id=self.id,
            chain=self.chain,
            address=self.address,
            hash=self.hash,
            from_address=self.from_address,
            to_address=self.to_address,
            from_address_name=self.from_address_name,
            to_address_name=self.to_address_name,
            asset_tx_id=self.asset_tx_id,
            isfee=self.isfee,
            amount=self.amount,
            timestamp=self.timestamp,
            direction=self.direction,
            tx_ledger_type=self.tx_ledger_type,
            asset_price_id=self.asset_price_id,
            symbol=self.symbol,
            price_usd=self.price_usd,
            price_source=self.price_source,
        )
        try:
            return TxLedger(**args)
        except Exception as err:
            print(args)
            raise err


class TxTyper:
    def __init__(self):
        # Future: load rules
        pass

    def get_transaction_type(self, tx_ledger):
        # NOTE: would be nice to look at the tx.tx_asset_id instead, but these aren't friendly for all values.
        # eg. when we have 'avax' in asset_tx_id we have symbol None. Conversely when we have symbol avUSD.e in symbol we have asset_tx_id '0x46a51127c3ce23fb7ab1de06226147f446e4a857'
        debank_mappings = {
            "claimed_reward": ["harvest", "claim_rewards"],
            "deposit": ["deposit", "depositETH"],
            "withdraw": ["withdraw", "withdrawETH"],
            "loan_repay": ["repay"],
        }

        mapper = {}
        for type, matches in debank_mappings.items():
            for match in matches:
                mapper[match] = type

        if tx_ledger.debank_name:
            if tx_ledger.debank_name in mapper:
                return mapper[tx_ledger.debank_name]

            return tx_ledger.debank_name

        return None
