from decimal import Decimal
from pprint import pprint

import jsonpickle
import pytest
from pytest import approx

from perfi.costbasis import regenerate_costbasis_lots
from perfi.events import EventStore
from perfi.models import (
    TxLedger,
    TxLogical,
    TX_LOGICAL_FLAG,
    CostbasisIncome,
    CostbasisLot,
    CostbasisDisposal,
    load_flags,
)
from perfi.transaction.chain_to_ledger import update_entity_transactions
from perfi.transaction.ledger_to_logical import TransactionLogicalGrouper
from tests.helpers import *
from tests.integration.test_tx_logicals import get_tx_logicals

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
    monkeysession.setattr("perfi.costbasis.price_feed", price_feed)
    monkeysession.setattr("perfi.transaction.chain_to_ledger.price_feed", price_feed)
    yield
    monkeysession.undo()


def get_costbasis_lots(test_db, entity, address):
    sql = """SELECT
                 tx_ledger_id,
                 entity,
                 address,
                 asset_price_id,
                 symbol,
                 asset_tx_id,
                 original_amount,
                 current_amount,
                 price_usd,
                 basis_usd,
                 timestamp,
                 history,
                 receipt,
                 price_source,
                 chain
             FROM costbasis_lot
             WHERE entity = ?
             AND address = ?
             ORDER BY timestamp ASC
    """
    params = [entity, address]
    results = test_db.query(sql, params)
    lots_to_return = []
    for r in results:
        r = dict(**r)
        r["history"] = jsonpickle.decode(r["history"])
        flags = load_flags(CostbasisLot.__name__, r["tx_ledger_id"])
        lot = CostbasisLot(flags=flags, **r)
        lots_to_return.append(lot)

    return lots_to_return


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

    return [CostbasisDisposal(**r) for r in results]


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
        r = dict(**r)
        r["lots"] = jsonpickle.decode(r["lots"])
        income = CostbasisIncome(**r)
        incomes_to_return.append(income)

    return incomes_to_return


def get_tx_ledgers(db, chain, address):
    sql = """SELECT id, chain, address, hash, from_address, to_address, from_address_name, to_address_name, asset_tx_id, isfee, amount, timestamp, direction, tx_ledger_type, asset_price_id, symbol, price_usd
           FROM tx_ledger
           WHERE chain = ? AND address = ?
           ORDER BY timestamp ASC, isfee ASC
        """
    results = list(db.query(sql, [chain, address]))
    return [TxLedger(**r) for r in results]


def common(test_db, event_store=None):
    map_assets()
    update_entity_transactions(entity_name)
    if event_store is None:
        event_store = EventStore(test_db, TxLogical, TxLedger)
    tlg = TransactionLogicalGrouper(entity_name, event_store)
    tlg.update_entity_transactions()
    regenerate_costbasis_lots(entity_name, quiet=True)


class TestCostbasisGeneral:
    def test_creates_zero_cost_lot_if_needed_to_auto_reconcile(self, test_db):
        # 5 AVAX in @ 1.00 - makes an initial lot w/ amount 5 for AVAX
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # 1 AVAX swapped @ 5.00 - normal disposal, nothing flagged since we have enough to drawdown from our AVAX lot
        # New JOE lot should also created, just fyi
        make.tx(
            outs=["1 AVAX"],
            ins=["10 JOE"],
            debank_name="swapExactTokensForETH",
            fee=0.00,
            timestamp=2,
            to_address="Some DEX",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)
        price_feed.stub_price(2, "joe", 0.50)

        # 1 AVAX out @ 10.00 - auto-reconciled disposal because we should only have 4 remaining AVAX in our lot,
        # but we are sending 10, so we expect a new auto-reconciled lot of amount 6 (10-4) below in our assertions
        # Another joe lot is created here, too
        make.tx(
            outs=["10 AVAX"],
            ins=["200 JOE"],
            debank_name="swapExactTokensForETH",
            fee=0.00,
            timestamp=3,
            to_address="Some DEX",
        )
        price_feed.stub_price(3, "avalanche-2", 10.00)
        price_feed.stub_price(3, "joe", 0.50)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        joe_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "joe"
        ]
        assert len(avax_lots) == 2  # 1 normal, 1 autoreconciled
        assert len(joe_lots) == 2  # 2 normal

        avax_normal_lot = avax_lots[0]
        avax_zerocost_lot = avax_lots[1]

        # No flags on the normal avax lot, zero_cost on the zero_cost avax lot
        assert len(avax_normal_lot.flags) == 0
        assert len(avax_zerocost_lot.flags) > 0
        flag_names = [f.name for f in avax_zerocost_lot.flags]
        assert "auto_reconciled" in flag_names
        # We should make sure that we've properly drawndown the overdrawn balance
        assert avax_zerocost_lot.original_amount == approx(Decimal(6))
        assert avax_zerocost_lot.current_amount == approx(Decimal(0))
        assert avax_zerocost_lot.basis_usd == approx(Decimal(0))
        assert avax_zerocost_lot.price_usd == approx(Decimal(0))

        # By the end, at timestamp 3, we should have a disposal for 1 at t1, 4 more avax from the first lot, then 6 more from a new zero cost lot
        avax_disposals = get_disposals(test_db, "AVAX")
        assert len(avax_disposals) == 3
        assert avax_disposals[0].amount == 1
        assert avax_disposals[1].amount == 4
        assert avax_disposals[2].amount == 6
        assert (
            avax_disposals[0].duration_held == 1
        )  # bought at time 1, disposed 1 at time 2, duration is 1
        assert (
            avax_disposals[1].duration_held == 2
        )  # bought at time 1, disposed 4 at time 3, duration is 2

        disposal_from_reconcile = avax_disposals[2]
        assert (
            disposal_from_reconcile.duration_held == 0
        )  # zerocost lot created to auto reconcile, duration is 0
        assert disposal_from_reconcile.basis_usd == 0
        assert disposal_from_reconcile.total_usd == 6 * 10
        # LATER: once we have a `lots` attr on `costbasis_disposal` we can add assertions to be sure each disposal targeted the right lots

    def test_non_disposal_lots_have_history_ref_to_original_asset(self, test_db):
        orig_avax_tx = make.tx(ins=["50 AVAX"], timestamp=1, from_address="A Friend")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        deposit_tx = make.tx(
            ins=["1 Foo|0xFoo"],
            outs=["10 AVAX"],
            timestamp=2,
            debank_name="deposit",
            from_address="Some Deposit Place",
        )
        price_feed.stub_price(2, "avalanche-2", 1.00)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        foo_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xFoo"
        ]
        assert len(avax_lots) == 1
        assert len(foo_lots) == 1
        assert foo_lots[0].receipt == 1

        print(orig_avax_tx)
        print(deposit_tx)
        print(foo_lots[0].history[0])
        assert foo_lots[0].history[0].amount == 10


class TestCostbasisFees:
    def test_fee_total_value_is_added_to_costbasis_total_usd_for_new_lots(
        self, test_db
    ):
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        make.tx(
            outs=["1 AVAX"],
            ins=["10 JOE"],
            debank_name="swapExactTokensForETH",
            fee=0.25,
            fee_usd=1.25,
            timestamp=2,
            to_address="Some DEX",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)
        price_feed.stub_price(2, "joe", 0.50)

        common(test_db)

        joe_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "joe"
        ]

        assert len(joe_lots) == 1
        # Total lot basis_usd should equal (asset_price at timestamp) * (amount of asset) + (value of fee paid)
        expected_asset_price_at_timestamp = 0.5
        expected_fee_value = 0.25 * 5.00
        expected_basis_usd = expected_asset_price_at_timestamp * 10 + expected_fee_value
        assert expected_basis_usd == joe_lots[0].basis_usd

    def test_fee_total_value_is_subtracted_from_disposal_total_usd(self, test_db):
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        make.tx(
            outs=["1 AVAX"],
            ins=["10 JOE"],
            debank_name="swapExactTokensForETH",
            fee=0.25,
            fee_usd=1.25,
            timestamp=2,
            to_address="Some DEX",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)
        price_feed.stub_price(2, "joe", 0.50)

        common(test_db)

        disposals = get_disposals(test_db, "AVAX")
        assert len(disposals) == 1
        # When we swapped 1 avax away, it had a unit value of 5.00,
        # but we also paid 0.25 avax in fees at a unit price of 5.00 for a total fee of 1.25
        # So our total usd proceeds value should be 5.00 - 1.25 == 3.75
        assert disposals[0].total_usd == 3.75


class TestCostbasisForm8949:
    def test_respects_ignored_from_costbasis_flag_on_tx_logicals(
        self, test_db, event_store
    ):
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        make.tx(
            outs=["1 AVAX"],
            ins=["10 JOE"],
            debank_name="swapExactTokensForETH",
            fee=0,
            timestamp=2,
            to_address="Some DEX",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)
        price_feed.stub_price(2, "joe", 0.50)

        common(test_db, event_store)

        # Flag the swap tx logical to be ignored from costbasis
        tx_logicals = get_tx_logicals(test_db, address)
        txl = tx_logicals[1]
        event = event_store.create_tx_logical_flag_added(
            txl.id, TX_LOGICAL_FLAG.ignored_from_costbasis, source="manual"
        )
        event_store.apply_event(event)

        # Regenerate costbasis again
        regenerate_costbasis_lots(entity_name, quiet=True)

        # Check our lots
        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        joe_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "joe"
        ]

        # Our JOE lot should not exist (since we ignored that swap)
        assert len(joe_lots) == 0

        # Our original avax lot current_amount should be untouched
        assert len(avax_lots) == 1
        assert avax_lots[0].current_amount == 5

        # No disposals should exist
        disposals = get_disposals(test_db, "AVAX")
        assert len(disposals) == 0

    def test_receive_flags_costbasis_for_disposal(self, test_db):
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        assert len(avax_lots) == 1
        assert avax_lots[0].receipt == 0


class TestCostbasisDisposal:
    def test_simple_sends_are_not_treated_as_disposals(self, test_db):
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        make.tx(outs=["1 AVAX"], fee=0.00, timestamp=2, to_address="ANOTHER FRIEND")
        price_feed.stub_price(2, "avalanche-2", 5.00)

        common(test_db)

        # Check to make sure no CostbasisDisposal was generated since this was a send (and we will assume sends are not disposals)
        disposals = get_disposals(test_db, "AVAX", 2)
        assert len(disposals) == 0

    # Test that our costbasis lot and disposal mapping/matching algorithms are working properly
    def test_disposing_like_kind_assets_from_different_asset_tx_ids_results_in_sane_disposals(
        self,
        test_db,
    ):
        make.tx(
            ins=[
                "1 USDC|0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e",  # Native USDC on Avalanche
                "1 USDC.e|0xa7d7079b0fead91f3e65f86e8915cb59c1a4c664",  # USDC.e on Avalanche
            ],
            timestamp=1,
            fee=0,
            from_address="A Friend",
        )
        price_feed.stub_price(1, "usd-coin", 1.00)
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # This may look unusual at first glance because we are setting up 1 each of native USDC and bridged USDC.e above
        # but then we send out 2 of the native. You might expect this to create a zero-cost lot for 2-1 amount But
        # we don't do that because we are testing here that like-kind mapped assets can dispose from each others lots
        # Avalanche USDC and USDC.e should both map to mapped_price_id:usd-coin and disposal should consume that for the lot

        make.tx(
            outs=[
                "1.5 USDC|0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"
            ],  # Native USDC on Avalanche
            timestamp=2,
            fee=0,
            debank_name="disposal",
            to_address="Other Person",
        )
        price_feed.stub_price(2, "usd-coin", 1.00)
        price_feed.stub_price(2, "avalanche-2", 1.00)

        common(test_db)

        usdc_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"
        ]
        usdce_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xa7d7079b0fead91f3e65f86e8915cb59c1a4c664"
        ]

        assert len(usdc_lots) == 1
        assert len(usdce_lots) == 1

        # Make sure our lots are correct
        assert usdc_lots[0].asset_price_id == "usd-coin"
        assert usdce_lots[0].asset_price_id == usdc_lots[0].asset_price_id
        assert usdc_lots[0].symbol == "USDC"
        assert usdce_lots[0].symbol == usdc_lots[0].symbol
        assert usdc_lots[0].asset_tx_id == "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"
        assert usdce_lots[0].asset_tx_id == "0xa7d7079b0fead91f3e65f86e8915cb59c1a4c664"

        # TODO: you would _think_ that at the same price, it should lotmatch by natural (insertion) order
        # but... this doesn't seem to be the case.
        assert usdce_lots[0].current_amount == approx(Decimal(0))
        assert usdc_lots[0].current_amount == approx(Decimal(0.5))

        disposals = get_disposals(test_db, "USDC", 2)
        assert len(disposals) == 2
        assert disposals[0].amount == approx(Decimal(1))
        assert disposals[0].asset_price_id == "usd-coin"
        assert disposals[1].amount == approx(Decimal(0.5))
        assert disposals[1].asset_price_id == "usd-coin"

    def test_changing_ownership_of_deposit_receipt_without_disposal(self, test_db):
        # Initial Receive so we have a non-zero costbasis_lot of AVAX
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # Deposit 1 AVAX and get 0.9 avWAVAX (deposit receipt)
        # value of AVAX has gone from $1 -> $5
        make.tx(
            outs=["1 AVAX"],
            ins=["0.5 avWAVAX|0xavWAVAX"],
            debank_name="depositBNB",
            fee=0.00,
            timestamp=2,
            to_address="Aave",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)

        # This is a send, but not a disposal
        make.tx(
            outs=["0.25 avWAVAX|0xavWAVAX"],
            debank_name="send",
            fee=0.00,
            timestamp=3,
            to_address="A FRIEND",
        )
        price_feed.stub_price(3, "avalanche-2", 6.00)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        avax_disposals = get_disposals(test_db, "AVAX", 3)
        avWAVAX_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xavWAVAX"
        ]
        avWAVAX_disposals = get_disposals(test_db, "0xavWAVAX", 3)

        # We should only have 4.5 AVAX left (subtracted by unwinding and multiplying by amount of receipt subtracted from original ratio)
        # 1 AVAX -> 0.5 avWAVAX; -0.25 avWAVAX -> -0.5 AVAX
        assert len(avax_lots) == 1
        avax_lot = avax_lots[0]
        assert avax_lot.current_amount == approx(Decimal(4.5))

        assert len(avWAVAX_lots) == 1
        assert avWAVAX_lots[0].current_amount == approx(Decimal(0.25))
        assert avWAVAX_lots[0].receipt == True
        assert len(avWAVAX_lots[0].history) == 1
        assert avWAVAX_lots[0].history[0].amount == approx(Decimal(1))

        # We shouldn't have an AVAX disposal
        assert len(avax_disposals) == 0

        # We also shouldn't have any avWAVAX disposals because a "send" is only a change in ownership, not a disposal
        assert len(avWAVAX_disposals) == 0

    def test_disposal_of_deposit_receipt(self, test_db):
        # Initial Receive so we have a non-zero costbasis_lot of AVAX
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # Deposit 1 AVAX and get 0.5 avWAVAX (deposit receipt)
        # value of AVAX has gone from $1 -> $5
        make.tx(
            outs=["1 AVAX"],
            ins=["0.5 avWAVAX|0xavWAVAX"],
            debank_name="depositBNB",
            fee=0.00000,
            timestamp=2,
            to_address="Aave",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)

        # This is a spend, so is a change of ownership and a disposal!
        make.tx(
            ins=["3 USDC"],
            outs=["0.25 avWAVAX|0xavWAVAX"],
            debank_name="swap",
            fee=0.00000,
            timestamp=3,
            to_address="A VENDOR",
        )
        price_feed.stub_price(3, "avalanche-2", 6.00)
        price_feed.stub_price(3, "usd-coin", 1.00)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        avax_disposals = get_disposals(test_db, "AVAX", 3)
        avWAVAX_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xavWAVAX"
        ]
        avWAVAX_disposals = get_disposals(test_db, "avWAVAX", 3)

        # We should only have 4.5 AVAX left (subtracted by unwinding and multiplying by amount of receipt subtracted from original ratio)
        # 1 AVAX -> 0.5 avWAVAX; -0.25 avWAVAX -> -0.5 AVAX
        assert len(avax_lots) == 1
        avax_lot = avax_lots[0]
        assert avax_lot.current_amount == approx(Decimal(4.5))

        assert len(avWAVAX_lots) == 1
        assert avWAVAX_lots[0].current_amount == approx(Decimal(0.25))
        assert avWAVAX_lots[0].receipt == True
        assert len(avWAVAX_lots[0].history) == 1
        assert avWAVAX_lots[0].history[0].amount == approx(Decimal(1))

        # We shouldn't have an AVAX disposal
        pprint(avax_disposals)
        assert len(avax_disposals) == 0

        pprint(avWAVAX_disposals)

        # We also should have one avWAVAX disposal because the swap of avWAVAX for USDC is a disposal
        assert len(avWAVAX_disposals) == 1
        assert avWAVAX_disposals[0].amount == approx(Decimal(0.25))
        assert avWAVAX_disposals[0].total_usd == approx(
            Decimal(3)
        )  # how much we receive for 0.5 AVAX
        # Now this is interesting... because in this case we have a price for when avWAVAX was swapped,
        # Because we are looking at the history of the receipt tx, we will get an avWAVAX disposal of the price of AVAX at the time it was deposited, not at the original costbasis of whatever AVAX lot we deduct from (which would be $1 AVAX). This is probably fine/more correct, we'd rather track the avWAVAX as a disposal, not the AVAX we deduct from in this case
        assert avWAVAX_disposals[0].basis_usd == approx(Decimal(2.5))


class TestCostbasisPrice:
    def test_map_like_kind_assets_like_avwavax_to_avax(self, test_db):
        # 5 AVAX in @ 1.00 - makes an initial lot w/ amount 5 for AVAX
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # 1 AVAX deposited
        make.tx(
            outs=["1 AVAX"],
            ins=["0.5 avWAVAX"],
            debank_name="depositBNB",
            fee=0.00000,
            timestamp=2,
            to_address="Aave",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)

        common(test_db)

        # The avWAVAX received at T2 should get mapped to avalanche-2 for costbasis purposes
        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "avax"
        ]
        avwavax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xdfe521292ece2a4f44242efbcd66bc594ca9714b"
        ]

        # Should be the original 5 amount
        assert len(avax_lots) == 1
        assert avax_lots[0].current_amount == 5.0

        # Now lets look at our receipt...
        assert len(avwavax_lots) == 1
        assert avwavax_lots[0].receipt == True
        avwl = avwavax_lots[0]
        assert len(avwl.history) == 1  # 1 while we don't store a fee tx
        assert avwl.basis_usd == approx(
            Decimal(5)
        )  # should be the amount * price = price of 1 AVAX
        assert avwl.price_usd == approx(
            Decimal(10)
        )  # since 0.5 avWAVAX = 1 AVAX @ 5, then 1 avWAVAX = 10

        # Check history - this should be the 1 AVAX out tx
        assert avwl.history[0].amount == approx(Decimal(1.0))
        assert avwl.history[0].asset_tx_id == "avax"

        # And, there should be no disposal records created
        avax_disposals = get_disposals(test_db, "avax", 2)
        assert len(avax_disposals) == 0

    def test_lot_and_disposal_use_tx_ledger_price_if_set(self, test_db, event_store):
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        make.tx(
            outs=["1 AVAX"],
            ins=["10 JOE"],
            debank_name="swapExactTokensForETH",
            fee=0.00,
            timestamp=2,
            to_address="Some DEX",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)
        price_feed.stub_price(2, "joe", 50.00)

        common(test_db, event_store)

        # Update our first tx_ledger (5 avax in, setting manual price)
        tx_ledgers = get_tx_ledgers(test_db, chain, address)
        tx = tx_ledgers[0]
        assert tx.asset_tx_id == "avax"
        assert tx.amount == 5
        event = event_store.create_tx_ledger_price_updated(
            tx.id, 20.00, "user-provided", source="manual"
        )
        event_store.apply_event(event)

        # Update our second tx_ledger (1 avax out, setting manual price)
        tx_ledgers = get_tx_ledgers(test_db, chain, address)
        tx = tx_ledgers[2]
        assert tx.asset_tx_id == "avax"
        assert tx.amount == 1
        event = event_store.create_tx_ledger_price_updated(
            tx.id, 10.00, "user-provided", source="manual"
        )
        event_store.apply_event(event)

        # Regenerate costbasis again
        regenerate_costbasis_lots(entity_name, quiet=True)

        # Check to make sure a CostbasisLot was generated with appropriate attrs
        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        joe_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "joe"
        ]

        assert len(avax_lots) == 1
        assert len(joe_lots) == 1

        lot = avax_lots[0]
        assert lot.price_usd == 20.00  # Updated from our event above
        assert lot.original_amount == 5
        assert lot.current_amount == 4

        # Check to make sure a CostbasisDisposal was generated with appropriate attrs (updated price)
        disposals = get_disposals(test_db, "AVAX")
        assert len(disposals) == 1
        disposal = disposals[0]
        assert disposal.amount == 1
        assert disposal.timestamp == 2
        assert disposal.duration_held == 1
        assert disposal.total_usd == Decimal(
            10.00
        )  # Note that we have a max_disposal guard that prevents the price of a disposal being more than the total price of the INs, so be sure that price of JOE above is enough to allow this to work
        assert disposal.basis_usd == Decimal(20.00)


class TestCostbasisReceive:
    def test_receive_unknown_token_with_no_price_creates_flagged_zerocost_lot(
        self,
        test_db,
    ):
        make.tx(ins=["1 FakePhishing|0xFake"], timestamp=1, from_address="A Spammer")

        common(test_db)

        # Check to make sure a CostbasisLot was generated with appropriate attrs
        lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xFake"
        ]

        assert len(lots) == 1
        lot = lots[0]
        assert lot.current_amount == 1
        assert lot.price_usd == 0
        assert "zero_price" in [
            f.name for f in lot.flags
        ], f"No zero_price in lot {lot}"


class TestCostbasisDeposit:
    def test_get_change_back_from_deposit_same_token_in_change(self, test_db):
        make.tx(ins=["50 AVAX"], timestamp=1, from_address="A Friend")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        make.tx(
            ins=["1 AVAX", "10 mooAVAX|0xMoo"],
            outs=["10 AVAX"],
            timestamp=2,
            debank_name="depositBNB",
            from_address="Beefy",
        )
        price_feed.stub_price(2, "avalanche-2", 1.00)

        common(test_db)

        # Should have 1 lot for AVAX only because the change is in same token
        lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        assert (
            len(lots) == 1
        )  # 1 original disposal lot, and we ignore the change because it's still 'in' the original lot
        avax_lot = lots[0]
        assert avax_lot.current_amount == 50
        assert avax_lot.receipt == 0

        # I should have 10 mooAVAX, and it should have been exchanged for only 9 AVAX (sent 10, but got 1 back as change)
        lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xMoo"
        ]
        receipt_lot = lots[0]
        assert len(lots) == 1
        assert receipt_lot.current_amount == approx(Decimal(10))
        assert receipt_lot.history[0].amount == approx(Decimal(9))

    def test_get_change_back_from_deposit_wrapped_token_in_change(self, test_db):
        make.tx(ins=["50 AVAX"], timestamp=1, from_address="A Friend")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # We need to use the actual WAVAX token contract since this is how our code will match for wrapped tokens
        make.tx(
            ins=[
                "1 WAVAX|0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7",
                "10 mooAVAX|0xMoo",
            ],
            outs=["10 AVAX"],
            debank_name="deposit",
            timestamp=2,
            from_address="Beefy",
        )
        price_feed.stub_price(2, "avalanche-2", 1.00)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "avax"
        ]
        print(avax_lots)
        assert len(avax_lots) == 1  # AVAX original lot
        assert avax_lots[0].current_amount == 50  # Our original amount
        wavax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7"
        ]
        assert len(wavax_lots) == 1  # WAVAX change lot
        assert (
            wavax_lots[0].receipt == 1
        )  # This is not a disposal because it's a wrapped version of the original input
        assert wavax_lots[0].current_amount == 1  # Our change amount

        # I should have 10 mooAVAX, and it should have been exchanged for only 9 AVAX (sent 10, but got 1 WAVAX back as change)
        lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xMoo"
        ]
        receipt_lot = lots[0]
        assert len(lots) == 1
        assert receipt_lot.current_amount == approx(Decimal(10))
        assert receipt_lot.history[0].amount == approx(Decimal(9))

    def test_does_not_dispose_for_deposits(self, test_db):
        # 5 AVAX in @ 1.00 - makes an initial lot w/ amount 5 for AVAX
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # 1 AVAX deposited
        make.tx(
            outs=["1 AVAX"],
            ins=["5 mysteryTOK|0xWhoKnows"],
            debank_name="deposit",
            fee=0.00,
            timestamp=2,
            to_address="Mystery",
        )
        price_feed.stub_price(2, "avalanche-2", 10.00)

        common(test_db)

        # Should only have 1 AVAX lot since the mysteryTOK asset in T2 doesn't map to AVAX
        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        assert len(avax_lots) == 1

        # The mysteryTOK lot should not be treated as a disposal
        other_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xWhoKnows"
        ]
        other_lot = other_lots[0]
        assert other_lot.timestamp == 2
        assert other_lot.original_amount == 5
        assert other_lot.receipt == True
        assert other_lot.asset_price_id == None  # Since assert_price_id is none....
        assert (
            other_lot.price_usd == 2.00
        )  # The price_usd should be derived from the (total out * amount per out) / total amount in

        # And, there should be no disposal records created
        avax_disposals = get_disposals(test_db, "avax", 2)
        assert len(avax_disposals) == 0


class TestCostbasisWithdraw:
    def test_deposit_and_withdrawal_earns_interest(self, test_db):
        # Initial Receive so we have a non-zero costbasis_lot of AVAX
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # Deposit 1 AVAX and get 0.9 avWAVAX (deposit receipt)
        # value of AVAX has gone from $1 -> $5
        make.tx(
            outs=["1 AVAX"],
            ins=["0.9 avWAVAX|0xavWAVAX"],
            debank_name="depositBNB",
            fee=0.00,
            timestamp=2,
            to_address="Aave",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)

        # Withdraw 0.9 (all deposited) avWAVAX and receive 1.1 AVAX (+0.1 more than deposited; eg from interest)
        # value of AVAX has gone from $5 (at time of deposit) -> $6 (at time of withdrawal)
        make.tx(
            outs=["0.9 avWAVAX|0xavWAVAX"],
            ins=["1.1 AVAX"],
            debank_name="withdrawBNB",
            fee=0.00,
            timestamp=3,
            to_address="Aave",
        )
        price_feed.stub_price(3, "avalanche-2", 6.00)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        avWAVAX_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xavWAVAX"
        ]

        # Should have the original plus a new AVAX lot 0.1 amount @ price 6.00 due to the interest we earned (the extra AVAX back in during withdrawl)
        assert len(avax_lots) == 2

        # We should have a costbasis_income record in the DB for the additional 0.1 AVAX we earned
        # The net_usd earned is priced at the AVAX price at time of withdrawal ($6/AVAX) * 0.1 AVAX = $0.60 net_usd
        incomes = get_costbasis_incomes(test_db, entity_name, address)
        assert len(incomes) == 1
        income = incomes[0]
        assert income.amount == approx(Decimal(0.1))
        assert income.symbol == "AVAX"
        assert income.net_usd == approx(
            Decimal(0.60)
        )  # AVAX @ 6.00 * .1 new AVAX = 0.6

        # Our original lot for AVAX should remain untouched
        original_lot = avax_lots[0]
        assert (
            original_lot.current_amount == original_lot.original_amount
        )  # this should be the same as before

        # We should now have a new CostbasisLot for our new AVAX we earned as interest since it has a different cost basis ($6 / AVAX)
        new_lot = avax_lots[1]
        assert new_lot.current_amount == approx(
            Decimal(0.1)
        ), "Newly created lot for income from the withdrawal should be .01"
        assert new_lot.price_usd == 6.00

        # The avWAVAX lot should have been zeroed out e.g. no more current_amount left
        avWAVAX_lot = avWAVAX_lots[0]
        assert avWAVAX_lot.current_amount == approx(
            Decimal(0.0)
        ), "avWAVAX lot should be unwound - current_amount in lot should be 0.0"


class TestCostbasisBorrow:
    def test_borrow(self, test_db):
        # Borrow 1 AVAX and get 1.25 variableDebtWAVAX
        # value of AVAX at $5
        make.tx(
            ins=["1 AVAX", "1.25 variableDebtWAVAX|0xvariableDebtWAVAX"],
            debank_name="borrow",
            fee=0.00,
            timestamp=2,
            from_address="Aave",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)

        common(test_db)

        # We should have borrowed 1 AVAX
        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        avax_lot = avax_lots[0]
        assert avax_lot.current_amount == approx(Decimal(1))
        assert avax_lot.price_usd == approx(Decimal(5))
        assert avax_lot.basis_usd == approx(Decimal(5))

        # We should have 1.25 variableDebWAVAX receipt...
        receipt_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xvariableDebtWAVAX"
        ]
        receipt_lot = receipt_lots[0]
        pprint(receipt_lot)
        assert receipt_lot.receipt == True
        assert receipt_lot.current_amount == approx(Decimal(1.25))
        assert len(receipt_lot.history) == 1
        assert receipt_lot.current_amount == approx(Decimal(1.25))

        assert receipt_lot.history[0].amount == approx(Decimal(1))
        assert receipt_lot.history[0].amount == approx(Decimal(1))


class TestCostbasisRepay:
    def test_borrow_and_repay_loan_w_interest(self, test_db):
        # Initial Receive so we have a non-zero costbasis_lot of AVAX
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # Borrow 1 AVAX and get 1.2 variableDebtWAVAX
        # value of AVAX at $5
        make.tx(
            ins=["1 AVAX", "1.2 variableDebtWAVAX|0xvariableDebtWAVAX"],
            debank_name="borrow",
            fee=0.00,
            timestamp=2,
            from_address="Aave",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)

        # Repay 1.1 AVAX (OUT) and 1.2 variableDebtWAVAX ()
        # This costs us 0.1 AVAX more than we originally borrowed (eg from interest paid)
        # value of AVAX has gone from $5 (at time of deposit) -> $6 (at time of repayment)
        make.tx(
            outs=["1.1 AVAX", "1.2 variableDebtWAVAX|0xvariableDebtWAVAX"],
            debank_name="repay",
            fee=0.00,
            timestamp=3,
            to_address="Aave",
        )
        price_feed.stub_price(3, "avalanche-2", 6.00)

        common(test_db)

        # Check to make sure lots were generated with appropriate attrs
        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        pprint(avax_lots)

        # We expect for there to be a first lot that is 3.9 (when the loan is repaid, subtract 1.1 from the lowest cost basis)
        # and our 1 AVAX that came in from our loan (cost basis 5.0)
        assert len(avax_lots) == 2
        assert avax_lots[0].current_amount == approx(Decimal(Decimal(3.9)))
        assert avax_lots[1].current_amount == approx(Decimal(Decimal(1)))

        # We expect the second (borrowed AVAX) to have the history to the loan receipt
        assert len(avax_lots[1].history) == 1
        assert avax_lots[1].history[0].asset_tx_id == "0xvariableDebtWAVAX"


class TestCostbasisWrap:
    def test_wrapped_balance_is_correct(self, test_db):
        WAVAX = "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7"

        """
        Instead of treating a wrapped token as a deposit receipt, we simply match any wrapped tokens to the unwrapped equivalent.
        We therefore want to just leave our original token alone when we are wrapping or unwrapping
        """

        # Receive
        make.tx(ins=["1 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # Wrap
        make.tx(
            ins=[f"1 WAVAX|{WAVAX}"], outs=["1 AVAX"], timestamp=2, to_address=WAVAX
        )
        price_feed.stub_price(2, "avalanche-2", 1.00)

        # # Unwrap
        # make.tx(ins=['1 AVAX'], outs=[f'1 WAVAX|{WAVAX}'], timestamp=3, from_address=WAVAX)
        # price_feed.stub_price(3, 'avalanche-2', 1.00)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "avax"
        ]
        wavax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == WAVAX
        ]
        assert (
            len(avax_lots) == 1
        )  # 1 original, 1 from the WAVAX which inherits the same asset price

        # We shouldn't have any wrapped asset lots
        assert len(wavax_lots) == 0

        assert avax_lots[0].current_amount == 1

        # Check to make sure no CostbasisDisposal was generated since this was a wrap (and we will assume wraps are not disposals)
        disposals = get_disposals(test_db, "AVAX", 2)
        assert len(disposals) == 0

    def test_dispose_of_wrapped_asset(self, test_db):
        WAVAX = "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7"

        """
        Disposing a wrapped asset should drawdown from its unwraped equivalent and create a disposal.
        This should happen automatically becaue we map wrapped asset_tx_ids to an unwrapped version.
        """

        # Receive
        make.tx(ins=["1 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # Wrap
        make.tx(
            ins=[f"1 WAVAX|{WAVAX}"], outs=["1 AVAX"], timestamp=2, to_address=WAVAX
        )
        price_feed.stub_price(2, "avalanche-2", 1.00)

        # Dispose as a swap
        make.tx(
            ins=["2 USDC"], outs=[f"1 WAVAX|{WAVAX}"], timestamp=3, to_address="Uniswap"
        )
        price_feed.stub_price(3, "avalanche-2", 2.00)
        price_feed.stub_price(3, "usd-coin", 1.00)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "avax"
        ]
        wavax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == WAVAX
        ]

        # Check to make sure no CostbasisDisposal was generated when we wrap (and we will assume wraps are not disposals)
        avax_disposals = get_disposals(test_db, "AVAX", 2)
        assert len(avax_disposals) == 0

        # We don't create a lot for a wrapped asset
        assert len(wavax_lots) == 0

        # We should have consumed 1 WAVAX from our original 1 AVAX lot
        assert len(avax_lots) == 1
        assert avax_lots[0].current_amount == approx(Decimal(0))
        assert (
            avax_lots[0].timestamp == 1
        )  # sanity check we're looking at our original deposit...

        # And created an AVAX disposal at timestamp=3
        avax_disposals = get_disposals(test_db, "AVAX", 3)
        assert len(avax_disposals) == 1
        assert avax_disposals[0].amount == approx(Decimal(1.0))
        assert avax_disposals[0].basis_usd == approx(Decimal(1.0))  # price when bought
        assert avax_disposals[0].total_usd == approx(
            Decimal(2.0)
        )  # price when disposed of

        # and no wavax disposal...
        wavax_disposals = get_disposals(test_db, WAVAX, 3)
        assert len(wavax_disposals) == 0


class TestCostbasisLP:
    def test_lp_exit_handles_with_IL(self, test_db):
        make.tx(ins=["2 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 100.00)

        make.tx(ins=["200 DAI"], timestamp=2, from_address="A FRIEND")
        price_feed.stub_price(2, "dai", 1.00)

        # LP Entry (AVAX trades at 1:100 to DAI) (assume we end up with 10% of the pool)
        # Assume we got 10% of the pool. Pool starts with 10 AVAX and 1,000 DAI in the pool.
        make.tx(
            outs=["1 AVAX", "100 DAI"],
            ins=["10 JLP|0xJoeLiquidity"],
            debank_name="addLiquidity",
            fee=0.00,
            timestamp=3,
            to_address="Some DEX",
        )
        price_feed.stub_price(3, "avalanche-2", 100.00)
        price_feed.stub_price(3, "dai", 1.00)

        # LP Exit (price of AVAX has gone 4x against DAI)
        # There is now 5 AVAX and 2,000 DAI in the pool.
        # We get back our 10% but due to IL, we get back .5 AVAX and 200 DAI
        make.tx(
            outs=["10 JLP|0xJoeLiquidity"],
            ins=["0.5 AVAX", "200 DAI"],
            debank_name="removeLiquidity",
            fee=0.00,
            timestamp=3,
            to_address="Some DEX",
        )
        price_feed.stub_price(3, "avalanche-2", 400.00)
        price_feed.stub_price(3, "dai", 1.00)

        common(test_db)

        # Check to make sure lots were generated with appropriate attrs
        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        dai_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "dai"
        ]
        jlp_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xJoeLiquidity"
        ]

        assert len(avax_lots) == 2  # 1 original price of 100, 1 at new price 400
        assert (
            len(dai_lots) == 2
        )  # 1 original price from first IN, 1 same price from LP exit IN
        assert len(jlp_lots) == 1  # 1 lot from back when we held the LP receipt

        avax_lot_orig = avax_lots[0]
        avax_lot_exit = avax_lots[1]
        dai_lot_orig = dai_lots[0]
        dai_lot_exit = dai_lots[1]
        jlp_lot = jlp_lots[0]
        assert avax_lot_orig.current_amount == approx(Decimal(1))
        assert avax_lot_exit.current_amount == approx(Decimal(0.5))
        assert dai_lot_orig.current_amount == approx(Decimal(100))
        assert dai_lot_exit.current_amount == approx(Decimal(200))
        assert jlp_lot.current_amount == 0  # fully exited
        assert avax_lot_exit.price_usd == approx(Decimal(400.0))
        assert dai_lot_exit.price_usd == approx(Decimal(1.00))

    # This test actually models a failure seen in the wild
    def test_borrow_and_lp(self, test_db):
        # Borrow 1 AVAX and get 1.2 variableDebtWAVAX
        # value of AVAX at $5
        make.tx(
            ins=["1 AVAX", "1.2 variableDebtWAVAX|0xvariableDebtWAVAX"],
            debank_name="borrow",
            fee=0.00,
            timestamp=2,
            from_address="Aave",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)

        # Enter an LP
        make.tx(
            ins=["1 LP|0xLP"],
            outs=["1 AVAX"],
            debank_name="provideLiquidity",
            fee=0.00,
            timestamp=3,
            to_address="Curve",
        )
        price_feed.stub_price(3, "avalanche-2", 6.00)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        receipt_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xLP"
        ]

        # Should have the original avax lot (with 0.1 AVAX less in it)
        assert len(avax_lots) == 1
        assert avax_lots[0].current_amount == approx(Decimal(0))
        assert avax_lots[0].price_usd == approx(Decimal(5))
        assert len(receipt_lots) == 1
        assert receipt_lots[0].current_amount == approx(Decimal(1))


class TestCostbasisSwap:
    def test_swap_is_disposal(self, test_db):
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        make.tx(
            outs=["1 AVAX"],
            ins=["10 JOE"],
            debank_name="swapExactTokensForETH",
            fee=0.00,
            timestamp=2,
            to_address="Some DEX",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)
        price_feed.stub_price(2, "joe", 0.50)

        common(test_db)

        # Check to make sure a CostbasisLot was generated with appropriate attrs
        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        joe_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "joe"
        ]

        assert len(avax_lots) == 1
        assert len(joe_lots) == 1

        lot = avax_lots[0]
        assert lot.price_usd == 1.00  # Price is 1.00, which is what we acquired AVAX at
        assert lot.original_amount == 5
        assert lot.current_amount == 4

        # Check to make sure a CostbasisDisposal was generated with appropriate attrs
        disposals = get_disposals(test_db, "AVAX", 2)
        assert len(disposals) == 1
        disposal = disposals[0]
        assert disposal.amount == 1
        assert disposal.timestamp == 2
        assert disposal.duration_held == 1
        assert disposal.total_usd - disposal.basis_usd == 4.00

    # this models https://etherscan.io/tx/0xf26c80e98a08d97c7eee6b63ee359b57adbee607738ae751347862063f08f594
    def test_swap_with_asset_price_known_in_and_unknown_out(self, test_db):
        make.tx(ins=["1.2 USDf|0xUSDf"], timestamp=1, from_address="A FRIEND")
        # no price known for this

        make.tx(
            outs=["1.2 USDf|0xUSDf"],
            ins=["1 USDC"],
            debank_name="swapExactTokensForTokens",
            fee=0.00,
            timestamp=2,
            to_address="Some DEX",
        )
        price_feed.stub_price(2, "usd-coin", 1.00)

        common(test_db)

        # Check to make sure a CostbasisLot was generated with appropriate attrs
        usdf_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xUSDf"
        ]
        usdc_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "usd-coin"
        ]

        assert len(usdf_lots) == 1
        assert len(usdc_lots) == 1

        lot = usdc_lots[0]
        assert lot.price_usd == Decimal(1.00)
        assert lot.original_amount == 1
        assert lot.current_amount == 1

        lot = usdf_lots[0]
        # assert lot.price_usd == Decimal(1.00) # don't know
        assert lot.original_amount == approx(Decimal(1.2))
        assert lot.current_amount == approx(0)

        # Check to make sure a CostbasisDisposal was generated with appropriate attrs
        disposals = get_disposals(test_db, "USDf", 2)
        assert len(disposals) == 1
        disposal = disposals[0]
        assert disposal.amount == approx(Decimal(1.2))
        assert disposal.timestamp == 2
        assert disposal.duration_held == 1
        assert disposal.total_usd == approx(Decimal(1.0))
        assert disposal.basis_usd == Decimal(0.0)


class TODO:
    def pending_test_send_to_address_not_belonging_to_entity_flags_it_for_review(
        self, test_db
    ):
        # TODO also add flags to TxLogical, flag the logical that has somethign that looks like an unknown send, then update this test to discover that, not in the costbasis tests but in a new test for the logicial grouping code
        make.tx(ins=["5 AVAX"], timestamp=1, from_address="A FRIEND")
        make.tx(outs=["1 AVAX"], timestamp=2, to_address="SOMEONE NOT US")
        price_feed.stub_price(2, "avalanche-2", 1.00)

        common(test_db)

        lots = [l for l in get_costbasis_lots(test_db, entity_name, address)]
        assert len(lots) == 1
        lot = lots[0]
        flag_names = [f["name"] for f in lot.flags]
        assert "unknown_send" in flag_names

    # This shouldn't happen
    def pending_test_costbasis_changing_ownership_overdraw_of_deposit_receipt(
        self, test_db
    ):
        # Initial Receive so we have a non-zero costbasis_lot of AVAX
        make.tx(ins=["1 AVAX"], timestamp=1, from_address="A FRIEND")
        price_feed.stub_price(1, "avalanche-2", 1.00)

        # Deposit 1 AVAX and get 0.9 avWAVAX (deposit receipt)
        # value of AVAX has gone from $1 -> $5
        make.tx(
            outs=["1 AVAX"],
            ins=["0.5 avWAVAX|0xavWAVAX"],
            debank_name="depositBNB",
            fee=0.00,
            timestamp=2,
            to_address="Aave",
        )
        price_feed.stub_price(2, "avalanche-2", 5.00)

        # This is a send, but not a disposal
        make.tx(
            outs=["1 avWAVAX|0xavWAVAX"],
            debank_name="send",
            fee=0.00,
            timestamp=3,
            to_address="A FRIEND",
        )
        price_feed.stub_price(3, "avalanche-2", 6.00)

        common(test_db)

        avax_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_price_id == "avalanche-2"
        ]
        avax_disposals = get_disposals(test_db, "AVAX", 3)
        avWAVAX_lots = [
            l
            for l in get_costbasis_lots(test_db, entity_name, address)
            if l.asset_tx_id == "0xavWAVAX"
        ]
        avWAVAX_disposals = get_disposals(test_db, "0xavWAVAX", 3)

        # pprint(avax_lots)
        # print('---')
        # pprint(avWAVAX_lots)

        # We should only have 4.5 AVAX left (subtracted by unwinding and multiplying by amount of receipt subtracted from original ratio)
        # 1 AVAX -> 0.5 avWAVAX; -0.25 avWAVAX -> -0.5 AVAX
        assert len(avax_lots) == 1
        avax_lot = avax_lots[0]
        assert avax_lot.current_amount == approx(Decimal(0))

        assert len(avWAVAX_lots) == 2
        assert avWAVAX_lots[0].current_amount == approx(Decimal(0))
        assert avWAVAX_lots[0].original_amount == approx(Decimal(0.5))
        assert avWAVAX_lots[0].receipt == True
        assert len(avWAVAX_lots[0].history) == 1
        assert avWAVAX_lots[0].history[0].amount == approx(Decimal(1))

        # This is the generated avWAVAX because we overdrew how much we had
        assert avWAVAX_lots[1].current_amount == approx(Decimal(0))
        assert avWAVAX_lots[1].original_amount == approx(Decimal(0.5))
        assert avWAVAX_lots[1].receipt == True
        assert len(avWAVAX_lots[1].history) == 0

        # We shouldn't have an AVAX disposal
        assert len(avax_disposals) == 0

        # We also shouldn't have any avWAVAX disposals because a "send" is only a change in ownership, not a disposal
        assert len(avWAVAX_disposals) == 0

    # This shouldn't happen
    def pending_test_costbasis_changing_ownership_overdraw_of_nonexistant_deposit_receipt(
        test_db,
    ):
        # Initial Receive so we have a non-zero costbasis_lot of AVAX
        make.tx(ins=["1 AVAX"], timestamp=1, from_address="A FRIEND")
