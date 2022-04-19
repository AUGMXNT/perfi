import io

import jsonpickle
import pytest
from pprint import pprint

import arrow
from pytest import approx

from tests.e2e.test_e2e_costbasis import get_costbasis_lots
from perfi.ingest.exchange import (
    CoinbaseProImporter,
    BROKEN_CoinbaseProAccountStatementImporter,
)
from tests.integration.test_imports_from_exchanges import table_to_csv
from tests.helpers import *
from perfi.transaction.chain_to_ledger import update_entity_transactions
from perfi.transaction.ledger_to_logical import TransactionLogicalGrouper

from perfi.models import CostbasisIncome, CostbasisLot, CostbasisDisposal
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
    monkeysession.setattr("chain_generate_ledgertxs.db", test_db)
    monkeysession.setattr("tx_logical_grouper.db", test_db)
    monkeysession.setattr("costbasis.db", test_db)
    monkeysession.setattr("costbasis.price_feed", price_feed)
    monkeysession.setattr("perfi.asset.db", test_db)


def get_disposals(test_db, symbol, timestamp=None):
    sql = f"""SELECT
                id,
                entity,
                address,
                asset_price_id,
                symbol,
                amount,
                timestamp,
                duration_held,
                basis_timestamp,
                basis_tx_ledger_id,
                basis_usd,
                total_usd,
                tx_ledger_id,
                price_source
             FROM costbasis_disposal
             WHERE symbol = ?
             {"AND timestamp = ?" if timestamp else ""}
             ORDER BY timestamp ASC
    """
    if timestamp:
        params = [symbol, timestamp]
    else:
        params = [symbol]
    results = test_db.query(sql, params)

    return [CostbasisDisposal(*r) for r in results]


def get_costbasis_incomes(test_db, entity, address):
    sql = """SELECT id, entity, address, net_usd, symbol, timestamp, tx_ledger_id, price, amount, lots
             FROM costbasis_income
             WHERE entity = ?
             AND address = ?
             ORDER BY timestamp ASC
    """
    params = [entity, address]
    results = test_db.query(sql, params)
    incomes_to_return = []
    for r in results:
        income = CostbasisIncome(*r)
        income = income._replace(lots=jsonpickle.decode(income.lots))
        incomes_to_return.append(income)

    return incomes_to_return


def date_to_timestamp(date_str):
    return arrow.get(date_str).timestamp()


def common(test_db):
    update_all_chain_tx_asset_ids()
    update_entity_transactions(entity_name)
    tlg = TransactionLogicalGrouper(entity_name)
    tlg.update_entity_transactions()
    regenerate_costbasis_lots(entity_name, quiet=True)


def BROKEN_test_coinbase_buy_usdc_send_to_pro_then_trade_for_eth_then_sell_eth_on_pro_after_1_year(
    test_db,
):
    coinbase_importer = BROKEN_CoinbaseProAccountStatementImporter()
    txns = """
| Transaction ID                       | Transaction Type | Date & time          | Asset Acquired | Quantity Acquired (Bought, Received, etc) | Cost Basis (incl. fees paid) (USD) | Data Source   | Asset Disposed (Sold, Sent, etc) | Quantity Disposed | Proceeds (excl. fees paid) (USD) |
| xxxxxxxx                             | Buy              | 2021-01-01T10:00:00Z | USDC           | 10000                                     | 10000                              | Coinbase      |                                  |                   |                                  |
| yyyyyyyy                             | Withdrawal       | 2021-01-02T10:00:00Z |                |                                           |                                    | Not available | USDC                             | 6000              |                                  |
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

    coinbase_pro_importer = CoinbaseProImporter()
    txns = """
| portfolio | type    | time                     | amount              | balance             | amount/balance unit | transfer id                          | trade id | order id                             |
| default   | deposit | 2021-01-02T10:00:00.001Z | 6000.0000000000000  | 6000.0000000000000  | USDC                | aaaaaaaa                             |          |                                      |
| default   | match   | 2022-02-01T01:00:00.000Z | 10.0000000000000000 | 10.0000000000000000 | ETH                 |                                      | 123456   | bbbbbbbb                             |
| default   | match   | 2022-02-01T01:00:00.000Z | -5000.0000000000000 | 1000.0000000000000  | USDC                |                                      | 123456   | bbbbbbbb                             |
| default   | fee     | 2022-02-01T01:00:00.000Z | -2.0000000000000000 | 998.00000000000000  | USDC                |                                      | 123456   | bbbbbbbb                             |
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

    assert len(eth_lots) == 1
    assert eth_lots[0].original_amount == 10
    assert eth_lots[0].current_amount == 10

    assert len(usdc_disposals) == 1
    assert usdc_disposals[0].amount == 5000
    assert (
        usdc_disposals[0].duration_held
        == arrow.get("2022-02-01T01:00:00.000Z").timestamp()
        - arrow.get("2021-01-01T10:00:00Z").timestamp()
    )

    assert len(eth_disposals) == 0


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
