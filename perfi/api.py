# Run this server like this: uvicorn api:app --reload
import builtins
import time
import pytz
import json

from perfi.db import DB
from perfi.models import TxLogical, TxLedger, AddressStore, Address, TxLogicalStore
from starlette.middleware.sessions import SessionMiddleware
from typing import List, Dict
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    responses,
    Response,
    status,
    Body,
    Request,
    UploadFile,
    HTTPException,
)
from siwe import siwe
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from perfi.transaction.ledger_to_logical import TransactionLogicalGrouper

from bin.update_coingecko_pricelist import main as update_coingecko_pricelist_main

from bin.cli import (
    ledger_update_logical_type,
    ledger_update_ledger_type,
    ledger_update_price,
    ledger_flag_logical,
    ledger_remove_flag_logical,
    ledger_move_tx_ledger,
)
from bin.import_from_exchange import do_import
from bin.map_assets import generate_constants
from perfi.asset import update_assets_from_txchain
from perfi.costbasis import regenerate_costbasis_lots
from perfi.db import DB
from perfi.events import EventStore
from perfi.ingest.chain import scrape_entity_transactions
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
    TxLedgerStore,
    TX_LOGICAL_FLAG,
)
from typing import List, Dict, Type

"""
-------------------------
TODOs
[] CRUD Addresses
[] List TxLogicals
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


def tx_ledger_store(db=Depends(db)):
    return TxLedgerStore(db)


def event_store(db=Depends(db)):
    return EventStore(db, TxLogical, TxLedger)


class Stores:
    def __init__(self, db: DB):
        self.entity: EntityStore = EntityStore(db)
        self.address: AddressStore = AddressStore(db)
        self.setting: SettingStore = SettingStore(db)
        self.tx_logical: TxLogicalStore = TxLogicalStore(db)
        self.tx_ledger: TxLedgerStore = TxLedgerStore(db)
        self.event_store: EventStore = event_store(db)


def stores():
    return Stores(db())


class TxLogicalOut(BaseModel):
    id: str
    count: int = -1
    description: Optional[str] = ""
    note: Optional[str] = ""
    timestamp: int = -1
    address: str = ""
    tx_logical_type: Optional[str] = ""  # replace with enum?
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

origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:3001",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key="change_me",  # pragma: allowlist secret
)


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
@app.get("/tx_logicals/{entity_name}", response_model=List[TxLogicalOut])
def list_tx_logicals(
    entity_name: str,
    page: Optional[int] = 0,
    limit: Optional[int] = 100,
    store: TxLogicalStore = Depends(tx_logical_store),
):
    return store.paginated_list(entity_name, items_per_page=limit, page_num=page)


# Update Logical Type
# Update Ledger Type
# Update Ledger Price
# Create Flag for Logical
# Delete Flag for Logical
# Move Ledger to new Logical
@app.put(
    "/tx_logicals/{id}/tx_logical_type/{updated_type_name}", response_model=TxLogicalOut
)
def update_tx_logical_type(
    id: str,
    updated_type_name: str,
    tx_logical: TxLogical = Depends(EnsureRecord("tx_logical")),
):
    # TODO: For some reason, refreshing state after this update causes
    # TxLogical.from_id() to load with no TxLedgers. This is probably because
    #  the API tests don't set up a TxLedger the same way that our real imports do
    #  and this causes the problem with costbasis regeneration.
    #  So, we should check this later with a full e2e test to see if we can reproduce with a manual rebuild of state later...
    tx_logical.load_entity_name()
    ledger_update_logical_type(
        tx_logical.entity, tx_logical.id, updated_type_name, auto_refresh_state=False
    )
    return TxLogical.from_id(id)


@app.post("/tx_logicals/{id}/flag/{flag_name}")
def add_flag_to_logical(
    flag_name: str, tx_logical: TxLogical = Depends(EnsureRecord("tx_logical"))
):
    tx_logical.load_entity_name()
    ledger_flag_logical(
        tx_logical.entity,
        tx_logical.id,
        TX_LOGICAL_FLAG[flag_name],
        auto_refresh_state=False,
    )
    return TxLogical.from_id(tx_logical.id)


@app.delete("/tx_logicals/{id}/flag/{flag_name}")
def remove_flag_from_logical(
    flag_name: str, tx_logical: TxLogical = Depends(EnsureRecord("tx_logical"))
):
    tx_logical.load_entity_name()
    ledger_remove_flag_logical(
        tx_logical.entity,
        tx_logical.id,
        TX_LOGICAL_FLAG[flag_name],
        auto_refresh_state=False,
    )
    return TxLogical.from_id(tx_logical.id)


# TX LEDGERS =================================================================================


@app.put("/tx_ledgers/{id}/tx_ledger_type/{updated_type_name}")
def update_tx_ledger_type(
    updated_type_name: str,
    tx_ledger: TxLedger = Depends(EnsureRecord("tx_ledger")),
    stores: Stores = Depends(stores),
):
    tx_logical = stores.tx_logical.find_by_primary_key(tx_ledger.tx_logical_id)[0]
    ledger_update_ledger_type(
        tx_logical.entity, tx_ledger.id, updated_type_name, auto_refresh_state=False
    )
    return stores.tx_ledger.find_by_primary_key(tx_ledger.id)


@app.put("/tx_ledgers/{id}/tx_ledger_price/{updated_price}")
def update_tx_ledger_price(
    updated_price: float,
    tx_ledger: TxLedger = Depends(EnsureRecord("tx_ledger")),
    stores: Stores = Depends(stores),
):
    tx_logical = stores.tx_logical.find_by_primary_key(tx_ledger.tx_logical_id)[0]
    ledger_update_price(
        tx_logical.entity, tx_ledger.id, updated_price, auto_refresh_state=False
    )
    return stores.tx_ledger.find_by_primary_key(tx_ledger.id)


@app.put("/tx_ledgers/{id}/tx_logical_id/{updated_tx_logical_id}")
def reparent_tx_ledger_to_tx_logical(
    updated_tx_logical_id: str,
    tx_ledger: TxLedger = Depends(EnsureRecord("tx_ledger")),
    stores: Stores = Depends(stores),
):
    tx_logical = stores.tx_logical.find_by_primary_key(tx_ledger.tx_logical_id)[0]
    new_tx_logical = stores.tx_logical.find_by_primary_key(updated_tx_logical_id)[0]
    ledger_move_tx_ledger(
        tx_logical.entity, tx_ledger.id, new_tx_logical.id, auto_refresh_state=False
    )
    return stores.tx_ledger.find_by_primary_key(tx_ledger.id)


# BIN TRIGGERS ===========================================================
@app.post("/update_coingecko_pricelist")
def update_coingecko_pricelist():
    update_coingecko_pricelist_main()
    return {"ok": True}


@app.post("/entities/{id}/import_chain_transactions")
def import_chain_transactions(entity: Entity = Depends(EnsureRecord("entity"))):
    scrape_entity_transactions(entity)
    return {"ok": True}


@app.post("/entities/{id}/import_from_exchange/{exchange_type}/{exchange_account_id}")
def import_chain_transactions(
    file: UploadFile,
    exchange_type: str,
    exchange_account_id: str,
    entity: Entity = Depends(EnsureRecord("entity")),
):
    do_import(entity.id, exchange_type, exchange_account_id, file)
    return {"ok": True}


@app.post("/entities/{id}/regenerate_costbasis")
def regenerate_costbasis(
    entity: Entity = Depends(EnsureRecord("entity")), stores: Stores = Depends(stores)
):
    update_assets_from_txchain()
    generate_constants()

    tlg = TransactionLogicalGrouper(entity.name, stores.event_store)
    tlg.update_entity_transactions()
    regenerate_costbasis_lots(entity.name, args=None, quiet=True)
    return {"ok": True}


if __name__ == "__main__":
    # Use this for debugging purposes only
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8001, log_level="debug", reload=True)
