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


def close_year(entity_name: str, year: int = None, output_path: str = None):
    entity = entity_name
    logging.basicConfig(
        level=logging.WARN,
        format="%(asctime)s : %(levelname)-8s : %(message)s",
        filename=f"{LOG_DIR}/costbasis.close_year.{entity}-{year}.log",
    )

    f = costbasis.CostbasisYearCloser(entity, year, output_path)
    f.lock_costbasis_lots()
    f.export_closing_values()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("entity", help="name of entity")
    parser.add_argument(
        "--year", help="Locks and exports the cost basis lots for a specific year"
    )
    parser.add_argument(
        "--output", help="Path for closed cost basis values export file"
    )
    global args
    args = parser.parse_args()
    close_year(args.entity, args.year, args.output)


if __name__ == "__main__":
    main()
