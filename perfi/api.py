# Run this server like this: uvicorn api:app --reload
import builtins

import pytz

from perfi.db import DB
from perfi.models import (
    TxLogical,
    TxLedger,
    AddressStore,
    EntityStore,
    Entity,
    Address,
    TxLogicalStore,
    BaseStore,
    StoreProtocol,
    SettingStore,
    Setting,
    TX_LOGICAL_TYPE,
)
from typing import List, Dict, Type

from fastapi import Depends, FastAPI, Response, HTTPException, Request
from pydantic import BaseModel
from typing import Optional


"""
-------------------------
TODOs
[] All the commands from cli_cmd
[] Trigger a full processing all the way through costbasis-8949

-------------------------
"""


def db():
    return DB(same_thread=False)


def address_store(db=Depends(db)):
    return AddressStore(db)


def entity_store(db=Depends(db)):
    return EntityStore(db)


def tx_logical_store(db=Depends(db)):
    return TxLogicalStore(db)


class Stores:
    def __init__(self, db: DB):
        self.entity: EntityStore = EntityStore(db)
        self.address: AddressStore = AddressStore(db)
        self.setting: SettingStore = SettingStore(db)
        self.tx_logical: TxLogicalStore = TxLogicalStore(db)


def stores():
    return Stores(db())


class TxLogicalOut(BaseModel):
    id: str
    count: int = -1
    description: str = ""
    note: str = ""
    timestamp: int = -1
    address: str = ""
    tx_logical_type: str = ""  # replace with enum?
    flags: List[Dict[str, str]] = []
    ins: List[TxLedger] = []
    outs: List[TxLedger] = []
    fee: Optional[TxLedger] = None
    others: List[TxLedger] = []

    class Config:
        orm_mode = True


class EnsureRecord:
    def __init__(self, store_name: str, primary_key: str = "id"):
        self.store_name = store_name
        self.primary_key = primary_key

    def __call__(self, request: Request, stores: Stores = Depends(stores)):
        record = getattr(stores, self.store_name).find_by_primary_key(
            request.path_params[self.primary_key]
        )
        if not record:
            raise HTTPException(status_code=404, detail=f"No record found for id {id}")
        return record[0]


app = FastAPI()


@app.get("/")
def read_root():
    return {"Hello": "World"}


# List  Entities
@app.get("/entities/")
def list_entities(store: EntityStore = Depends(entity_store)):
    return store.list()


# ENTITIES =================================================================================

# Get Entity
@app.get("/entities/{id}")
def list_addresses_for_entity(entity: Entity = Depends(EnsureRecord("entity"))):
    return entity


# List Addresses for Entity
@app.get("/entities/{id}/addresses")
def list_addresses_for_entity(
    stores: Stores = Depends(stores), entity: Entity = Depends(EnsureRecord("entity"))
):
    return stores.address.find(entity_id=entity.id)


# Create entity
@app.post("/entities/")
def create_entity(entity: Entity, stores: Stores = Depends(stores)):
    return stores.entity.create(**entity.dict())


@app.put("/entities/{id}", dependencies=[Depends(EnsureRecord("entity"))])
def update_entity(entity: Entity, stores: Stores = Depends(stores)):
    return stores.entity.save(entity)


# Delete Entity
@app.delete("/entities/{id}", dependencies=[Depends(EnsureRecord("entity"))])
def delete_entity(id: int, store: EntityStore = Depends(entity_store)):
    return store.delete(id)


# ADDRESSES =================================================================================

# List Addresses
@app.get("/addresses/")
def list_addresses(store: AddressStore = Depends(address_store)):
    return store.list()


# Create Address
@app.post("/addresses")
def create_address(address: Address, store: AddressStore = Depends(address_store)):
    return store.create(**address.dict())


# Edit Address
@app.put("/addresses/{id}", dependencies=[Depends(EnsureRecord("address"))])
def update_address(address: Address, store: AddressStore = Depends(address_store)):
    return store.save(address)


# Delete Address
@app.delete("/addresses/{id}", dependencies=[Depends(EnsureRecord("address"))])
def delete_address(id: int, store: AddressStore = Depends(address_store)):
    return store.delete(id)


# SETTINGS =================================================================================

# List Settings
@app.get("/settings")
def list_settingss(stores: Stores = Depends(stores)):
    return stores.setting.list()


# Create Setting
@app.post("/settings")
def create_setting(setting: Setting, stores: Stores = Depends(stores)):
    return stores.setting.create(**setting.dict())


# Update Setting
@app.put(
    "/settings/{key}",
    dependencies=[Depends(EnsureRecord("setting", primary_key="key"))],
)
def update_setting(setting: Setting, stores: Stores = Depends(stores)):
    return stores.setting.save(setting)


# Delete Setting
@app.delete(
    "/settings/{key}",
    dependencies=[Depends(EnsureRecord("setting", primary_key="key"))],
)
def delete_setting(key: str, stores: Stores = Depends(stores)):
    return stores.setting.delete(key)


# Get list of reporting timezones
@app.get("/settings/_help/reporting_timezones")
def get_reporting_timezones_help():
    return pytz.all_timezones


# Get list of settings used by the app
@app.get("/settings/_help/keys")
def get_settings_keys_used_list():
    return ["COINGECKO_KEY", "REPORTING_TIMEZONE", "ETHERSCAN_KEY", "COVALENT_KEY"]


# TX LOGICALS =================================================================================

# List TxLogicals
@app.get("/tx_logicals/", response_model=List[TxLogicalOut])
def list_tx_logicals(store: TxLogicalStore = Depends(tx_logical_store)):
    return store.list()


@app.put(
    "/tx_logicals/{id}/tx_logical_type/{updated_type_name}", response_model=TxLogicalOut
)
def update_tx_logical_type(
    updated_type_name: str,
    tx_logical: TxLogical = Depends(EnsureRecord("tx_logical")),
    stores: Stores = Depends(stores),
):
    updated = tx_logical.copy(
        update={"tx_logical_type": TX_LOGICAL_TYPE[updated_type_name].value}
    )
    return stores.tx_logical.save(updated)


# Update Logical Type
# Update Ledger Type
# Update Ledger Price
# Create Flag for Logical
# Delete Flag for Logical
# Move Ledger to new Logical


if __name__ == "__main__":
    # Use this for debugging purposes only
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8001, log_level="debug", reload=True)
