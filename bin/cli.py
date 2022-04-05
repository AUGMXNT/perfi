# This is a single-command parser for perfi actions that we want users to be able to do
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
import json
import logging
from devtools import debug
import sys
import time
import typer
import os

from perfi.constants.paths import (
    CACHEDB_PATH,
    DATA_DIR,
    DB_PATH,
    DB_SCHEMA_PATH,
    CACHEDB_SCHEMA_PATH,
)
from perfi.costbasis import regenerate_costbasis_lots
from perfi.events import EVENT_ACTION, EventStore
from perfi.models import (
    Entity,
    Address,
    Chain,
    TxLedger,
    TxLogical,
    TX_LOGICAL_FLAG,
    TX_LOGICAL_TYPE,
    AddressStore,
    EntityStore,
)
from perfi.db import db

from perfi.transaction.ledger_to_logical import TransactionLogicalGrouper

# TODO: better way to do this
from perfi.transaction.chain_to_ledger import update_entity_transactions

"""
=======================================
CLI TODOs left:
TX Logical
[] LATER Change tx_logical description or note

Costbasis Lot
[] update asset_price_id/symbol
=======================================
"""

logger = logging.getLogger(__name__)

if sys.stdout.isatty():
    # Setup logger config so we get lines that look like: 2017-06-06:17:07:02,158 DEBUG    [log.py:11] This is a debug log
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s : %(levelname)-8s  [%(filename)s:%(lineno)d] %(message)s"
    )
    logger.addHandler(console)

args = None


entity_store = EntityStore(db)
address_store = AddressStore(db)


# Entity
# ---------------------------------------------
entity_app = typer.Typer()


@entity_app.command("create")
def entity_create(name: str):
    entity = entity_store.create(name=name)
    print(f"Created entity {entity}")
    choice = ""
    num_addresses_added = 0
    while choice.lower() != "n":
        choice = typer.prompt(
            f"Would you like to add an{'other' if num_addresses_added > 0 else ''} address for `{name}`? [Y]es or [N]o"
        )
        match choice.lower():
            case "y" | "yes":
                address = typer.prompt(
                    f"Enter an ethereum-compatible wallet address (e.g. 0x12345....):"
                )
                label = typer.prompt(
                    f"Enter a label for this address (e.g. 'My DeFi'):"
                )
                address = address_store.create(
                    entity_name=entity.name,
                    label=label,
                    chain=Chain.ethereum,
                    address=address,
                )
                print(f"Created address {address}")
                num_addresses_added += 1
    print("Done!")


@entity_app.command("add_address")
def entity_add_address(entity_name: str, label: str, chain: Chain, address: str):
    address = address_store.create(
        entity_name=entity_name, label=label, chain=chain, address=address
    )
    print(f"Created address {address}")


# Ledgers
# ---------------------------------------------

ledger_app = typer.Typer()

event_store = EventStore(db, TxLogical, TxLedger)


def _refresh_state(entity_name: str, trigger_action: EVENT_ACTION):
    print("Refreshing downstream state...")
    match trigger_action:
        case EVENT_ACTION.tx_ledger_type_updated:
            update_entity_transactions(entity_name)
            tlg = TransactionLogicalGrouper(entity_name, event_store)
            tlg.update_entity_transactions()
            regenerate_costbasis_lots(entity_name, args=None, quiet=True)
        case EVENT_ACTION.tx_ledger_moved | EVENT_ACTION.tx_logical_type_updated:
            tlg = TransactionLogicalGrouper(entity_name, event_store)
            tlg.update_entity_transactions()
            regenerate_costbasis_lots(entity_name, args=None, quiet=True)
        case EVENT_ACTION.tx_logical_flag_added | EVENT_ACTION.tx_ledger_price_updated:
            regenerate_costbasis_lots(entity_name, args=None, quiet=True)
        case _:
            raise Exception(
                f"Don't know how to handle refreshing state for trigger action {trigger_action.value}"
            )
    print("State is fully refreshed now.")


@ledger_app.command("update_logical_type")
def ledger_update_logical_type(
    entity_name: str, tx_logical_id: str, new_tx_logical_type: str
):
    allowed_values = [e.value for e in TX_LOGICAL_TYPE]
    if new_tx_logical_type not in allowed_values:
        raise Exception(
            f"Value {new_tx_logical_type} not allowed for tx_logical_type. Valid values are: {', '.join(allowed_values)}"
        )
    event = event_store.create_tx_logical_type_updated(
        tx_logical_id, new_tx_logical_type, source="manual"
    )
    event_store.apply_event(event)
    print(
        f"Updated tx_logical {tx_logical_id} - set tx_logical_type to {new_tx_logical_type}"
    )
    _refresh_state(entity_name, event.action)


@ledger_app.command("update_ledger_type")
def ledger_update_ledger_type(
    entity_name: str, tx_ledger_id: str, new_tx_ledger_type: str
):
    allowed_values = [e.value for e in TX_LOGICAL_TYPE]
    if new_tx_ledger_type not in allowed_values:
        raise Exception(
            f"Value {new_tx_ledger_type} not allowed for tx_ledger_type. Valid values are: {', '.join(allowed_values)}"
        )
    event = event_store.create_tx_ledger_type_updated(
        tx_ledger_id, new_tx_ledger_type, source="manual"
    )
    event_store.apply_event(event)
    print(
        f"Updated tx_ledger {tx_ledger_id} - set tx_ledger_type to {new_tx_ledger_type}"
    )
    _refresh_state(entity_name, event.action)


@ledger_app.command("update_price")
def ledger_update_price(entity_name: str, tx_ledger_id: str, new_price_usd: float):
    event = event_store.create_tx_ledger_price_updated(
        tx_ledger_id, new_price_usd, source="manual"
    )
    event_store.apply_event(event)
    print(f"Updated tx_ledger {tx_ledger_id} - set price to {new_price_usd}")
    _refresh_state(entity_name, event.action)


@ledger_app.command("add_flag_to_logical")
def ledger_flag_logical(entity_name: str, tx_logical_id: str, flag: TX_LOGICAL_FLAG):
    event = event_store.create_tx_logical_flag_added(
        tx_logical_id, flag, source="manual"
    )
    event_store.apply_event(event)
    print(f"Updated tx_logical {tx_logical_id} - added flag {flag.value}")
    _refresh_state(entity_name, event.action)


@ledger_app.command("move")
def ledger_move_tx_ledger(entity_name: str, tx_ledger_id: str, new_tx_logical_id: str):
    old_tx_logical = TxLogical.get_by_tx_ledger_id(tx_ledger_id)
    new_tx_logical = TxLogical.from_id(new_tx_logical_id)
    event = event_store.create_tx_ledger_moved(
        tx_ledger_id, old_tx_logical.id, new_tx_logical.id, source="manual"
    )
    event_store.apply_event(event)
    print(
        f"Moved tx_ledger {tx_ledger_id} - from tx_logical_id {old_tx_logical.id} to tx_logical_id {new_tx_logical.id}"
    )
    _refresh_state(entity_name, event.action)


app = typer.Typer(add_completion=False)
app.add_typer(entity_app, name="entity")
app.add_typer(ledger_app, name="ledger")


# Perfi Setup
# ---------------------------------------------
@app.command("setup")
def setup_perfi():
    # Entity
    print(
        "perfi uses Entities to group On-Chain Addresses together. Think of an Entity like a user."
    )
    entity_name = typer.prompt("Please enter a name for your first entity")
    entity = entity_store.create(name=entity_name)
    print(f"Created entity {entity}")
    print("Now you should probably add at least one Address for your Entity.")
    choice = ""
    num_addresses_added = 0
    while choice.lower() != "n":
        choice = typer.prompt(
            f"Would you like to add an{'other' if num_addresses_added > 0 else ''} address for `{entity.name}`? [Y]es or [N]o"
        )
        match choice.lower():
            case "y" | "yes":
                address = typer.prompt(
                    f"Enter an ethereum-compatible wallet address (e.g. 0x12345....):"
                )
                label = typer.prompt(
                    f"Enter a label for this address (e.g. 'My DeFi'):"
                )
                address = address_store.create(
                    entity_name=entity.name,
                    label=label,
                    chain=Chain.ethereum,
                    address=address,
                )
                print(f"Created address {address}")
                num_addresses_added += 1
    print("Done!")
    print(
        "If you want to create more Entities later, run `poetry run bin/cli.py entity create`"
    )
    print(
        "If you want to create more Addresses later, run `poetry run bin/cli.py address create`"
    )  # TODO check these help texts

    # Add Settings
    print(
        "perfi interacts with some third-party systems to gather data. You'll need to enter some API keys now..."
    )

    # Various Keys, or skip - optional

    # TODO: crawling, skip service if we don't have a key (eg covalent)?


def main():
    app()


if __name__ == "__main__":
    main()
