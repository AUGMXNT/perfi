import argparse
import colorama
from colorama import Fore
from colorama import Style
from decimal import *
import delegator
import json

from devtools import debug

from perfi.cache import cache
from perfi.db import db
from perfi.balance.updating import update_entity_balances
from perfi.models import AddressStore
from perfi.settings import setting
from pprint import pprint
import subprocess
import sys
import tabulate
import time
import numpy as np
import scipy.optimize as opt

"""
poetry run python farm-helper.py | less -r
hacky paging: https://stackoverflow.com/questions/6728661/paging-output-from-python
https://github.com/prompt-toolkit/pypager
* would work but requires yielding all output also in an array? a bit weird
* maybe handles ANSI maybe not?
"""


# Optimal compounding w/ fees solver
# via [https://math.stackexchange.com/questions/3966206/how-often-should-i-compound-my-algorand-or-other-proof-of-stake-crypto-assets](https://math.stackexchange.com/questions/3966206/how-often-should-i-compound-my-algorand-or-other-proof-of-stake-crypto-assets)
"""
apy should be in decimal form. e.g. .4 = 40% APY
"""
def get_optimal_days_between_compound_events(principal, apy, fee):
    # Compound interest formula with fees
    def simulateCompoundYear(principal, claimingEvents, apy, fee):
        firstTerm = principal-fee/apy*claimingEvents
        secondTerm = (1+apy/claimingEvents)**claimingEvents
        thirdTerm = fee/apy*claimingEvents
        result = firstTerm*secondTerm+thirdTerm
        return result

    minimumDeltaT=fee/(principal*apy/365)

    # Calculate for 3rd party compounding
    minimumDeltaT=fee/(306024.53*0.24/365)
    maximumClaimingEvents = 365/minimumDeltaT

    # Solve for the maximum
    neg_simulateYear = lambda claimingEvents: -1 * simulateCompoundYear(principal, claimingEvents, apy, fee)
    bounded_o = opt.minimize_scalar(neg_simulateYear,bounds=[0.1,maximumClaimingEvents],method="bounded")
    ideal_reinvests_per_year = bounded_o.x
    ideal_number_of_days_between_reinvests = 365/bounded_o.x
    return ideal_number_of_days_between_reinvests


# Minimum to claim
DEFAULT_MIN = 100
chain_min = {
    "arb": 500,
    "avax": 500,
    "eth": 4000,
    "ftm": 500,
    "matic": 100,
    "op": 500,
}

# Gas prices per chain
gas_price_urls = {
    "eth": "https://api.etherscan.io/api?module=gastracker&action=gasoracle" # [1]
}

tabulate.PRESERVE_WHITESPACE = True

address_store = AddressStore(db)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Forces a refresh, otherwise, only does it if data is > 60min old",
    )
    parser.add_argument(
        "--entity",
    )
    args = parser.parse_args()

    rewards = get_claimable(args.entity, args.refresh)
    print_claimable(rewards)


def refresh_balance_if_needed(entity_name, force_refresh):
    address_recs = address_store.find_all_by_entity_name(entity_name, "ethereum")
    addresses_str = [f"'{a.address}'" for a in address_recs]  # format a list of addresses enclosed in single quotes for the db query below

    # find the oldest record among this entity's addresses
    sql = f"""SELECT updated 
           FROM balance_current 
           WHERE address in ({','.join(addresses_str)})
           ORDER BY updated DESC 
           LIMIT 1
        """
    r = db.query(sql)
    try:
        delta = time.time() - int(r[0][0])
    except:
        # Force refresh
        delta = 999999999

    # Old!
    if delta > 3600 or force_refresh:
        print(f"Balances for {entity_name} is {int(delta/60)} minutes old. UPDATING...")
        update_entity_balances(entity_name)
    else:
        print(f"Using existing balances for {entity_name}. Oldest record is ({int(delta/60)} minutes old)")


def get_claimable(entity_name, force_refresh=False):
    refresh_balance_if_needed(entity_name, force_refresh)
    return _get_rewards(entity_name)


def _get_rewards(entity_name):
    sql = """SELECT address.label, balance_current.address, balance_current.chain, balance_current.protocol, balance_current.symbol, balance_current.usd_value, balance_current.label, balance_current.extra
             FROM balance_current, address, entity
             WHERE address.entity_id = entity.id
             AND balance_current.address = address.address
             AND entity.name = ?
             AND balance_current.type = 'reward'
             AND usd_value > 1
             ORDER BY address.ord, balance_current.chain, protocol, usd_value
          """
    results = db.query(sql, entity_name)

    ### Missing Info
    ### We need to Store/get the farm contract info (or at least the index) for multiple claims
    """
  pool_id
  pool.id
  pool.description
  pool.cost
  pool.gas
  pool.apr
  ACCOUNT:
    CHAIN:
      PROTOCOL:
        POOLS
  """

    address = ""
    chain = ""
    protocol = ""

    # Let's turn this our SQL into a data structure we can more easily work with...
    rewards = {}
    for r in results:
        label, address, chain, protocol, symbol, usd_value, type, extra = r

        if not label in rewards:
            rewards[label] = {}

        rewards[label]["address"] = address

        if not "data" in rewards[label]:
            rewards[label]["data"] = {}
        if not chain in rewards[label]["data"]:
            rewards[label]["data"][chain] = {}

        if not protocol in rewards[label]["data"][chain]:
            rewards[label]["data"][chain][protocol] = {
                "reward_usd_value": Decimal(0.0),
                "rewards": [],
            }

        # Let's Set min
        min = chain_min.get(chain, DEFAULT_MIN)
        should_claim = usd_value > min
        rewards[label]["data"][chain][protocol]["should_claim"] = should_claim
        rewards[label]["data"][chain][protocol]["rewards"].append(
            {"type": type, "symbol": symbol, "usd_value": usd_value}
        )
        rewards[label]["data"][chain][protocol]["reward_usd_value"] += usd_value

        protocol_info = get_debank_protocol_details(protocol)
        rewards[label]["data"][chain][protocol]["site_url"] = protocol_info["site_url"]
        rewards[label]["data"][chain][protocol]["logo_url"] = protocol_info["logo_url"]

    return rewards


def get_debank_protocol_details(id):
    DEBANK_PROTOCOL_INFO_URL = f'https://openapi.debank.com/v1/protocol?&id={id}'
    c = cache.get(DEBANK_PROTOCOL_INFO_URL, refresh_if=3600)
    return json.loads(c['value'])



def print_claimable(rewards):
    # For each wallet...
    for label in rewards:
        print()
        print(
            f"{Style.RESET_ALL}{Fore.CYAN}{label} ({rewards[label]['address']}){Fore.RESET}"
        )

        # For each chain...
        for chain in rewards[label]["data"]:
            # Only print if the chain isn't empty...
            if rewards[label]["data"][chain]:
                print(f"{Fore.YELLOW}>>> {chain.upper()}{Fore.RESET}")

                # For each protocol...
                for protocol in rewards[label]["data"][chain]:
                    p = rewards[label]["data"][chain][protocol]

                    if not p["should_claim"]:
                        print(Style.DIM, end="")

                    # Let's make our text
                    reward_text = ""
                    for r in p["rewards"]:
                        reward_text += f"${r['usd_value']:11,.2f} {r['symbol']:8}\n"

                    row = []
                    row.append(f"{Fore.RED}{protocol:18}{Fore.RESET}")
                    # row.append(reward_text)
                    row.append(f"${p['reward_usd_value']:11,.2f}")
                    print(tabulate.tabulate([row], tablefmt="plain"))

                    if not p["should_claim"]:
                        print(Style.RESET_ALL, end="")


if __name__ == "__main__":
    main()
