import pytest
from chain_generate_ledgertxs import main as chain_generate_ledgertxs__main
from tests.helpers import *

# TODO monkeypatch price fetches for coingecko or use real timestamps and just get real values?

chain = "ethereum"
address = "__TEST_ADDRESS__"
entity_name = "__TEST_ENTITY__"
ethereum = None


@pytest.fixture(scope="module", autouse=True)
def common_setup(monkeysession, test_db, setup_asset_and_price_ids):
    global ethereum
    setup_entity(test_db, entity_name, [(chain, address)])
    asset_map = setup_asset_and_price_ids
    ethereum = TxFactory(db=test_db, address=address, chain=chain, asset_map=asset_map)
    monkeysession.setattr("chain_generate_ledgertxs.db", test_db)


@pytest.fixture(scope="function", autouse=True)
def before_each(test_db):
    tables_to_clear = ["tx_chain", "tx_ledger"]
    for t in tables_to_clear:
        test_db.execute(f"DELETE FROM {t}")
    yield


def test_receiving_doesnt_generate_fee(monkeypatch, test_db):
    ethereum.tx(ins=["1 ETH"], timestamp=1, from_address="_FAKE_A")
    update_all_chain_tx_asset_ids()

    chain_generate_ledgertxs__main(entity_override=entity_name)

    results = test_db.query("SELECT isfee from tx_ledger where address = ?", [address])
    assert len(results) == 1
    result = results[0]
    assert result[0] == 0


def test_sending_generates_the_out_and_the_fee(monkeypatch, test_db):
    ethereum.tx(outs=["1 ETH"], timestamp=1, to_address="_FAKE_A")
    update_all_chain_tx_asset_ids()

    chain_generate_ledgertxs__main(entity_override=entity_name)

    results = test_db.query("SELECT isfee from tx_ledger where address = ?", [address])
    assert len(results) == 2
    assert set(r[0] for r in results) == {0, 1}


def test_swap_one_for_one_generates_3_ledger_txs(monkeypatch, test_db):
    ethereum.tx(
        ins=["1 DAI"],
        outs=[".1 ETH"],
        fee=0.00123,
        timestamp=1,
        to_address="__MAKER_DAO",
    )
    update_all_chain_tx_asset_ids()

    chain_generate_ledgertxs__main(entity_override=entity_name)

    results = test_db.query(
        "SELECT direction, isfee from tx_ledger where address = ?", [address]
    )
    assert len(results) == 3
    directions = [r[0] for r in results]
    assert sorted(directions) == ["IN", "OUT", "OUT"]
