import json
from perfi.cache import cache
from perfi.db import db
from perfi.settings import setting
from pprint import pprint
import sys
from tqdm import tqdm
from perfi.balance.updating import update_entity_balances


def main():
    if len(sys.argv) == 2:
        entity = sys.argv[-1]
    else:
        entity = 'peepo'
    update_entity_balances(entity)


if __name__ == "__main__":
    main()
