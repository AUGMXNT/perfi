import argparse
import logging
import sys


from perfi.db import db
from perfi.ingest.exchange import (
    BitcoinTaxImporter,
    CoinbaseImporter,
    CoinbaseProImporter,
    GeminiImporter,
    KrakenImporter,
    CoinbaseTransactionHistoryImporter,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--entity_name",
        help="must match an existing entity name in the db. (e.g. peepo)",
        required=True,
    )
    parser.add_argument("--file", help="path to an exchange export file", required=True)
    parser.add_argument(
        "--exchange",
        help="bitcointax|coinbasepro|coinbase|kraken|gemini",
        required=True,
    )
    parser.add_argument(
        "--exchange_account_id",
        help='some sort of ID to associate with the records in FILE (e.g. "peepo_coinbase_1")',
        required=True,
    )

    args = parser.parse_args()

    if sys.stdout.isatty():
        logger.setLevel(logging.DEBUG)
        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        logger.addHandler(console)

    # Get the entity ID for entity_name
    sql = """SELECT id from entity where name = ?"""
    params = [args.entity_name]
    entity_id = None
    try:
        entity_id = int(db.query(sql, params)[0][0])
    except:
        raise Exception(f"Entity name {args.entity_name} not found in database!")

    do_import(entity_id, args.exchange, args.exchange_account_id, args.file)


def do_import(entity_id: int, exchange: str, exchange_account_id: str, file):
    # See if our entity_address we want to use exists yet. If not, create it.
    entity_address_for_imports = f"{exchange}.{exchange_account_id}"
    sql = """SELECT a.address from address a where a.address = ?"""
    params = [entity_address_for_imports]
    result = db.query(sql, params)
    if len(result) != 0:
        print(f"Address already seems to exist: {entity_address_for_imports}")
    else:
        sql = """
            INSERT INTO address
            (label, chain, address, type, source, entity_id, ord)
            VALUES
            (?, ?, ?, ?, ?, ?, ?)
        """
        params = [
            f"{exchange}",
            f"import.{exchange}",
            entity_address_for_imports,
            "account",
            "imported",
            int(entity_id),
            99,
        ]
        print(f"Creating new address: {params}")
        db.execute(sql, params)

    # Figure out which importer class to use
    importer_mapping = {
        "bitcointax": BitcoinTaxImporter,
        "coinbase": CoinbaseTransactionHistoryImporter,
        "coinbasepro": CoinbaseProImporter,
        "kraken": KrakenImporter,
        "gemini": GeminiImporter,
    }
    importer_class = importer_mapping[exchange]

    # Do the import
    logger.debug("Importing...")
    importer = importer_class()
    filemode = "rb" if exchange == "gemini" else "r"

    with open(file, filemode) as file:
        importer.do_import(
            file,
            entity_address_for_imports=entity_address_for_imports,
            exchange_account_id=exchange_account_id,
        )

    logger.debug("Done.")


if __name__ == "__main__":
    main()
