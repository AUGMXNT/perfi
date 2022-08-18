import datetime
import time
import uuid
from decimal import Decimal
from typing import List

import pytest
from _pytest.python_api import approx
from fastapi.encoders import jsonable_encoder
from starlette.testclient import TestClient

from perfi.api import app, TxLogicalOut
from perfi.costbasis import regenerate_costbasis_lots
from perfi.events import EventStore, EVENT_ACTION
from perfi.models import (
    AddressStore,
    Chain,
    EntityStore,
    TxLogicalStore,
    TxLedger,
    TxLogical,
    Entity,
    TX_LOGICAL_TYPE,
    SettingStore,
    Setting,
    TxLedgerStore,
    TX_LOGICAL_FLAG,
    AssetBalanceCurrentStore,
    AssetBalance,
)


def without(d, key):
    new_d = d.copy()
    new_d.pop(key)
    return new_d


@pytest.fixture(scope="function", autouse=True)
def common_setup(monkeysession, test_db, setup_asset_and_price_ids):
    event_store = EventStore(test_db, TxLogical, TxLedger)

    def test_db_returner(**kwargs):
        return test_db

    monkeysession.setattr("perfi.api.DB", test_db_returner)
    monkeysession.setattr("perfi.models.db", test_db)
    monkeysession.setattr("bin.cli.db", test_db)
    monkeysession.setattr("bin.cli.costbasis_lot_store.db", test_db)
    monkeysession.setattr("perfi.transaction.ledger_to_logical.db", test_db)
    monkeysession.setattr("perfi.costbasis.db", test_db)
    monkeysession.setattr("bin.cli.event_store", event_store)


client = TestClient(app)


def test_list_entities(test_db):
    entity_store = EntityStore(test_db)
    entity_foo = entity_store.create(name="Entity Foo")
    entity_bar = entity_store.create(name="Entity Bar")

    response = client.get(f"/entities/")
    assert response.json() == jsonable_encoder(
        [entity_bar, entity_foo]
    )  # Expected in name order
    assert response.status_code == 200


def test_list_addresses_for_entity(test_db):
    entity_store = EntityStore(test_db)
    address_store = AddressStore(test_db)
    entity_foo = entity_store.create(name="Entity Foo2")
    entity_bar = entity_store.create(name="Entity Bar2")

    address_store.create("foo", Chain.ethereum, "0x123", entity_foo.name)
    bar_1 = address_store.create("bar 1", Chain.ethereum, "0x456", entity_bar.name)
    bar_2 = address_store.create("bar 2", Chain.ethereum, "0x789", entity_bar.name)

    response = client.get(f"/entities/{entity_bar.id}/addresses")
    assert response.json() == jsonable_encoder([bar_1, bar_2])
    assert response.status_code == 200

    response = client.get(f"/entities/-1/addresses")
    assert response.status_code == 404


def test_get_entity(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Original Name", note="Original Note")

    response = client.get(f"/entities/{entity.id}")
    assert response.json() == jsonable_encoder(entity)
    assert response.status_code == 200


def test_create_entity(test_db):
    entity_store = EntityStore(test_db)
    response = client.post(f"/entities", json=dict(name="my name", note="some note"))
    assert response.status_code == 200
    results = entity_store.find(name="my name")
    assert len(results) == 1
    assert without(results[0].dict(), "id") == without(
        Entity(name="my name", note="some note").dict(), "id"
    )


def test_update_entity(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Original Name", note="Original Note")
    entity.name = "Updated Name"
    entity.note = "Updated Note"

    updated_json = jsonable_encoder(entity)
    response = client.put(f"/entities/{entity.id}", json=updated_json)
    assert response.json() == updated_json
    assert response.status_code == 200

    response = client.put(f"/entities/-1", json=updated_json)
    assert response.status_code == 404


def test_delete_entity(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Original Name", note="Original Note")

    response = client.delete(f"/entities/{entity.id}")
    assert response.status_code == 200

    response = client.get(f"/entities/{entity.id}")
    assert response.status_code == 404


def test_get_addresses(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")

    address_store = AddressStore(test_db)
    address_store.create("foo", Chain.ethereum, "0x123", entity.name)
    response = client.get("/addresses/")
    assert response.json() == [
        {
            "address": "0x123",
            "chain": "ethereum",
            "entity_id": 1,
            "id": 1,
            "label": "foo",
            "ord": 1,
            "source": "manual",
            "type": "account",
        }
    ]
    assert response.status_code == 200


def test_create_address(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")
    response = client.post(
        f"/addresses",
        json=dict(entity_id=entity.id, chain="ethereum", label="bar", address="0x4321"),
    )
    assert (
        response.json().items()
        >= dict(
            chain="ethereum",
            label="bar",
            address="0x4321",
        ).items()
    )
    assert response.json()["id"] >= 0
    assert response.status_code == 200


def test_update_address(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    address.label = "updated"
    updated_json = jsonable_encoder(address)
    response = client.put(f"/addresses/{address.id}", json=updated_json)
    assert response.json() == updated_json
    assert response.status_code == 200


def test_delete_address(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    response = client.delete(f"/addresses/{address.id}")
    assert response.json() == dict(deleted=True)
    assert response.status_code == 200


def test_list_setting(test_db):
    setting_store = SettingStore(test_db)
    setting_foo = setting_store.create(key="foo", value="bar")
    setting_baz = setting_store.create(key="baz", value="qux")
    response = client.get(f"/settings")
    assert response.status_code == 200
    assert response.json() == jsonable_encoder(
        [setting_baz, setting_foo]
    )  # Alphabetized by key


def test_create_setting(test_db):
    setting_store = SettingStore(test_db)
    setting = Setting(key="my_setting", value="123")
    response = client.post(
        f"/settings",
        json=dict(key="my_setting", value="123"),
    )
    assert response.status_code == 200
    assert response.json() == jsonable_encoder(setting)
    assert setting_store.find(key=setting.key) == [setting]


def test_update_setting(test_db):
    setting_store = SettingStore(test_db)
    setting = setting_store.create(key="foo", value="bar")
    updated_setting = Setting(key=setting.key, value="updated")
    response = client.put(
        f"/settings/{setting.key}",
        json=setting.copy(update={"value": "updated"}).dict(),
    )
    assert response.status_code == 200
    assert response.json() == jsonable_encoder(updated_setting)
    assert setting_store.find(key=setting.key) == [updated_setting]


def test_delete_setting(test_db):
    setting_store = SettingStore(test_db)
    setting_1 = setting_store.create(key="foo", value="bar")
    setting_2 = setting_store.create(key="baz", value="qux")
    response = client.delete(f"/settings/{setting_1.key}")
    assert response.status_code == 200
    assert setting_store.list() == [setting_2]


def make_tx_ledger(address: str, direction: str, tx_ledger_type: str, **kw):
    return TxLedger(
        id=f"test_tx_ledger__{uuid.uuid4()}",
        chain=kw.get("chain") or Chain.ethereum.value,
        address=address,
        hash=f"test_hash__{uuid.uuid4()}",
        from_address=kw.get("from_address") or f"from__{uuid.uuid4()}",
        to_address=kw.get("to_address") or f"from__{uuid.uuid4()}",
        asset_tx_id=kw.get("asset_tx_id") or "ethereum",
        isfee=kw.get("isfee") or 0,
        amount=kw.get("amount") or 123,
        timestamp=kw.get("timestamp") or 1,
        direction=direction,
        tx_ledger_type=tx_ledger_type,
        asset_price_id=kw.get("asset_price_id") or None,
        symbol=kw.get("symbol") or None,
        price_usd=kw.get("price_usd") or None,
    )


def make_tx_logical(
    entity_name: str, tx_ledgers: List[TxLedger], tx_logical_type: TX_LOGICAL_TYPE, **kw
):
    tx_logical = TxLogical(
        id=f"test_tx_logical__{uuid.uuid4()}",
        count=len(tx_ledgers),
        timestamp=kw.get("timestamp") or 1,
        tx_ledgers=tx_ledgers,
        tx_logical_type=tx_logical_type.value,
        address=kw.get("address") or "test_address",
        entity=entity_name,
    )
    tx_logical._group_ledgers()
    return tx_logical


def test_list_tx_logicals(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    tx_logical_store = TxLogicalStore(test_db)
    tx_logical1 = make_tx_logical(
        entity_name=entity.name,
        address=address.address,
        tx_ledgers=[
            make_tx_ledger(address.address, "OUT", "send"),
        ],
        tx_logical_type=TX_LOGICAL_TYPE.send,
    )
    tx_logical1 = tx_logical_store._create_for_tests(tx_logical1)

    response = client.get(f"/tx_logicals/{entity.name}")
    assert response.json() == jsonable_encoder([TxLogicalOut(**tx_logical1.dict())])
    assert response.status_code == 200


def test_update_tx_logical_type(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    tx_logical_store = TxLogicalStore(test_db)
    tx_logical = make_tx_logical(
        entity_name=entity.name,
        address=address.address,
        tx_ledgers=[
            make_tx_ledger(address.address, "OUT", "send"),
        ],
        tx_logical_type=TX_LOGICAL_TYPE.send,
    )
    tx_logical = TxLogical.from_id(tx_logical_store._create_for_tests(tx_logical).id)
    print(tx_logical.id)

    updated_type = TX_LOGICAL_TYPE.receive.value
    response = client.put(
        f"/tx_logicals/{tx_logical.id}/tx_logical_type/{updated_type}"
    )
    assert response.json() == jsonable_encoder(
        TxLogicalOut(
            **tx_logical.copy(
                deep=True, update={"tx_logical_type": updated_type}
            ).dict()
        )
    )
    assert response.status_code == 200
    assert tx_logical_store.find(id=tx_logical.id)[0].tx_logical_type == updated_type
    assert TxLogical.from_id(tx_logical.id).outs == tx_logical.outs


def test_update_tx_ledger_type(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    tx_logical_store = TxLogicalStore(test_db)
    tx_logical = make_tx_logical(
        entity_name=entity.name,
        address=address.address,
        tx_ledgers=[
            make_tx_ledger(address.address, "OUT", "send"),
        ],
        tx_logical_type=TX_LOGICAL_TYPE.send,
    )
    tx_logical = tx_logical_store._create_for_tests(tx_logical)

    tx_ledger = tx_logical.outs[0]
    updated_type = TX_LOGICAL_TYPE.receive.value
    response = client.put(f"/tx_ledgers/{tx_ledger.id}/tx_ledger_type/{updated_type}")
    assert response.status_code == 200
    tx_ledger_store = TxLedgerStore(test_db)
    assert tx_ledger_store.find(id=tx_ledger.id)[0].tx_ledger_type == updated_type


def test_update_tx_ledger_price(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    tx_logical_store = TxLogicalStore(test_db)
    tx_logical = make_tx_logical(
        entity_name=entity.name,
        address=address.address,
        tx_ledgers=[
            make_tx_ledger(address.address, "OUT", "send"),
        ],
        tx_logical_type=TX_LOGICAL_TYPE.send,
    )
    tx_logical = tx_logical_store._create_for_tests(tx_logical)

    tx_ledger = tx_logical.outs[0]
    updated_price = Decimal(99.87)
    response = client.put(f"/tx_ledgers/{tx_ledger.id}/tx_ledger_price/{updated_price}")
    assert response.status_code == 200
    tx_ledger_store = TxLedgerStore(test_db)
    assert tx_ledger_store.find(id=tx_ledger.id)[0].price_usd == approx(Decimal(99.87))


def test_add_and_remove_flag_to_logical(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    tx_logical_store = TxLogicalStore(test_db)
    tx_logical = make_tx_logical(
        entity_name=entity.name,
        address=address.address,
        tx_ledgers=[
            make_tx_ledger(address.address, "OUT", "send"),
        ],
        tx_logical_type=TX_LOGICAL_TYPE.send,
    )
    tx_logical = tx_logical_store._create_for_tests(tx_logical)
    flag = TX_LOGICAL_FLAG.hidden_from_8949

    response = client.post(f"/tx_logicals/{tx_logical.id}/flag/{flag.value}")
    assert response.status_code == 200

    response = client.delete(f"/tx_logicals/{tx_logical.id}/flag/{flag.value}")
    assert response.status_code == 200
    assert flag.value not in [f.name for f in TxLogical.from_id(tx_logical.id).flags]


def test_reparent_tx_ledger(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    tx_logical_store = TxLogicalStore(test_db)
    tx_logical = make_tx_logical(
        entity_name=entity.name,
        address=address.address,
        tx_ledgers=[
            make_tx_ledger(address.address, "OUT", "send"),
        ],
        tx_logical_type=TX_LOGICAL_TYPE.send,
    )
    tx_logical = tx_logical_store._create_for_tests(tx_logical)

    tx_logical_2 = make_tx_logical(
        entity_name=entity.name,
        address=address.address,
        tx_ledgers=[
            make_tx_ledger(address.address, "IN", "receive"),
        ],
        tx_logical_type=TX_LOGICAL_TYPE.receive,
    )
    tx_logical_2 = tx_logical_store._create_for_tests(tx_logical_2)

    tx_ledger = TxLogical.from_id(tx_logical.id).tx_ledgers[0]
    response = client.put(f"/tx_ledgers/{tx_ledger.id}/tx_logical_id/{tx_logical_2.id}")
    assert response.status_code == 200

    tx_ledger_store = TxLedgerStore(test_db)
    updated_ledger = tx_ledger_store.find_by_primary_key(tx_ledger.id)[0]
    assert updated_ledger.tx_logical_id == tx_logical_2.id


class TestCostbasisLocking:
    def test_lock_costbasis_lot_then_try_to_edit_tx_ledger_price_should_give_error(
        self, test_db
    ):
        entity_store = EntityStore(test_db)
        entity = entity_store.create(name="Foo")

        address_store = AddressStore(test_db)
        address = address_store.create(
            "foo", Chain.ethereum, "0x123", entity_id=entity.id
        )

        tx_logical_store = TxLogicalStore(test_db)
        timestamp_now = int(time.time())
        tx_logical = make_tx_logical(
            entity_name=entity.name,
            address=address.address,
            tx_ledgers=[
                make_tx_ledger(
                    address.address,
                    "OUT",
                    "swap",
                    timestamp=timestamp_now,
                    symbol="AVAX",
                    amount=10,
                    price_usd=Decimal(100),
                ),
                make_tx_ledger(
                    address.address,
                    "IN",
                    "swap",
                    timestamp=timestamp_now,
                    symbol="ETH",
                    amount=1,
                    price_usd=Decimal(1000),
                ),
            ],
            tx_logical_type=TX_LOGICAL_TYPE.swap,
            timestamp=timestamp_now,
        )
        tx_logical = tx_logical_store._create_for_tests(tx_logical)

        regenerate_costbasis_lots(entity.name, args=None, quiet=True)

        # Lock the costbasis lots
        year = datetime.datetime.fromtimestamp(timestamp_now).year
        client.post(f"/lock_costbasis_lots/{entity.name}/{year}")

        # Now try to edit the price of the tx_ledger that associated with the locked costbasis_lot
        tx_ledger = tx_logical.ins[0]
        updated_price = Decimal(99.87)
        response = client.put(
            f"/tx_ledgers/{tx_ledger.id}/tx_ledger_price/{updated_price}"
        )

        # We should see an error in the API response
        assert response.status_code == 200
        assert response.json()["error"]

        # Let's also make sure the price didn't get updated on the ledger
        tx_ledger_store = TxLedgerStore(test_db)
        assert tx_ledger_store.find(id=tx_ledger.id)[0].price_usd == Decimal(1000)

    def test_lock_costbasis_creates_and_applies_a_COSTBASIS_LOCKED_event(self, test_db):
        entity_store = EntityStore(test_db)
        entity = entity_store.create(name="Foo")

        address_store = AddressStore(test_db)
        address = address_store.create(
            "foo", Chain.ethereum, "0x123", entity_id=entity.id
        )

        event_store = EventStore(test_db, TxLogical, TxLedger)

        tx_logical_store = TxLogicalStore(test_db)
        timestamp_now = int(time.time())
        tx_logical = make_tx_logical(
            entity_name=entity.name,
            address=address.address,
            tx_ledgers=[
                make_tx_ledger(
                    address.address,
                    "OUT",
                    "swap",
                    timestamp=timestamp_now,
                    symbol="AVAX",
                    amount=10,
                    price_usd=Decimal(100),
                ),
                make_tx_ledger(
                    address.address,
                    "IN",
                    "swap",
                    timestamp=timestamp_now,
                    symbol="ETH",
                    amount=1,
                    price_usd=Decimal(1000),
                ),
            ],
            tx_logical_type=TX_LOGICAL_TYPE.swap,
            timestamp=timestamp_now,
        )
        tx_logical = tx_logical_store._create_for_tests(tx_logical)

        regenerate_costbasis_lots(entity.name, args=None, quiet=True)

        # Lock the costbasis lots
        year = datetime.datetime.fromtimestamp(timestamp_now).year
        client.post(f"/lock_costbasis_lots/{entity.name}/{year}")

        # We should have a COSTBASIS_LOTS_LOCKED event for this entity/year
        events = event_store.find_events(EVENT_ACTION.costbasis_lots_locked)
        assert len(events) == 1
        assert events[0].data["year"] == year
        assert events[0].data["entity_name"] == entity.name


def test_get_balances(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name="Foo")

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    asset_balance_store = AssetBalanceCurrentStore(test_db)
    ab1 = AssetBalance(
        source="debank",
        address=address.address,
        chain=Chain.ethereum.value,
        symbol="ETH",
        exposure_symbol="ETH",
        protocol="wallet",
        label="foo",
        price=Decimal(12.34),
        amount=Decimal(1),
        usd_value=Decimal(12.34),
        updated=1,
        extra="{}",
    )
    ab2 = AssetBalance(
        source="debank",
        address=address.address,
        chain=Chain.ethereum.value,
        symbol="FTM",
        exposure_symbol="FTM",
        protocol="wallet",
        label="bar",
        price=Decimal(43.21),
        amount=Decimal(1),
        usd_value=Decimal(43.21),
        updated=2,
        extra="{}",
    )
    asset_balance_store.save(ab1)
    asset_balance_store.save(ab2)

    response = client.get(f"/entities/{entity.id}/balances/")
    assert response.status_code == 200
    assert response.json() == jsonable_encoder([ab1, ab2])
