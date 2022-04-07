import argparse
import logging
import sys
import time


from perfi.db import db
from perfi.events import EventStore
from perfi.models import TxLedger, TxLogical
from perfi.transaction.chain_to_ledger import update_entity_transactions
from perfi.transaction.ledger_to_logical import TransactionLogicalGrouper


logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)

messages = []


def main():
    ### Chain to Ledger
    if sys.stdout.isatty():
        logger.setLevel(logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument("entity", help="name of entity")
    parser.add_argument(
        "--skip", action="store_true", help="DEBUG: skips regenerating tx_logical"
    )
    parser.add_argument(
        "--refresh-type",
        action="store_true",
        help="DEBUG: Just regenerates tx_logical_type",
    )
    args = parser.parse_args()

    update_entity_transactions(args.entity)

    if len(messages) == 0:
        logger.debug(
            "\n\nNo important messages to display after generating LedgerTxs. Great!"
        )
    else:
        logger.debug("\n\n")
        logger.debug("-----------------------------------------------")
        logger.debug("Important Messages after generating LedgerTxs.")
        logger.debug("-----------------------------------------------")
        for message in messages:
            logger.debug(message)
        logger.debug("-----------------------------------------------")

    ### Ledger to Logical

    # Clear all the non-manual events from the DB.
    # perfi will make some source='perfi' move events below, then it will apply them, then we will apply other manual events
    sql = "DELETE FROM event WHERE source != 'manual'"
    db.execute(sql)

    if args.refresh_type:
        # Later: if it's too slow we should implement only refreshing types
        # tlg = TransactionLogicalGrouper(entity, print=True)
        # for tl in tlg:
        #    tl.refresh_type()
        # sys.exit()
        pass

    tlg = TransactionLogicalGrouper(
        args.entity, EventStore(db, TxLogical, TxLedger), print=True
    )
    tlg.update_entity_transactions(args.skip)

    # re-apply any manual events
    event_store = EventStore(db, TxLogical, TxLedger)
    event_store.apply_events(source="manual")


if __name__ == "__main__":
    main()
