import json

from perfi.constants.paths import DB_SCHEMA_PATH
from perfi.db import DB
import pytest
import os
from pathlib import Path
from _pytest.monkeypatch import MonkeyPatch

from perfi.models import TxLogical, TxLedger
from perfi.events import EventStore


@pytest.fixture(scope="session")
def monkeysession(request):
    mpatch = MonkeyPatch()
    yield mpatch
    mpatch.undo()


@pytest.fixture(scope="function", autouse=True)
def test_db():
    test_db_file = ":memory:"
    tdb = DB(db_file=test_db_file, same_thread=False)

    dir_path = os.path.dirname(os.path.realpath(__file__))
    db_schema = Path(DB_SCHEMA_PATH).read_text()
    # HACK: schema may have a line about creating the sequence table. Ensure it doesn't exist or the schema import will fail.
    seq_line = "CREATE TABLE sqlite_sequence(name,seq);"
    db_schema = db_schema.replace(seq_line, "")
    tdb.cur.executescript(db_schema)
    yield tdb

    # keep the last test run's db around in case we want to inspect the db after tests finish
    last_test_db_path = Path(dir_path) / "last_test_core.db"
    try:
        os.remove(last_test_db_path)
        os.rename(test_db_file, last_test_db_path)
    except:
        pass


@pytest.fixture(scope="function")
def setup_asset_and_price_ids(test_db):
    sql = """REPLACE INTO asset_price
         (id, source, symbol, name, raw_data)
         VALUES
         (?, ?, ?, ?, ?)
      """

    # First load these default chain:symbol -> asset_price_id mappings
    symbol_asset_mapping = {
        "avalanche:AVAX": "avax",
        "ethereum:ETH": "eth",
        "fantom:FTM": "ftm",
        "polygon:MATIC": "matic",
        "xdai:XDAI": "xdai",
    }
    for chain_symbol, price_id in symbol_asset_mapping.items():
        chain, symbol = chain_symbol.split(":")
        params = [price_id, "manual", symbol, symbol, None]
        test_db.execute(sql, params)

    # Now load assets from coingecko into asset_price
    dir_path = os.path.dirname(os.path.realpath(__file__))
    coingecko_json_path = f"{dir_path}/coingecko_coin_list.json"

    with open(coingecko_json_path, "r") as f:
        j = json.load(f)
        for i in j:
            if i["id"]:
                symbol = i["symbol"].upper()
                params = [i["id"], "coingecko", symbol, i["name"], json.dumps(i)]
                test_db.execute(sql, params)

                for chain, address in i["platforms"].items():
                    symbol_asset_mapping[f"{chain}:{symbol}"] = address

    yield symbol_asset_mapping


@pytest.fixture
def event_store(test_db):
    yield EventStore(test_db, TxLogical, TxLedger)
