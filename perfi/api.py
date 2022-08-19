# Run this server like this: uvicorn api:app --reload
import contextlib
import mimetypes
import os
import shutil
import threading
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

from perfi.balance.updating import update_entity_balances
from perfi.constants.paths import DATA_DIR, IS_PYINSTALLER
from perfi import costbasis
from perfi.constants.paths import DATA_DIR
from perfi.farming.farm_helper import get_claimable

from os import listdir
from os.path import isfile, join
from pathlib import Path
from tempfile import NamedTemporaryFile
import pytz
import json

from devtools import debug

from perfi.transaction.chain_to_ledger import (
    update_entity_transactions as do_chain_to_ledger,
)


from perfi.db import DB
from perfi.models import (
    TxLogical,
    TxLedger,
    AddressStore,
    Address,
    TxLogicalStore,
    AssetBalanceCurrentStore,
    AssetBalance,
    AssetBalanceHistoryStore,
)
from perfi.models import TxLogical, TxLedger, AddressStore, Address, TxLogicalStore
from starlette.middleware.sessions import SessionMiddleware

from typing import List, Dict
from typing import Optional

import pytz
import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    Request,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from bin.cli import (
    ledger_update_logical_type,
    ledger_update_ledger_type,
    ledger_update_price,
    ledger_flag_logical,
    ledger_remove_flag_logical,
    ledger_move_tx_ledger,
    CommandNotPermittedException,
    entity_lock_costbasis_lots,
)
from bin.generate_8949 import generate_file as generate_8949_file
from bin.import_from_exchange import do_import
from bin.map_assets import generate_constants
from bin.update_coingecko_pricelist import main as update_coingecko_pricelist_main
from perfi.asset import update_assets_from_txchain
from perfi.constants.paths import DATA_DIR, SOURCE_ROOT
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
    SettingStore,
    Setting,
    TX_LOGICAL_TYPE,
    TxLedgerStore,
    TX_LOGICAL_FLAG,
)
from perfi.transaction.chain_to_ledger import (
    update_entity_transactions as do_chain_to_ledger,
)
from perfi.transaction.ledger_to_logical import TransactionLogicalGrouper
from perfi.balance.exposure import calculate as calculate_exposure
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

# On Windows, js files can get mapped to text/plain based on Win registry keys.
# Let's try overriding manaully
mimetypes.init()
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")


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
        self.asset_balance_current: AssetBalanceCurrentStore = AssetBalanceCurrentStore(
            db
        )
        self.asset_balance_history: AssetBalanceHistoryStore = AssetBalanceHistoryStore(
            db
        )
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
    def __init__(self, store_name: str, path_param: str = "id"):
        self.store_name = store_name
        self.path_param = path_param

    def __call__(self, request: Request, stores: Stores = Depends(stores)):
        key_val = request.path_params[self.path_param]
        record = getattr(stores, self.store_name).find_by_primary_key(key_val)
        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"No record found for {self.path_param} {key_val}",
            )
        return record[0]


origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1",
    "http://127.0.0.1:5002",
]
if os.environ.get("API_PORT"):
    api_port = os.environ["API_PORT"]
    origins.append(f"http://127.0.0.1:{api_port}")

if os.environ.get("FRONTEND_PORT"):
    frontend_port = os.environ["FRONTEND_PORT"]
    origins.append(f"http://127.0.0.1:{frontend_port}")

# We will serve what vite usually serves if we're in the packaged app
if IS_PYINSTALLER:
    frontend_app = FastAPI()
    frontend_app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    FRONTEND_FILES_PATH = f"{SOURCE_ROOT}/frontend/dist"
    frontend_app.mount(
        "/",
        StaticFiles(directory=FRONTEND_FILES_PATH, html=True),
        name="frontend_files_static",
    )


app = FastAPI()

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

GENERATED_FILES_PATH = f"{DATA_DIR}/generated_files"
app.mount(
    "/static",
    StaticFiles(directory=GENERATED_FILES_PATH),
    name="generated_files_static",
)


@app.get("/")
def read_root():
    return {"Hello": "World"}


# List  Entities
@app.get("/entities")
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
@app.post("/entities")
def create_entity(entity: Entity, stores: Stores = Depends(stores)):
    return stores.entity.create(**entity.dict())


@app.put("/entities/{id}", dependencies=[Depends(EnsureRecord("entity"))])
def update_entity(entity: Entity, stores: Stores = Depends(stores)):
    return stores.entity.save(entity)


# Delete Entity
@app.delete("/entities/{id}", dependencies=[Depends(EnsureRecord("entity"))])
def delete_entity(id: int, store: EntityStore = Depends(entity_store)):
    return store.delete(id)


# Entity Balances and Exposure ------------------------
@app.get("/entities/{id}/balances")
def get_balances(
    id: int,
    stores: Stores = Depends(stores),
    entity: Entity = Depends(EnsureRecord("entity")),
):
    return stores.asset_balance_current.all_for_entity_id(entity.id)


@app.post("/entities/{id}/balances/refresh")
def refresh_balances(
    id: int,
    stores: Stores = Depends(stores),
    entity: Entity = Depends(EnsureRecord("entity")),
):
    update_entity_balances(entity.name)
    return stores.asset_balance_current.all_for_entity_id(entity.id)


@app.get("/entities/{id}/exposure")
def get_exposure(
    id: int,
    stores: Stores = Depends(stores),
    entity: Entity = Depends(EnsureRecord("entity")),
):
    results = calculate_exposure(entity.name)
    results["assets"] = [a._asdict() for a in results["assets"]]
    results["loans"] = [l._asdict() for l in results["loans"]]
    return results


# ADDRESSES =================================================================================

# List Addresses
@app.get("/addresses")
def list_addresses(store: AddressStore = Depends(address_store)):
    return store.list()


# Create Address
@app.post("/addresses")
def create_address(address: Address, store: AddressStore = Depends(address_store)):
    return store.create(**address.dict())


@app.get("/addresses/{id}")
def get_address(
    address: Address = Depends(EnsureRecord("address")),
    store: AddressStore = Depends(address_store),
):
    return address


# Edit Address
@app.put("/addresses/{id}", dependencies=[Depends(EnsureRecord("address"))])
def update_address(address: Address, store: AddressStore = Depends(address_store)):
    return store.save(address)


# Delete Address
@app.delete("/addresses/{id}", dependencies=[Depends(EnsureRecord("address"))])
def delete_address(id: int, store: AddressStore = Depends(address_store)):
    return store.delete(id)


@app.get("/addresses/{id}/manual_balances")
def get_address_manual_balances(
    stores: Stores = Depends(stores),
    address: Address = Depends(EnsureRecord("address")),
):
    return stores.asset_balance_current.find(source="manual")


@app.post("/addresses/{id}/manual_balances")
def create_address_manual_balance(
    asset_balance: AssetBalance,
    stores: Stores = Depends(stores),
    address: Address = Depends(EnsureRecord("address")),
):
    new_record = asset_balance.copy(
        update={
            "updated": int(time.time()),
            "source": "manual",
            "chain": address.chain.value,
            "address": address.address,
            "protocol": "wallet",
        }
    )

    # Stuck this new record in both the current and history stores
    stores.asset_balance_current.update_or_create(new_record)
    return stores.asset_balance_history.update_or_create(new_record)


@app.put("/addresses/{id}/manual_balances/{balance_id}")
def update_address_manual_balance(
    id: int,
    balance_id: int,
    asset_balance: AssetBalance,
    stores: Stores = Depends(stores),
    address: Address = Depends(EnsureRecord("address")),
):
    # Update this record in the current store
    updated_record = asset_balance.copy(
        update={
            "updated": int(time.time()),
        }
    )
    stores.asset_balance_current.save(updated_record)

    # Stick a copy of it in the history store
    new_record = updated_record.copy(exclude={"id"})
    stores.asset_balance_history.update_or_create(new_record)


@app.delete("/addresses/{id}/manual_balances/{balance_id}")
def delete_address_manual_balance(
    id: int,
    balance_id: int,
    stores: Stores = Depends(stores),
    asset_balance: AssetBalance = Depends(
        EnsureRecord("asset_balance_current", "balance_id")
    ),
    address: Address = Depends(EnsureRecord("address")),
):
    # Remove this record in the current store
    stores.asset_balance_current.delete(str(balance_id))

    # Write an entry to balance_history with an amount of 0 at this timestamp
    new_record = asset_balance.copy(
        exclude={"id"}, update={"updated": int(time.time()), "amount": 0}
    )
    stores.asset_balance_history.update_or_create(new_record)


# FARMING =================================================================================
@app.get("/entities/{id}/farm_helper")
def get_farm_helper(entity: Entity = Depends(EnsureRecord("entity"))):
    return get_claimable(entity.name, False)


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
    dependencies=[Depends(EnsureRecord("setting", path_param="key"))],
)
def update_setting(setting: Setting, stores: Stores = Depends(stores)):
    return stores.setting.save(setting)


# Delete Setting
@app.delete(
    "/settings/{key}",
    dependencies=[Depends(EnsureRecord("setting", path_param="key"))],
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


@app.get("/entities/{id}/tx_logicals/", response_model=List[TxLogicalOut])
def list_tx_logicals(
    page: Optional[int] = 0,
    limit: Optional[int] = 100,
    stores: Stores = Depends(stores),
    entity: Entity = Depends(EnsureRecord("entity")),
):
    return stores.tx_logical.paginated_list(
        entity.name, items_per_page=limit, page_num=page
    )


@app.get("/tx_logicals/{entity_name}", response_model=List[TxLogicalOut])
def list_tx_logicals(
    entity_name: str,
    page: Optional[int] = 0,
    limit: Optional[int] = 100,
    store: TxLogicalStore = Depends(tx_logical_store),
):
    return store.paginated_list(entity_name, items_per_page=limit, page_num=page)


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


@app.get("/tx_logical_types")
def get_tx_logical_types():
    return [t.value for t in TX_LOGICAL_TYPE]


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
    try:
        ledger_update_price(
            tx_logical.entity, tx_ledger.id, updated_price, auto_refresh_state=False
        )
    except CommandNotPermittedException as err:
        return {"error": err.message}
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


def save_upload_file_tmp(upload_file: UploadFile) -> Path:
    try:
        suffix = Path(upload_file.filename).suffix
        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(upload_file.file, tmp)
            tmp_path = Path(tmp.name)
    finally:
        upload_file.file.close()
    return tmp_path


@app.post("/entities/{id}/import_from_exchange/{exchange_type}/{exchange_account_id}")
def import_chain_transactions(
    exchange_type: str,
    exchange_account_id: str,
    file: UploadFile,
    entity: Entity = Depends(EnsureRecord("entity")),
    stores: Stores = Depends(stores),
):
    tmp_path = save_upload_file_tmp(file)
    try:
        do_import(entity.id, exchange_type, exchange_account_id, tmp_path)
        update_assets_from_txchain()
        generate_constants()
        do_chain_to_ledger(entity.name)
        tlg = TransactionLogicalGrouper(entity.name, stores.event_store)
        tlg.update_entity_transactions()
    finally:
        tmp_path.unlink()

    return {"ok": True}


def remove_file(path: str) -> None:
    os.unlink(path)


@app.get("/entities/{id}/calculateTaxInfo")
def list_generated_tax_reports(
    entity: Entity = Depends(EnsureRecord("entity")),
):
    try:
        path = f"{GENERATED_FILES_PATH}/{entity.id}"
        files = [f for f in listdir(path) if isfile(join(path, f))]
    except:
        files = []
    return files


@app.post("/entities/{id}/calculateTaxInfo/{year}")
def generate_tax_report(
    year: str,
    entity: Entity = Depends(EnsureRecord("entity")),
    stores: Stores = Depends(stores),
):
    update_coingecko_pricelist_main()
    scrape_entity_transactions(entity.name)

    update_assets_from_txchain()
    generate_constants()

    do_chain_to_ledger(entity.name)
    tlg = TransactionLogicalGrouper(entity.name, stores.event_store)
    tlg.update_entity_transactions()
    regenerate_costbasis_lots(entity.name, args=None, quiet=True)

    filename = f"8949_{entity.name}_{year}.xlsx"
    dir = f"{GENERATED_FILES_PATH}/{entity.id}"
    try:
        os.mkdir(dir)
    except:
        pass
    output = f"{dir}/{filename}"
    generate_8949_file(entity.name, int(year), output)
    return {"path": f"/static/{entity.id}/{filename}"}


# Costbasis Lots
# ============================================================
@app.post("/lock_costbasis_lots/{entity}/{year}")
def lock_costbasis_lots(entity: str, year: int):
    entity_lock_costbasis_lots(entity, year)
    return {"ok": year}


# Server class via https://stackoverflow.com/questions/61577643/python-how-to-use-fastapi-and-uvicorn-run-without-blocking-the-thread
class Server(uvicorn.Server):
    def install_signal_handlers(self):
        pass

    @contextlib.contextmanager
    def run_in_thread(self):
        thread = threading.Thread(target=self.run)
        thread.start()
        try:
            while not self.started:
                time.sleep(1e-3)
            yield
        finally:
            self.should_exit = True
            thread.join()


if __name__ == "__main__":
    # Use this for debugging purposes only
    import uvicorn

    if IS_PYINSTALLER:
        reload = False
    else:
        reload = True

    uvicorn.run("api:app", host="0.0.0.0", port=5001, log_level="debug", reload=reload)
