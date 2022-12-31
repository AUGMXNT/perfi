import argparse
import logging

from devtools import debug

from perfi import costbasis
from perfi.constants.paths import LOG_DIR
import sys

if sys.stdout.isatty():
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s : %(levelname)-8s : %(message)s")
    costbasis.logger.addHandler(console)

args = None


def generate_file(entity_name: str, year: int = None, output_path: str = None):
    if year:
        year = int(year)
    entity = entity_name
    logging.basicConfig(
        level=logging.WARN,
        format="%(asctime)s : %(levelname)-8s : %(message)s",
        filename=f"{LOG_DIR}/costbasis.8949-{entity}.log",
    )

    f = costbasis.Form8949(entity, year, output_path)

    f.get_disposal()
    f.get_income()
    f.get_lots()
    f.link_lots()
    f.get_ledger()

    f.wb.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("entity", help="name of entity")
    parser.add_argument("--year", help="Generates cost basis for a specific year")
    parser.add_argument("--output", help="Output file (xslx) location")
    global args
    args = parser.parse_args()
    generate_file(args.entity, args.year, args.output)


if __name__ == "__main__":
    main()
