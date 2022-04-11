from .constants import assets
from .db import db

import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from functools import cache
from pprint import pformat

import jsonpickle
from devtools import debug
from pydantic import BaseModel


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
    import_coinbase = "import.coinbasepro"
    import_kraken = "import.kraken"
    import_gemini = "import.gemini"
    import_bitcointax = "import.bitcointax"


class Entity(BaseModel):
    id: int | None = None
    name: str
    note: str | None = None


class Address(BaseModel):
    id: int | None = None
    label: str
    chain: Chain
    address: str
    type: str = "account"
    source: str = "manual"
    ord: int = 1
    entity_id: int


Entity.update_forward_refs()


class TxLedger(BaseModel):
    id: str | None = None
    chain: str  # Consider migrating to Chain enum
    address: str
    hash: str
    from_address: str
    to_address: str
    from_address_name: str | None = None
    to_address_name: str | None = None
    asset_tx_id: str
    isfee: int
    amount: Decimal
    timestamp: int
    direction: str  # Consider migrating to a new Direction enum
    tx_ledger_type: str | None = None  # Consider migrating to TX_LOGICAL_TYPE enum
    asset_price_id: str | None = None
    symbol: str | None = None
    price_usd: Decimal | None = None

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
    tx_ledgers: list[TxLedger] = []
    address: str = ""
    addresses: list[str] = []
    tx_logical_type: str = ""  # replace with enum?
    entity: str | None = None
    flags: list[dict[str, str]] = []
    ins: list[TxLedger] = []
    outs: list[TxLedger] = []
    fee: TxLedger | None = None
    others: list[TxLedger] = []

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
    @cache
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
        sql = """SELECT id, count, description, note, timestamp, address, tx_logical_type, flags
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
        try:
            txl.flags = jsonpickle.decode(r[7])
        except:
            txl.flags = []

        # load the tx ledgers
        sql = """SELECT id, chain, address, hash, from_address, to_address, from_address_name, to_address_name, asset_tx_id, isfee, amount, timestamp, direction, tx_ledger_type, asset_price_id, symbol, price_usd
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

    def auto_description(self):
        datestamp = datetime.fromtimestamp(self.timestamp).isoformat() + "Z"
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
        if len(self.ins) > 0:
            chain = self.ins[0].chain
            hash = self.ins[0].hash
        return " | ".join(
            [
                datestamp,
                tx_logical_type,
                "OUTs " + ", ".join(outs_strs),
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
                  flags = ?
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
            jsonpickle.encode(self.flags),
            self.id,
        ]
        db.execute(sql, params)

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

        # HACK - but seeing if this works.  I don't think you can put assets into CoinbasePro without it being a self-transfer.
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

        if self.tx_logical_type in [
            "CoinbasePro.BUY",
            "CoinbasePro.SELL",
            "CoinbasePro.trade",
            "Kraken.trade",
            "Gemini.Buy",
            "Gemini.Sell",
            "Coinbase.Buy",
            "Coinbase.Sell",
        ]:
            self.save_type("trade")
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
                self.flags.append(
                    {
                        "name": "unknown_send",
                        "description": "This send may be a PAYMENT or GIFT",
                    }
                )
                self.save()
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
    market_cap: int | None


class CostbasisLot(BaseModel):
    tx_ledger_id: str
    entity: str
    address: str
    asset_price_id: str | None = None
    symbol: str | None = None
    asset_tx_id: str
    original_amount: Decimal
    current_amount: Decimal
    price_usd: Decimal
    basis_usd: Decimal
    timestamp: int
    history: list[TxLedger] = []
    flags: list[dict[str, str]] = []
    receipt: int
    price_source: str


class CostbasisDisposal(BaseModel):
    id: int | None = None
    entity: str
    address: str
    asset_price_id: str | None
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
    price: Decimal | None  # TODO: should this be allowed to be None?
    amount: Decimal
    lots: list


class EntityStore:
    def __init__(self, db):
        self.db = db

    def create(self, name: str, note: str = None, addresses: list[Address] = None):
        entity = Entity(name=name, note=note)
        sql = """INSERT INTO entity (name) VALUES (?);"""
        params = [entity.name]
        result = self.db.execute(sql, params)
        # LATER do we want to allow creating of any addresses inside the passed <entity>?
        entity.id = db.cur.lastrowid
        return entity


class AddressStore:
    def __init__(self, db):
        self.db = db

    def list(self):
        sql = """SELECT a.*, e.name as entity_name FROM address a JOIN entity e on e.id = a.entity_id"""
        rows = self.db.query(sql)
        addresses = []
        for r in rows:
            d = dict(**r)
            d["chain"] = Chain[
                d["chain"].replace("import.", "import_")
            ]  # HACK: we use a `import.exchange_name` pattern but we can't use `.` in our Enum values...
            entity = Entity(id=d["entity_id"], name=d["entity_name"])
            d["entity"] = entity
            addresses.append(Address(**d))
        return addresses

    def _insert_or_create(self, address: Address):
        if address.id:
            sql = """REPLACE INTO address (id, label, chain, address, type, source, entity_id, ord) VALUES (?,?,?,?,?,?,?, ?)"""
        else:
            sql = """INSERT INTO address (label, chain, address, type, source, entity_id, ord) VALUES (?,?,?,?,?,?,?)"""

        params = [
            address.label,
            address.chain.value,
            address.address,
            address.type,
            address.source,
            address.entity_id,
            address.ord
            or 1,  # TODO: count existing addresses and increment by 1 for this, rather than just hardcoding to 1
        ]
        if address.id:
            params.insert(0, address.id)
        self.db.execute(sql, params)
        if not address.id:
            address.id = db.cur.lastrowid
        return address

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
        return self._insert_or_create(address)

    def save(self, address: Address):
        return self._insert_or_create(address)

    def delete(self, address_id):
        sql = """DELETE FROM address where id = ?"""
        params = [address_id]
        self.db.execute(sql, params)
        return dict(deleted=True)


class TxLogicalStore:
    def __init__(self, db):
        self.db = db
        self.tx_ledger_store = TxLedgerStore(db)

    def list(self):
        sql = """SELECT id from tx_logical ORDER BY timestamp ASC"""
        tx_logicals: list[TxLogical] = []
        for row in self.db.query(sql):
            txl = TxLogical.from_id(row["id"])

            # # Now load the ledgers
            # sql = """
            #     SELECT *
            #     FROM tx_ledger t
            #     JOIN tx_rel_ledger_logical trll on t.id = trll.tx_ledger_id
            #     WHERE trll.tx_logical_id = ?
            # """
            # params = [txl.id]
            # for ledger_row in self.db.query(sql, params):
            #     tx_ledger = TxLedger(**ledger_row)
            #     txl.tx_ledgers.append(tx_ledger)
            #
            # txl._group_ledgers()

            tx_logicals.append(txl)
        return tx_logicals

    def create(self, tx_logical: TxLogical):
        """
        IMPORTANT: This method is only intended to make our tests easier to write (rather than requiring constructing TxLedgers and TxLogicals from chain data)
        """

        # First, handle the tx_logical record
        sql = """INSERT INTO tx_logical (id, count, description, note, timestamp, address, tx_logical_type, flags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""

        params = [
            tx_logical.id,
            tx_logical.count,
            tx_logical.description,
            tx_logical.note,
            tx_logical.timestamp,
            tx_logical.address,
            tx_logical.tx_logical_type,
            jsonpickle.encode(tx_logical.flags),
        ]
        self.db.execute(sql, params)

        # Now handle the related tx_ledgers
        for index, tx_ledger in enumerate(tx_logical.tx_ledgers):
            # Save the tx_ledger record
            self.tx_ledger_store.save(tx_ledger)

            # And update the relation
            sql = """INSERT INTO tx_rel_ledger_logical (tx_ledger_id, tx_logical_id, ord) VALUES (?, ?, ?)"""
            params = [tx_ledger.id, tx_logical.id, index]
            self.db.execute(sql, params)

        return tx_logical


class TxLedgerStore:
    def __init__(self, db):
        self.db = db

    def save(self, tx: TxLedger):
        sql = """REPLACE INTO tx_ledger
             (id, chain, address, hash, from_address, to_address, from_address_name, to_address_name, asset_tx_id, isfee, amount, timestamp, direction, tx_ledger_type, asset_price_id, symbol, price_usd)
             VALUES
             (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ]
        self.db.execute(sql, params)
        return tx
