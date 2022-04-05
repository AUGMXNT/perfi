import jsonpickle
import pytest
from pprint import pprint
from tests.helpers import *
from chain_generate_ledgertxs import main as chain_generate_ledgertxs__main
from tx_logical_grouper import TransactionLogicalGrouper
from models import TxLogical, CostbasisLot, CostbasisDisposal, CostbasisIncome


chain = "avalanche"
address = "__TEST_ADDRESS__"
entity_name = "__TEST_ENTITY__"
make: TxFactory = TxFactory()
price_feed = MockPriceFeed()

WAVAX = "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7"


# Ignores empty logicals because we dont care to test most of the time
def get_tx_logicals(test_db, address):
    sql = """SELECT id from tx_logical WHERE address = ? and count > 0 ORDER BY timestamp ASC"""
    results = test_db.query(sql, [address])
    return [TxLogical.from_id(id=r[0], entity_name=entity_name) for r in results]


# ===================================================================
# THESE BLOCKS SHOULD EXIST IN ALL TEST FILES THAT NEED DB ACCESS


@pytest.fixture(scope="module", autouse=True)
def common_setup(monkeysession, test_db, setup_asset_and_price_ids):
    global make
    setup_entity(test_db, entity_name, [(chain, address)])
    asset_map = setup_asset_and_price_ids
    make = TxFactory(db=test_db, address=address, chain=chain, asset_map=asset_map)
    monkeysession.setattr("chain_generate_ledgertxs.db", test_db)
    monkeysession.setattr("tx_logical_grouper.db", test_db)


# IMPORTANT: Update below as appropriate for your stuff under test
@pytest.fixture(scope="function", autouse=True)
def delete_all_from_tables_before_each_test(test_db):
    tables_to_clear = ["tx_chain", "tx_ledger", "tx_logical"]
    for t in tables_to_clear:
        test_db.execute(f"DELETE FROM {t}")
    yield


# ===================================================================


class TestTxTyping:
    def test_wraps_and_unwraps(self, test_db, event_store):
        # Receive
        make.tx(ins=["1 AVAX"], timestamp=1, from_adddress="A Friend")

        # Wrap
        make.tx(
            ins=[f"1 WAVAX|{WAVAX}"], outs=["1 AVAX"], timestamp=2, to_adddress=WAVAX
        )

        # Unwrap
        make.tx(
            ins=["1 AVAX"], outs=[f"1 WAVAX|{WAVAX}"], timestamp=3, from_adddress=WAVAX
        )

        update_all_chain_tx_asset_ids(test_db)
        chain_generate_ledgertxs__main(entity_override=entity_name)
        tlg = TransactionLogicalGrouper(entity_name, event_store)
        tlg.update_entity_transactions()

        txls = get_tx_logicals(test_db, address)

        assert txls[1].timestamp == 2
        wrap = txls[1]

        assert txls[2].timestamp == 3
        unwrap = txls[2]

        assert wrap.tx_logical_type == "wrap"
        assert unwrap.tx_logical_type == "unwrap"