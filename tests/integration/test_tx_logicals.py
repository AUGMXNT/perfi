import jsonpickle
import pytest
from pprint import pprint
from tests.helpers import *
from perfi.transaction.chain_to_ledger import update_entity_transactions
from perfi.transaction.ledger_to_logical import TransactionLogicalGrouper
from perfi.models import TxLogical, CostbasisLot, CostbasisDisposal, CostbasisIncome


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


@pytest.fixture(scope="function", autouse=True)
def common_setup(monkeysession, test_db, setup_asset_and_price_ids):
    global make
    setup_entity(test_db, entity_name, [(chain, address)])
    asset_map = setup_asset_and_price_ids
    make = TxFactory(db=test_db, address=address, chain=chain, asset_map=asset_map)
    monkeysession.setattr("perfi.transaction.chain_to_ledger.db", test_db)
    monkeysession.setattr("perfi.transaction.ledger_to_logical.db", test_db)
    monkeysession.setattr("perfi.models.db", test_db)


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

        map_assets()
        update_entity_transactions(entity_name)
        tlg = TransactionLogicalGrouper(entity_name, event_store)
        tlg.update_entity_transactions()

        txls = get_tx_logicals(test_db, address)

        assert txls[1].timestamp == 2
        wrap = txls[1]

        assert txls[2].timestamp == 3
        unwrap = txls[2]

        assert wrap.tx_logical_type == "wrap"
        assert unwrap.tx_logical_type == "unwrap"
