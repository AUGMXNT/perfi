# This is a single-command parser for perfi actions that we want users to be able to do
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
import json
import logging

import coinaddrvalidator
from devtools import debug
from rich.console import Console
import sys
import time
import typer
import os
import pytz

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
    CostbasisLotStore,
    RecordNotFoundException,
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

colors
* https://typer.tiangolo.com/tutorial/printing/
* https://github.com/tiangolo/typer/issues/196
* https://github.com/click-contrib/click-help-colors
rich vs pytermgui
* https://github.com/bczsalba/pytermgui
"""


class CommandNotPermittedException(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


logger = logging.getLogger(__name__)

if sys.stdout.isatty():
    # Setup logger config so we get lines that look like: 2017-06-06:17:07:02,158 DEBUG    [log.py:11] This is a debug log
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s : %(levelname)-8s  [%(filename)s:%(lineno)d] %(message)s"
    )
    logger.addHandler(console)


def save_setting(key: str, value: str):
    sql = """REPLACE INTO setting (key, value) VALUES (?, ?)"""
    params = [key, value]
    db.execute(sql, params)


args = None

# rich console
console = Console()


entity_store = EntityStore(db)
address_store = AddressStore(db)
costbasis_lot_store = CostbasisLotStore(db)


# Entity
# ---------------------------------------------
entity_app = typer.Typer()


@entity_app.command("create")
def entity_create(name: str):
    results = entity_store.find(name=name)
    if len(results) != 0:
        print(
            f"ERROR: Failed to create entity. An entity with name {name} already exists."
        )
        return
    else:
        entity = entity_store.create(name=name)
        print(f"Created entity {entity}")


@entity_app.command("add_address")
def entity_add_address(entity_name: str, label: str, chain: Chain, address: str):
    try:
        result = address_store.get_by_chain_and_address(
            chain=chain.value, address=address
        )
        print(
            f"ERROR: Failed to create address. An address with chain {chain.value} and address {address} already exists: {dict(**result)}"
        )
        return
    except RecordNotFoundException as err:
        validation_result = coinaddrvalidator.validate("eth", address)
        if not validation_result.valid:
            print(
                f"ERROR: Failed to create address. Address {address} doesn't look valid for chain {chain.value}"
            )
            return

        address = address_store.create(
            entity_name=entity_name, label=label, chain=chain, address=address
        )
        print(f"Created address {address}")


@entity_app.command("lock_costbasis_lots")
def entity_lock_costbasis_lots(entity_name: str, year: int):
    event = event_store.create_costbasis_lots_locked(entity_name, year, source="manual")
    event_store.apply_event(event)
    print(f"Locked costbasis lots for entity {entity_name} and year {year}")


# Setting
# ---------------------------------------------
setting_app = typer.Typer()


@setting_app.command("add")
def setting_update(key: str, value: str):
    save_setting(key, value)
    print(f"Done. Set {key} to {value}")


@setting_app.command("remove")
def setting_remove(key: str):
    sql = """DELETE FROM SETTING WHERE key = ?"""
    params = [key]
    db.execute(sql, params)
    print(f"Done. Removed setting with key {key}")


@setting_app.command("set_reporting_timezone")
def setting_set_reporting_timezone(name: str):
    if name not in pytz.all_timezones_set:
        print(f"ERROR - {name} is not a time zone name that perfi knows how to handle.")
        print(
            f"Try running `poetry run bin/cli.py setting get_timezone_names` to see all the valid time zone names."
        )
    else:
        save_setting("REPORTING_TIMEZONE_NAME", name)
        print(f"Done. Your disposal date/times will now be shown in {name} time.")


@setting_app.command("get_timezone_names")
def setting_get_reporting_timezones():
    for name in pytz.all_timezones:
        print(name)


# Ledgers
# ---------------------------------------------

ledger_app = typer.Typer()

event_store = EventStore(db, TxLogical, TxLedger)


def _refresh_state(entity_name: str, trigger_action: EVENT_ACTION):
    print("Refreshing downstream state...")
    if trigger_action == EVENT_ACTION.tx_ledger_type_updated:
        update_entity_transactions(entity_name)
        tlg = TransactionLogicalGrouper(entity_name, event_store)
        tlg.update_entity_transactions()
        regenerate_costbasis_lots(entity_name, args=None, quiet=True)
    elif trigger_action in [
        EVENT_ACTION.tx_ledger_moved,
        EVENT_ACTION.tx_logical_type_updated,
    ]:
        tlg = TransactionLogicalGrouper(entity_name, event_store)
        tlg.update_entity_transactions()
        regenerate_costbasis_lots(entity_name, args=None, quiet=True)
    elif trigger_action in [
        EVENT_ACTION.tx_logical_flag_added,
        EVENT_ACTION.tx_ledger_price_updated,
    ]:
        regenerate_costbasis_lots(entity_name, args=None, quiet=True)
    else:
        raise Exception(
            f"Don't know how to handle refreshing state for trigger action {trigger_action.value}"
        )
    print("State is fully refreshed now.")


@ledger_app.command("update_logical_type")
def ledger_update_logical_type(
    entity_name: str,
    tx_logical_id: str,
    new_tx_logical_type: str,
    auto_refresh_state: bool = True,
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
    if auto_refresh_state:
        _refresh_state(entity_name, event.action)


@ledger_app.command("update_ledger_type")
def ledger_update_ledger_type(
    entity_name: str,
    tx_ledger_id: str,
    new_tx_ledger_type: str,
    auto_refresh_state: bool = True,
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
    if auto_refresh_state:
        _refresh_state(entity_name, event.action)


@ledger_app.command("update_price")
def ledger_update_price(
    entity_name: str, tx_ledger_id: str, new_price_usd: float, auto_refresh_state=True
):
    # Don't allow the ledger's price to be changed if we have locked a costbasis_lot for this ledger
    results = costbasis_lot_store.find(tx_ledger_id=tx_ledger_id)
    if len(results) > 0:
        if len(results) != 1:
            raise Exception(
                f"Found more than 1 lot for tx_ledger_id {tx_ledger_id}. How is this possible?"
            )
        lot = results[0]
        if lot.locked_for_year is not None:
            raise CommandNotPermittedException(
                f"The CostbasisLot for this tx_ledger_id ({tx_ledger_id}) was locked starting for tax year {lot.locked_for_year}. The price for the tx_ledger that created it can't be changed now."
            )

    event = event_store.create_tx_ledger_price_updated(
        tx_ledger_id,
        new_price_usd,
        new_price_source="user-provided",
        source="manual",  # new_price_souce can be anything. source is manual to reflect that this is not a perf-generated event
    )
    event_store.apply_event(event)
    print(f"Updated tx_ledger {tx_ledger_id} - set price to {new_price_usd}")
    if auto_refresh_state:
        _refresh_state(entity_name, event.action)


@ledger_app.command("add_flag_to_logical")
def ledger_flag_logical(
    entity_name: str, tx_logical_id: str, flag: TX_LOGICAL_FLAG, auto_refresh_state=True
):
    event = event_store.create_tx_logical_flag_added(
        tx_logical_id, flag, source="manual"
    )
    event_store.apply_event(event)
    print(f"Updated tx_logical {tx_logical_id} - added flag {flag.value}")
    if auto_refresh_state:
        _refresh_state(entity_name, event.action)


@ledger_app.command("delete_flag_from_logical")
def ledger_remove_flag_logical(
    entity_name: str, tx_logical_id: str, flag: TX_LOGICAL_FLAG, auto_refresh_state=True
):
    event = event_store.create_tx_logical_flag_removed(
        tx_logical_id, flag, source="manual"
    )
    event_store.apply_event(event)
    print(f"Updated tx_logical {tx_logical_id} - added flag {flag.value}")
    if auto_refresh_state:
        _refresh_state(entity_name, event.action)


@ledger_app.command("move")
def ledger_move_tx_ledger(
    entity_name: str, tx_ledger_id: str, new_tx_logical_id: str, auto_refresh_state=True
):
    old_tx_logical = TxLogical.get_by_tx_ledger_id(tx_ledger_id)
    new_tx_logical = TxLogical.from_id(new_tx_logical_id)
    event = event_store.create_tx_ledger_moved(
        tx_ledger_id, old_tx_logical.id, new_tx_logical.id, source="manual"
    )
    event_store.apply_event(event)
    print(
        f"Moved tx_ledger {tx_ledger_id} - from tx_logical_id {old_tx_logical.id} to tx_logical_id {new_tx_logical.id}"
    )
    if auto_refresh_state:
        _refresh_state(entity_name, event.action)


app = typer.Typer(add_completion=False)
app.add_typer(entity_app, name="entity")
app.add_typer(ledger_app, name="ledger")
app.add_typer(setting_app, name="setting")


# Perfi Setup
# ---------------------------------------------
@app.command("setup")
def setup_perfi():
    # Entity
    console.print(
        "[i]perfi[/i] uses [b]entities[/b] to group [b]addresses[/b] together. Think of an [b]entity[/b] like a user."
    )
    entity_name = typer.prompt("Please enter a name for your first entity")
    entity = entity_store.create(name=entity_name)
    console.print(f"Created entity [b]{entity}[/b]")
    console.print(
        "Now you should probably add at least one [b]address[/b] for your [b]entity[/b]."
    )
    choice = ""
    num_addresses_added = 0
    while choice.lower() != "n":
        choice = typer.prompt(
            f"Would you like to add an{'other' if num_addresses_added > 0 else ''} address for `{entity.name}`? [Y]es or [N]o"
        )
        if choice.lower() in ["y", "yes"]:
            address = typer.prompt(
                f"Enter an ethereum-compatible wallet address (e.g. 0x12345....):"
            )
            label = typer.prompt(f"Enter a label for this address (e.g. 'My DeFi'):")
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
        "If you want to create more Addresses later, run `poetry run bin/cli.py entity add_address`"
    )

    # Add Settings
    print(
        "\nperfi interacts with some third-party systems to gather data. You don't need to enter any API keys but if you have any of the following you can enter them now:"
    )
    choice = typer.prompt(
        f"Would you like to add a CoinGecko paid API key? [Y]es or [N]o"
    )
    if choice.lower() == "y" or choice.lower() == "yes":
        key = typer.prompt(f"Enter your CoinGecko API Key:")
        save_setting("COINGECKO_KEY", key)
    print("OK. You're done configuring perfi!")


def main():
    app()


if __name__ == "__main__":
    main()
