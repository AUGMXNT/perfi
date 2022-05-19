import uuid
from typing import List

import pytest
from starlette.testclient import TestClient
from perfi.api import app, TxLogicalOut
from perfi.models import (
    AddressStore,
    Chain,
    EntityStore,
    TxLogicalStore,
    TxLedger,
    TxLogical,
    Entity,
    TX_LOGICAL_TYPE,
)

from fastapi.encoders import jsonable_encoder
from tests.helpers import *

client = TestClient(app)


@pytest.fixture(scope="function", autouse=True)
def common_setup(monkeysession, test_db, setup_asset_and_price_ids):
    def test_db_returner(**kwargs):
        return test_db

    monkeysession.setattr("perfi.api.DB", test_db_returner)
    monkeysession.setattr("perfi.models.db", test_db)


ENTITY_NAME = "tester"
TEST_ADDRESS = "test_address"


# @pytest.fixture(autouse=True)
# def entity(test_db):
#     entity_store = EntityStore(test_db)
#     entity_store.create(ENTITY_NAME)


def test_list_entities(test_db):
    entity_store = EntityStore(test_db)
    entity_foo = entity_store.create(name="Entity Foo")
    entity_bar = entity_store.create(name="Entity Bar")

    response = client.get(f"/entities/")
    assert response.json() == jsonable_encoder([entity_bar, entity_foo])
    assert response.status_code == 200


def test_list_addresses_for_entity(test_db):
    entity_store = EntityStore(test_db)
    address_store = AddressStore(test_db)
    entity_foo = entity_store.create(name="Entity Foo")
    entity_bar = entity_store.create(name="Entity Bar")

    address_store.create("foo", Chain.ethereum, "0x123", entity_foo.name)
    bar_1 = address_store.create("bar 1", Chain.ethereum, "0x456", entity_bar.name)
    bar_2 = address_store.create("bar 2", Chain.ethereum, "0x789", entity_bar.name)

    response = client.get(f"/entities/{entity_bar.id}/addresses")
    assert response.json() == jsonable_encoder([bar_1, bar_2])
    assert response.status_code == 200

    response = client.get(f"/entities/-1/addresses")
    assert response.status_code == 404


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


def test_get_addresses(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name=ENTITY_NAME)

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
    entity = entity_store.create(name=ENTITY_NAME)
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
    entity = entity_store.create(name=ENTITY_NAME)

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    address.label = "updated"
    updated_json = jsonable_encoder(address)
    response = client.put(f"/addresses", json=updated_json)
    assert response.json() == updated_json
    assert response.status_code == 200


def test_delete_address(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name=ENTITY_NAME)

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    response = client.delete(f"/addresses/{address.id}")
    assert response.json() == dict(deleted=True)
    assert response.status_code == 200


def make_tx_ledger(direction: str, tx_ledger_type: str, **kw):
    return TxLedger(
        id=f"test_tx_ledger__{uuid.uuid4()}",
        chain=kw.get("chain") or Chain.ethereum.value,
        address=TEST_ADDRESS,
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


def make_tx_logical(tx_ledgers: List[TxLedger], tx_logical_type: TX_LOGICAL_TYPE, **kw):
    tx_logical = TxLogical(
        id=f"test_tx_logical__{uuid.uuid4()}",
        count=len(tx_ledgers),
        timestamp=kw.get("timestamp") or 1,
        tx_ledgers=tx_ledgers,
        tx_logical_type=tx_logical_type.value,
        address=kw.get("address") or TEST_ADDRESS,
    )
    tx_logical._group_ledgers()
    return tx_logical


def test_list_tx_logicals(test_db):
    entity_store = EntityStore(test_db)
    entity = entity_store.create(name=ENTITY_NAME)

    address_store = AddressStore(test_db)
    address = address_store.create("foo", Chain.ethereum, "0x123", entity_id=entity.id)

    tx_logical_store = TxLogicalStore(test_db)
    tx_logical1 = make_tx_logical(
        address=address.address,
        tx_ledgers=[
            make_tx_ledger("OUT", "send"),
        ],
        tx_logical_type=TX_LOGICAL_TYPE.send,
    )
    tx_logical1 = tx_logical_store.create(tx_logical1)

    tx_logical2 = make_tx_logical(
        tx_ledgers=[
            make_tx_ledger("IN", "receive"),
        ],
        tx_logical_type=TX_LOGICAL_TYPE.receive,
    )
    tx_logical2 = tx_logical_store.create(tx_logical2)

    response = client.get(f"/tx_logicals/")
    assert response.json() == jsonable_encoder(
        [TxLogicalOut(**tx_logical1.dict()), TxLogicalOut(**tx_logical2.dict())]
    )
    assert response.status_code == 200
