import argparse
import logging
from perfi import costbasis
from perfi.constants.paths import LOG_DIR
import sys

if sys.stdout.isatty():
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s : %(levelname)-8s : %(message)s")
    costbasis.logger.addHandler(console)

args = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("entity", help="name of entity", nargs=1)
    parser.add_argument("--year", help="Generates cost basis for a specific year")
    global args
    args = parser.parse_args()

    entity = args.entity
    logging.basicConfig(
        level=logging.WARN,
        format="%(asctime)s : %(levelname)-8s : %(message)s",
        filename=f"{LOG_DIR}/costbasis-{entity}.log",
    )

    costbasis.regenerate_costbasis_lots(entity, args=args)


if __name__ == "__main__":
    main()
