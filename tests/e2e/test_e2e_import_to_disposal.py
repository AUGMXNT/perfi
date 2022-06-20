import io

import jsonpickle
import pytest
from pprint import pprint

import arrow
from pytest import approx

from perfi.events import EventStore
from tests.e2e.test_e2e_costbasis import get_costbasis_lots
from perfi.ingest.exchange import (
    CoinbaseProImporter,
    BROKEN_CoinbaseProAccountStatementImporter,
    CoinbaseImporter,
)
from tests.integration.test_imports_from_exchanges import table_to_csv
from tests.helpers import *
from perfi.transaction.chain_to_ledger import update_entity_transactions
from perfi.transaction.ledger_to_logical import TransactionLogicalGrouper

from perfi.models import CostbasisIncome, CostbasisLot, CostbasisDisposal, TxLogical
from perfi.costbasis import regenerate_costbasis_lots

from perfi.price import CoinPrice

chain = "avalanche"
address = "__TEST_ADDRESS__"
entity_name = "__TEST_ENTITY__"
make: TxFactory = TxFactory()


price_feed = MockPriceFeed()


@pytest.fixture(scope="function", autouse=True)
def common_setup(monkeysession, test_db, setup_asset_and_price_ids):
    global make
    setup_entity(test_db, entity_name, [(chain, address)])
    asset_map = setup_asset_and_price_ids
    make = TxFactory(db=test_db, address=address, chain=chain, asset_map=asset_map)
    monkeysession.setattr("perfi.transaction.chain_to_ledger.db", test_db)
    monkeysession.setattr("perfi.transaction.ledger_to_logical.db", test_db)
    monkeysession.setattr("perfi.costbasis.db", test_db)
    monkeysession.setattr("perfi.models.db", test_db)
    monkeysession.setattr("perfi.asset.db", test_db)
    monkeysession.setattr("perfi.price.db", test_db)
    monkeysession.setattr("perfi.ingest.chain.db", test_db)
    monkeysession.setattr("perfi.costbasis.price_feed", price_feed)
    monkeysession.setattr("perfi.transaction.chain_to_ledger.price_feed", price_feed)
    monkeysession.setattr("perfi.ingest.exchange.price_feed", price_feed)
    yield
    monkeysession.undo()


def date_to_timestamp(date_str):
    return arrow.get(date_str).timestamp()


def common(test_db):
    update_entity_transactions(entity_name)
    event_store = EventStore(test_db, TxLogical, TxLedger)
    tlg = TransactionLogicalGrouper(entity_name, event_store)
    tlg.update_entity_transactions()
    regenerate_costbasis_lots(entity_name, quiet=True)


def test_coinbase_buy_usdc_send_to_pro_then_trade_for_eth_then_sell_eth_on_pro_after_1_year(
    test_db,
):
    # 1. Buy 10,000 USDC on Coinbase and send it (to Coinbase Pro)
    coinbase_importer = CoinbaseImporter()
    txns = """
| Transaction ID                       | Transaction Type | Date & time          | Asset Acquired | Quantity Acquired (Bought, Received, etc) | Cost Basis (incl. fees paid) (USD) | Data Source   | Asset Disposed (Sold, Sent, etc) | Quantity Disposed | Proceeds (excl. fees paid) (USD) |
| xxxxxxxx                             | Buy              | 2021-01-01T10:00:00Z | USDC           | 10000                                     | 10000                              | Coinbase      |                                  |                   |                                  |
| yyyyyyyy                             | Withdrawal       | 2021-01-02T10:00:00Z |                |                                           |                                    | Not available | USDC                             | 6000              | 6000                             |
""".lstrip(
        "\n"
    )
    csv = table_to_csv(txns)
    csv_file = io.StringIO(csv)
    # No need to stub price because we have USD cost basis and proceeds from Coinbase export
    coinbase_importer.do_import(
        csv_file,
        entity_address_for_imports=address,
        exchange_account_id="SomeCoinbaseAccountId",
    )

    # 2a. Trade 6,000 USDC for 2.5 ETH plus 1,000 fee (makes math easy) on Coinbase Pro
    # 2b. Sell 1 ETH after one year on Coinbase Pro at price of 5,000 plus a fee of 100 for total of 4,900 USDC
    price_feed.stub_price(
        "2021-01-03T06:22:49.000Z", "usd-coin", 1.00
    )  # USDC Price will be looked up at import
    price_feed.stub_price(
        "2022-03-03T06:22:49.000Z", "usd-coin", 1.00
    )  # USDC Price will be looked up at import
    coinbase_pro_importer = CoinbaseProImporter()
    txns = """
| portfolio | trade id | product  | side | created at               | size           | size unit | price   | fee         | total           | price/fee/total unit  |
| default   | 45678    | ETH-USDC | BUY  | 2021-01-03T06:22:49.000Z | 2.0            | ETH       | 2500.00 | 1000.000000 | 6000.0000000000 | USDC                  |
| default   | 65432    | ETH-USDC | SELL | 2022-03-03T06:22:49.000Z | 1.0            | ETH       | 5000.00 | 100.0000000 | 4900.0000000000 | USDC                  |
""".lstrip(
        "\n"
    )
    csv = table_to_csv(txns)
    csv_file = io.StringIO(csv)
    coinbase_pro_importer.do_import(
        csv_file,
        entity_address_for_imports=address,
        exchange_account_id="SomeCoinbaseProAccountId",
    )

    common(test_db)

    usdc_lots = [
        l
        for l in get_costbasis_lots(test_db, entity_name, address)
        if l.asset_tx_id == "usdc"
    ]
    eth_lots = [
        l
        for l in get_costbasis_lots(test_db, entity_name, address)
        if l.asset_tx_id == "eth"
    ]
    usdc_disposals = get_disposals(test_db, "USDC")
    eth_disposals = get_disposals(test_db, "ETH")

    assert (
        len(usdc_lots) == 2
    )  # 1 for initial USDC buy on Coinbase, 1 for the receit pf USDC for selling ETH on CoinbasePro
    assert usdc_lots[0].original_amount == 10000
    assert (
        usdc_lots[0].current_amount == 3900
    )  # 10,000 - 6,000 to buy eth - 100 fee for selling eth
    assert usdc_lots[1].original_amount == 5000
    assert usdc_lots[1].current_amount == 5000

    assert eth_lots[0].current_amount == 1.0

    assert (
        len(usdc_disposals) == 3
    )  # 1 for the buy of ETH, 1 for the fee for the buy of ETH, 1 for the sell of ETH
    assert usdc_disposals[0].amount == 1000
    assert usdc_disposals[1].amount == 5000
    assert usdc_disposals[2].amount == 100
    assert (
        usdc_disposals[0].duration_held
        == arrow.get("2021-01-03T06:22:49.000Z").timestamp()
        - arrow.get("2021-01-01T10:00:00Z").timestamp()
    )

    assert len(eth_disposals) == 1


def BROKEN_test_cb_buy_sell_on_both(test_db):
    coinbase_importer = BROKEN_CoinbaseProAccountStatementImporter()
    txns = """
| Transaction ID                       | Transaction Type | Date & time          | Asset Acquired | Quantity Acquired (Bought, Received, etc) | Cost Basis (incl. fees paid) (USD) | Data Source   | Asset Disposed (Sold, Sent, etc) | Quantity Disposed | Proceeds (excl. fees paid) (USD) |
| aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Buy              | 2021-01-01T10:00:00Z | USDC           | 10000                                     | 10000                              | Coinbase      |                                  |                   |                                  |
| bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb | Withdrawal       | 2021-01-02T10:00:00Z |                |                                           |                                    | Not available | USDC                             | 6000              |                                  |
| cccccccccccccccccccccccccccccccccccc | Buy              | 2021-01-03T10:00:00Z | ETH            | 2                                         | 60.0                               | Not available |                                  |                   |                                  |
| dddddddddddddddddddddddddddddddddddd | Sell             | 2021-01-08T10:00:00Z |                |                                           |                                    | Not available | ETH                              | 1                 | 200.00                           |
""".lstrip(
        "\n"
    )
    csv = table_to_csv(txns)
    csv_file = io.StringIO(csv)
    coinbase_importer.do_import(
        csv_file,
        entity_address_for_imports=address,
        exchange_account_id="SomeCoinbaseAccountId",
        db=test_db,
    )

    price_feed.stub_price("2021-01-01T10:00:00Z", "usd-coin", 1.00)
    price_feed.stub_price("2021-01-03T10:00:00Z", "ethereum", 30.00)
    price_feed.stub_price("2021-01-08T10:00:00Z", "ethereum", 200.00)

    coinbase_pro_importer = CoinbaseProImporter()
    txns = """
| portfolio | type    | time                     | amount              | balance             | amount/balance unit | transfer id                          | trade id | order id                             |
| default   | deposit | 2021-01-02T10:00:00.001Z | 6000.0000000000000  | 6000.0000000000000  | USDC                | aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |          |                                      |
| default   | match   | 2022-02-01T01:00:00.000Z | 10.0000000000000000 | 10.0000000000000000 | ETH                 |                                      | 123456   | bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb |
| default   | match   | 2022-02-01T01:00:00.000Z | -5000.0000000000000 | 1000.0000000000000  | USDC                |                                      | 123456   | bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb |
| default   | fee     | 2022-02-01T01:00:00.000Z | -2.0000000000000000 | 998.00000000000000  | USDC                |                                      | 123456   | bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb |
""".lstrip(
        "\n"
    )

    price_feed.stub_price("2022-02-01T01:00:00.000Z", "usd-coin", 1.00)
    price_feed.stub_price("2022-02-01T01:00:00.000Z", "ethereum", 500.00)

    csv = table_to_csv(txns)
    csv_file = io.StringIO(csv)
    coinbase_pro_importer.do_import(
        csv_file,
        entity_address_for_imports=address,
        exchange_account_id="SomeCoinbaseProAccountId",
        db=test_db,
    )

    common(test_db)

    usdc_lots = [
        l for l in get_costbasis_lots(test_db, entity_name) if l.asset_tx_id == "usdc"
    ]
    eth_lots = [
        l for l in get_costbasis_lots(test_db, entity_name) if l.asset_tx_id == "eth"
    ]
    usdc_disposals = get_disposals(test_db, "USDC")
    eth_disposals = get_disposals(test_db, "ETH")

    assert len(usdc_lots) == 1
    assert usdc_lots[0].original_amount == 10000
    # PENDING -- assert usdc_lots[0].current_amount == 4998

    assert len(eth_lots) == 2  # 1 buy on CB and 1 on CBP
    assert eth_lots[0].original_amount == 2
    assert eth_lots[0].current_amount == 1

    assert eth_lots[1].original_amount == 10
    assert eth_lots[1].current_amount == 10

    assert len(eth_disposals) == 1
    assert eth_disposals[0].amount == 1
    assert eth_disposals[0].total_usd == 200

    assert len(usdc_disposals) == 1
    assert usdc_disposals[0].amount == 5000
    assert (
        usdc_disposals[0].duration_held
        == arrow.get("2022-02-01T01:00:00.000Z").timestamp()
        - arrow.get("2021-01-01T10:00:00Z").timestamp()
    )
