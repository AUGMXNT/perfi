import argparse
import logging
import sys

from perfi.constants.paths import LOG_DIR
from perfi.ingest.chain import scrape_entity_transactions

### Control DEBUG output/flow
logger = logging.getLogger(__name__)
if sys.stdout.isatty():
    DEBUG = True
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s : %(levelname)-8s : %(message)s")
    logger.addHandler(console)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("entity", help="name of entity")
    parser.add_argument(
        "--refresh",
        help="Force re-indexing vs pulling cached chain values",
        action="store_true",
    )
    args = parser.parse_args()

    entity = args.entity

    if args.refresh:
        REFRESH_DETAILS = True
        REFRESH_INDEXES = True
    else:
        REFRESH_DETAILS = False
        REFRESH_INDEXES = False

    logging.basicConfig(
        level=logging.WARN,
        format="%(asctime)s : %(levelname)-8s : %(message)s",
        filename=f"{LOG_DIR}/import_chain_txs-{entity}.log",
    )

    scrape_entity_transactions(entity)


if __name__ == "__main__":
    main()
