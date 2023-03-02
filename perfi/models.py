import logging
import time
from abc import ABC
from datetime import datetime
from decimal import Decimal
from enum import Enum
from functools import lru_cache
from pprint import pformat
from typing import Optional, List, Type, Protocol, TypeVar, Generic

import jsonpickle
from devtools import debug
from pydantic import BaseModel

from .constants import assets
from .db import db, DB

T = TypeVar("T")

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


class TX_LOGICAL_TYPE(Enum):
    borrow = "borrow"
    repay = "repay"
    deposit = "deposit"
    withdraw = "withdraw"
    disposal = "disposal"
    lp = "lp"
    swap = "swap"
    yield_ = "yield"  # HACK using yield_ for enum name because 'yield' is a keyword
    mint = "mint"
    gift = "gift"
    airdrop = "airdrop"
    trade = "trade"
    self_transfer = "self_transfer"
    receive = "receive"
    send = "send"
    income = "income"
    approval = "approval"


# TODO: go find the places where we create unknown_send, zero_price, auto_reconciled flags and use this enum.value instead
class TX_LOGICAL_FLAG(Enum):
    unknown_send = "unknown_send"
    zero_price = "zero_price"
    auto_reconciled = "auto_reconciled"
    ignored_from_costbasis = "ignored_from_costbasis"
    hidden_from_8949 = "hidden_from_8949"


# This is more of a chain format from our address perspective...
class Chain(Enum):
    # avalanche = "avalanche"
    ethereum = "ethereum"
    # fantom = "fantom"
    # polygon = "polygon"
    import_coinbasepro = "import.coinbasepro"
    import_coinbase = "import.coinbase"
    import_kraken = "import.kraken"
    import_gemini = "import.gemini"
    import_bitcointax = "import.bitcointax"


class Flag(BaseModel):
    id: Optional[int]
    target_type: Optional[str]
    target_id: Optional[str]
    source: str
    created_at: Optional[int]
    name: str
    description: Optional[str]


def load_flags(target_type: str, target_id: str) -> List[Flag]:
    sql = """SELECT id, name, description, created_at, source FROM flag WHERE target_type = ? AND target_id = ?"""
    params = [target_type, target_id]
    rows = db.query(sql, params)
    flags = []
    for r in rows:
        flags.append(
            Flag(
                id=r["id"],
                target_type=target_type,
                target_id=target_id,
                name=r["name"],
                description=r["description"],
                created_at=r["created_at"],
                source=r["source"],
            )
        )
    return flags


def add_flag(target_type: str, target_id: str, flag):
    now = int(time.time())
    insert_sql = """INSERT INTO flag (target_type, target_id, created_at, name, description, source) VALUES (?, ?, ?, ?, ?, ?)"""
    params = [target_type, target_id, now, flag.name, flag.description, flag.source]
    db.execute(insert_sql, params)


def replace_flags(target_type: str, target_id: str, flags: List[Flag]):
    delete_sql = """DELETE FROM flag WHERE target_type = ? AND target_id = ?"""
    params = [target_type, target_id]
    db.execute(delete_sql, params)

    insert_sql = """INSERT INTO flag (target_type, target_id, created_at, name, description, source) VALUES (?, ?, ?, ?, ?, ?)"""
    for flag in flags:
        now = int(time.time())
        params = [target_type, target_id, now, flag.name, flag.description, flag.source]
        db.execute(insert_sql, params)


class Entity(BaseModel):
    id: Optional[int] = None
    name: str
    note: Optional[str] = None


class Address(BaseModel):
    id: Optional[int] = None
    label: str
    chain: Chain
    address: str
    type: str = "account"
    source: str = "manual"
    ord: int = 1
    entity_id: int


class Setting(BaseModel):
    key: str
    value: str


Entity.update_forward_refs()


class TxLedger(BaseModel):
    id: Optional[str] = None
    chain: str  # Consider migrating to Chain enum
    address: str
    hash: str
    from_address: str
    to_address: str
    from_address_name: Optional[str] = None
    to_address_name: Optional[str] = None
    asset_tx_id: str
    isfee: int
    amount: Decimal
    timestamp: int
    direction: str  # Consider migrating to a new Direction enum
    tx_ledger_type: Optional[str] = None  # Consider migrating to TX_LOGICAL_TYPE enum
    asset_price_id: Optional[str] = None
    symbol: Optional[str] = None
    price_usd: Optional[Decimal] = None
    price_source: Optional[str] = None
    tx_logical_id: Optional[int] = None

    def __eq__(self, other):
        if not isinstance(other, TxLedger):
            return NotImplemented
        d1 = self.dict()
        d2 = other.dict()
        amounts_equal = abs(d1["amount"] - d2["amount"]) < 1e-18
        d1.pop("amount")
        d2.pop("amount")
        return amounts_equal and all(
            [self.dict()[f] == other.dict()[f] for f in self.__fields_set__]
        )

    @classmethod
    def from_row(cls, t):
        attrs = dict(
            id=t[0],
            chain=t[1],
            address=t[2],
            hash=t[3],
            from_address=t[4],
            to_address=t[5],
            from_address_name=t[6],
            to_address_name=t[7],
            asset_tx_id=t[8],
            isfee=t[9],
            amount=t[10],
            timestamp=t[11],
            direction=t[12],
            tx_ledger_type=t[13],
            asset_price_id=t[14],
            symbol=t[15],
            price_usd=t[16],
        )
        return cls(**attrs)

    @classmethod
    def get(cls, id: str):
        sql = """SELECT
                    id,
                    chain,
                    address,
                    hash,
                    from_address,
                    to_address,
                    from_address_name,
                    to_address_name,
                    asset_tx_id,
                    isfee,
                    amount,
                    timestamp,
                    direction,
                    tx_ledger_type,
                    asset_price_id,
                    symbol,
                    price_usd
                FROM tx_ledger
                WHERE id = ?
              """
        params = [id]
        result = db.query(sql, params)
        if len(result) == 0:
            raise Exception(f"No tx_ledger found for id {id}")
        return cls(**result[0])

    def auto_description(self):
        return f"{self.amount} {self.symbol}"

    def save_price(self, price_usd):
        self.price_usd = price_usd
        """
        LATER: we should create a tx_ledger_event table
        and apply price updates in the same way so they can be replayed, store source etc
        """
        sql = """UPDATE tx_ledger
                 SET price_usd = ?
                 WHERE id = ?
              """
        params = [float(price_usd), self.id]
        db.execute(sql, params)


class TxLogical(BaseModel):
    id: str
    count: int = -1
    description: str = ""
    note: str = ""
    timestamp: int = -1
    tx_ledgers: List[TxLedger] = []
    address: str = ""
    addresses: List[str] = []
    tx_logical_type: str = ""  # replace with enum?
    entity: Optional[str] = None
    flags: Optional[List[Flag]] = []
    ins: List[TxLedger] = []
    outs: List[TxLedger] = []
    fee: Optional[TxLedger] = None
    others: List[TxLedger] = []

    def _group_ledgers(self):
        # group ledgers into INs, OUTs, fee, others
        for t in self.tx_ledgers:
            if t.tx_ledger_type == "fee":
                self.fee = t
            elif t.direction == "IN":
                self.ins.append(t)
            elif t.direction == "OUT":
                self.outs.append(t)
            else:
                logger.debug(pformat("What type of tx is this? Not fee, IN or OUT.."))
                logger.debug(pformat(t))
                self.others.append(t)

    @classmethod
    @lru_cache
    def from_id(cls, id: str, entity_name: str = None):
        txl = cls(id=id, entity=entity_name)
        txl.id = id

        # LATER: Optimize this with a memoized return since this data doesnt change. Don't hit the DB for this on every TXLogical init
        if txl.entity:
            sql = """SELECT address
                     FROM address, entity
                     WHERE entity.id = address.entity_id
                     AND entity.name = ?
                  """
            results = db.query(sql, txl.entity)
            addresses = [r[0] for r in results]
            txl.addresses = addresses

        # load the logical attrs
        sql = """SELECT id, count, description, note, timestamp, address, tx_logical_type
             FROM tx_logical log
             WHERE log.id = ?
          """
        params = [id]
        r = db.query(sql, params)[0]
        txl.count = r[1]
        txl.description = r[2]
        txl.note = r[3]
        txl.timestamp = r[4]
        txl.address = r[5]
        txl.tx_logical_type = r[6]
        txl.flags = load_flags(cls.__name__, id)

        # load the tx ledgers
        sql = """SELECT id, chain, address, hash, from_address, to_address, from_address_name, to_address_name, asset_tx_id, isfee, amount, timestamp, direction, tx_ledger_type, asset_price_id, symbol, price_usd, price_source
             FROM tx_rel_ledger_logical rel
             JOIN tx_ledger led on led.id = rel.tx_ledger_id
             WHERE rel.tx_logical_id = ?
             ORDER BY led.timestamp
          """
        params = [id]
        results = db.query(sql, params)
        for r in results:
            txl.tx_ledgers.append(TxLedger(**r))

        txl._group_ledgers()

        return txl

    @classmethod
    def get_by_tx_ledger_id(cls, tx_ledger_id: str, entity_name: str = None):
        sql = """
            SELECT id
            FROM tx_logical tlo
            JOIN tx_rel_ledger_logical trll on tlo.id = trll.tx_logical_id
            WHERE trll.tx_ledger_id = ?
        """
        params = [tx_ledger_id]
        result = db.query(sql, params)
        if len(result) == 0:
            raise Exception(
                f"No tx_logical found containing tx_ledger_id id {tx_ledger_id}"
            )
        if entity_name:
            return cls(id=result[0][0], entity=entity_name)
        else:
            return cls(id=result[0][0], entity=None)

    def load_entity_name(self):
        # Assuming that this TxLogical has TxLedgers, we can take the entity from the address of any of the TxLedgers since
        # we certainly don't support a TxLogical comprised of TxLedgers from addressess belonging to different entities
        if len(self.tx_ledgers) == 0:
            return None
        else:
            sql = """SELECT name
                     FROM entity e
                     JOIN address a on e.id = a.entity_id
                     WHERE a.address = ?"""
            params = self.tx_ledgers[0].address
            results = db.query(sql, params)
            if results:
                self.entity = results[0]["name"]
        return self.entity

    def auto_description(self):
        datestamp = datetime.utcfromtimestamp(self.timestamp).isoformat() + "Z"
        outs_strs = [t.auto_description() for t in self.outs]
        ins_strs = [t.auto_description() for t in self.ins]
        chain = None
        hash = None
        if self.tx_logical_type:
            tx_logical_type = self.tx_logical_type
        else:
            tx_logical_type = ""
        if len(self.outs) > 0:
            chain = self.outs[0].chain
            hash = self.outs[0].hash
        elif len(self.ins) > 0:
            chain = self.ins[0].chain
            hash = self.ins[0].hash
        elif self.fee:
            chain = self.fee.chain
            hash = self.fee.hash

        return " | ".join(
            [
                datestamp,
                tx_logical_type,
                "OUTs: " + ", ".join(outs_strs),
                "INs: " + ", ".join(ins_strs),
                chain,
                hash,
            ]
        )

    def save(self):
        sql = """
                  UPDATE tx_logical
                  SET
                  count = ?,
                  description = ?,
                  note = ?,
                  timestamp = ?,
                  address = ?,
                  tx_logical_type = ?,
                  WHERE
                  id = ?
                  """
        params = [
            self.count,
            self.description,
            self.note,
            self.timestamp,
            self.address,
            self.tx_logical_type,
            self.id,
        ]
        db.execute(sql, params)

        replace_flags(self.__class__.__name__, self.id, self.flags)

    # LATER: this should generate an event?
    def save_type(self, tx_logical_type):
        if tx_logical_type != self.tx_logical_type:
            self.tx_logical_type = tx_logical_type
            sql = """UPDATE tx_logical
                     SET tx_logical_type = ?
                     WHERE id = ?
                  """
            params = [tx_logical_type, self.id]
            db.execute(sql, params)

    def refresh_type(self):
        # Ignore empty logicals
        if len(self.tx_ledgers) == 0:
            return

        # Get all unique tx_perfi_types from the ledger entries except for fee
        ledger_types = set(
            [t.tx_ledger_type for t in self.tx_ledgers if t.tx_ledger_type != "fee"]
        )

        if len(ledger_types) > 1:
            raise Exception(
                f"We dont yet know how to assign a tx_perfi_type to a TxLogical if it has multiple ledger type besides the fee. \n {ledger_types}"
            )

        # Skip logicals that only have a fee
        if len(ledger_types) == 0:
            return

        if (
            len(self.ins) == 0
            and len(self.outs) == 0
            and len(self.others) == 1
            and self.others[0].tx_ledger_type == "approval"
        ):
            self.save_type("approval")

        # Wrap and unwrap are special cases we'll look at first
        def is_native(txle):
            return txle.asset_tx_id in assets.WRAPPED_TOKENS.values()

        def is_wrapped(txle):
            return assets.WRAPPED_TOKENS.get(f"{txle.chain}:{txle.asset_tx_id}")

        if (
            len(self.ins) == 1
            and len(self.outs) == 1
            and self.ins[0].amount == self.outs[0].amount
        ):
            tin = self.ins[0]
            tout = self.outs[0]

            if is_native(tout) and is_wrapped(tin):
                self.save_type("wrap")
                return
            elif is_native(tin) and is_wrapped(tout):
                self.save_type("unwrap")
                return

        # We take from debank here and look at it below
        self.tx_logical_type = [type for type in ledger_types][0]  # type:ignore

        # We trust the Debank types if we have one for it
        if self.tx_logical_type:
            # These are 1:1 matches, but there are conditional types below as well
            map = {
                "borrow": [
                    "borrow",
                    "borrowETH",
                ],
                "repay": [
                    "repay",
                    "loan_repay",
                    "repayETH",
                ],
                "deposit": [
                    "deposit",  # Aave, Curve Staking Gauge, WFTM, platypus, etc
                    "depositBNB",  # Beefy
                    "depositETH",  # Aave
                    "depositAll",  # Beefy Vaults, Convex
                    "depositWithPermit",  # YieldYak
                    "stake",
                    "depositERC20",  # Optimism Bridge
                    "depositFor",  # Polygon Bridge
                    "depositEtherFor",  # Polygon Bridge
                    "depositERC20ForUser",  # Plasma Bridge
                    "depositTokenByAddress",  # mystery Polygon
                    "depositCollateral",  # qi dao
                    "depositERC20ToByChainId",  # metis bridge
                    "depositMultiple",  # arb bridge
                    "depositDai",
                ],
                "withdraw": [
                    "redeem",  # Iron Bank
                    "withdraw",
                    "widthdraw",  # lol TOMB
                    "withdrawNative",  # TODO XXX look at Anyswap, see if it's a withdrawal or not
                    "withdrawAll",
                    "withdrawAllBNB",
                    "withdrawBNB",
                    "withdrawAndHarvest",
                    "withdrawCollateral",  # qidao
                    "withdrawFromSP",  # vesta
                    "withdrawLocked",  # frax
                    "exit",
                    "unstake",
                ],
                # wrap and unwrap are handled above
                "disposal": [
                    "disposal",
                ],
                "lp": [
                    "lp",
                    "add_liquidity",  # Curve entering USD.E in and getting Triple back, lido
                    "remove_liquidity_imbalance",  # Curve
                    "addLiquidity",  # Sushi Swap,  Spell + USDC into an SLP
                    "addLiquidityETH",  # Spooky Router:  In: SPLP  Out: TOMB + FTM
                    "multicall",  # Uniswap V3 in and out
                    "ZapIn",  # Out:MiMATIC  In: UniV2
                    "remove_liquidity",
                    "remove_liquidity_one_coin",  # Curve
                    "removeLiquidity",
                    "removeLiquidityOneToken",  # Hop, Axial
                    "removeLiquidityETHWithPermit",
                    "DepositInEth",  # Popsicle Zap
                ],
                "swap": [
                    "swap",
                    "swapExactTokensForETH",  # Spiritswap FTM -> DAI
                    "swapExactTokensForTokens",  #  SpookySwap WFTM -> USDC.e
                    "swapExactETHForTokens",
                    "swapTokensForExactTokens",
                ],
                "yield": [
                    "claimRewards",
                    "claimed_reward",
                    "getReward",
                    "yield",
                ],
                "approval": ["approve", "approval"],
            }

            # See if we match
            for action in map:
                for action_to_map in map[action]:
                    if action_to_map == self.tx_logical_type:
                        self.save_type(action)
                        return

            # "mint" is a special case because Iron Bank, Abracadrabra uses it as a "deposit"
            # but Uniswap V3 uses it as an LP (make a NFT position) -
            # LATER: mintETH (imxB Impermax?), mintCollateral (Impermax), zapMint (IRON/USDC)
            if self.tx_logical_type == "mint":
                if len(self.ins) == 1 and len(self.outs) == 1:
                    self.save_type("deposit")
                elif len(self.ins) == 1 and len(self.outs) == 2:
                    self.save_type("lp")

            # Juicebox "pay" are gifts
            for t in self.outs:
                if t.to_address == "0xd569d3cce55b71a8a3f3c418c329a66e5f714431":
                    self.save_type("gift")
                    return

        # IF we got this far, we couldn't map a debank tx name to a tx_logicial_type so we try to infer...

        # TODO: We need to figure out not overriding types...
        if self.tx_logical_type == "airdrop":
            return
        if self.tx_logical_type in [
            "Coinbase.Airdrop",
        ]:
            self.save_type("airdrop")
            return

        # lets do some UniV3...
        """
        Multicall looks the same to our send and receives
        later we can try to distinguish between a yield claim and removing from an LP

        if (
            self.tx_logical_type == "multicall"
            and len(self.outs) == 0
            and len(self.ins) == 2
        ):
            self.save_type("yield")
            return
        """

        # self_transfer
        if self.tx_logical_type in [
            "CoinbasePro.deposit",
            "CoinbasePro.withdrawal",
            "Coinbase.Receive",
            "Coinbase.Withdrawal",
            "Coinbase.Deposit",
            "Coinbase.Transfer",
            "Coinbase.Send",
            "Gemini.Credit",
            "Gemini.Debit",
        ]:
            self.save_type("self_transfer")
            return

        # trade
        if self.tx_logical_type in [
            "CoinbasePro.BUY",
            "CoinbasePro.SELL",
            "CoinbasePro.trade",
            "Kraken.trade",
            "Gemini.Buy",
            "Gemini.Sell",
            "Coinbase.Buy",
            "Coinbase.Sell",
            "Coinbase.Convert",
        ]:
            self.save_type("trade")
            return

        # income
        if self.tx_logical_type in [
            "CoinbasePro.Reward",
            "Coinbase.Rewards Income",
            "Coinbase.Coinbase Earn",
        ]:
            self.save_type("income")
            return

        # receive
        if len(self.ins) >= 1 and not self.outs:
            if all([t.from_address in self.addresses for t in self.ins]):
                self.save_type("self_transfer")
            else:
                self.save_type("receive")
            return

        # send
        if len(self.outs) >= 1 and not self.ins:
            if all([t.to_address in self.addresses for t in self.outs]):
                self.save_type("self_transfer")
            else:
                self.save_type("send")
            # We should leave the tx_ledger.type alone so we can retype more easily...
            # for t in self.outs:
            #    t.save_type('send')

            # if we don't know that we're sending to ourselves, then we should flag the tx_logical for review
            # LATER: could there be a case if someone manually groups sends to different addresses in txlogical and then this is false? maybe but we won't care since it'll be up to them to make sure the tx_logical_type is correct if they've manually combined stuff but by default we won't group multiple asset sends to different addresses
            if len(self.outs) >= 1 and self.outs[0].to_address not in self.addresses:
                add_flag(
                    self.__class__.__name__,
                    self.id,
                    Flag(
                        source="perfi",
                        name="unknown_send",
                        description="This send may be a PAYMENT or GIFT",
                    ),
                )
            return

        ### TODO: flag guesses?

        # This is likely an approval but could be any contract interactio without finding call?
        if len(self.ins) == 0 and len(self.outs) == 0 and len(self.others) == 0:
            return

        if len(self.ins) == 1 and len(self.outs) == 1:
            # If either the in or the out was for FIAT, mark as a trade
            if self.ins[0].asset_tx_id.startswith("FIAT:") or self.outs[
                0
            ].asset_tx_id.startswith("FIAT:"):
                self.save_type("trade")
                return
            # Otherwise, it's a swap
            else:
                self.save_type("swap")
                return

        if len(self.ins) == 1 and len(self.outs) > 1:
            self.save_type("lp")
            return

        if len(self.ins) >= 1 and len(self.outs) == 1:
            self.save_type("lp")
            return

        # TODO: Default - unknown?
        # Unknown Tx Type
        logger.warning("UNKNOWN TX TYPE! fix in type_transactions")
        logger.warning(pformat(self))


class AssetPrice(BaseModel):
    id: int
    source: str
    symbol: str
    name: str
    raw_data: str
    market_cap: Optional[int]


class CostbasisLot(BaseModel):
    tx_ledger_id: str
    entity: str
    address: str
    asset_price_id: Optional[str] = None
    symbol: Optional[str] = None
    asset_tx_id: str
    original_amount: Decimal
    current_amount: Decimal
    price_usd: Decimal
    basis_usd: Decimal
    timestamp: int
    history: List[TxLedger] = []
    flags: List[Flag] = []
    receipt: int
    price_source: str
    chain: str
    locked_for_year: Optional[int]


class CostbasisDisposal(BaseModel):
    id: Optional[int] = None
    entity: str
    address: str
    asset_price_id: Optional[str]
    symbol: str
    amount: Decimal
    timestamp: int
    duration_held: int
    basis_timestamp: int
    basis_tx_ledger_id: str
    basis_usd: Decimal
    total_usd: Decimal
    tx_ledger_id: str
    price_source: str


class CostbasisIncome(BaseModel):
    id: int
    entity: str
    address: str
    net_usd: Decimal
    symbol: str
    timestamp: int
    tx_ledger_id: str
    price: Optional[Decimal]  # TODO: should this be allowed to be None?
    amount: Decimal
    lots: list


class AssetBalance(BaseModel):
    id: Optional[int]
    symbol: str
    exposure_symbol: str
    amount: Decimal
    protocol: Optional[str]
    address: Optional[str]
    chain: Optional[str]
    source: Optional[str]
    updated: Optional[int]
    label: Optional[str]
    price: Optional[Decimal]
    usd_value: Optional[Decimal]
    type: Optional[str]
    locked: Optional[int]
    proxy: Optional[str]
    extra: Optional[str]
    stable: Optional[int]


class RecordNotFoundException(Exception):
    pass


class StoreProtocol(Protocol):
    def find(self, **kwargs):
        pass


class BaseStore(ABC, Generic[T]):
    def __init__(
        self, db: DB, table_name: str, model_class: Type[T], primary_key: str = "id"
    ):
        self.db = db
        self.table_name = table_name
        self.model_class = model_class
        self.primary_key = primary_key
        self.param_mappings = {}

    def _add_param_mapping(self, attr, mapping_func):
        self.param_mappings[attr] = mapping_func

    def _model_field_names(self):
        return list(self.model_class.schema(False).get("properties").keys())

    def find_by_primary_key(self, key):
        args = {}
        args[self.primary_key] = key
        return self.find(**args)

    def find(self, **kwargs) -> List[T]:
        where = " AND ".join([f"{arg} = ?" for arg in kwargs])
        sql = f"""SELECT *
                  FROM {self.table_name}
                  WHERE {where}
               """
        params = [kwargs[arg] for arg in kwargs]
        result = self.db.query(sql, params)
        return [self.model_class(**r) for r in result]

    def update_or_create(self, record) -> T:
        attrs = self._model_field_names()
        sql = ""
        if getattr(record, self.primary_key, None):
            sql += "REPLACE INTO "
        else:
            sql += "INSERT INTO "
            attrs.remove(self.primary_key)
        sql += f"{self.table_name} "
        sql += f"""({", ".join(attrs)}) VALUES ({", ".join("?" * len(attrs))})"""

        record_dict = record.dict()
        params = []
        for attr in attrs:
            if self.param_mappings.get(attr):
                mapped = self.param_mappings.get(attr)(record_dict[attr])
                params.append(mapped)
            else:
                params.append(record_dict[attr])
        try:
            self.db.execute(sql, params)
        except Exception as err:
            debug(sql)
            debug(params)
            raise err

        if not getattr(record, self.primary_key, None) and self.primary_key == "id":
            record.id = self.db.cur.lastrowid
        return record

    def list(self, order_by: str = None) -> List[T]:
        order_by = order_by or f"{self.primary_key} ASC"
        sql = f"""SELECT * FROM {self.table_name} order by {order_by}"""
        return [self.model_class(**r) for r in self.db.query(sql)]

    def delete(self, key: str):
        sql = f"""DELETE FROM {self.table_name} where {self.primary_key} = ?"""
        params = [key]
        self.db.execute(sql, params)
        return dict(deleted=True)

    def save(self, record: T):
        return self.update_or_create(record)


class SettingStore(BaseStore[Setting]):
    def __init__(self, db):
        super().__init__(db, "setting", Setting, primary_key="key")

    def create(self, key: str, value: str) -> Setting:
        setting = Setting(key=key, value=value)
        return self.update_or_create(setting)


class EntityStore(BaseStore[Entity]):
    def __init__(self, db):
        super().__init__(db, "entity", Entity)

    def create(self, name: str, note: str = None, **kwargs) -> Entity:
        entity = Entity(name=name, note=note)
        return self.update_or_create(entity)

    def list(self, order_by: str = "name ASC"):
        return super().list(order_by=order_by)

    def delete(self, id):
        address_store = AddressStore(self.db)
        for address in address_store.find(entity_id=id):
            address_store.delete(address.id)

        return super().delete(id)


class AddressStore(BaseStore[Address]):
    def __init__(self, db):
        super().__init__(db, "address", Address)
        super()._add_param_mapping("chain", lambda c: c.value)

    def get_by_chain_and_address(self, chain, address):
        sql = "SELECT * FROM address WHERE chain = ? and address = ?"
        params = [chain, address]
        result = self.db.query(sql, params)
        if len(result) == 0:
            raise RecordNotFoundException(
                f"No address found with for chain `{chain}` and address `{address}`"
            )
        return result[0]

    # LATER: support accepting other attrs like type and source
    def create(
        self,
        label: str,
        chain: Chain,
        address: str,
        entity_name: str = None,
        entity_id: int = None,
        **kwargs,
    ):
        if not entity_id and entity_name:
            entity_id = int(
                self.db.query("SELECT id FROM entity WHERE name = ?", entity_name)[0][0]
            )

        address = Address(
            entity_id=entity_id, label=label, chain=chain, address=address
        )
        return self.update_or_create(address)

    def delete(self, address_id):
        return super().delete(address_id)

    def find_all_by_entity_name(self, entity_name, chain=None):
        chain_filter = "" if not chain else "AND address.chain == :chain"
        sql = f"""SELECT address.*
               FROM address, entity
               WHERE address.entity_id = entity.id
               AND entity.name = :entity_name
               {chain_filter}
               ORDER BY ord, label
            """
        params = {"entity_name": entity_name, "chain": chain}
        return [self.model_class(**r) for r in self.db.query(sql, params)]


class TxLogicalStore(BaseStore[TxLogical]):
    def __init__(self, db):
        self.tx_ledger_store = TxLedgerStore(db)
        super().__init__(db, "tx_logical", TxLogical)
        super()._add_param_mapping("tx_logical_type", lambda c: c.value)

    def paginated_list(
        self,
        entity_name: str,
        items_per_page: int = 100,
        page_num=0,
        direction: str = "DESC",
    ):
        sql = f"""
            SELECT id
            FROM tx_logical
             WHERE address IN (
                 SELECT address
                 FROM address, entity
                 WHERE entity_id = entity.id
                 AND entity.name = ?
             )
            AND count > 0
            ORDER BY timestamp { "DESC" if direction == "DESC" else "ASC" }
            LIMIT ? OFFSET ?
        """
        params = [entity_name, items_per_page, page_num * items_per_page]
        tx_logicals: List[TxLogical] = []
        for row in self.db.query(sql, params):
            txl = TxLogical.from_id(
                row["id"]
            )  # this is some sad n+1 querying but whatever
            tx_logicals.append(txl)
        return tx_logicals

    def find_by_primary_key(self, key):
        sql = """SELECT id from tx_logical WHERE id = ? ORDER BY timestamp ASC"""
        params = [key]
        results = self.db.query(sql, params)
        return [TxLogical.from_id(r["id"]) for r in results]

    def list(self, order_by="timestamp ASC"):
        sql = """SELECT id from tx_logical ORDER BY timestamp ASC"""
        tx_logicals: List[TxLogical] = []
        for row in self.db.query(sql):
            txl = TxLogical.from_id(row["id"])
            tx_logicals.append(txl)
        return tx_logicals

    def _create_for_tests(self, tx_logical: TxLogical):
        """
        IMPORTANT: This method is only intended to make our tests easier to write (rather than requiring constructing TxLedgers and TxLogicals from chain data)
        """

        # First, handle the tx_logical record
        sql = """INSERT INTO tx_logical (id, count, description, note, timestamp, address, tx_logical_type) VALUES (?, ?, ?, ?, ?, ?, ?)"""

        params = [
            tx_logical.id,
            tx_logical.count,
            tx_logical.description,
            tx_logical.note,
            tx_logical.timestamp,
            tx_logical.address,
            tx_logical.tx_logical_type,
        ]
        self.db.execute(sql, params)

        replace_flags(tx_logical.__class__.__name__, tx_logical.id, tx_logical.flags)

        # Now handle the related tx_ledgers
        for index, tx_ledger in enumerate(tx_logical.tx_ledgers):
            # Save the tx_ledger record
            self.tx_ledger_store.save(tx_ledger)

            # And update the relation
            sql = """INSERT INTO tx_rel_ledger_logical (tx_ledger_id, tx_logical_id, ord) VALUES (?, ?, ?)"""
            params = [tx_ledger.id, tx_logical.id, index]
            self.db.execute(sql, params)

        return tx_logical

    def save(self, tx_logical: TxLogical):
        sql = """REPLACE INTO tx_logical (id, count, description, note, timestamp, address, tx_logical_type) VALUES (?, ?, ?, ?, ?, ?, ?)"""
        params = [
            tx_logical.id,
            tx_logical.count,
            tx_logical.description,
            tx_logical.note,
            tx_logical.timestamp,
            tx_logical.address,
            tx_logical.tx_logical_type,
        ]
        self.db.execute(sql, params)
        TxLogical.from_id.cache_clear()
        return tx_logical

    def find(self, **kwargs):
        return [TxLogical.from_id(txl.id) for txl in super().find(**kwargs)]


class TxLedgerStore(BaseStore[TxLedger]):
    def __init__(self, db):
        super().__init__(db, "tx_ledger", TxLedger)
        super()._add_param_mapping("tx_ledger_type", lambda c: c.value)

    def find_by_primary_key(self, key):
        ledger: TxLedger = super().find_by_primary_key(key)[0]

        # Also load in the tx_logical_id as a convenience in case we want to know which logical this belongs to
        sql = (
            """SELECT tx_logical_id FROM tx_rel_ledger_logical where tx_ledger_id = ?"""
        )
        params = [ledger.id]
        results = self.db.query(sql, params)
        if len(results) == 1:
            return [ledger.copy(update={"tx_logical_id": results[0]["tx_logical_id"]})]
        else:
            raise Exception(
                "Every TX Ledger should belong to a TxLogical. What happened here for tx_ledger id {ledger.id}"
            )

    def save(self, tx: TxLedger):
        sql = """REPLACE INTO tx_ledger
             (id, chain, address, hash, from_address, to_address, from_address_name, to_address_name, asset_tx_id, isfee, amount, timestamp, direction, tx_ledger_type, asset_price_id, symbol, price_usd, price_source)
             VALUES
             (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          """
        params = [
            tx.id,
            tx.chain,
            tx.address,
            tx.hash,
            tx.from_address,
            tx.to_address,
            tx.from_address_name,
            tx.to_address_name,
            tx.asset_tx_id,
            tx.isfee,
            tx.amount,
            tx.timestamp,
            tx.direction,
            tx.tx_ledger_type,
            tx.asset_price_id,
            tx.symbol,
            tx.price_usd,
            tx.price_source,
        ]
        self.db.execute(sql, params)
        return tx


class CostbasisLotStore:
    def __init__(self, db):
        self.db = db

    def find(self, **kwargs) -> List[CostbasisLot]:
        where = " AND ".join([f"{arg} = ?" for arg in kwargs])
        sql = f"""SELECT *
                  FROM costbasis_lot
                  WHERE {where}
               """
        params = [kwargs[arg] for arg in kwargs]
        rows = self.db.query(sql, params)

        results = []
        for r in rows:
            r_dict = dict(**r)
            r_dict["history"] = jsonpickle.decode(r["history"])
            r_dict.pop("flags")
            flags = load_flags(CostbasisLot.__name__, r["tx_ledger_id"])
            lot = CostbasisLot(flags=flags, **r_dict)
            results.append(lot)
        return results


class AssetBalanceCurrentStore(BaseStore[AssetBalance]):
    def __init__(self, db):
        super().__init__(db, "balance_current", AssetBalance)

    def all_for_entity_id(self, id: int):
        sql = """SELECT bc.*
                 FROM balance_current bc
                 JOIN address a on bc.address = a.address
                 WHERE a.entity_id = ?
              """
        params = [id]
        return self.db.query(sql, params)


class AssetBalanceHistoryStore(BaseStore[AssetBalance]):
    def __init__(self, db):
        super().__init__(db, "balance_history", AssetBalance)

    def all_for_entity_id(self, id: int):
        sql = """SELECT bc.*
                 FROM balance_current bc
                 JOIN address a on bc.address = a.address
                 WHERE a.entity_id = ?
              """
        params = [id]
        return self.db.query(sql, params)
