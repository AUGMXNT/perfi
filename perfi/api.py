# Run this server like this: uvicorn api:app --reload

from .db import DB
from .models import TxLogical, TxLedger, AddressStore, Address, TxLogicalStore
from typing import List, Dict

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from typing import Optional


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


def tx_logical_store(db=Depends(db)):
    return TxLogicalStore(db)


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
