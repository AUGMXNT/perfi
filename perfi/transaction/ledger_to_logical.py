import os

from ..db import db
from ..events import EventStore, EVENT_ACTION
from ..models import TxLedger, TxLogical

import argparse
from collections import namedtuple, defaultdict
from copy import copy
from decimal import Decimal
from datetime import datetime
from enum import Enum
import json
import jsonpickle
import logging
from prettytable import PrettyTable
from pprint import pprint, pformat
import rich.repr
import sys
import time
from tqdm import tqdm


logger = logging.getLogger(__name__)
LOGLEVEL = os.environ.get("LOGLEVEL", "WARNING").upper()
logger.setLevel(LOGLEVEL)


class TransactionLogicalGrouper:
    def __init__(self, entity, event_store: EventStore, print=False):
        self.entity = entity
        self._print = print
        self.event_store = event_store

    def update_entity_transactions(self, skip_regeneration=False):
        logger.debug(f"Entity: {self.entity}")
        logger.debug("---")
        # Get List of Accounts
        sql = """SELECT address.label, address.chain, address.address
               FROM address
               JOIN entity on entity.id = address.entity_id
               WHERE entity.name = ?
               ORDER BY ord, label
            """
        results = db.query(sql, self.entity)

        for wallet in results:
            label = wallet[0]
            chain = wallet[1]
            address = wallet[2]

            self.update_wallet_logical_transactions(address, skip_regeneration)

    def update_wallet_logical_transactions(self, address, skip_regeneration):
        logger.debug(f"Updating {address}")
        sql = """SELECT id, chain, address, hash, from_address, to_address, from_address_name, to_address_name, asset_tx_id, isfee, amount, timestamp, direction, tx_ledger_type, asset_price_id, symbol, price_usd
               FROM tx_ledger
               WHERE address = ?
            """
        tx_ledgers = list(db.query(sql, address))
        logger.debug(f"{len(tx_ledgers)} of tx_ledgers")

        # First Pass is going to insert a tx_logical for every tx_ledger (we need this for idempotency to be able to replay events)
        for tx in tqdm(tx_ledgers, desc="Generate Logical TXs", disable=None):
            if skip_regeneration:
                logger.debug("> SKIPPING regenerating tx_logical from tx_ledger")
                break

            sql = """REPLACE INTO tx_logical
                 (id, address, count, timestamp)
                 VALUES
                 (?, ?, ?, ?)
              """
            tx_ledger = TxLedger(**tx)

            params = [tx_ledger.id, address, 1, tx_ledger.timestamp]
            db.execute(sql, params)

            sql = """REPLACE INTO tx_rel_ledger_logical
                 (tx_ledger_id, tx_logical_id, ord)
                 VALUES
                 (?, ?, ?)
              """
            params = [tx_ledger.id, tx_ledger.id, 0]
            db.execute(sql, params)

        # Second pass is to group all our transaction by hash
        tx_logicals_by_hash = defaultdict(list)
        for tx in tqdm(tx_ledgers, desc="Group TXs by Hash   ", disable=None):
            # 1. Group all tx_logicals by the tx hash
            tx_ledger = TxLedger(**tx)
            tx_logicals_by_hash[tx_ledger.hash].append(tx_ledger)

        for hash in tqdm(
            tx_logicals_by_hash, desc="Generate MOVE events", disable=None
        ):
            hg = tx_logicals_by_hash[hash]
            txs = sorted(
                hg, key=lambda t: tx_ledger.timestamp + tx_ledger.isfee
            )  # timestamp + isfee

            # 2. Generate move event - a tx_logical_event with perfi:moved
            # Make move events to move all txs except first
            tx_logical_id_target = None
            for tx in txs:
                if not tx_logical_id_target:
                    tx_logical_id_target = tx.id
                else:
                    # create a move_event to the target
                    self.event_store.create_tx_ledger_moved(
                        tx.id, tx.id, tx_logical_id_target
                    )

        # 3. Apply move events (Or, optimization, do this at move event insert time too because we know it's safe)
        self.event_store.apply_events(action=EVENT_ACTION.tx_ledger_moved)

        # 4. Set tx_perfi_type based on hueristics of the grouped transactions
        self.assign_tx_perfi_type_for_logicals(address)

        # We are now done grouping. Printing here for dubugging pursposes.
        # self.print_groupings(address)

    def assign_tx_perfi_type_for_logicals(self, address):
        """
        IMPORTANT: This only works right now because we are lazy and using the debank tx name VALUES
        (something like 'deposit' or 'swap') when we set the tx ledger perfi type.  Eventually we will
        update this to be better and have swap_in and swap_out for example, which will require us
        to revisit this logic and make it better (e.g. dont just look for unique not 'fee' below)
        """
        sql = """SELECT id
       FROM tx_logical
       WHERE address = ?
       """
        params = [address]
        results = db.query(sql, params)
        for r in results:
            TxLogical.from_id(id=r["id"], entity_name=self.entity).refresh_type()

    def print_groupings(self, address, only_chain=None):
        sql = """SELECT id
                 FROM tx_logical
                 WHERE address = ?
                """
        params = [address]
        results = db.query(sql, params)

        tbl_logicals = PrettyTable()
        tbl_logicals.field_names = ["id", "description", "timestamp", "tx_ledgers"]

        for result in results:
            skip = False
            tx_log = TxLogical.from_id(id=result["id"], entity_name=self.entity)
            if tx_log.count == 0:
                skip = True
                continue
            tbl_logical_ledgers = PrettyTable()
            tbl_logical_ledgers.field_names = [
                "id",
                "chain",
                "hash",
                "from_address",
                "from_address_name",
                "to_address",
                "to_address_name",
                "isfee",
                "amount",
                "direction",
                "tx_ledger_type",
                "asset_price_id",
                "price",
                "symbol",
            ]
            for t in tx_log.tx_ledgers:
                if only_chain and t.chain != only_chain:
                    skip = True
                    continue
                tbl_logical_ledgers.add_row(
                    [
                        t.id,
                        t.chain,
                        t.hash[0:6] + "...",
                        t.from_address[0:6] + "...",
                        t.from_address_name,
                        t.to_address[0:6] + "...",
                        t.to_address_name,
                        t.isfee,
                        t.amount,
                        t.direction,
                        t.tx_ledger_type,
                        t.asset_price_id,
                        t.price_usd,
                        t.symbol,
                    ]
                )

            if not skip:
                tbl_logicals.add_row(
                    [
                        tx_log.id,
                        tx_log.description,
                        tx_log.timestamp,
                        tbl_logical_ledgers,
                    ]
                )

        logger.debug(tbl_logicals)
        print(tbl_logicals)
