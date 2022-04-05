import logging
import sys
from perfi.constants.paths import LOG_DIR
from perfi.ingest.chain import scrape_entity_transactions

REFRESH_DETAILS = False
REFRESH_INDEXES = False
if sys.argv[-1] == "refresh":
    REFRESH_DETAILS = True
    REFRESH_INDEXES = True

### Control DEBUG output/flow

logger = logging.getLogger(__name__)
DEBUG = True
if sys.stdout.isatty():
    DEBUG = True
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s : %(levelname)-8s : %(message)s")
    logger.addHandler(console)
DEBUG = False


def main():
    if len(sys.argv) == 2:
        entity = sys.argv[-1]
    else:
        entity = "peepo"

    logging.basicConfig(
        level=logging.WARN,
        format="%(asctime)s : %(levelname)-8s : %(message)s",
        filename=f"{LOG_DIR}/ingest_chain_txs-{entity}.log",
    )

    scrape_entity_transactions(entity)


if __name__ == "__main__":
    main()
