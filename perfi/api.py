# Run this server like this: uvicorn api:app --reload

from perfi.db import DB
from perfi.models import (
    TxLogical,
    TxLedger,
    AddressStore,
    EntityStore,
    Entity,
    Address,
    TxLogicalStore,
)
from typing import List, Dict

from fastapi import Depends, FastAPI, Response
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


_stores = None


def stores():
    global _stores
    if not _stores:
        _stores = Stores(db())
    return _stores


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


app = FastAPI()


@app.get("/")
def read_root():
    return {"Hello": "World"}


# List  Entities
@app.get("/entities/")
def list_entities(store: EntityStore = Depends(entity_store)):
    return store.list()


# List Addresses for Entity
@app.get("/entities/{id}/addresses")
def list_addresses_for_entity(
    id: int, response: Response, stores: Stores = Depends(stores)
):
    entity = stores.entity.find(id=id)
    if not entity:
        response.status_code = 404
        return dict(error=f"No entity found with id {id}")
    return stores.address.find(entity_id=id)


@app.put("/entities/{id}")
def update_entity(
    id: int, entity: Entity, response: Response, stores: Stores = Depends(stores)
):
    result = stores.entity.find(id=id)
    if not result:
        response.status_code = 404
        return dict(error=f"No entity found with id {id}")
    return stores.entity.save(entity)


# List Addresses
@app.get("/addresses/")
def list_addresses(store: AddressStore = Depends(address_store)):
    return store.list()


# Create Address
@app.post("/addresses")
def create_address(address: Address, store: AddressStore = Depends(address_store)):
    return store.create(**address.dict())


# Edit Address
@app.put("/addresses")
def update_address(address: Address, store: AddressStore = Depends(address_store)):
    return store.save(address)


# Delete Address
@app.delete("/addresses/{address_id}")
def delete_address(address_id: int, store: AddressStore = Depends(address_store)):
    return store.delete(address_id)


# List TxLogicals
@app.get("/tx_logicals/", response_model=List[TxLogicalOut])
def list_tx_logicals(store: TxLogicalStore = Depends(tx_logical_store)):
    return store.list()


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
