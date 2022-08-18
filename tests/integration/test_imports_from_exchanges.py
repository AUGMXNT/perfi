import csv
import io
from decimal import Decimal

import pytest
import xlsxwriter
from sttable import parse_str_table

from perfi.ingest.exchange import (
    CoinbaseImporter,
    GeminiImporter,
    CoinbaseProImporter,
    KrakenImporter,
    CoinbaseTransactionHistoryImporter,
)
from perfi.models import TxLedger
from perfi.transaction.chain_to_ledger import update_entity_transactions
from tests.helpers import *

kraken_sample_ledgers_tbl = """
| txid                | refid                 | time                | type       | subtype | aclass   | asset | amount        | fee          | balance      |
| aaaaaaaaaaaaaaaaaaa | fffffffffffffffffffff | 2016-10-29 11:30:16 | deposit    |         | currency | XXBT  | 0.7625000000  | 0.0000000000 | 0.7625000000 |
| bbbbbbbbbbbbbbbbbbb | ggggggggggggggggggggg | 2016-10-29 13:14:18 | withdrawal |         | currency | XXBT  | -0.7620000000 | 0.0005000000 | 0.0000000000 |
| ccccccccccccccccccc | hhhhhhhhhhhhhhhhhhhh  | 2016-10-29 20:35:29 | trade      |         | currency | XZEC  | 0.0011900000  | 0.0000000000 | 0.0041928800 |
| ddddddddddddddddddd | iiiiiiiiiiiiiiiiiiii  | 2018-11-18 23:29:42 | transfer   |         | currency | BSV   | 0.0000059400  | 0.0000000000 | 0.0000059400 |
| eeeeeeeeeeeeeeeeeee | jjjjjjjjjjjjjjjjjjjj  | 2021-03-28 02:54:17 | staking    |         | currency | ETH2  | 0.0418840560  | 0.0000000000 | 0.0418840560 |
""".lstrip(
    "\n"
)


coinbase_sample_raw_txs_tbl = """
| Transaction ID                       | Transaction Type | Date & time          | Asset Acquired | Quantity Acquired (Bought, Received, etc) | Cost Basis (incl. fees paid) (USD) | Data Source   | Asset Disposed (Sold, Sent, etc) | Quantity Disposed | Proceeds (excl. fees paid) (USD) |
| aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Receive          | 2020-01-01T00:00:00Z | BTC            | 0.9997288                                 | 0                                  | Not available |                                  |                   |                                  |
| baaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Withdrawal       | 2020-01-02T00:00:00Z |                |                                           |                                    |               | BTC                              | 0.5               | 0                                |
| caaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Deposit          | 2020-01-03T00:00:00Z | ETH            | 30.34                                     | 0                                  | Not available |                                  |                   |                                  |
| daaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Sell             | 2020-01-04T00:00:00Z |                |                                           |                                    |               | ETH                              | 30.341            | 838.0499999999999992456          |
| eaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Transfer         | 2020-01-05T00:00:00Z | BTC            | 0.4997288                                 | 0                                  | Not available |                                  |                   |                                  |
| faaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Fork             | 2020-01-06T00:00:00Z | BSV            | 0.49972881                                | 32.5404861133149                   | Coinbase      |                                  |                   |                                  |
| gaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Incoming         | 2020-01-07T00:00:00Z | BCH            | 0.4997288                                 | 0                                  | Not available |                                  |                   |                                  |
| haaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Converted from   | 2020-01-08T00:00:00Z |                |                                           |                                    |               | ETH                              | 5.38952815        | 1000.32337228075                 |
| iaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Converted to     | 2020-01-11T00:00:00Z | XLM            | 650.1690543                               | 207.734763516                      | Coinbase      |                                  |                   |                                  |
| jaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Airdrop          | 2020-01-09T00:00:00Z | OMG            | 2.59862241                                | 4.895544758199                     | Coinbase      |                                  |                   |                                  |
| laaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Reward           | 2020-01-10T00:00:00Z | XLM            | 32.3224488                                | 1.9980768174695998                 | Coinbase      |                                  |                   |                                  |
| maaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Buy              | 2017-03-14T05:56:39Z | ETH            | 50                                        | 1031.71                            | Coinbase      |                                  |                   |                                  |
| naaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Interest         | 2020-01-12T00:00:00Z | USDC           | 0.032737                                  | 0.032736999999999995               | Coinbase      |                                  |                   |                                  |
""".lstrip(
    "\n"
)


coinbase_pro_sample_fills_tbl = """
| portfolio | trade id | product | side | created at               | size           | size unit | price   | fee         | total           | price/fee/total unit |
| default   | 123      | SOL-ETH | BUY  | 2021-11-06T09:33:32.618Z | 0.00100000     | SOL       | 0.05507 | 2.7535e-7   | -0.00005534535  | ETH                  |
| default   | 45678    | UST-USD | SELL | 2021-12-06T06:22:49.825Z | 20413.54000000 | UST       | 1.002   | 2.045436708 | 20452.321643292 | USD                  |
""".lstrip(
    "\n"
)


gemini_sample_xlsx_tbl_sgd = """
| Date                    | Time (UTC)              | Type   | Symbol | Specification           | Liquidity Indicator | Trading Fee Rate (bps) | DAI Amount DAI       | Fee (DAI) DAI | DAI Balance DAI     | SGD Amount SGD | Fee (SGD) SGD | SGD Balance SGD | FTM Amount FTM      | Fee (FTM) FTM | FTM Balance FTM     | Trade ID    | Order ID    | Order Date | Order Time   | Client Order ID | API Session | Tx Hash                                                          | Deposit Destination | Deposit Tx Output | Withdrawal Destination                     | Withdrawal Tx Output |
| 2021-12-08 03:47:23.014 | 2021-12-08 03:47:23.014 | Buy    | DAISGD | Mobile                  | Taker               |                        | "3,595.150506 DAI "  |               | "3,595.150506 DAI " | "($4,925.50)"  | ($74.50)      | $0.00           |                     |               | 0.0 FTM             | 73739034458 | 73739033096 | 2021-12-08 | 03:47:22.369 | Mobile          |             |                                                                  |                     |                   |                                            |                      |
| 2021-12-08 04:00:30.911 | 2021-12-08 04:00:30.911 | Debit  | DAI    | Withdrawal (DAI)        |                     |                        | "(3,584.150506 DAI)" | 0.0 DAI       | 0.0 DAI             |                |               | $0.00           |                     |               | 0.0 FTM             |             |             |            |              |                 |             | aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |                     |                   | 0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |                      |
| 2022-01-12 01:19:55.026 | 2022-01-12 01:19:55.026 | Buy    | FTMSGD | Mobile                  | Taker               |                        |                      |               | 0.0 DAI             | "($4,826.99)"  | ($73.01)      | $0.00           | "1,358.911629 FTM " |               | "1,385.804645 FTM " | 81088107685 | 81088085705 | 2022-01-12 | 01:19:51.683 | Mobile          |             |                                                                  |                     |                   |                                            |                      |
| 2022-01-12 01:45:08.840 | 2022-01-12 01:45:08.840 | Credit | SGD    | Deposit (Fast Transfer) |                     |                        |                      |               | 0.0 DAI             | "$20,000"      |               | $20,000.00      |                     | 0.0 FTM       | 0.0 FTM             |             |             |            |              |                 |             |                                                                  |                     |                   |                                            |                      |
|                         |                         |        |        |                         |                     |                        |                      | 0.0 DAI       | 0.0 DAI             |                | $0.00         | $0.00           |                     | 0.0 FTM       | 0.0 FTM             |             |             |            |              |                 |             |                                                                  |                     |                   |                                            |                      |
""".lstrip(
    "\n"
)  # NOTE: The last line without date/time etc. is intentional. No idea why Gemini puts it there, but it does...


address = "__TEST_ADDRESS__"
entity_name = "__TEST_ENTITY__"


@pytest.fixture(scope="function", autouse=True)
def common_setup(monkeysession, test_db, setup_asset_and_price_ids):
    setup_entity(test_db, entity_name, [("avalanche", address)])
    monkeysession.setattr("perfi.transaction.chain_to_ledger.db", test_db)
    monkeysession.setattr("perfi.asset.db", test_db)
    monkeysession.setattr("perfi.ingest.chain.db", test_db)


def get_tx_chains(db, chain, address):
    sql = """SELECT chain, address, hash, timestamp, raw_data_lzma from tx_chain WHERE chain = ? AND address = ? ORDER BY timestamp ASC"""
    params = [chain, address]
    return db.query(sql, params)


def get_tx_ledgers(db, chain, address):
    sql = """SELECT id, chain, address, hash, from_address, to_address, from_address_name, to_address_name, asset_tx_id, isfee, amount, timestamp, direction, tx_ledger_type, asset_price_id, symbol, price_usd
           FROM tx_ledger
           WHERE chain = ? AND address = ?
           ORDER BY timestamp ASC, isfee ASC
        """
    results = list(db.query(sql, [chain, address]))
    return [TxLedger(**r) for r in results]


def get_tx_ledgers_by_hash(db, hash):
    sql = """SELECT id, chain, address, hash, from_address, to_address, from_address_name, to_address_name, asset_tx_id, isfee, amount, timestamp, direction, tx_ledger_type, asset_price_id, symbol, price_usd
           FROM tx_ledger
           WHERE hash = ?
           ORDER BY timestamp ASC
        """
    results = list(db.query(sql, [hash]))
    return [TxLedger(**r) for r in results]


def table_to_csv(table):
    parsed = parse_str_table(table)
    fields = parsed.fields
    output = io.StringIO()
    fieldnames = fields
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in parsed.rows:
        writer.writerow(row)
    return output.getvalue().rstrip("\n")


class XlsxDictWriter:
    def __init__(self, worksheet, fieldnames):
        self.worksheet = worksheet
        self.fieldnames = fieldnames
        self.nrow = 1

    def writerow(self, d):
        for k in d:
            ncol = self.fieldnames.index(k)
            self.worksheet.write(self.nrow, ncol, d[k])
        self.nrow += 1

    def writeheader(self):
        for ncol, fieldname in enumerate(self.fieldnames):
            self.worksheet.write(0, ncol, fieldname)


def table_to_xlsx(table):
    parsed = parse_str_table(table)
    fields = parsed.fields
    fieldnames = fields

    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    worksheet = workbook.add_worksheet()
    writer = XlsxDictWriter(worksheet, fieldnames)
    writer.writeheader()

    for row in parsed.rows:
        writer.writerow(row)
    workbook.close()

    # return xlsx_file_path.read_text().rstrip("\n")
    return output.getvalue()


class TestKrakenImporter:
    kraken_importer = KrakenImporter()

    def test_non_swap_case(self, test_db):
        txns = """
| txid                | refid                 | time                | type    | subtype | aclass   | asset | amount       | fee          | balance      |
| aaaaaaaaaaaaaaaaaaa | bbbbbbbbbbbbbbbbbbbbb | 2016-10-29 11:30:16 | deposit |         | currency | XXBT  | 0.7625000000 | 0.0000000000 | 0.7625000000 |
""".lstrip(
            "\n"
        )

        csv = table_to_csv(txns)
        csv_file = io.StringIO(csv)

        self.kraken_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeKrakenAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.kraken", address)

        assert len(tx_ledgers) == 1  # only 1 ledger for a non-swap case

        expected_deposit = TxLedger(
            chain="import.kraken",
            address=address,
            hash="import.kraken_bbbbbbbbbbbbbbbbbbbbb",
            from_address="Kraken:SomeKrakenAccountId",
            to_address="Kraken:SomeKrakenAccountId",
            asset_tx_id="btc",
            amount=Decimal("0.7625"),
            isfee=0,
            timestamp=int(arrow.get("2016-10-29 11:30:16").timestamp()),
            direction="IN",
            tx_ledger_type="Kraken.deposit",
            symbol="BTC",
        )
        actual_deposit = tx_ledgers[0]
        actual_deposit.id = None
        assert actual_deposit == expected_deposit

        # We _could_ assert on the other Transaction types but the logic treatment is the same, so skipping for now...

    def test_deposit_fiat(self, test_db):
        txns = """
| txid                | refid                 | time                | type    | subtype | aclass   | asset | amount | fee          | balance      |
| aaaaaaaaaaaaaaaaaaa | bbbbbbbbbbbbbbbbbbbbb | 2016-10-29 11:30:16 | deposit |         | currency | ZUSD  | 100.23 | 0.0000000000 | 100.76000000 |
""".lstrip(
            "\n"
        )

        csv = table_to_csv(txns)
        csv_file = io.StringIO(csv)

        self.kraken_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeKrakenAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.kraken", address)

        assert len(tx_ledgers) == 1  # only 1 ledger for a non-swap case

        expected_deposit = TxLedger(
            chain="import.kraken",
            address=address,
            hash="import.kraken_bbbbbbbbbbbbbbbbbbbbb",
            from_address="Kraken:SomeKrakenAccountId",
            to_address="Kraken:SomeKrakenAccountId",
            asset_tx_id="FIAT:USD",
            amount=Decimal("100.23"),
            isfee=0,
            timestamp=int(arrow.get("2016-10-29 11:30:16").timestamp()),
            direction="IN",
            price_usd=Decimal(1.0),  # currency was USD so price is 1
            tx_ledger_type="Kraken.deposit",
            symbol="USD",
        )
        actual_deposit = tx_ledgers[0]
        actual_deposit.id = None
        assert actual_deposit == expected_deposit

    def test_trade_is_swap(self, test_db):
        txns = """
| txid                | refid               | time                | type  | subtype  | aclass | asset | amount        | fee          | balance      |
| aaaaaaaaaaaaaaaaaaa | ccccccccccccccccccc | 2016-10-29 19:13:09 | trade | currency |        | XZEC  | -0.0036300000 | 0.0000000000 | 0.0000086200 |
| baaaaaaaaaaaaaaaaaa | dcccccccccccccccccc | 2016-10-29 19:13:09 | trade | currency |        | XXBT  | 0.0232320000  | 0.0000600000 | 0.0231720000 |
""".lstrip(
            "\n"
        )

        csv = table_to_csv(txns)
        csv_file = io.StringIO(csv)

        self.kraken_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeKrakenAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.kraken", address)

        assert len(tx_ledgers) == 3  # 2 ledgers for a swap plus a fee
        actual_out = [t for t in tx_ledgers if t.direction == "OUT" and t.isfee == 0][0]
        actual_in = [t for t in tx_ledgers if t.direction == "IN"][0]
        actual_fees = [t for t in tx_ledgers if t.direction == "OUT" and t.isfee == 1]

        expected_in = TxLedger(
            chain="import.kraken",
            address=address,
            hash="import.kraken_dcccccccccccccccccc_trade_zec_btc",
            from_address="Kraken:SomeKrakenAccountId",
            to_address="Kraken:SomeKrakenAccountId",
            asset_tx_id="btc",
            amount=Decimal("0.0232320000"),
            isfee=0,
            timestamp=int(arrow.get("2016-10-29 19:13:09").timestamp()),
            direction="IN",
            tx_ledger_type="Kraken.trade",
            symbol="BTC",
        )
        actual_in.id = None
        assert actual_in == expected_in

        expected_out = TxLedger(
            chain="import.kraken",
            address=address,
            hash="import.kraken_dcccccccccccccccccc_trade_zec_btc",
            from_address="Kraken:SomeKrakenAccountId",
            to_address="Kraken:SomeKrakenAccountId",
            asset_tx_id="zec",
            amount=Decimal("0.0036300000"),
            isfee=0,
            timestamp=int(arrow.get("2016-10-29 19:13:09").timestamp()),
            direction="OUT",
            tx_ledger_type="Kraken.trade",
            symbol="ZEC",
        )
        actual_out.id = None
        assert actual_out == expected_out

        expected_fee = TxLedger(
            chain="import.kraken",
            address=address,
            hash="import.kraken_dcccccccccccccccccc_trade_zec_btc",
            from_address="Kraken:SomeKrakenAccountId",
            to_address="Kraken:SomeKrakenAccountId",
            asset_tx_id="btc",
            amount=Decimal("0.0000600000"),
            isfee=1,
            timestamp=int(arrow.get("2016-10-29 19:13:09").timestamp()),
            direction="OUT",
            tx_ledger_type="fee",
            symbol="BTC",
            price_usd=Decimal("715.4103243232162868"),
        )
        actual_fee = actual_fees[0]
        actual_fee.id = None
        assert actual_fee == expected_fee


class TestCoinbaseImporter:
    coinbase_importer = CoinbaseImporter()

    def test_non_swap_case(self, test_db):
        txns = """
| Transaction ID                       | Transaction Type | Date & time          | Asset Acquired | Quantity Acquired (Bought, Received, etc) | Cost Basis (incl. fees paid) (USD) | Data Source   | Asset Disposed (Sold, Sent, etc) | Quantity Disposed | Proceeds (excl. fees paid) (USD) |
| bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb | Deposit          | 2020-01-03T00:00:00Z | ETH            | 30.34                                     | 0                                  | Not available |                                  |                   |                                  |
""".lstrip(
            "\n"
        )

        csv = table_to_csv(txns)
        csv_file = io.StringIO(csv)

        self.coinbase_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeCoinbaseAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.coinbase", address)

        assert len(tx_ledgers) == 1  # only 1 ledger for a non-swap case

        expected_deposit = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1578009600.0_Deposit_eth",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="eth",
            amount=Decimal("30.34"),
            isfee=0,
            timestamp=int(arrow.get("2020-01-03T00:00:00Z").timestamp()),
            direction="IN",
            tx_ledger_type="Coinbase.Deposit",
            symbol="ETH",
        )
        actual_deposit = tx_ledgers[0]
        actual_deposit.id = None
        assert actual_deposit == expected_deposit

        # We _could_ assert on the other Transaction types but the logic treatment is the same, so skipping for now...

    def test_sell(self, test_db):
        txns = """
| Transaction ID                       | Transaction Type | Date & time          | Asset Acquired | Quantity Acquired (Bought, Received, etc) | Cost Basis (incl. fees paid) (USD) | Data Source | Asset Disposed (Sold, Sent, etc) | Quantity Disposed | Proceeds (excl. fees paid) (USD) |
| aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Sell             | 2020-01-04T00:00:00Z |                |                                           |                                    |             | ETH                              | 30.341            | 838.0499999999999992456          |
""".lstrip(
            "\n"
        )

        csv = table_to_csv(txns)
        csv_file = io.StringIO(csv)

        self.coinbase_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeCoinbaseAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.coinbase", address)

        # Should have 2 TxLedgers for a Sell
        assert len(tx_ledgers) == 2
        actual_out = [t for t in tx_ledgers if t.direction == "OUT"][0]
        actual_in = [t for t in tx_ledgers if t.direction == "IN"][0]

        # One OUT for the asset we sold...
        expected_out = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1578096000.0_Sell_eth",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="eth",
            symbol="ETH",
            amount=Decimal("30.341"),
            timestamp=int(arrow.get("2020-01-04T00:00:00Z").timestamp()),
            direction="OUT",
            tx_ledger_type="Coinbase.Sell",
            isfee=0,
        )
        actual_out.id = None
        assert expected_out == actual_out

        # ... and one IN for the fiat we received from the same

        expected_in = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1578096000.0_Sell_eth",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="FIAT:USD",
            symbol="USD",
            amount=Decimal("838.0499999999999992"),  # rounding to 18 decimal places
            timestamp=int(arrow.get("2020-01-04T00:00:00Z").timestamp()),
            direction="IN",
            tx_ledger_type="Coinbase.Sell",
            isfee=0,
            price_usd=Decimal(1.0),  # currency was USD to price is 1
        )
        actual_in.id = None
        assert actual_in == expected_in

    def test_buy(self, test_db):
        txns = """
| Transaction ID                       | Transaction Type | Date & time          | Asset Acquired | Quantity Acquired (Bought, Received, etc) | Cost Basis (incl. fees paid) (USD) | Data Source | Asset Disposed (Sold, Sent, etc) | Quantity Disposed | Proceeds (excl. fees paid) (USD) |
| aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Buy              | 2017-03-14T05:56:39Z | ETH            | 50                                        | 1000.00                            | Coinbase    |                                  |                   |                                  |
""".lstrip(
            "\n"
        )

        csv = table_to_csv(txns)
        csv_file = io.StringIO(csv)

        self.coinbase_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeCoinbaseAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.coinbase", address)

        # Should have 2 TxLedgers for a Sell
        assert len(tx_ledgers) == 2
        actual_out = [t for t in tx_ledgers if t.direction == "OUT"][0]
        actual_in = [t for t in tx_ledgers if t.direction == "IN"][0]

        # One OUT for the asset we sold...
        expected_out = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1489470999.0_Buy_eth",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="FIAT:USD",
            symbol="USD",
            amount=Decimal("1000.00"),
            timestamp=int(arrow.get("2017-03-14T05:56:39Z").timestamp()),
            direction="OUT",
            tx_ledger_type="Coinbase.Buy",
            isfee=0,
            price_usd=Decimal(1.0),  # currency was USD so price is 1.0
        )
        actual_out.id = None
        assert actual_out == expected_out

        # ... and one IN for the fiat we received from the same

        expected_in = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1489470999.0_Buy_eth",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="eth",
            symbol="ETH",
            amount=Decimal("50.0"),
            timestamp=int(arrow.get("2017-03-14T05:56:39Z").timestamp()),
            direction="IN",
            tx_ledger_type="Coinbase.Buy",
            isfee=0,
            price_usd=Decimal(20.0),
        )
        actual_in.id = None
        assert actual_in == expected_in

    def test_converted_from_to(self, test_db):
        txns = """
| Transaction ID                       | Transaction Type | Date & time          | Asset Acquired | Quantity Acquired (Bought, Received, etc) | Cost Basis (incl. fees paid) (USD) | Data Source | Asset Disposed (Sold, Sent, etc) | Quantity Disposed | Proceeds (excl. fees paid) (USD) |
| aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Converted from   | 2020-01-11T00:00:01Z |                |                                           |                                    |             | ETH                              | 5.38952815        | 1000.32337228075                 |
| baaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | Converted to     | 2020-01-11T00:00:02Z | XLM            | 650.1690543                               | 207.734763516                      | Coinbase    |                                  |                   |                                  |
""".lstrip(
            "\n"
        )

        csv = table_to_csv(txns)
        csv_file = io.StringIO(csv)

        self.coinbase_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeCoinbaseAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.coinbase", address)

        # Should have 2 TxLedgers
        assert len(tx_ledgers) == 2
        actual_out = [t for t in tx_ledgers if t.direction == "OUT"][0]
        actual_in = [t for t in tx_ledgers if t.direction == "IN"][0]

        # One OUT for the asset we converted from
        expected_out = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1578700802.0_ConvertedFromTo_eth_xlm",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="eth",
            symbol="ETH",
            amount=Decimal("5.38952815"),
            timestamp=int(arrow.get("2020-01-11T00:00:02Z").timestamp()),
            direction="OUT",
            tx_ledger_type="Coinbase.ConvertedFromTo",
            isfee=0,
            price_usd=Decimal("185.6050"),
        )
        actual_out.id = None
        assert actual_out == expected_out

        # ... and one IN for the assert we converted to

        expected_in = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1578700802.0_ConvertedFromTo_eth_xlm",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="xlm",
            symbol="XLM",
            amount=Decimal("650.1690543"),
            timestamp=int(arrow.get("2020-01-11T00:00:02Z").timestamp()),
            direction="IN",
            tx_ledger_type="Coinbase.ConvertedFromTo",
            isfee=0,
        )
        actual_in.id = None
        assert actual_in == expected_in


COINBASE_TRANSACTIONS_HISTORY_HEADER = """"You can use this transaction report to inform your likely tax obligations. For US customers, Sells, Converts, Rewards Income, Coinbase Earn transactions, and Donations are taxable events. For final tax obligations, please consult your tax advisor."



Transactions
User,xxxxxxxx@xxxxxxxxx.com,aaaaaaaaaaaaaaaaaaaaaaaa

""".lstrip(
    "\n"
)


class TestCoinbaseTransactionHistoryImporter:
    coinbase_importer = CoinbaseTransactionHistoryImporter()

    def test_receive(self, test_db):
        txns = """
| Timestamp            | Transaction Type | Asset | Quantity Transacted | Spot Price Currency | Spot Price at Transaction | Subtotal | Total (inclusive of fees) | Fees | Notes                                           |
| 2017-03-04T06:52:21Z | Receive          | BTC   | 0.9997288           | USD                 | 1291.49                   | ""       | ""                        | ""   | Received 0.9997288 BTC from an external account |
""".lstrip(
            "\n"
        )
        csv = table_to_csv(txns)
        csv_file = io.StringIO(COINBASE_TRANSACTIONS_HISTORY_HEADER + csv)

        self.coinbase_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeCoinbaseAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.coinbase", address)

        assert len(tx_ledgers) == 1  # only 1 ledger for a receive

        expected_receive = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1488610341_Receive_btc",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="btc",
            amount=Decimal("0.9997288"),
            isfee=0,
            timestamp=int(arrow.get("2017-03-04T06:52:21Z").timestamp()),
            direction="IN",
            tx_ledger_type="Coinbase.Receive",
            symbol="BTC",
            price_usd=Decimal("1291.4900000000000000"),
        )
        actual_receive = tx_ledgers[0]
        actual_receive.id = None
        assert actual_receive == expected_receive

    def test_convert(self, test_db):
        txns = """
| Timestamp            | Transaction Type | Asset | Quantity Transacted | Spot Price Currency | Spot Price at Transaction | Subtotal | Total (inclusive of fees) | Fees | Notes                                      |
| 2021-01-29T09:21:33Z | Convert          | BCH   | 0.4997288           | USD                 | 415.69                    | 203.22   | 207.73                    | 4.51 | Converted 0.4997288 BCH to 650.1690543 XLM |
""".lstrip(
            "\n"
        )
        csv = table_to_csv(txns)
        csv_file = io.StringIO(COINBASE_TRANSACTIONS_HISTORY_HEADER + csv)

        self.coinbase_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeCoinbaseAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.coinbase", address)

        assert len(tx_ledgers) == 3  # out, in, fee

        expected_out = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1611912093_Convert_BCH_XLM",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="bch",
            amount=Decimal("0.4997288"),
            isfee=0,
            timestamp=int(arrow.get("2021-01-29T09:21:33Z").timestamp()),
            direction="OUT",
            tx_ledger_type="Coinbase.Convert",
            symbol="BCH",
            price_usd=Decimal("415.69"),
        )
        actual_out = tx_ledgers[0]
        actual_out.id = None
        assert actual_out == expected_out

        expected_in = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1611912093_Convert_BCH_XLM",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="xlm",
            amount=Decimal("650.1690543"),
            isfee=0,
            timestamp=int(arrow.get("2021-01-29T09:21:33Z").timestamp()),
            direction="IN",
            tx_ledger_type="Coinbase.Convert",
            symbol="XLM",
            price_usd=Decimal("0.3125648608711397"),
        )
        actual_in = tx_ledgers[1]
        actual_in.id = None
        assert actual_in == expected_in

        expected_fee = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1611912093_Convert_BCH_XLM",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="FIAT:USD",
            amount=Decimal("4.5100000000000000"),
            isfee=1,
            timestamp=int(arrow.get("2021-01-29T09:21:33Z").timestamp()),
            direction="OUT",
            tx_ledger_type="fee",
            symbol="USD",
            price_usd=Decimal("1.0000000000000000"),
        )
        actual_fee = tx_ledgers[2]
        actual_fee.id = None
        assert actual_fee == expected_fee

    def test_buy(self, test_db):
        txns = """
| Timestamp            | Transaction Type | Asset | Quantity Transacted | Spot Price Currency | Spot Price at Transaction | Subtotal | Total (inclusive of fees) | Fees | Notes                                |
| 2019-02-12T20:41:42Z | Buy              | BSV   | 0.49972881          | USD                 | 65.12                     | 32.54    | 32.54                     | 0.00 | Bought 0.49972881 BSV for $32.54 USD |
""".lstrip(
            "\n"
        )
        csv = table_to_csv(txns)
        csv_file = io.StringIO(COINBASE_TRANSACTIONS_HISTORY_HEADER + csv)

        self.coinbase_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeCoinbaseAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.coinbase", address)

        assert len(tx_ledgers) == 3  # out, in, fee

        expected_out = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1550004102_Buy_bsv",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="FIAT:USD",
            amount=Decimal("32.54"),
            isfee=0,
            timestamp=int(arrow.get("2019-02-12T20:41:42Z").timestamp()),
            direction="OUT",
            tx_ledger_type="Coinbase.Buy",
            symbol="USD",
            price_usd=Decimal("1.0000000000000000"),
        )
        actual_out = tx_ledgers[0]
        actual_out.id = None
        assert actual_out == expected_out

        expected_in = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1550004102_Buy_bsv",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="bsv",
            amount=Decimal("0.4997288100000000"),
            isfee=0,
            timestamp=int(arrow.get("2019-02-12T20:41:42Z").timestamp()),
            direction="IN",
            tx_ledger_type="Coinbase.Buy",
            symbol="BSV",
            price_usd=Decimal("65.1200000000000000"),
        )
        actual_in = tx_ledgers[1]
        actual_in.id = None
        assert actual_in == expected_in

        expected_fee = TxLedger(
            chain="import.coinbase",
            address=address,
            hash="import.coinbase_1550004102_Buy_bsv",
            from_address="Coinbase:SomeCoinbaseAccountId",
            to_address="Coinbase:SomeCoinbaseAccountId",
            asset_tx_id="FIAT:USD",
            amount=Decimal("0.00"),
            isfee=1,
            timestamp=int(arrow.get("2019-02-12T20:41:42Z").timestamp()),
            direction="OUT",
            tx_ledger_type="fee",
            symbol="USD",
            price_usd=Decimal("1.0000000000000000"),
        )
        actual_fee = tx_ledgers[2]
        actual_fee.id = None
        assert actual_fee == expected_fee


class TestCoinbaseProImporter:
    coinbase_pro_importer = CoinbaseProImporter()

    def test_sell(self, test_db):
        txns = """
| portfolio | trade id | product | side | created at               | size           | size unit | price | fee         | total           | price/fee/total unit |
| default   | 45678    | UST-USD | SELL | 2021-12-06T06:22:49.825Z | 20413.54000000 | UST       | 1.002 | 2.045436708 | 20452.321643292 | USD                  |
""".lstrip(
            "\n"
        )

        csv = table_to_csv(txns)
        csv_file = io.StringIO(csv)

        self.coinbase_pro_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeCoinbaseProAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.coinbase_pro", address)

        assert len(tx_ledgers) == 3  # 1 out, 1 in, 1 fee
        actual_out = [t for t in tx_ledgers if t.direction == "OUT" and t.isfee == 0][0]
        actual_in = [t for t in tx_ledgers if t.direction == "IN"][0]
        actual_fee = [t for t in tx_ledgers if t.direction == "OUT" and t.isfee == 1][0]

        expected_out = TxLedger(
            chain="import.coinbase_pro",
            address=address,
            hash="default_45678_UST-USD_SELL",
            from_address="CoinbasePro:SomeCoinbaseProAccountId",
            to_address="CoinbasePro:SomeCoinbaseProAccountId",
            asset_tx_id="ust",
            symbol="UST",
            amount=Decimal("20413.54000000"),
            timestamp=int(arrow.get("2021-12-06T06:22:49.825Z").timestamp()),
            direction="OUT",
            tx_ledger_type="CoinbasePro.SELL",
            isfee=0,
        )
        actual_out.id = None
        assert expected_out == actual_out

        # ... and one IN for the fiat we received from the same

        expected_in = TxLedger(
            chain="import.coinbase_pro",
            address=address,
            hash="default_45678_UST-USD_SELL",
            from_address="CoinbasePro:SomeCoinbaseProAccountId",
            to_address="CoinbasePro:SomeCoinbaseProAccountId",
            asset_tx_id="FIAT:USD",
            symbol="USD",
            amount=Decimal("20454.3670800000000000"),
            timestamp=int(arrow.get("2021-12-06T06:22:49.825Z").timestamp()),
            direction="IN",
            tx_ledger_type="CoinbasePro.SELL",
            isfee=0,
            price_usd=Decimal("1.0000000000000000"),
        )
        actual_in.id = None
        assert actual_in == expected_in

        # And fee
        expected_fee = TxLedger(
            chain="import.coinbase_pro",
            address=address,
            hash="default_45678_UST-USD_SELL",
            from_address="CoinbasePro:SomeCoinbaseProAccountId",
            to_address="CoinbasePro:SomeCoinbaseProAccountId",
            asset_tx_id="FIAT:USD",
            symbol="USD",
            amount=Decimal("2.045436708"),
            timestamp=int(arrow.get("2021-12-06T06:22:49.825Z").timestamp()),
            direction="OUT",
            tx_ledger_type="fee",
            isfee=1,
            price_usd=Decimal("1.0000000000000000"),
        )
        actual_fee.id = None
        assert actual_fee == expected_fee


class BROKEN_TestCoinbaseProAccountStatementImporter:
    coinbase_pro_importer = CoinbaseProImporter()

    def test_import(self, test_db):
        txns = """
| portfolio | type       | time                     | amount                  | balance                | amount/balance unit | transfer id                          | trade id | order id                             |
| default   | deposit    | 2017-03-11T07:17:51.950Z | 0.5000000000000000      | 0.5000000000000000     | BTC                 | aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |          |                                      |
| default   | match      | 2017-03-11T07:18:22.670Z | 30.3411125900000000     | 30.3411125900000000    | ETH                 |                                      | 123456   | bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb |
| default   | match      | 2017-03-11T07:18:22.670Z | -0.4985044798537000     | 0.0014955201463000     | BTC                 |                                      | 123456   | bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb |
| default   | fee        | 2017-03-11T07:18:22.670Z | -0.0014955134395611     | 0.0000000067067389     | BTC                 |                                      | 123456   | bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb |
| default   | withdrawal | 2017-03-11T07:20:52.526Z | -30.3400000000000000    | 0.0011125900000000     | ETH                 | aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |          |                                      |
| default   | conversion | 2017-12-06T14:10:25.056Z | -35000.3100000000000000 | 0.0021739833102500     | USDC                |                                      |          |                                      |
| default   | conversion | 2017-12-06T14:10:25.056Z | 35000.3100000000000000  | 35018.1966350203981000 | USD                 |                                      |          |                                      |
| default   | match      | 2018-03-11T07:18:22.670Z | 1111.000000000000       | 30.3411125900000000    | ETH                 |                                      | 111111   | aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |
| default   | match      | 2018-03-11T07:18:22.670Z | -100.00000000000000     | 0.0014955201463000     | USD                 |                                      | 111111   | aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |
""".lstrip(
            "\n"
        )

        csv = table_to_csv(txns)
        csv_file = io.StringIO(csv)

        self.coinbase_pro_importer.do_import(
            csv_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeCoinbaseProAccountId",
            db=test_db,
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.coinbase_pro", address)

        assert (
            len(tx_ledgers) == 13
        )  # 1 in for deposit, 1 out and 1 in for the trade, 1 out for the fee, and 1 out for the withdrawal, and 1 in and 1 out for the conversion
        outs = [t for t in tx_ledgers if t.direction == "OUT" and t.isfee != 1]
        ins = [t for t in tx_ledgers if t.direction == "IN"]

        actual_deposit = ins[0]
        actual_out = outs[0]
        actual_in = ins[1]
        actual_fee = [t for t in tx_ledgers if t.direction == "OUT" and t.isfee == 1][0]
        actual_withdrawal = outs[1]
        actual_conversion_out = outs[2]
        actual_conversion_in = ins[2]

        expected_deposit = TxLedger(
            chain="import.coinbase_pro",
            address=address,
            hash="default_deposit_9d06cba3-7f1c-4da6-b257-44d697887594",
            from_address="CoinbasePro:SomeCoinbaseProAccountId",
            to_address="CoinbasePro:SomeCoinbaseProAccountId",
            asset_tx_id="btc",
            symbol="BTC",
            amount=Decimal("0.5"),
            timestamp=int(arrow.get("2017-03-11T07:17:51.950Z").timestamp()),
            direction="IN",
            tx_ledger_type="CoinbasePro.deposit",
            isfee=0,
        )
        actual_deposit.id = None
        assert expected_deposit == actual_deposit

        # 1 OUT for the trade
        expected_out = TxLedger(
            chain="import.coinbase_pro",
            address=address,
            hash="default_trade_297592",
            from_address="CoinbasePro:SomeCoinbaseProAccountId",
            to_address="CoinbasePro:SomeCoinbaseProAccountId",
            asset_tx_id="btc",
            symbol="BTC",
            amount=Decimal("0.4985044798537000"),
            timestamp=int(arrow.get("2017-03-11T07:18:22.670Z").timestamp()),
            direction="OUT",
            tx_ledger_type="CoinbasePro.trade",
            isfee=0,
        )
        actual_out.id = None
        assert actual_out == expected_out

        # ... and one IN for the fiat we received from the same

        expected_in = TxLedger(
            chain="import.coinbase_pro",
            address=address,
            hash="default_trade_297592",
            from_address="CoinbasePro:SomeCoinbaseProAccountId",
            to_address="CoinbasePro:SomeCoinbaseProAccountId",
            asset_tx_id="eth",
            symbol="ETH",
            amount=Decimal("30.3411125900000000"),
            timestamp=int(arrow.get("2017-03-11T07:18:22.670Z").timestamp()),
            direction="IN",
            tx_ledger_type="CoinbasePro.trade",
            isfee=0,
        )
        actual_in.id = None
        assert actual_in == expected_in

        # And fee
        expected_fee = TxLedger(
            chain="import.coinbase_pro",
            address=address,
            hash="default_trade_297592",
            from_address="CoinbasePro:SomeCoinbaseProAccountId",
            to_address="CoinbasePro:SomeCoinbaseProAccountId",
            asset_tx_id="btc",
            symbol="BTC",
            amount=Decimal("0.0014955134395611"),
            timestamp=int(arrow.get("2017-03-11T07:18:22.670Z").timestamp()),
            direction="OUT",
            tx_ledger_type="fee",
            isfee=1,
        )
        actual_fee.id = None
        assert actual_fee == expected_fee

        # And withdrawal
        expected_withdrawal = TxLedger(
            chain="import.coinbase_pro",
            address=address,
            hash="default_withdrawal_bf420211-4bc6-4ba3-907c-85877f9a7e91",
            from_address="CoinbasePro:SomeCoinbaseProAccountId",
            to_address="CoinbasePro:SomeCoinbaseProAccountId",
            asset_tx_id="eth",
            symbol="ETH",
            amount=Decimal("30.3400000000000000"),
            timestamp=int(arrow.get("2017-03-11T07:20:52.526Z").timestamp()),
            direction="OUT",
            tx_ledger_type="CoinbasePro.withdrawal",
            isfee=0,
        )
        actual_withdrawal.id = None
        assert actual_withdrawal == expected_withdrawal

        # Conversion out
        expected_conversion_out = TxLedger(
            chain="import.coinbase_pro",
            address=address,
            hash="default_conversion_2021-12-06T14:10:25.056Z",
            from_address="CoinbasePro:SomeCoinbaseProAccountId",
            to_address="CoinbasePro:SomeCoinbaseProAccountId",
            asset_tx_id="usdc",
            symbol="USDC",
            amount=Decimal("35000.31"),
            timestamp=int(arrow.get("2021-12-06T14:10:25.056Z").timestamp()),
            direction="OUT",
            tx_ledger_type="CoinbasePro.conversion",
            isfee=0,
        )
        actual_conversion_out.id = None
        assert actual_conversion_out == expected_conversion_out

        # Conversion in
        expected_conversion_in = TxLedger(
            chain="import.coinbase_pro",
            address=address,
            hash="default_conversion_2021-12-06T14:10:25.056Z",
            from_address="CoinbasePro:SomeCoinbaseProAccountId",
            to_address="CoinbasePro:SomeCoinbaseProAccountId",
            asset_tx_id="FIAT:USD",
            symbol="USD",
            amount=Decimal("35000.31"),
            timestamp=int(arrow.get("2021-12-06T14:10:25.056Z").timestamp()),
            direction="IN",
            tx_ledger_type="CoinbasePro.conversion",
            isfee=0,
        )
        actual_conversion_in.id = None
        assert actual_conversion_in == expected_conversion_in


class TestGeminiImporter:
    gemini_importer = GeminiImporter()

    def test_buy(self, test_db, tmp_path):
        txn = """
| Date                    | Time (UTC)              | Type | Symbol | Specification | Liquidity Indicator | Trading Fee Rate (bps) | DAI Amount DAI      | Fee (DAI) DAI | DAI Balance DAI     | SGD Amount SGD | Fee (SGD) SGD | SGD Balance SGD | FTM Amount FTM | Fee (FTM) FTM | FTM Balance FTM | Trade ID    | Order ID    | Order Date | Order Time   | Client Order ID | API Session | Tx Hash | Deposit Destination | Deposit Tx Output | Withdrawal Destination | Withdrawal Tx Output |
| 2021-12-08 03:47:23.014 | 2021-12-08 03:47:23.014 | Buy  | DAISGD | Mobile        | Taker               |                        | "3,595.150506 DAI " |               | "3,595.150506 DAI " | "($4,925.50)"  | ($74.50)      | $0.00           |                |               | 0.0 FTM         | 12345678901 | 98765433210 | 2021-12-08 | 03:47:22.369 | Mobile          |             |         |                     |                   |                        |                      |
|                         |                         |      |        |               |                     |                        |                     | 0.0 DAI       | 0.0 DAI             |                | $0.00         | $0.00           |                | 0.0 FTM       | 0.0 FTM         |             |             |            |              |                 |             |         |                     |                   |                        |                      |
""".lstrip(
            ("\n")
        )  # NOTE: The last line without date/time etc. is intentional. No idea why Gemini puts it there, but it does...

        xlsx = table_to_xlsx(txn)
        xlsx_file = io.BytesIO(xlsx)

        self.gemini_importer.do_import(
            xlsx_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeGeminiAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.gemini", address)

        # Should have 3 TxLedgers for a Buy
        assert len(tx_ledgers) == 3  # 1 out 1 in 1 fee
        actual_out = [t for t in tx_ledgers if t.direction == "OUT" and t.isfee == 0][0]
        actual_in = [t for t in tx_ledgers if t.direction == "IN"][0]
        actual_fee = [t for t in tx_ledgers if t.direction == "OUT" and t.isfee == 1][0]

        expected_out = TxLedger(
            chain="import.gemini",
            address=address,
            hash="import.gemini_1638935243.014_Buy_DAISGD",
            from_address="Gemini:SomeGeminiAccountId",
            to_address="Gemini:SomeGeminiAccountId",
            asset_tx_id="FIAT:SGD",
            symbol="SGD",
            amount=Decimal("4925.50"),
            timestamp=int(arrow.get("2021-12-08 03:47:23.014").timestamp()),
            direction="OUT",
            tx_ledger_type="Gemini.Buy",
            isfee=0,
            price_usd=Decimal(
                "3610.3291923451183912"
            ),  # price converted to USD from SGD.
        )
        actual_out.id = None
        assert actual_out == expected_out

        # ... and one IN for the fiat we received from the same

        expected_in = TxLedger(
            chain="import.gemini",
            address=address,
            hash="import.gemini_1638935243.014_Buy_DAISGD",
            from_address="Gemini:SomeGeminiAccountId",
            to_address="Gemini:SomeGeminiAccountId",
            asset_tx_id="dai",
            symbol="DAI",
            amount=Decimal("3595.1505060000000000"),
            timestamp=int(arrow.get("2021-12-08 03:47:23.014").timestamp()),
            direction="IN",
            tx_ledger_type="Gemini.Buy",
            isfee=0,
            price_usd=Decimal("1.0042219891266823"),
        )
        actual_in.id = None
        assert actual_in == expected_in

        expected_fee = TxLedger(
            chain="import.gemini",
            address=address,
            hash="import.gemini_1638935243.014_Buy_DAISGD",
            from_address="Gemini:SomeGeminiAccountId",
            to_address="Gemini",
            asset_tx_id="FIAT:SGD",
            symbol="SGD",
            amount=Decimal("74.50"),
            timestamp=int(arrow.get("2021-12-08 03:47:23.014").timestamp()),
            direction="OUT",
            tx_ledger_type="fee",
            isfee=1,
            price_usd=Decimal("0.7329873499837820"),
        )
        actual_fee.id = None
        assert actual_fee == expected_fee

    def test_credit(self, test_db, tmp_path):
        txn = """
| Date                    | Time (UTC)              | Type   | Symbol | Specification           | Liquidity Indicator | Trading Fee Rate (bps) | DAI Amount DAI | Fee (DAI) DAI | DAI Balance DAI | SGD Amount SGD | Fee (SGD) SGD | SGD Balance SGD | FTM Amount FTM | Fee (FTM) FTM | FTM Balance FTM | Trade ID | Order ID | Order Date | Order Time | Client Order ID | API Session | Tx Hash | Deposit Destination | Deposit Tx Output | Withdrawal Destination | Withdrawal Tx Output |
| 2022-01-12 01:45:08.840 | 2022-01-12 01:45:08.840 | Credit | SGD    | Deposit (Fast Transfer) |                     |                        |                |               | 0.0 DAI         | "$20,000"      |               | $20,000.00      |                | 0.0 FTM       | 0.0 FTM         |          |          |            |            |                 |             |         |                     |                   |                        |                      |
|                         |                         |        |        |                         |                     |                        |                | 0.0 DAI       | 0.0 DAI         |                | $0.00         | $0.00           |                | 0.0 FTM       | 0.0 FTM         |          |          |            |            |                 |             |         |                     |                   |                        |                      |
""".lstrip(
            ("\n")
        )  # NOTE: The last line without date/time etc. is intentional. No idea why Gemini puts it there, but it does...

        xlsx_file_path = tmp_path / "gemini.xlsx"
        xlsx = table_to_xlsx(txn)
        xlsx_file = io.BytesIO(xlsx)

        self.gemini_importer.do_import(
            xlsx_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeGeminiAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.gemini", address)

        # Should have 1 TxLedgers for a Credit
        assert len(tx_ledgers) == 1
        actual_in = [t for t in tx_ledgers if t.direction == "IN"][0]

        expected_in = TxLedger(
            chain="import.gemini",
            address=address,
            hash="import.gemini_1641951908.84_Credit_SGD",
            from_address="Gemini:SomeGeminiAccountId",
            to_address="Gemini:SomeGeminiAccountId",
            asset_tx_id="sgd",
            symbol="SGD",
            amount=Decimal("20000"),
            timestamp=int(arrow.get("2022-01-12 01:45:08.840").timestamp()),
            direction="IN",
            tx_ledger_type="Gemini.Credit",
            isfee=0,
            price_usd=Decimal("0.7403307722359682"),
        )
        actual_in.id = None
        assert actual_in == expected_in

    def test_debit(self, test_db, tmp_path):
        txn = """
| Date                    | Time (UTC)              | Type  | Symbol | Specification    | Liquidity Indicator | Trading Fee Rate (bps) | DAI Amount DAI       | Fee (DAI) DAI | DAI Balance DAI | SGD Amount SGD | Fee (SGD) SGD | SGD Balance SGD | FTM Amount FTM | Fee (FTM) FTM | FTM Balance FTM | Trade ID | Order ID | Order Date | Order Time | Client Order ID | API Session | Tx Hash                                                          | Deposit Destination | Deposit Tx Output | Withdrawal Destination                     | Withdrawal Tx Output |
| 2021-12-08 04:00:30.911 | 2021-12-08 04:00:30.911 | Debit | DAI    | Withdrawal (DAI) |                     |                        | "(3,584.150506 DAI)" | 0.0 DAI       | 0.0 DAI         |                |               | $0.00           |                |               | 0.0 FTM         |          |          |            |            |                 |             | bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb |                     |                   | 0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |                      |
|                         |                         |       |        |                  |                     |                        |                      | 0.0 DAI       | 0.0 DAI         |                | $0.00         | $0.00           |                | 0.0 FTM       | 0.0 FTM         |          |          |            |            |                 |             |                                                                  |                     |                   |                                            |                      |
""".lstrip(
            ("\n")
        )  # NOTE: The last line without date/time etc. is intentional. No idea why Gemini puts it there, but it does...

        xlsx_file_path = tmp_path / "gemini.xlsx"
        xlsx = table_to_xlsx(txn)
        xlsx_file = io.BytesIO(xlsx)

        self.gemini_importer.do_import(
            xlsx_file,
            entity_address_for_imports=address,
            exchange_account_id="SomeGeminiAccountId",
        )
        update_entity_transactions(entity_name)
        tx_ledgers = get_tx_ledgers(test_db, "import.gemini", address)

        # Should have 1 TxLedgers for a Debit
        assert len(tx_ledgers) == 1
        actual_out = [t for t in tx_ledgers if t.direction == "OUT"][0]

        expected_out = TxLedger(
            chain="import.gemini",
            address=address,
            hash="import.gemini_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            from_address="Gemini:SomeGeminiAccountId",
            to_address="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # If we have the withdrawal destination we show it
            asset_tx_id="dai",
            symbol="DAI",
            amount=Decimal("3584.1505060000000000"),
            timestamp=int(arrow.get("2021-12-08 04:00:30.911").timestamp()),
            direction="OUT",
            tx_ledger_type="Gemini.Debit",
            isfee=0,
        )
        actual_out.id = None
        assert actual_out == expected_out
