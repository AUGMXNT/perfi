from .models import TxLedger, TxLogical, Flag, replace_flags

from copy import copy
from dataclasses import dataclass
from enum import Enum
from tqdm import tqdm
import json
import jsonpickle
import time
import uuid


class EVENT_ACTION(Enum):
    tx_ledger_moved = "tx_ledger_moved"
    tx_ledger_type_updated = "tx_ledger_type_updated"
    tx_ledger_price_updated = "tx_ledger_price_updated"
    tx_logical_type_updated = "tx_logical_type_updated"
    tx_logical_flag_added = "tx_logical_flag_added"


@dataclass
class Event:
    id: str
    source: str
    action: EVENT_ACTION
    data: dict
    timestamp: int


class EventStore:
    def __init__(self, db, TxLogical, TxLedger):
        self.db = db
        self.TxLogical = TxLogical
        self.TxLedger = TxLedger

    def new_id(self):
        return str(uuid.uuid4())

    def apply_events(self, action: EVENT_ACTION = None, source: str = None):
        # QUESTION: should we consider moving to entity-scoped events?
        # Right now we re-apply all events here, which is fine as long as we
        # keep event application as idempotent.
        sql = f"""
            SELECT id, source, action, data, timestamp
            FROM event
            WHERE 1=1
            {'AND action = ?' if action else ''}
            {'AND source = ?' if source else ''}
            ORDER BY timestamp
        """
        params = []
        if action:
            params.append(action.value)
        if source:
            params.append(source)
        results = self.db.query(sql, params)
        desc = "Applying events"
        if action:
            desc += ": " + action.value
        for rec in tqdm(results, desc=desc, disable=None):
            id = rec[0]
            source = rec[1]
            action = EVENT_ACTION(rec[2])
            data = json.loads(rec[3])
            timestamp = rec[4]
            event = Event(id, source, action, data, timestamp)
            self.apply_event(event)

    def apply_event(self, event: Event):
        handlers = {
            EVENT_ACTION.tx_ledger_moved: self.handle_tx_ledger_moved_event,
            EVENT_ACTION.tx_ledger_type_updated: self.handle_tx_ledger_type_updated_event,
            EVENT_ACTION.tx_ledger_price_updated: self.handle_tx_ledger_price_updated_event,
            EVENT_ACTION.tx_logical_flag_added: self.handle_tx_logical_flag_added_event,
            EVENT_ACTION.tx_logical_type_updated: self.handle_tx_logical_type_updated_event,
        }
        if event.action not in handlers.keys():
            raise Exception(f"Don't know how to handle event action {event.action}")
        else:
            handlers[event.action].__call__(event)

    def create_tx_logical_type_updated(
        self, tx_logical_id: str, new_tx_logical_type: str, source: str = "perfi"
    ):
        tx = self.TxLogical.from_id(tx_logical_id)

        id = self.new_id()
        source = source
        action = EVENT_ACTION.tx_logical_type_updated
        data = {
            "version": 1,
            "tx_logical_id": tx_logical_id,
            "tx_logical_type_old": tx.tx_logical_type,
            "tx_logical_type_new": new_tx_logical_type,
        }
        timestamp = int(time.time())
        sql = """INSERT INTO event
               (id, source, action, data, timestamp)
               VALUES
               (?, ?, ?, ?, ?)
            """
        params = [
            id,
            source,
            action.value,
            json.dumps(data),
            timestamp,
        ]
        self.db.execute(sql, params)
        TxLogical.from_id.cache_clear()
        return Event(id, source, action, data, timestamp)

    def create_tx_ledger_type_updated(
        self, tx_ledger_id: str, new_tx_ledger_type: str, source: str = "perfi"
    ):
        tx = self.TxLedger.get(tx_ledger_id)

        id = self.new_id()
        source = source
        action = EVENT_ACTION.tx_ledger_type_updated
        data = {
            "version": 1,
            "tx_ledger_id": tx_ledger_id,
            "tx_ledger_type_old": tx.tx_ledger_type,
            "tx_ledger_type_new": new_tx_ledger_type,
        }
        timestamp = int(time.time())
        sql = """INSERT INTO event
               (id, source, action, data, timestamp)
               VALUES
               (?, ?, ?, ?, ?)
            """
        params = [
            id,
            source,
            action.value,
            json.dumps(data),
            timestamp,
        ]
        self.db.execute(sql, params)
        TxLogical.from_id.cache_clear()
        return Event(id, source, action, data, timestamp)

    def create_tx_ledger_moved(
        self,
        tx_ledger_id: str,
        source_tx_logical_id: str,
        target_tx_logical_id: str,
        source: str = "perfi",
    ):
        id = self.new_id()
        source = source
        action = EVENT_ACTION.tx_ledger_moved
        data = {
            "version": 1,
            # We need to know which ledger tx we're reparenting
            "tx_ledger_id": tx_ledger_id,
            # On our first run, this will be where we're moving from
            "from_tx_logical_id": source_tx_logical_id,
            # And we'll be reparenting to the target
            "to_tx_logical_id": target_tx_logical_id,
        }
        timestamp = int(time.time())
        sql = """INSERT INTO event
           (id, source, action, data, timestamp)
           VALUES
           (?, ?, ?, ?, ?)
        """
        params = [
            id,
            source,
            action.value,
            json.dumps(data),
            timestamp,
        ]
        self.db.execute(sql, params)
        TxLogical.from_id.cache_clear()
        return Event(id, source, action, data, timestamp)

    def create_tx_ledger_price_updated(
        self,
        tx_ledger_id: str,
        new_price_usd: float,
        new_price_source: str,
        source: str = "perfi",
    ):
        id = self.new_id()
        source = source
        action = EVENT_ACTION.tx_ledger_price_updated
        data = {
            "version": 1,
            "tx_ledger_id": tx_ledger_id,
            "price_usd_new": new_price_usd,
            "price_source_new": new_price_source,
        }
        timestamp = int(time.time())
        sql = """INSERT INTO event
           (id, source, action, data, timestamp)
           VALUES
           (?, ?, ?, ?, ?)
        """
        params = [
            id,
            source,
            action.value,
            json.dumps(data),
            timestamp,
        ]
        self.db.execute(sql, params)
        TxLogical.from_id.cache_clear()
        return Event(id, source, action, data, timestamp)

    # TODO refactor type signature to use TX_LOGICAL_FLAG for flag param after we move TX_LOGICAL_FLAG to its own module to avoid circular imports
    def create_tx_logical_flag_added(
        self, tx_logical_id: str, flag, source: str = "perfi"
    ):
        id = self.new_id()
        source = source
        action = EVENT_ACTION.tx_logical_flag_added
        data = {
            "version": 1,
            "tx_logical_id": tx_logical_id,
            "flag_value": flag.value,
        }
        timestamp = int(time.time())
        sql = """INSERT INTO event
           (id, source, action, data, timestamp)
           VALUES
           (?, ?, ?, ?, ?)
        """
        params = [
            id,
            source,
            action.value,
            json.dumps(data),
            timestamp,
        ]
        self.db.execute(sql, params)
        TxLogical.from_id.cache_clear()
        return Event(id, source, action, data, timestamp)

    def handle_tx_ledger_moved_event(self, event: Event):
        data = event.data
        tx_ledger_id = data["tx_ledger_id"]
        from_tx_logical_id = data["from_tx_logical_id"]
        to_tx_logical_id = data["to_tx_logical_id"]

        sql = """UPDATE tx_rel_ledger_logical
               SET tx_ledger_id = ?, tx_logical_id = ?
               WHERE tx_ledger_id = ?
               AND tx_logical_id = ?
            """
        params = [tx_ledger_id, to_tx_logical_id, tx_ledger_id, from_tx_logical_id]
        self.db.execute(sql, params)

        # Update tx count and last updated
        for id in (from_tx_logical_id, to_tx_logical_id):
            sql = """UPDATE tx_logical
                 SET count = (
                   SELECT COUNT(*)
                   FROM tx_rel_ledger_logical
                   WHERE tx_logical_id = ?
                 ) WHERE id = ?
              """
            params = [id, id]
            self.db.execute(sql, params)
        TxLogical.from_id.cache_clear()

    def handle_tx_ledger_type_updated_event(self, event: Event):
        tx = self.TxLedger.get(event.data["tx_ledger_id"])
        updated_tx = copy(tx)
        updated_tx.tx_ledger_type = event.data["tx_ledger_type_new"]
        sql = """UPDATE tx_ledger SET tx_ledger_type = ? where id = ?"""
        params = [event.data["tx_ledger_type_new"], event.data["tx_ledger_id"]]
        self.db.execute(sql, params)
        TxLogical.from_id.cache_clear()

    def handle_tx_logical_type_updated_event(self, event: Event):
        tx = self.TxLogical.from_id(event.data["tx_logical_id"])
        updated_tx = copy(tx)
        updated_tx.tx_logical_type = event.data["tx_logical_type_new"]
        sql = """UPDATE tx_logical SET tx_logical_type = ? where id = ?"""
        params = [event.data["tx_logical_type_new"], event.data["tx_logical_id"]]
        self.db.execute(sql, params)
        TxLogical.from_id.cache_clear()

    def handle_tx_ledger_price_updated_event(self, event: Event):
        tx = self.TxLedger.get(event.data["tx_ledger_id"])
        updated_tx = copy(tx)
        updated_tx.price_usd = event.data["price_usd_new"]
        sql = """UPDATE tx_ledger SET price_usd = ?, price_source = ? where id = ?"""
        params = [
            event.data["price_usd_new"],
            event.data["price_source_new"],
            event.data["tx_ledger_id"],
        ]
        self.db.execute(sql, params)
        TxLogical.from_id.cache_clear()

    def handle_tx_logical_flag_added_event(self, event: Event):
        tx: TxLogical = self.TxLogical.from_id(event.data["tx_logical_id"])
        new_flag = Flag(source="manual", name=event.data["flag_value"])
        updated_flags = tx.flags + [new_flag]
        replace_flags(TxLogical.__name__, tx.id, updated_flags)
        TxLogical.from_id.cache_clear()
