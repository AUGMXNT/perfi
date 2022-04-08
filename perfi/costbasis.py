from devtools import debug

from .db import db
from .constants import assets
from .models import (
    TxLogical,
    TxLedger,
    TX_LOGICAL_FLAG,
    AssetPrice,
    CostbasisLot,
    CostbasisDisposal,
)
from .price import price_feed

import arrow
import atexit
from collections import namedtuple, defaultdict
from copy import copy
from datetime import date, datetime
from decimal import Decimal
import jsonpickle
import logging
from pprint import pprint, pformat
import sys
from tqdm import tqdm
from types import SimpleNamespace
import xlsxwriter


logger = logging.getLogger(__name__)


### Helper Functions


# This is added for rounding errors...
CLOSE_TO_ZERO = Decimal(0.0000000001)


def round_to_zero(number):
    if number == None:
        return None

    if Decimal(number) < CLOSE_TO_ZERO:
        return Decimal(0)
    else:
        return Decimal(number)


# Asset
def get_asset_price_record(asset_tx_id=None):
    if asset_tx_id is None:
        raise Exception("You must provide an asset_tx_id to get a tx_price_id for")
    sql = """SELECT p.id, p.source, p.symbol, p.name, p.raw_data
             FROM asset_price p
             JOIN asset_tx a on a.asset_price_id = p.id
             WHERE a.id = ?
          """
    params = [asset_tx_id]
    results = db.query(sql, params)
    if len(results) > 0:
        return AssetPrice(**results[0])
    else:
        return None


def regenerate_costbasis_lots(entity, args=None, quiet=False):
    if quiet:
        global DEBUG
        DEBUG = False

    if not args or not args.resumefrom:
        # Theoretically
        # costbasis_lot is idempotent to tx_ledger_id and we can generally leave it
        # LATER in the future we want to be able to store and replay edits, maybe in costbasis_edits table?
        sql = """DELETE FROM costbasis_lot WHERE entity = ?"""
        db.execute(sql, entity)

        # Clear out costbasis_disposal for each run - this uses an autoincrement ID, must be regenerated
        sql = """DELETE FROM costbasis_disposal WHERE entity = ?"""
        db.execute(sql, entity)

        # Clear out costbasis_income for each run
        sql = """DELETE FROM costbasis_income WHERE entity = ?"""
        db.execute(sql, entity)

    # Get start and end range for year...
    if args and args.year:  # type: ignore
        start_year = int(args.year)  # type: ignore
        end_year = start_year + 1
        start = arrow.get(date(start_year, 1, 1), "US/Pacific")
        end = arrow.get(date(end_year, 1, 1), "US/Pacific")
        start = int(start.timestamp())
        end = int(end.timestamp()) - 1

        daterange_filter = f"AND timestamp >= {start} AND timestamp <= {end}"

        logger.debug("Regenerating costbasis lots for {args.year}.....")
    else:
        logger.debug("Regenerating costbasis lots.....")
        daterange_filter = ""

    # Get all Logical TX's for an entity's accounts
    sql = f"""SELECT id FROM tx_logical
             WHERE address IN (
                 SELECT address
                 FROM address, entity
                 WHERE entity_id = entity.id
                 AND entity.name = ?
             )
             {daterange_filter}
             ORDER BY timestamp ASC
           """
    results = db.query(sql, entity)

    logger.debug(f"Found {len(results)} TxLogicals to process...")

    global last_tx_logical_id
    global finished_cleanly

    last_tx_logical_id = None

    @atexit.register
    def report_last_processed_id():
        if not finished_cleanly:
            print("-------------------------------------------------------------------")
            print("It looks like calculating costbasis didn't finish cleanly...")
            print(f"The last in-progress tx_logical_id was: {last_tx_logical_id}")
            print("-------------------------------------------------------------------")

    stop_skipping = False
    finished_cleanly = False
    for r in tqdm(results, desc="Generating Costbasis", disable=None):
        tx_logical: TxLogical = TxLogical.from_id(id=r["id"], entity_name=entity)
        last_tx_logical_id = r["id"]

        if TX_LOGICAL_FLAG.ignored_from_costbasis.value in [
            f["name"] for f in tx_logical.flags
        ]:
            continue

        if args and args.resumefrom and not stop_skipping:
            if tx_logical.id == args.resumefrom:
                stop_skipping = True
                print(f"Resuming now on tx_logical_id {args.resumefrom} ")
            else:
                continue

        # only process non-empty tx_logicals
        if len(tx_logical.tx_ledgers) > 0:
            try:
                CostbasisGenerator(tx_logical).process()
            except Exception as err:
                logger.error("-----------------")
                logger.error(
                    "Encountered an unknown error when processing a tx_logical for costbasis:"
                )
                logger.error(err, exc_info=True)
                logger.error("TxLogical:")
                logger.error(pformat(tx_logical))
                logger.error("-----------------")

    finished_cleanly = True

    logger.debug(f"Done regenerating costbasis lots for {entity}")


# CostbasisLot
def save_costbasis_lot(lot: CostbasisLot):
    # QUESTION: Do we want to do REPLACE INTO here? Since the ID comes from the tx_ledger_id, it should be safe to do so...
    sql = """REPLACE INTO costbasis_lot
             (
              tx_ledger_id,
              entity,
              address,
              asset_price_id,
              symbol,
              asset_tx_id,
              original_amount,
              current_amount,
              price_usd,
              basis_usd,
              timestamp,
              history,
              flags,
              receipt
             )
             VALUES
             (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           """

    params = [
        lot.tx_ledger_id,
        lot.entity,
        lot.address,
        lot.asset_price_id,
        lot.symbol,
        lot.asset_tx_id,
        round_to_zero(lot.original_amount),
        round_to_zero(lot.current_amount),
        round_to_zero(lot.price_usd),
        round_to_zero(lot.basis_usd),
        lot.timestamp,
        jsonpickle.encode(lot.history),
        jsonpickle.encode(lot.flags),
        lot.receipt,
    ]
    db.execute(sql, params)


# PriceFeed
def get_coinprice_for_asset(chain, asset_tx_id, timestamp):
    asset_price = costbasis_asset_mapper(chain, asset_tx_id)

    if asset_price:
        try:
            return price_feed.get(asset_price["asset_price_id"], timestamp)
        except:
            raise Exception(
                f"Failed to get price from pricefeed despite having an asset_price record of: {asset_price} for asset_tx_id {asset_tx_id}"
            )
    else:
        return None


# CostbasisLot
# TODO: Make this better!
"""
We actually want to map our costbasis_lots with a mapped asset_price_id that is a canonical version
eg, all chain USDC linclude USDC.e should map to USDC.e

costbasis_mapper

we should generate the costbasis_canonical_asset_tx, then match SYMBOL to it

* Bridged Assets
* Wrapped Assets

We have a more aggressive symbol_fallback that needs to be used carefully (or made smarter to skip known receipts of LP tokens...)
"""


def costbasis_asset_mapper(chain, asset_tx_id, symbol_fallback=False):
    # We want things like usdc_on_avax -> usdc_core
    # This will be differen from our asset_tx_id -> asset_price_id mapping because that goes for the most specific asset_price_id it can find, but for costbasis, we want to group all the variants together for LOT MATCHING purposes. This mapping can be used for exposure mapping as well (we need to do additional mappings for exposure since that needs to split LP amounts and account for ib multipliers)

    # This allows up to use our manual COSTBASIS_LIKEKIND matching for imported asset_tx_ids
    if chain.startswith("import."):
        chain = "import"

    tx_key = f"{chain}:{asset_tx_id}"
    canonical_key = None
    symbol = None
    if tx_key in assets.COSTBASIS_LIKEKIND:
        canonical_key = assets.COSTBASIS_LIKEKIND[tx_key]
        sql = """SELECT symbol
                 FROM asset_price
                 WHERE id = ?
              """
        r = db.query(sql, canonical_key)
        symbol = r[0][0]
    else:
        sql = """SELECT asset_price_id, symbol
                 FROM asset_tx
                 WHERE chain = ?
                 AND id = ?
              """
        params = (chain, asset_tx_id)
        r = db.query(sql, params)
        if r:
            canonical_key = r[0][0]
            symbol = r[0][1]

    if canonical_key and symbol:
        return {
            "asset_price_id": canonical_key,
            "symbol": symbol,
        }
    # Only if asked to do a symbol_fallback do we try to match by symbol...
    elif symbol_fallback:
        """
        LATER: Make sure we have guards to protect against known different assets with the same symbol (like QI and QI)
               Also make sure we skip any type of LPs or deposit receipts...
               ??? Are LP tokens really receipts?
        """
        if symbol:
            sql = """SELECT * FROM asset_price
                     WHERE symbol = ?
                     AND market_cap IS NOT NULL
                     ORDER BY market_cap DESC
                  """
            r = db.query(sql, symbol)
            if r:
                return {
                    "asset_price_id": r[0][0],
                    "symbol": symbol,
                }

    return None


# CostbasisDisposal
def save_costbasis_disposal(disposal):
    sql = """INSERT INTO costbasis_disposal
             (entity, address, asset_price_id, symbol, amount, timestamp, duration_held, basis_timestamp, basis_tx_ledger_id, basis_usd, total_usd, tx_ledger_id)
             VALUES
             (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = [
        disposal.entity,
        disposal.address,
        disposal.asset_price_id,
        disposal.symbol,
        round_to_zero(disposal.amount),
        disposal.timestamp,
        disposal.duration_held,
        disposal.basis_timestamp,  # <--
        disposal.basis_tx_ledger_id,
        round_to_zero(disposal.basis_usd),
        round_to_zero(disposal.total_usd),
        disposal.tx_ledger_id,
    ]
    db.execute(sql, params)


# CostbasisLot
def update_costbasis_lot_current_amount(tx_ledger_id, new_amount_remaining):
    sql = """UPDATE costbasis_lot
             SET current_amount = ?
             WHERE tx_ledger_id = ?
          """
    params = [round_to_zero(new_amount_remaining), tx_ledger_id]
    db.execute(sql, params)


# CostbasisLot
def get_costbasis_lot_by_tx_ledger_id(tx_ledger_id):
    sql = """SELECT
                 tx_ledger_id,
                 entity,
                 address,
                 asset_price_id,
                 asset_tx_id,
                 original_amount,
                 current_amount,
                 price_usd,
                 basis_usd,
                 timestamp,
                 history,
                 flags
             FROM costbasis_lot
             WHERE tx_ledger_id = ?
             AND current_amount > 0
             ORDER BY price_usd DESC
          """
    params = [tx_ledger_id]
    result = db.query(sql, params)
    lot = CostbasisLot(*result[0])
    lot._replace(history=jsonpickle.decode(lot.history))
    lot._replace(flags=jsonpickle.decode(lot.flags))
    return lot


def get_url(chain, tx_hash):
    url = {
        "avalanche": f"https://snowtrace.io/tx/{tx_hash}",
        "ethereum": f"https://etherscan.io/tx/{tx_hash}",
        "fantom": f"https://ftmscan.com/tx/{tx_hash}",
        "polygon": f"https://polygonscan.com/tx/{tx_hash}",
    }
    try:
        return url[chain]
    except:
        return tx_hash


### CostbasisGenerator handles all our costbasis logic for a single tx_logical
class CostbasisGenerator:
    def __init__(self, tx_logical):
        self.tx_logical = tx_logical
        self.entity = self.get_entity()
        self.addresses = self.get_addresses()

        # tx_ledgers
        self.ins = []
        self.outs = []
        self.others = []
        self.fee = None

        self.is_receipt = False
        self.is_ownership_change = False
        self.is_disposal = False
        self.is_income = False

        self.debug_print = False

        self.stack = []

    def print_if_debug(self, str):
        if self.debug_print:
            print(str)

    def get_entity(self):
        sql = """SELECT entity.name
                 FROM entity, address
                 WHERE entity.id = address.entity_id
                 AND address = ?
              """
        results = db.query(sql, self.tx_logical.address)
        return results[0][0]

    def get_addresses(self):
        sql = """SELECT address
                 FROM address, entity
                 WHERE entity.id = address.entity_id
                 AND entity.name = ?
              """
        results = db.query(sql, self.entity)
        addresses = [r[0] for r in results]
        return addresses

    # This takes the self.tx_logical and creates the lots and disposals
    def process(self):
        # Ensure clean state
        self.debug_print = False
        self.ins = []
        self.outs = []
        self.others = []
        self.fee = None
        self.is_receipt = False
        self.is_ownership_change = False
        self.is_disposal = False
        self.is_income = False

        logger.debug(f"PROCESSING tx_logical: {self.tx_logical.id}")

        # Let's first populate ins[] outs[] others[] and fee
        self.populate_sorted_tx_ledgers()

        # This is gonna do a lot of hairy stuff for typing tx_logical and tx_ledgers
        self.type_transactions()

        # DEBUG: Use something like this below to turn on detailed lot/drawdown print debugging
        # for assets you want to trace
        # if 'ETH' in [t.symbol for t in self.ins] or 'ETH' in [t.symbol for t in self.outs]:
        #     self.debug_print = True

        self.print_if_debug("\n\n===========================")
        self.print_if_debug(
            datetime.fromtimestamp(self.tx_logical.timestamp).isoformat()
        )
        self.print_if_debug("INs")
        for t in self.ins:
            self.print_if_debug(f"{t.chain} {t.address} {t.hash} {t.amount} {t.symbol}")
        self.print_if_debug("OUTs")
        for t in self.outs:
            self.print_if_debug(f"{t.chain} {t.address} {t.hash} {t.amount} {t.symbol}")

        ### Establish our properties
        # LATER: this may differ based on an entity's tax treatment preferences/regime

        # is_disposal
        disposal_types = [
            "lp",
            "swap",
            "spend",
            "disposal",  # 'disposal' is currently used by tests but might be useful elsewhere as well in future
        ]
        if self.tx_logical.tx_logical_type in disposal_types:
            self.is_disposal = True

        # A trade where the OUT is FIAT is BUY, not a disposal
        elif self.tx_logical.tx_logical_type == "trade" and not self.outs[
            0
        ].asset_tx_id.startswith("FIAT:"):
            self.is_disposal = True

        # TODO: revisit and see if we actually use this
        # is_ownership_change
        ownership_change_types = [
            "send",
            "receive",
            "yield",
            "income",
            "airdrop",
            "claim",
            "gift",
            "borrow",
        ]
        if self.tx_logical.tx_logical_type in ownership_change_types:
            self.is_ownership_change = True

        # Disposals are always ownership changes...
        if self.is_disposal == True:
            self.is_ownership_change = True

        # In the case of a send/receive we need to determine if it's to a third party and then will also have an ownership change
        # Skipping for now until we have to look at uncategorized stuff

        # is_receipt
        """
        is_receipt will determine whether we need to do an additional unwind on the history[].lots only in the case of a ownership_change of a is_receipt lot.

        for a deposit(), we still to determine which one of the ins is the receipt lot
        however, this is_receipt flag will be used for drawdown_from_lots()

        we also use this for create_lots() to determine if a lot is a receipt or not

        NOTE: in cases where we have mixed lots (eg, some lots should be receipts and some not, like a Beefy deposit), or a withdrawal where the excess lots created are income, then we can't use create_lots()

        is_receipt is not very smart at the moment - it doesn't actually know if we're transacting with a receipt token, eg if we're sending a receipt (it only knows that if we've assigned receipt to a lot that it's dealing with. I'm not sure we can fix this unless we have a receipt_map and specify certain tokens as receipts. This becomes potentially quite hairy if we are frequently transacting with receipt tokens directly but our "deposit_receipt" tests should make sure we're the right thing)
        LATER: we need to make sure that a receipt property is stored in the tx_ledger, or against a token or is it depend on the context? eg, if you're trading a receipt token directly (sSPELL, yvBOOST) you should never have to worry about the underlying/history) - we have a history guard that should ameliorate this somewhat
        """
        # we don't include "repay" or withdraw since we don't usually receive a receipt...
        if self.tx_logical.tx_logical_type == "deposit" and len(self.ins) >= 1:
            self.is_receipt = 1
        # if self.tx_logical.tx_logical_type == 'withdraw' and len(self.outs) >= 1:
        #     self.is_receipt = 1
        if self.tx_logical.tx_logical_type == "borrow" and len(self.ins) > 1:
            self.is_receipt = 1
        # if self.tx_logical.tx_logical_type == 'repay' and len(self.outs) > 1:
        #     self.is_receipt = 1

        ### Processing transaction types
        """
        We are calling specific functions for each type because they can have unique and complex interactions

        NOTE: create_lots() can be dangerous because we don't know if an "in" tx is actually a receipt or not
        """

        self.print_if_debug(self.tx_logical.tx_logical_type)
        if self.tx_logical.tx_logical_type == "trade":
            tout = self.outs[0]
            tin = self.ins[0]
            self.print_if_debug(
                f"OUT {tout.amount} {tout.symbol}    IN {tin.amount} {tin.symbol}"
            )

        ### Least specific typing
        if self.tx_logical.tx_logical_type == "self_transfer":
            # this is a no-op since we don't aren't creating a new costbasis or any drawdowns when we send to ourselves
            pass

        # If a trade is a BUY from fiat, we only create a lot (otherwise, we have already set it to is_disposal and it will drawdown_from_lots and create disposals as appropriate)
        elif self.tx_logical.tx_logical_type == "trade" and self.outs[
            0
        ].asset_tx_id.startswith("FIAT:"):
            self.create_lots()

        # Wrap and unwrap
        # there should be no costbasis change for wrapping or unwrapping so we nothing
        elif self.tx_logical.tx_logical_type == "wrap":
            pass
        elif self.tx_logical.tx_logical_type == "unwrap":
            pass

        # Deposit can be complex
        elif self.tx_logical.tx_logical_type == "deposit":
            self.deposit()

        elif self.tx_logical.tx_logical_type == "withdraw":
            self.withdraw()

        elif self.tx_logical.tx_logical_type == "borrow":
            self.borrow()

        elif self.tx_logical.tx_logical_type == "repay":
            self.repay()

        # LATER: think about receiving a gift, or a donation
        elif self.tx_logical.tx_logical_type == "gift":
            for t in self.outs:
                lots = LotMatcher().get_lots(t)
                self.drawdown_from_lots(lots, t)

            # We'd expect to get nothing or if we are receiving one in then treat as a receipt
            # otherwise we should flag this...
            if len(self.ins) == 1:
                self.is_receipt = True
                self.create_lots()
            elif len(self.ins) > 1:
                logging.warning(
                    "We are giving a gift but for some reason receiving more than one thing:\n{pformat(self.ins)}"
                )

        #### Disposals
        elif self.is_disposal:
            self.create_lots()
            if self.tx_logical.tx_logical_type == "swap" and len(self.outs) != 1:
                logging.error("--- CostbasisGenerator.process disposal ---")
                logging.error(
                    f"Currently dont know how to handle swaps with more than one OUT {pformat(self.tx_logical)}"
                )
                # raise Exception('Currently dont know how to handle swaps with more than one OUT', self.tx_logical)
            else:
                # We now add a guard to make sure that we know what our maximum disposal should be in USD - it can't be more than what we got in...
                # This is only relevant for "swap" or "lps"
                if not self.ins:
                    max_disposal_usd = None
                else:
                    max_disposal_usd = Decimal(0.0)
                    for t in self.ins:
                        # If we don't have a price, then let's just continue as before...
                        if t.price_usd is None:
                            max_disposal_usd = None
                            break
                        else:
                            max_disposal_usd += Decimal(t.price_usd) * Decimal(t.amount)

                for t in self.outs:
                    lots = LotMatcher().get_lots(t)
                    self.drawdown_from_lots(lots, t, max_disposal_usd=max_disposal_usd)

        # income
        elif self.tx_logical.tx_logical_type in ["yield", "airdrop", "income"]:
            for t in self.ins:
                self.create_costbasis_income(t)

        # Contract interactions? We don't have method names sadly...
        elif len(self.ins) == 0 and len(self.outs) == 0 and self.fee:
            # we're just paying a fee, assume it's for an interaction...
            # Later: maybe flag for combining? We should see if we can parse token approvals...
            pass

        elif self.tx_logical.tx_logical_type == "receive":
            self.create_lots()

        elif self.tx_logical.tx_logical_type == "send":
            for t in self.outs:
                lots = LotMatcher().get_lots(t)
                self.drawdown_from_lots(lots, t)

        # If this ever happens we should make sure our tx_logical typer is smarter
        else:
            logging.error("--- CostbasisGenerator.process unknown type ---")
            logging.error(
                f"Trying to create disposal for unknown type: {self.tx_logical.tx_logical_type} \n{pformat(self.tx_logical)}"
            )
            # raise Exception(f"Trying to create disposal for unknown type: {self.tx_logical.tx_logical_type} \n{pformat(self.tx_logical)}")

    """
    Sort tx_ledger into basics...
    """

    def populate_sorted_tx_ledgers(self):
        for t in self.tx_logical.tx_ledgers:
            if t.tx_ledger_type == "fee":
                self.fee = t
            elif t.direction == "IN":
                self.ins.append(t)
            elif t.direction == "OUT":
                self.outs.append(t)
            else:
                logger.debug(pformat("What type of tx is this? Not fee, IN or OUT..."))
                logger.debug(pformat(t))
                self.others.append(t)

    def type_transactions(self):
        self.tx_logical.refresh_type()  # LATER: why do we still need this? (tests say we do but shouldnt this be done once on INIT and it's enough? lets figure it out later)

    """
    We take most of the logic from costbasis_handle_asset_received(entity, address, event)
    """

    def create_lots(self):
        # We'll be creating costbasis lots in this function, since we received asset in.
        # It may be flagged for review (if zero cost)
        # or marked as a receipt lot (if we received our asset as part of a deposit/etc)
        for t in self.ins:
            # We don't track fiat in costbasis lots b/c it doesn't apply for fiat
            if t.asset_tx_id.startswith("FIAT:"):
                continue

            logger.debug("---")
            logger.debug("Creating lot...")
            logger.debug(pformat(t))

            # These are flags for each costbasis_lot generated
            flags = []
            chain = t.chain

            # TODO: Refactor
            price, _ = self.get_costbasis_price_and_source(t)
            if price == Decimal(0.0):
                # If we couldn't establish price, flag for review
                flags.append(
                    {
                        "name": "zero_price",
                        "description": "Couldn't establish a cost basis price for asset (set to $0)",
                    }
                )

            # We want to make sure that we are tracking the swap history for receipt assets
            # This is typically to track the original token for a deposit or withdrawal receipt
            # our history is just going to be an array of tx_ledgers that gets jsonpickled
            lot_history = []
            if self.is_receipt:
                # We store the other tx_ledgers (besides itself)
                # LATER: we may want account for fees somehow...

                # For a deposit, we only care about the outs...
                if self.tx_logical.tx_logical_type in ["deposit", "gift", "payment"]:
                    for t_history in self.outs:
                        if t.id != t_history.id:
                            lot_history.append(t_history)
                if self.tx_logical.tx_logical_type == "borrow":
                    for t_history in self.ins:
                        if t.id != t_history.id:
                            lot_history.append(t_history)

            self.create_costbasis_lot(
                t, price, receipt=self.is_receipt, history=lot_history, flags=flags
            )

    def create_reconciliation_lot(self, t, current_amount, history=None):
        self.print_if_debug(f"** RECONCILIATION LOT: {current_amount} is left")
        # We want the asset_price_id
        mapped_asset = costbasis_asset_mapper(t.chain, t.asset_tx_id)
        if mapped_asset:
            asset_price_id = mapped_asset["asset_price_id"]
            symbol = mapped_asset["symbol"]
        else:
            asset_price_id = None
            symbol = None

        # Get the price to use for this lot based on our `t` below
        sale_price, _ = self.get_costbasis_price_and_source(t)

        flags = []
        flags.append(
            {
                "name": "auto_reconciled",
                "description": "Ran out of costbasis lots for asset; create a new reconciliation lot before consuming it",
            }
        )

        history = history or []
        lot = CostbasisLot(
            tx_ledger_id=t.id,
            original_amount=current_amount,
            current_amount=0.0,
            address=t.address,
            entity=self.entity,
            asset_price_id=asset_price_id,
            symbol=symbol,
            asset_tx_id=t.asset_tx_id,
            # An overdrawn, auto-reconciled lot should be 0 cost basis
            price_usd=0.0,
            basis_usd=0.0,
            timestamp=t.timestamp,
            history=history,
            flags=flags,
            receipt=0,
        )
        save_costbasis_lot(lot)
        return lot

    def deposit(self):
        # In a normal case, we deposit an asset and receive a receipt, we create a lot for the receipt
        # We use this lot in the case of redeeming the receipt for our original assets
        # We use the history to calculate our income based on the deposit vs withdrawal ratios
        # We unwind the history to drawdown (and maybe dispose?) the original asset if we change ownership of the receipt
        if len(self.outs) == 1 and len(self.ins) == 1:
            self.create_lots()
            return

        # Tomb TShares does not generate a deposit receipt
        elif len(self.outs) == 1 and len(self.ins) == 0:
            # We don't need to do anything
            return

        # Kogecoin deposit?
        elif len(self.outs) == 0 and len(self.ins) == 1:
            # LATER: revisit
            # Most don't have deposit receipts...
            # logging.error('--- CostbasisGenerator.deposit ---')
            # logging.error(f"No deposit receipt? {pformat(self.tx_logical)}")
            self.create_lots()
            return

        # Beefy has 2 ins and one out, gives you change)
        elif len(self.outs) == 1 and len(self.ins) == 2:
            deposit: TxLedger = self.outs[0]
            actual_deposit_amount = deposit.amount

            receipts = []
            for received in self.ins:
                # If we get the same token back, it is "change" that never gets deposited
                if received.asset_tx_id == deposit.asset_tx_id:
                    actual_deposit_amount -= received.amount
                # Let's see if this is a wrapped token for a native coin...
                elif (
                    f"{received.chain}:{received.asset_tx_id}" in assets.WRAPPED_TOKENS
                ):
                    # We need to create a non-disposal wrapped token deposit
                    self.create_costbasis_lot(
                        received, 0, receipt=True, history=[deposit]
                    )
                    # We treat the wrapped token the same as unwrapped for our deposit math
                    actual_deposit_amount -= received.amount
                # There is hopefully one receipt, but maybe not...
                else:
                    receipts.append(received)

            # If not die...
            if not receipts:
                logging.error("--- CostbasisGenerator.deposit ---")
                logging.error(
                    f"We didn't have a deposit receipt left in TxLog after counting change in {pformat(self.tx_logical)}"
                )
                return
                # raise Exception(f"We didn't have a deposit receipt left in TxLog after counting change in {pformat(self.tx_logical)}")
            if len(receipts) > 1:
                logging.error("--- CostbasisGenerator.deposit ---")
                logging.error(
                    f"We still have multiple potential deposit receipts after counting change in {pformat(receipts)}"
                )
                return
                # raise Exception(f"We still have multiple potential deposit receipts after counting change in {pformat(receipts)}")

            history_txle = copy(deposit)
            history_txle.amount = actual_deposit_amount

            # We create our receipt lot now with the history attached, but with the amount adjusted to the actual deposit amount for our ratio calculations...
            # We set the price to 0; it's not a disposal so doesn't matter... LATER (check)
            self.create_costbasis_lot(
                receipts[0], 0, receipt=True, history=[history_txle]
            )

            # We don't know how to handle more...
        else:
            logging.error(
                f"SKIPPING We don't know how to handle a deposit with and {len(self.ins)} INS {len(self.outs)} OUTs",
                self.ins,
                self.outs,
            )
            ### XXX TODO: HACK: just seeing how far we can get...
            # raise Exception(f"We don't know how to handle a deposit with and {len(self.ins)} INS {len(self.outs)} OUTs", self.ins, self.outs)

    # Handler for withdrawal outputs
    def withdraw(self):
        # Later: TOMB does not have a deposit receipt - see clickup for discussion of proper unwinding
        """
        To correctly calculate income for tomb, we need to know how much we deposited originally.
        We need to generate virtual deposit receipt lots "perfi_receipt:TOMB" receipt=True...
        """
        # for now we do nothing
        if not self.outs:
            # TODO
            return

        # This is a withdraw but might be like a bridge
        if not self.ins:
            # XXX: TODO
            # it's a transfer... if 0x00000 - burn; is really a bridge?
            # Maybe need smarter typer
            # No disposal...
            return

        """
        LATER: in the future we should think about refunds when there was a drawdown? but for now we have a special case for a withdrawal with Juicebox
        you *should* have the right info in receipt history to be able to unwind
        and instead of lot matching, you should probably just add back in what you drewdown from
        * the gift amount your receive
        * the amount of the receipt you drawdown
        * we should try to reincrement what we drewdown from - do we store this?
        """

        """
        Here we need to create lots and income if we got back more than we put in
        """
        t = self.outs[
            0
        ]  # Should only be 1 out for a withdrawal (this is an assumption that might be wrong but we think is ok)
        lots = LotMatcher().get_lots(t)

        # This is how much of our deposit receipt (eg avWAVAX) we are redeeming
        deposit_receipt_balance = Decimal(t.amount)

        ### HACK: Temporary workaround for float rounding issues
        deposit_receipt_balance = round(deposit_receipt_balance, 9)

        # This is how much we actually got back from our deposit (AVAX)
        deposit_withdrawal_balance_remaining = Decimal(self.ins[0].amount)

        for lot in lots:
            # Amount to subtract, limited to what can be deducted from the lot size
            amount_to_subtract_from_lot = Decimal(
                min(deposit_receipt_balance, lot.current_amount)
            )

            # For this lot, lets see how much original deposit we should redeem
            """
            We need to debit our deposit_receipt_balance (avWAVAX) amount
            But we also need to debit the deposit_withdrawal_balance (AVAX)
            To do this, we need to calculate the amount of AVAX from each avWAVAX we converted
            The remaining deposit_withdrawal_balance is income/loss stored in costbasis_income
            """
            if lot.history:
                try:
                    ratio_of_deposit_receipt_to_deposit = Decimal(
                        lot.original_amount
                    ) / Decimal(lot.history[0].amount)
                    percent_of_original_lot = amount_to_subtract_from_lot / Decimal(
                        lot.original_amount
                    )
                    deposit_redeemed = (
                        percent_of_original_lot
                        * amount_to_subtract_from_lot
                        / ratio_of_deposit_receipt_to_deposit
                    )
                except:
                    deposit_redeemed = amount_to_subtract_from_lot
            else:
                """
                If there's no lot history, we aren't dealing with a proper receipt, or can't unwind if it is?
                So we can't calculate income, so we just draw down and get out of here.
                LATER: we should try to properly drawdown all the sent items (receipt or not) and do the asset redemption separtely...
                """
                logging.error(
                    f"Withdrawal without a history, not a receipt? We will drawdown this lot but not try to calculate income. You should look at this lot to make sure whats going on:\n {pformat(lot)}"
                )
                update_costbasis_lot_current_amount(
                    lot.tx_ledger_id,
                    round(
                        Decimal(lot.current_amount)
                        - Decimal(amount_to_subtract_from_lot),
                        18,
                    ),
                )
                return

            ### HACK: Temporary workaround for float rounding issues from lot.original_amount
            deposit_redeemed = round(deposit_redeemed, 9)
            deposit_withdrawal_balance_remaining -= deposit_redeemed

            # Subtract from the lot's `current_amount`
            update_costbasis_lot_current_amount(
                lot.tx_ledger_id,
                round(
                    Decimal(lot.current_amount) - Decimal(amount_to_subtract_from_lot),
                    18,
                ),
            )

            deposit_receipt_balance -= amount_to_subtract_from_lot

            if deposit_receipt_balance <= CLOSE_TO_ZERO:
                break

        # We assign the remaining deposit_withdrawal_balance to our history TxLedger
        history_txle = copy(self.ins[0])
        history_txle.amount = deposit_withdrawal_balance_remaining

        # Reconcilation lots if we still have deposit_receipt_balance
        if deposit_receipt_balance > CLOSE_TO_ZERO:
            lot = self.create_reconciliation_lot(
                t, deposit_receipt_balance, history=[history_txle]
            )

        # Track income, create lot if we earned more
        if (
            deposit_withdrawal_balance_remaining > CLOSE_TO_ZERO
            or deposit_withdrawal_balance_remaining < CLOSE_TO_ZERO
        ):
            self.create_costbasis_income(history_txle)

    # Handler for loan repayment outputs
    def borrow(self):
        # This is a loan with no receipt
        if len(self.ins) == 1:
            self.is_receipt = False
            self.create_lots()
            return

        # First, we need to determine which IN (we should have 2) is the loan_receipt and which is the loan_asset
        # The general way is to look for the IN that has a tx_ledger.asset_price_id
        # If this doesn't work we need to brute force and see which one lots are receipt and history
        # If we can't differentiate then we need to raise because otherwise we will break the world (can't arbitrarily unwind)
        loan_asset = None
        loan_receipt = None

        if len(self.ins) > 2:
            logging.error("--- CostbasisGenerator.borrow ---")
            logging.error(
                f"We don't know how to handle a loan with more than 2 ins {pformat(self.ins)}"
            )
            return

        # Try to find the asset by the in that has an asset_price_id
        for t in self.ins:
            if t.asset_price_id:
                loan_asset = t
            else:
                loan_receipt = t

        if not loan_asset or not loan_receipt:
            logging.error("--- CostbasisGenerator.borrow ---")
            logging.error(
                f"We cant determine which in is a loan_receipt and which is a loan_asset {pformat(self.ins)}"
            )
            return

        flags = []
        price, _ = self.get_costbasis_price_and_source(loan_asset)
        if price == Decimal(0.0):
            # If we couldn't establish price, flag for review
            flags.append(
                {
                    "name": "zero_price",
                    "description": "Couldn't establish a cost basis price for asset (set to $0)",
                }
            )

        # Now we add assign our loan_asset and loan_receipt
        self.create_costbasis_lot(
            loan_asset, price, receipt=False, history=[loan_receipt], flags=flags
        )
        self.create_costbasis_lot(
            loan_receipt, price, receipt=True, history=[loan_asset], flags=flags
        )

    # Handler for loan repayment outputs
    def repay(self):
        # First, we need to determine which OUT (we should have 2) is the loan_receipt and which is the loan_asset
        # The general way is to look for the OUT that has a tx_ledger.asset_price_id
        # If this doesn't work we need to brute force and see which one lots are receipt and history
        # If we can't differentiate then we need to raise because otherwise we will break the world (can't arbitrarily unwind)
        loan_asset = None
        loan_receipt = None

        if len(self.outs) > 2:
            logging.error("--- CostbasisGenerator.repay ---")
            logging.error(
                f"We don't know how to handle a loan repayment with more than 2 outs {pformat(self.outs)}"
            )
            return

        # Try to find the asset by the out that has an asset_price_id
        for out in self.outs:
            if out.asset_price_id:
                loan_asset = out
            else:
                loan_receipt = out

        # If that didn't work we try to brute force things by looking at the lots
        if not loan_asset:
            for out in self.outs:
                lots = LotMatcher().get_lots(out)
                if lots:
                    if lots[0].receipt and lots[0].history:
                        loan_receipt = out
                    else:
                        loan_asset = out

        if not loan_asset or not loan_receipt:
            logging.error("--- CostbasisGenerator.repay ---")
            logging.error(
                f"We cant determine which out is a loan_receipt and which is a loan_asset {pformat(self.outs)}"
            )
            return
            # raise Exception('We cant determine which out is a loan_receipt and which is a loan_asset', self.outs)

        ### Now we can actually calculate our loan repayments

        # This is how much of our loan receipt (eg avWAVAX) we are redeeming
        loan_receipt_balance = Decimal(loan_receipt.amount)

        ### HACK: Temporary workaround for float rounding issues
        loan_receipt_balance = round(loan_receipt_balance, 9)
        logger.debug(f"Loan receipt sent: {loan_receipt_balance} {loan_receipt.symbol}")

        # This is how much we actually got back from our loan (AVAX)
        loan_asset_repaid = Decimal(loan_asset.amount)
        loan_asset_repaid = round(loan_asset_repaid, 9)
        logger.debug(f"Loan asset repaid: {loan_asset_repaid} {loan_asset.symbol}")

        # This is always what we will use to calculate how much of the original loan to redeem
        receipt_to_asset_ratio_repay = loan_receipt_balance / loan_asset_repaid

        # We need these to total up what we originally borrowed and get our income difference
        loan_asset_originally_borrowed = Decimal(0.0)

        # Loan receipts
        lots = LotMatcher().get_lots(loan_receipt)
        for lot in lots:
            # Amount to subtract, limited to what can be deducted from the lot size
            amount_to_subtract_from_lot = Decimal(
                min(loan_receipt_balance, lot.current_amount)
            )
            amount_to_subtract_from_lot = round(amount_to_subtract_from_lot, 9)

            percent_of_original_lot = amount_to_subtract_from_lot / Decimal(
                lot.original_amount
            )

            # We need to tally our for the receipts that we consume, what the original borrowed assets were
            try:
                receipt_to_asset_ratio_borrowed = Decimal(
                    lot.original_amount
                ) / Decimal(lot.history[0].amount)
            except:
                receipt_to_asset_ratio_borrowed = 1
            loan_asset_originally_borrowed += round(
                percent_of_original_lot
                * amount_to_subtract_from_lot
                / receipt_to_asset_ratio_borrowed,
                9,
            )

            ### We need to handle the actual repayment of the loan_asset (subtract from our costbasis_lots)
            loan_redeemed = (
                percent_of_original_lot
                * amount_to_subtract_from_lot
                / receipt_to_asset_ratio_repay
            )
            loan_redeemed = round(loan_redeemed, 9)
            asset_redeemed_txle = copy(loan_asset)
            asset_redeemed_txle.amount = loan_redeemed
            asset_lots = LotMatcher().get_lots(loan_asset, algorithm="low")
            self.drawdown_from_lots(asset_lots, asset_redeemed_txle)

            # Subtract from the loan_receipt lot's `current_amount`
            update_costbasis_lot_current_amount(
                lot.tx_ledger_id,
                round(
                    Decimal(lot.current_amount) - Decimal(amount_to_subtract_from_lot),
                    18,
                ),
            )

            loan_receipt_balance -= amount_to_subtract_from_lot

            if loan_receipt_balance <= CLOSE_TO_ZERO:
                break

        # This is the difference between what we repaid and what we originally borrowed
        loan_asset_balance = loan_asset_originally_borrowed - loan_asset_repaid

        # We assign the remaining loan_withdrawal_balance to our history TxLedger
        history_txle = copy(loan_asset)
        history_txle.amount = loan_asset_balance

        # Reconcilation lots if we still have loan_receipt_balance
        if loan_receipt_balance > CLOSE_TO_ZERO:
            lot = self.create_reconciliation_lot(
                loan_receipt, loan_receipt_balance, history=[history_txle]
            )

        # Track income, create lot if we earned more
        if loan_asset_balance > CLOSE_TO_ZERO or loan_asset_balance < CLOSE_TO_ZERO:
            self.create_costbasis_income(history_txle)

    def create_costbasis_income(self, tin):
        # Create income record
        sql = """INSERT INTO costbasis_income
                 (entity, address, net_usd, symbol, timestamp, tx_ledger_id, price, amount, lots)
                 VALUES
                 (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        sale_price, _ = self.get_costbasis_price_and_source(tin)
        amount = tin.amount
        net_usd = Decimal(amount) * sale_price

        # Mapped version of symbol only (price is from get_costbasis_price_and_source...)
        mapped_asset = costbasis_asset_mapper(tin.chain, tin.asset_tx_id)
        if mapped_asset:
            symbol = mapped_asset["symbol"]
        else:
            symbol = tin.symbol

        # LATER: we may not need lots (last arg, passed as an empty []) at all
        params = [
            self.entity,
            tin.address,
            round_to_zero(net_usd),
            symbol,
            tin.timestamp,
            tin.id,
            round_to_zero(tin.price_usd),
            round_to_zero(amount),
            jsonpickle.encode([]),
        ]
        db.execute(sql, params)

        # Also create a costbasis lot for this if we got more of the asset
        if amount > 0:
            self.create_costbasis_lot(tin, sale_price)

    def create_costbasis_lot(self, t, price, receipt=False, history=[], flags=[]):
        asset_price_id = None
        """
        This code will store the costbasis mapped asset_price_id and symbol into CostbasisLot.
        This should be a cross-chain canonical (eg: usd-coin, USDC for all variations/chains and is what we use to intelligently do like-kind asset math on all our costbasis lots/drawdowns)
        """
        mapped_asset = costbasis_asset_mapper(t.chain, t.asset_tx_id)
        if mapped_asset:
            asset_price_id = mapped_asset["asset_price_id"]
            symbol = mapped_asset["symbol"]
        else:
            asset_price_id = None
            symbol = None

        # LATER: we should be considering TxLogical fees, approvals, etc...
        basis_usd = Decimal(price) * Decimal(t.amount)

        lot = CostbasisLot(
            tx_ledger_id=t.id,
            entity=self.entity,
            address=t.address,
            asset_price_id=asset_price_id,
            symbol=symbol,
            asset_tx_id=t.asset_tx_id,
            original_amount=Decimal(t.amount),
            current_amount=Decimal(t.amount),
            price_usd=price,
            basis_usd=basis_usd,
            timestamp=t.timestamp,
            history=history,
            flags=flags,
            receipt=receipt,
        )
        save_costbasis_lot(lot)
        self.print_if_debug(
            f"{datetime.fromtimestamp(t.timestamp)}  |  LOT_CREATED | {lot.original_amount} {lot.symbol} @ {lot.basis_usd}"
        )

    def drawdown_from_lots(self, lots, t, is_disposal=None, max_disposal_usd=None):
        # Normally we want to use self.is_disposal, except in the case where we are unwinding a disposal of a receipt
        # in that case, we actually need to pass in is_disposal = False to make sure we drawdown but do not generate a disposal
        # for the original asset
        if is_disposal is None:
            is_disposal = self.is_disposal

        if self.debug_print:
            self.print_if_debug("-------------------------------")
            self.print_if_debug(datetime.fromtimestamp(t.timestamp).isoformat())
            self.print_if_debug(f"Need to drawdown {t.amount} {t.symbol}")
            for l in lots:
                self.print_if_debug(
                    f"\t {l.timestamp} has {l.current_amount} / {l.original_amount} @ {l.basis_usd}"
                )

        amount_left_to_subtract = Decimal(t.amount)
        while amount_left_to_subtract > CLOSE_TO_ZERO:
            for lot in lots:
                # up to the amount of the lot
                amount_to_subtract_from_lot = min(
                    amount_left_to_subtract, lot.current_amount
                )

                # We set this whether these is a disposal or not
                amount = Decimal(amount_to_subtract_from_lot)

                # Get the costbasis_lot's price if it's an ownership change, otherwise we don't care
                lot_price = None
                if self.is_ownership_change:
                    # We will do a single unwind if receipt to get the original cost basis
                    # this will override any included lot_price (but is probably more accurate)
                    lot_price = Decimal(lot.price_usd)
                    if lot.receipt and lot.history:
                        # if lot is receipt, we need to follow history to get the cost basis
                        history_tx = lot.history[0]
                        coin_price = get_coinprice_for_asset(
                            history_tx.chain,
                            history_tx.asset_tx_id,
                            history_tx.timestamp,
                        )
                        if not coin_price:
                            # We set our disposal basis price as 0...
                            coin_price = SimpleNamespace(price=0.0)
                            """ LATER TODO: assign this flag somewhere appropriate???
                            We should have flags stored with a disposal, right?
                            flags.append({
                                "name": "zero_price",
                                "description": "Couldn't establish a cost basis price for asset (set to $0)",
                            })
                            """
                            # LATER: (maybe TODO soon?) next time we see this, we should instead set costbasis to 0
                            logging.error(
                                f"Couldnt get price for {history_tx}\n\ntxlogical:\n{self.tx_logical}\n\nt: {t} \n\nlotmatcher lots:\n{pformat(lots)}"
                            )

                        if coin_price.price:
                            # Lastly, we multiply by the ratio of the drawdown amount from the original amount
                            lot_price = (
                                Decimal(coin_price.price)
                                * Decimal(history_tx.amount)
                                / Decimal(lot.original_amount)
                            )

                    # Sale Price
                    sale_price, _ = self.get_costbasis_price_and_source(t)

                    # Attrs for new Costbasis disposal row
                    total_usd = amount * sale_price
                    basis_usd = amount * lot_price

                    # max_disposal guard simple - note, this should be less if we were multi-out aware
                    if max_disposal_usd:
                        if total_usd > max_disposal_usd:
                            logging.error(
                                f"The calculated total {total_usd} is greater than max_disposal_usd {max_disposal_usd}, be sure to check on:\n{t}"
                            )
                            total_usd = max_disposal_usd
                            # LATER: we probably need a flag for this as well...

                    # Asset and Price
                    """
                    We should assign the mapped symbol into disposal
                    First if there's an unwind, try to use the unwound asset
                    t:  asset
                    tx: unwound asset
                    """
                    # Fallback
                    asset_price_id = t.asset_price_id
                    symbol = t.symbol
                    if symbol:
                        sql = "SELECT id FROM asset_price WHERE symbol = ?"
                        r = db.query(sql, symbol)
                        try:
                            asset_price_id = r[0][0]
                        except:
                            pass

                    # Normally we want to be aggressive about how we map our assets for drawdowns, except in the case of a
                    # receipt
                    if not lot.receipt:
                        try:
                            # Try to get a mapped price/symbol from unwound tx
                            mapped_asset = costbasis_asset_mapper(
                                history_tx.chain, history_tx.asset_tx_id
                            )
                            asset_price_id = mapped_asset["asset_price_id"]
                            symbol = mapped_asset["symbol"]
                        except:
                            # Try to get mapped price/symbol from tx
                            try:
                                mapped_asset = costbasis_asset_mapper(
                                    t.chain, t.asset_tx_id
                                )
                                asset_price_id = mapped_asset["asset_price_id"]
                                symbol = mapped_asset["symbol"]
                            except:
                                pass

                    duration_held = t.timestamp - lot.timestamp
                    timestamp = t.timestamp
                    tx_ledger_id = t.id

                    # Only if we're also transferring ownership or a receipt, then we also need to subtract the original deposit amount
                    if lot.receipt and lot.history:
                        history_tx = copy(lot.history[0])
                        history_asset_lots = LotMatcher().get_lots(
                            history_tx, algorithm="low"
                        )

                        # We need to get the amount of the original asset to drawdown
                        # this is based on percent of the lot and multiplied by the original conversion amount
                        history_tx.amount = (
                            amount / Decimal(lot.original_amount) * history_tx.amount
                        )

                        # We call drawdown to subtract the original lots...

                        # Emergency recursion guard
                        self.stack.append(lot)
                        if len(self.stack) > 3:
                            logging.error(
                                "Recursion error: stack too big. Stack:\n{pformat(self.stack)}"
                            )

                        # this should prevent most cases of recursion...
                        if (
                            len(self.stack) == 1
                            or self.stack[-1].history[0].asset_tx_id
                            != history_tx.asset_tx_id
                        ):
                            self.drawdown_from_lots(
                                history_asset_lots, history_tx, is_disposal=False
                            )
                        else:
                            logging.error(
                                "Recursion error: self reference. Stack:\n{pformat(self.stack)}"
                            )

                    # Only certain types of ownership_change's are disposals - see CostbasisGenerator.process()
                    if is_disposal:
                        # See https://etherscan.io/tx/0x0c0ad7b213997a82b890b741754870bd08a4ac0fd1c8cd13cd5f99c9e48d851b
                        # for example of receiving an ERC-721 CRV/SS that DeBank doesnt know how to make into a symbo.
                        # for now we'll just call this __UNKNOWN__.
                        if symbol is None:
                            symbol = "__UNKNOWN__"
                        disposal = CostbasisDisposal(
                            entity=self.entity,
                            address=t.address,
                            asset_price_id=asset_price_id,
                            symbol=symbol,
                            amount=amount,
                            timestamp=timestamp,
                            duration_held=duration_held,
                            basis_timestamp=lot.timestamp,
                            basis_tx_ledger_id=lot.tx_ledger_id,
                            basis_usd=basis_usd,
                            total_usd=total_usd,
                            tx_ledger_id=tx_ledger_id,
                        )
                        save_costbasis_disposal(disposal)

                # We subtract the amount for the current lot
                update_costbasis_lot_current_amount(
                    lot.tx_ledger_id,
                    Decimal(lot.current_amount) - Decimal(amount_to_subtract_from_lot),
                )

                # unused but putting it here in case we ever want the updated lot in memory, it should have the updated current_amount...
                updated_current_amount = (
                    lot.current_amount - amount_to_subtract_from_lot
                )
                updated_lot = lot.copy(
                    update={"current_amount": updated_current_amount}
                )

                amount_left_to_subtract -= amount

                # We're done and can stop looking at other lots
                if amount_left_to_subtract <= CLOSE_TO_ZERO:
                    break

            # We ran out of appropriate lots for this asset.
            if amount_left_to_subtract > CLOSE_TO_ZERO:
                # So, create a new zero-cost lost to handle the remainder
                lot = self.create_reconciliation_lot(
                    t, amount_left_to_subtract  # ???? <--- XXX
                )

                ### We have to repeat this because it's possible if there's no lot to start with we need to generate a new one
                # Fallback
                asset_price_id = t.asset_price_id
                symbol = t.symbol

                # TODO: add a if receipt, skip thigs
                """'
                print('===')
                print('is_receipt:', self.is_receipt)
                pprint(lot)
                print(asset_price_id)
                print(symbol)
                if not self.is_receipt:

                See also the note that we left in process() for is_receipt

                if we overdraft a receipt token, we won't know if it's actually a receipt or not unless we record a previous lot where it was a receipt (but that won't occur if we overdraft a receipt where we have no lots for that receipt asset)

                see also in tests/e2e/test_e2e_chain_disposal.py
                *deposit_receipt* tests
                """
                try:
                    # Try to get a mapped price/symbol from unwound tx
                    mapped_asset = costbasis_asset_mapper(
                        history_tx.chain, history_tx.asset_tx_id
                    )
                    asset_price_id = mapped_asset["asset_price_id"]
                    symbol = mapped_asset["symbol"]
                except:
                    # Try to get mapped price/symbol from tx
                    try:
                        mapped_asset = costbasis_asset_mapper(t.chain, t.asset_tx_id)
                        asset_price_id = mapped_asset["asset_price_id"]
                        symbol = mapped_asset["symbol"]
                    except:
                        pass

                # Make sure we also dispose from that new zerocost lot if is_disposal
                if is_disposal:
                    if symbol is None:
                        symbol = "__UNKNOWN__"
                    sale_price, _ = self.get_costbasis_price_and_source(t)
                    disposal = CostbasisDisposal(
                        entity=self.entity,
                        address=t.address,
                        asset_price_id=asset_price_id,
                        symbol=symbol,
                        amount=amount_left_to_subtract,
                        timestamp=t.timestamp,
                        duration_held=(t.timestamp - lot.timestamp),
                        basis_timestamp=lot.timestamp,
                        basis_tx_ledger_id=lot.tx_ledger_id,
                        basis_usd=Decimal(0.0),
                        total_usd=amount_left_to_subtract * sale_price,
                        tx_ledger_id=t.id,
                    )
                    save_costbasis_disposal(disposal)
                # We're done here
                break

    """
    symbol_feedback needs to be used carefully, but will ask the costbasis_asset_mapper to be more aggressive
    """
    # def get_costbasis_price_and_source(self, chain, asset_tx_id, timestamp, symbol_fallback=False):
    def get_costbasis_price_and_source(self, tx: TxLedger, symbol_fallback=False):
        """
        Tries to return a price for asset_tx_id at timestamp.
        1. If we can map this asset to a like kind, do so and ask price_feed for price e.g. WAVAX -> AVAX
        2. Otherwise, try to look up price via asset_tx_id -> asset_price_id and then ask price feed
        3. Otherwise if we have exactly 1 out and 1 in, look at the in and out from tx_logical to derive price from a ratio of what we gave versus what we got (assuming we can value the out)
        4. If we have more, then we have a bunch of tx_logical_type specific handling
        """
        price = Decimal(0.0)
        source = None

        # 0. FIXED PRICE OVERRIDE - mostly for worthless tokens
        tx_key = f"{tx.chain}:{tx.asset_tx_id}"
        if tx_key in assets.FIXED_PRICE_TOKENS:
            coin_price = Decimal(assets.FIXED_PRICE_TOKENS[tx_key])
            return (coin_price, "fixed_price")

        # 0.5  If we have a price_usd on the tx_ledger, return that
        if tx.price_usd is not None:
            return (Decimal(tx.price_usd), "tx_ledger")

        # 1. Try to get the price from our mapped assets
        # tx_ledgers[] have chain, not tx_logical
        mapped_asset = costbasis_asset_mapper(tx.chain, tx.asset_tx_id, symbol_fallback)
        if mapped_asset:
            costbasis_asset_price_id = mapped_asset["asset_price_id"]  # type: ignore
            coin_price = price_feed.get(costbasis_asset_price_id, tx.timestamp)
            if coin_price:
                return (Decimal(coin_price.price), "price_feed__mapped_asset")

        # 2. Try to get a price from the asset_tx_id's corresponding asset_price_id, if it has one
        coin_price = get_coinprice_for_asset(tx.chain, tx.asset_tx_id, tx.timestamp)
        if coin_price:
            return (Decimal(coin_price.price), "price_feed__asset")

        out_tx = None
        in_tx = None

        # 3. If this tx's logical type makes sense to allow deriving price from the corresponding out value (e.g. swap), do that
        if len(self.outs) == 1 and len(self.ins) == 1:
            out_tx = self.outs[0]
            in_tx = self.ins[0]

        ## We could, but actually we don't want to assign a price for borrow receipts...
        ## Leaving this empty keeps us out of trouble
        # if self.tx_logical.tx_logical_type == 'borrow' and len(self.ins) == 2:
        #     out_tx = self.ins[0]
        #     in_tx = self.ins[1]

        if out_tx and in_tx:
            # If we can value the OUT asset, then the cost basis price will be
            # amount_of_asset_in / amount_of_asset_out * asset_out_price
            # LATER: all our coinpricing from assets should look for mapped prices if available?
            coin_price = get_coinprice_for_asset(
                out_tx.chain, out_tx.asset_tx_id, out_tx.timestamp
            )
            if coin_price:
                out_price, _ = (Decimal(coin_price.price), coin_price.source)
                price = (Decimal(out_tx.amount) * out_price) / Decimal(in_tx.amount)
                # LATER account for fees
                return price, "derived_from_out"

            # If we're still here, we should try the IN before giving up
            coin_price = get_coinprice_for_asset(
                in_tx.chain, in_tx.asset_tx_id, in_tx.timestamp
            )
            if coin_price:
                in_price, _ = (Decimal(coin_price.price), coin_price.source)
                price = (Decimal(in_tx.amount) * in_price) / Decimal(out_tx.amount)
                # LATER account for fees
                return price, "derived_from_in"

            return price, source

        # 4. tx_logical_type case handling

        # borrow - still here?
        elif self.tx_logical.tx_logical_type == "borrow":
            return 0, "borrow_receipt"

        # repay - this should have 2 outs
        elif self.tx_logical.tx_logical_type == "repay":
            return 0, "repay_receipt"

        # withdraw - there can be two outs...
        elif self.tx_logical.tx_logical_type == "withdraw":
            # XXX LATER: for something like TOMB, 1 of these TSHARES might be a disposal!
            return 0, "withdraw_receipt"

        # lp - enter should have 2+ outs, in should have 2+ ins
        elif self.tx_logical.tx_logical_type == "lp":
            assets_to_price = []
            lp_amount = 0
            # LP Entry
            # We find the LP price from the sum of the (price*amount) of the tokens going out / LP tokens in
            if len(self.ins) == 1 and len(self.outs) >= 2:
                is_lp_entry = True
                assets_to_price = self.outs
                lp_txle = self.ins[0]
                lp_amount = lp_txle.amount
            # LP Exit
            # We find the LP price from the sum of the (price*amount) of the tokens going in / LP tokens out
            elif len(self.ins) >= 2 and len(self.outs) == 1:
                is_lp_entry = False
                assets_to_price = self.ins
                lp_txle = self.outs[0]
                lp_amount = lp_txle.amount

            #  We'll sum up our LP entry tokens to get the LP value
            price_accum = 0
            for t in assets_to_price:
                # We really want to be able to price our tokens if we can to establish an LP value, so we use symbol_fallback
                mapped_asset = costbasis_asset_mapper(
                    t.chain, t.asset_tx_id, symbol_fallback=True
                )
                if mapped_asset:
                    asset_price_id = mapped_asset["asset_price_id"]  # type: ignore
                    coin_price = price_feed.get(asset_price_id, t.timestamp)
                if coin_price:
                    price, _ = (Decimal(coin_price.price), coin_price.source)
                    price_accum += price * Decimal(t.amount)

            if price_accum:
                price = price_accum / Decimal(lp_amount)
                # Only when we enter an lp do we want to update the price
                if is_lp_entry:
                    lp_txle.save_price(price)

                return price, "lp_derived"
            else:
                # In the case that we can't get coin_prices for the LP exchange assets, we should
                # TODO: We should flag properly if price_unknown
                return 0, "price_unknown"

        # Unknown token price (e.g. spam tokens)
        if len(self.ins) == 1 and len(self.outs) == 0:
            # TODO: We should flag properly if price_unknown
            return 0, "price_unknown"

        ### If we're still here, it means we don't know how to handle this
        logging.warning("--- get_cost_basis_price_and_source ---")
        logging.warning(
            f"Not sure how to handle this case yet. Help? asset_tx_id: {tx.asset_tx_id}\n{pformat(self.tx_logical)}"
        )
        return 0, "price_unknown"


class LotMatcher:
    def get_lots(self, tx, algorithm="hifo"):
        asset_price_id = tx.asset_price_id
        asset_tx_id = tx.asset_tx_id

        # Try to match mapped lots...
        mapped_asset = costbasis_asset_mapper(tx.chain, tx.asset_tx_id)
        if mapped_asset:
            asset_price_id = mapped_asset["asset_price_id"]

        if asset_tx_id is None and asset_price_id is None:
            # raise Exception(f'Cant get a lot without either an asset_tx_id {asset_tx_id} or asset_price_id {asset_price_id}')
            return []
        logger.debug(f"--- {algorithm} ---")
        sql = f"""SELECT
                     tx_ledger_id,
                     entity,
                     address,
                     asset_price_id,
                     symbol,
                     asset_tx_id,
                     original_amount,
                     current_amount,
                     price_usd,
                     basis_usd,
                     timestamp,
                     history,
                     flags,
                     receipt
                 FROM costbasis_lot
                 WHERE
                 address IN (
                    SELECT address
                    FROM address
                    WHERE entity_id = (
                        SELECT e.id
                        FROM address a
                        JOIN entity e on e.id = a.entity_id
                        WHERE a.address = ?
                    )
                 )
                 AND
                 timestamp <= ?
                 {'AND asset_price_id = ?' if asset_price_id else ''}
                 {'AND asset_tx_id = ?' if not asset_price_id else ''}
                 AND current_amount > {CLOSE_TO_ZERO:.18f}
        """
        if algorithm == "hifo":
            sql += "ORDER BY price_usd DESC"
        if algorithm == "low":
            sql += "ORDER BY price_usd ASC"
        if algorithm == "fifo":
            sql += "ORDER BY timestamp ASC"
        if algorithm == "lifo":
            sql += "ORDER BY timestamp DESC"

        params = [tx.address, tx.timestamp]
        if asset_price_id:
            params.append(asset_price_id)
        else:
            params.append(asset_tx_id)
        results = db.query(sql, params)
        available_lots = []

        for r in results:
            r = dict(**r)
            r["history"] = jsonpickle.decode(r["history"])
            r["flags"] = jsonpickle.decode(r["flags"])
            lot = CostbasisLot(**r)
            available_lots.append(lot)
        return available_lots


class Form8949:
    def __init__(self, entity, args=None):
        self.entity = entity

        # Generate our 8949
        if args and args.output:
            self.filename = args.output
        else:
            self.filename = f"{self.entity}-8949.xlsx"

        print(f"Saving File: {self.filename}")
        self.wb = xlsxwriter.Workbook(self.filename)
        self.header_format = self.wb.add_format(
            {
                "font_name": "Inconsolata",
                "font_size": 10,
                "bold": True,
                "bg_color": "#b2d0f9",
            }
        )
        self.default_format = self.wb.add_format(
            {
                "font_name": "Inconsolata",
                "font_size": 10,
            }
        )
        self.amount_format = self.wb.add_format(
            {
                "font_name": "Inconsolata",
                "font_size": 10,
                "num_format": "0.000",
            }
        )
        self.currency_format = self.wb.add_format(
            {
                "font_name": "Inconsolata",
                "font_size": 10,
                "num_format": "[$$-409]#,##0.00;[RED]-[$$-409]#,##0.00",
            }
        )

        self.default_format_grey = self.wb.add_format(
            {
                "font_name": "Inconsolata",
                "font_size": 10,
                "font_color": "#888888",
            }
        )
        self.amount_format_grey = self.wb.add_format(
            {
                "font_name": "Inconsolata",
                "font_size": 10,
                "font_color": "#888888",
                "num_format": "0.000",
            }
        )
        self.currency_format_grey = self.wb.add_format(
            {
                "font_name": "Inconsolata",
                "font_size": 10,
                "font_color": "#888888",
                "num_format": "[$$-409]#,##0.00;[RED]-[$$-409]#,##0.00",
            }
        )

        self.lot_row = {}

        if args and args.year:
            self.year = args.year
        else:
            self.year = arrow.now().year - 1

        # TODO: TZ should load from settings

        self.start = arrow.get(date(self.year, 1, 1), "US/Pacific")
        self.start = int(self.start.timestamp())
        self.end = arrow.get(date(self.year + 1, 1, 1), "US/Pacific")
        self.end = int(self.end.timestamp())

    def get_logical_summary(self, tx_ledger_id):
        sql = f"""
                select tlo.id
                from tx_ledger tle
                join tx_rel_ledger_logical rll on rll.tx_ledger_id = tle.id
                join tx_logical tlo on tlo.id = rll.tx_logical_id
                where tle.id = ?
              """
        params = [tx_ledger_id]
        results = db.query(sql, params)
        if len(results) != 1:
            raise Exception(
                f"Could not find 1 tx_logical for the given tx_ledger. You gave tx_ledger_id {tx_ledger_id} and I found {results}"
            )
        txl = TxLogical.from_id(results[0]["id"], entity_name=self.entity)
        return txl.auto_description()

    def get_disposal(self):
        """
        One Gregorian calendar year, has 365.2425 days:
        1 year = 365.2425 days = (365.2425 days) × (24 hours/day) × (3600 seconds/hour) = 31556952 seconds

        One calendar common year has 365 days:
        1 common year = 365 days = (365 days) × (24 hours/day) × (3600 seconds/hour) = 31536000 seconds

        One calendar leap year has 366 days (occures every 4 years):
        1 leap year = 366 days = (366 days) × (24 hours/day) × (3600 seconds/hour) = 31622400 seconds
        """
        sql = f"""SELECT
                    d.amount,
                    d.symbol,
                    d.basis_timestamp,
                    d.timestamp,
                    d.total_usd,
                    d.basis_usd,
                    t.chain,
                    t.hash,
                    d.duration_held,
                    d.tx_ledger_id,
                    tlo.flags
                 FROM costbasis_disposal as d
                 JOIN tx_ledger t ON d.basis_tx_ledger_id = t.id
                 JOIN tx_rel_ledger_logical trll on t.id = trll.tx_ledger_id
                 JOIN tx_logical tlo on trll.tx_logical_id = tlo.id
                 WHERE entity = ?
                 AND d.timestamp  >= {self.start}
                 AND d.timestamp < {self.end}
                 ORDER BY d.timestamp ASC
              """
        params = [self.entity]
        disposal_results = db.query(sql, params)

        short = []
        long = []
        for r in tqdm(disposal_results, desc="Getting Disposals", disable=None):
            if r[10]:
                logical_flags = jsonpickle.decode(r[10])
                if TX_LOGICAL_FLAG.hidden_from_8949.value in [
                    f["name"] for f in logical_flags
                ]:
                    continue
            summary = self.get_logical_summary(r[9])
            if r[8] > 31556952:
                long.append((r, summary))
            else:
                short.append((r, summary))

        # Short Term
        self.create_disposal_sheet(f"{self.year} Short Term", short)

        # Long Term
        self.create_disposal_sheet(f"{self.year} Long Term", long)

    def create_disposal_sheet(self, title, disposals):
        ws = self.wb.add_worksheet(title)

        # Column Widths
        ws.set_column("A:A", 20)
        ws.set_column("B:C", 12)
        ws.set_column("D:G", 11)
        ws.set_column("H:H", 12)
        ws.set_column("I:I", 60)
        ws.set_column("J:J", 30)  # date
        ws.set_column("L:L", 40)  # outs
        ws.set_column("M:M", 40)  # ins
        ws.set_column("N:N", 20)  # chain
        ws.set_column("O:O", 60)  # hash
        ws.set_column("P:P", 60)  # tx ledger id

        # Header
        ws.write_row(
            0,
            0,
            [
                "Description",
                "Date Acquired",
                "Date Disposed",
                "Proceeds",
                "Cost Basis",
                "Gain or Loss",
                "Sum",
                "Basis Chain",
                "Basis TX",
                "TX Date",
                "TX Type",
                "TX OUTs",
                "TX INs",
                "TX Chain",
                "TX Hash",
                "TX Ledger ID",
            ],
            self.header_format,
        )

        i = 1
        for r, summary in tqdm(disposals, desc=title, disable=None):
            amount = r[0]
            symbol = r[1]
            in_timestamp = r[2]
            out_timestamp = r[3]
            total_usd = r[4]
            basis_usd = r[5]
            net_usd = total_usd - basis_usd
            basis_chain = r[6]
            basis_hash = r[7]
            tx_ledger_id = r[9]

            description = f"{amount:,.2f} {symbol}"

            # User needs a time zone
            d = arrow.get(in_timestamp)
            d = d.to("US/Pacific")
            date_acquired = d.format("M/D/YYYY")

            d = arrow.get(out_timestamp)
            d = d.to("US/Pacific")
            date_disposed = d.format("M/D/YYYY")

            url = get_url(basis_chain, basis_hash)

            date, type, outs, ins, chain, hash = summary.split(" | ")
            outs = outs[6:]
            ins = ins[5:]

            # Skip close to zero entries...
            if net_usd >= 0.01 or net_usd <= -0.01:
                ws.write(i, 0, description, self.default_format)
                ws.write(i, 1, date_acquired, self.default_format)
                ws.write(i, 2, date_disposed, self.default_format)
                ws.write_number(i, 3, total_usd, self.currency_format)
                ws.write_number(i, 4, basis_usd, self.currency_format)
                ws.write_number(i, 5, net_usd, self.currency_format)
                ws.write(i, 7, basis_chain, self.default_format)
                ws.write(i, 8, basis_hash, self.default_format)
                ws.write(i, 9, date, self.default_format)
                ws.write(i, 10, type, self.default_format)
                ws.write(i, 11, outs, self.default_format)
                ws.write(i, 12, ins, self.default_format)
                ws.write(i, 13, chain, self.default_format)
                ws.write(i, 14, get_url(chain, hash), self.default_format)
                ws.write(i, 15, tx_ledger_id, self.default_format)

                i += 1

        # LibreOffice! https://stackoverflow.com/questions/32205927/xlsxwriter-and-libreoffice-not-showing-formulas-result
        ws.write_formula(1, 6, "=SUM(F:F)", self.currency_format, "")

        # Freeze Header Row
        ws.freeze_panes(1, 0)

        # ws.calculate_dimension()

    def get_income(self):
        sql = f"""SELECT i.amount, i.symbol, i.timestamp, i.net_usd, t.chain, t.hash
                 FROM costbasis_income as i
                 JOIN tx_ledger t ON i.tx_ledger_id = t.id
                 WHERE entity = ?
                 AND i.timestamp  >= {self.start}
                 AND i.timestamp < {self.end}
                 ORDER BY i.timestamp ASC
              """
        params = [self.entity]
        results = db.query(sql, params)

        title = f"{self.year} Earned Income"

        ws = self.wb.add_worksheet(title)
        # Column Widths
        ws.set_column("A:A", 20)
        ws.set_column("B:C", 12)
        ws.set_column("D:G", 11)
        ws.set_column("H:H", 12)
        ws.set_column("I:I", 60)

        ws.write_row(
            0,
            0,
            [
                "Description",
                "Date Earned",
                "Net Income",
                "Sum",
                "",
                "",
                "",
                "Basis Chain",
                "Basis TX",
            ],
            self.header_format,
        )

        i = 1
        for r in tqdm(results, desc=title, disable=None):
            description = f"{r[0]:,.2f} {r[1]}"

            d = arrow.get(r[2])
            d = d.to("US/Pacific")
            # Date Format in settings too
            date_earned = d.format("M/D/YYYY")

            net = r[3]
            chain = r[4]
            tx_hash = r[5]

            if r[3] >= 0.01 or r[3] <= -0.01:
                ws.write(i, 0, description, self.default_format)
                ws.write(i, 1, date_earned, self.default_format)
                ws.write_number(i, 2, net, self.currency_format)
                ws.write_blank(i, 3, None, self.default_format)
                ws.write_blank(i, 4, None, self.default_format)
                ws.write_blank(i, 5, None, self.default_format)
                ws.write_blank(i, 6, None, self.default_format)
                ws.write(i, 7, chain, self.default_format)
                ws.write(i, 8, tx_hash, self.default_format)

                i += 1

        ws.write_formula("D2", "=SUM(C:C)", self.currency_format, "")

        # Freeze Header Row
        ws.freeze_panes(1, 0)

    def get_lots(self):
        sql = f"""SELECT
                    cl.timestamp,
                    tx.hash,
                    cl.address,
                    cl.asset_price_id,
                    cl.symbol,
                    cl.asset_tx_id,
                    cl.current_amount,
                    cl.original_amount,
                    cl.price_usd,
                    cl.basis_usd,
                    cl.history,
                    cl.flags,
                    cl.receipt,
                    tx.chain
                 FROM costbasis_lot cl
                 join tx_ledger tx on tx.id = cl.tx_ledger_id
                 WHERE cl.entity = ?
                 -- AND cl.receipt != 1
                 AND cl.timestamp < {self.end}
                 ORDER BY cl.timestamp ASC
              """
        params = [self.entity]
        results = db.query(sql, params)

        ws = self.wb.add_worksheet("Costbasis Lots")

        # Column Widths
        ws.set_column("A:A", 14)
        ws.set_column("B:B", 24)
        ws.set_column("C:F", 12)
        ws.set_column("G:G", 9)
        ws.set_column("H:H", 14)
        ws.set_column("I:I", 38)
        ws.set_column("J:K", 15)
        ws.set_column("L:L", 9)
        ws.set_column("M:M", 12)
        ws.set_column("N:N", 60)

        ws.write_row(
            0,
            0,
            [
                "Date",
                "Address",
                "Current Amount",
                "Original Amount",
                "Price",
                "Basis",
                "Symbol",
                "asset_price_id",
                "asset_tx_id",
                "history",
                "flags",
                "receipt",
                "chain",
                "tx_hash",
            ],
            self.header_format,
        )

        i = 1
        for r in results:
            d = arrow.get(r[0])
            # TODO: use settings for tz
            d = d.to("US/Pacific")
            date = d.format()

            address = r[2]

            current_amount = r[6]
            if current_amount < 0.01:
                current_amount = 0

            original_amount = r[7]

            price = r[8]
            basis = r[9]

            symbol = r[4]

            asset_price_id = r[3]

            asset_tx_id = r[5]

            history = jsonpickle.decode(r[10])
            try:
                history_s = "\n".join([h.hash for h in history])
            except:
                history_s = "x"

            flags = jsonpickle.decode(r[11])
            flags_s = ", ".join([f["name"] for f in flags])

            receipt = r[12]

            chain = r[13]
            tx_hash = r[1]

            url = get_url(chain, tx_hash)

            self.lot_row[tx_hash] = i

            if current_amount <= CLOSE_TO_ZERO or receipt == 1:
                ws.write(i, 0, date, self.default_format_grey)
                ws.write(i, 1, address, self.default_format_grey)
                ws.write(i, 2, current_amount, self.amount_format_grey)
                ws.write(i, 3, original_amount, self.amount_format_grey)
                ws.write(i, 4, price, self.currency_format_grey)
                ws.write(i, 5, basis, self.currency_format_grey)
                ws.write(i, 6, symbol, self.default_format_grey)
                ws.write(i, 7, asset_price_id, self.default_format_grey)
                ws.write(i, 8, asset_tx_id, self.default_format_grey)
                ws.write(i, 9, history_s, self.default_format_grey)
                ws.write(i, 10, flags_s, self.default_format_grey)
                ws.write(i, 11, receipt, self.default_format_grey)
                ws.write(i, 12, chain, self.default_format_grey)
                ws.write_url(i, 13, url, self.default_format_grey, tx_hash)
            else:
                ws.write(i, 0, date, self.default_format)
                ws.write(i, 1, address, self.default_format)
                ws.write(i, 2, current_amount, self.amount_format)
                ws.write(i, 3, original_amount, self.amount_format)
                ws.write(i, 4, price, self.currency_format)
                ws.write(i, 5, basis, self.currency_format)
                ws.write(i, 6, symbol, self.default_format)
                ws.write(i, 7, asset_price_id, self.default_format)
                ws.write(i, 8, asset_tx_id, self.default_format)
                ws.write(i, 9, history_s, self.default_format)
                ws.write(i, 10, flags_s, self.default_format)
                ws.write(i, 11, receipt, self.default_format)
                ws.write(i, 12, chain, self.default_format)
                ws.write_url(i, 13, url, self.default_format, tx_hash)

            i += 1

        # Freeze Header Row
        ws.freeze_panes(1, 0)

    def link_lots(self):
        for ws in self.wb.worksheets():
            if "Lots" not in ws.name:
                # https://stackoverflow.com/questions/62865195/python-xlsxwriter-extract-value-from-cell
                shared_strings = sorted(
                    ws.str_table.string_table, key=ws.str_table.string_table.get
                )

                # Lets look at our sheet now
                for row in ws.table:
                    if row != 0:
                        try:
                            tx_hash = shared_strings[ws.table[row][8].string]
                            target_row = self.lot_row[tx_hash] + 1
                            # https://stackoverflow.com/questions/50369352/creating-a-hyperlink-for-a-excel-sheet-xlsxwriter
                            url = f"internal:'Costbasis Lots'!{target_row}:{target_row}"
                            ws.write_url(row, 8, url, self.default_format, tx_hash)
                        except:
                            # Could be empty
                            pass

    def get_ledger(self):
        sql = f"""SELECT id, tx_logical_type, flags
                  FROM tx_logical
                  WHERE address IN (
                      SELECT address
                      FROM address, entity
                      WHERE entity_id = entity.id
                      AND entity.name = ?
                  )
                 AND count > 0
                 AND timestamp  >= {self.start}
                 AND timestamp < {self.end}
                 ORDER BY timestamp ASC
              """
        params = [self.entity]
        results = db.query(sql, params)

        ws = self.wb.add_worksheet("Ledger TXs")

        ws.write_row(
            0,
            0,
            [
                "Date",
                "Entity Address",
                "tx_logical_type",
                "tx_ledger_type",
                "Direction",
                "Is Fee",
                "Chain",
                "from_address",
                "to_address",
                "Amount",
                "Price USD",
                "symbol",
                "asset_price_id",
                "asset_tx_id",
                "Hash",
                "tx_ledger.id",
                "flags",
            ],
            self.header_format,
        )

        # Column Widths
        ws.set_column("A:A", 14)
        ws.set_column("B:B", 38)
        ws.set_column("C:D", 14)
        ws.set_column("E:F", 9)
        ws.set_column("G:G", 18)
        ws.set_column("H:I", 38)
        ws.set_column("J:K", 14)
        ws.set_column("L:L", 9)
        ws.set_column("M:M", 16)
        ws.set_column("N:N", 38)
        ws.set_column("O:P", 60)
        ws.set_column("Q:Q", 30)

        i = 1
        for txlog in tqdm(results, desc="Logical TXs", disable=None):
            sql = """SELECT id,
                            chain,
                            address,
                            hash,
                            from_address,
                            to_address,
                            asset_tx_id,
                            isfee,
                            amount,
                            timestamp,
                            direction,
                            tx_ledger_type,
                            asset_price_id,
                            symbol,
                            price_usd
                     FROM tx_ledger txle
                     JOIN tx_rel_ledger_logical as rel ON txle.id = rel.tx_ledger_id
                     WHERE rel.tx_logical_id = ?
                     ORDER by timestamp ASC
                  """
            params = [txlog["id"]]
            r_txle = db.query(sql, params)

            for txle in r_txle:
                d = arrow.get(txle["timestamp"])
                # TODO: use settings for tz
                d = d.to("US/Pacific")
                date = d.format()

                url = get_url(txle["chain"], txle["hash"])

                ws.write(i, 0, date, self.default_format)
                ws.write(i, 1, txle["address"], self.default_format)
                ws.write(i, 2, txlog["tx_logical_type"], self.default_format)
                ws.write(i, 3, txle["tx_ledger_type"], self.default_format)
                ws.write(i, 4, txle["direction"], self.default_format)
                ws.write(i, 5, txle["isfee"], self.default_format)
                ws.write(i, 6, txle["chain"], self.default_format)
                ws.write(i, 7, txle["from_address"], self.default_format)
                ws.write(i, 8, txle["to_address"], self.default_format)
                ws.write(i, 9, txle["amount"], self.amount_format)
                ws.write(i, 10, txle["price_usd"], self.currency_format)
                ws.write(i, 11, txle["symbol"], self.default_format)
                ws.write(i, 12, txle["asset_price_id"], self.default_format)
                ws.write(i, 13, txle["asset_tx_id"], self.default_format)
                ws.write_url(i, 14, url, self.default_format, txle["hash"])
                ws.write(i, 15, txle["id"], self.default_format)
                ws.write(i, 16, txlog["flags"], self.default_format)
                i += 1
            # Extra space between logical groups
            i += 1

        # Freeze Header Row
        ws.freeze_panes(1, 0)
