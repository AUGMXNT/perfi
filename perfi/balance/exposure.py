from collections import defaultdict, namedtuple
from decimal import *
from typing import List

import delegator
import json
import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pprint import pprint
import squarify
import sys
import tabulate
import time

import warnings

from devtools import debug

warnings.simplefilter(action='ignore', category=FutureWarning)

from perfi.cache import cache
from perfi.db import db
from perfi.settings import setting

from perfi.price import PriceFeed

from operator import itemgetter

# Globals
price_feed = PriceFeed()

price_urls_and_paths = {
    'SUSHI': ('https://min-api.cryptocompare.com/data/price?fsym=SUSHI&tsyms=USD', lambda j: j['USD']),
}

ExposureRecord = namedtuple('ExposureRecord', ['asset', 'amount', 'price', 'usd_value', 'percentage'])

def get_price_from_alt_source(symbol):
    url, extractor = price_urls_and_paths[symbol]
    return Decimal(extractor(get(url)))


def get_balance_data(chain, address):
    if chain == 'cosmos':
        return get_atom_balance(address), get_price('cosmos'), 'ATOM'

    # Fallback, raise exception
    raise Exception(f"Don't know how to get balance/price for chain {chain} yet.")


def get_price_by_symbol(symbol):
    sql = """ SELECT * FROM asset_price
              WHERE symbol = ?
              AND market_cap IS NOT NULL
              ORDER BY market_cap DESC
      """
    r = db.query(sql, symbol)
    if not r:
        raise Exception(f"Couldn't get price for symbol {symbol}")
    asset_price_id = r[0]["id"]
    coin_price = price_feed.get(asset_price_id, int(time.time()))
    return coin_price.price


def calculate(entity_name):
    # Get exposure for ethereum chain wallets from debank
    total_usd_value, exposure = itemgetter('total_usd_value', 'exposure')(get_exposure(entity_name))

    # Now look at all the non-ethereum chain wallets we can get balances and price for
    sql = '''SELECT address.label, address.chain, address.address
           FROM address, entity
           WHERE address.entity_id = entity.id
           AND entity.name = ?
           AND address.chain != 'ethereum'
           AND address.chain not like 'import.%'
           ORDER BY ord, label
        '''
    results = db.query(sql, entity_name)

    for wallet in results:
        label = wallet[0]
        chain = wallet[1]
        address = wallet[2]
        try:
            balance, price, symbol = get_balance_data(chain, address)
            if symbol in exposure:
                exposure[symbol]['amount'] += Decimal(balance)
            else:
                exposure[symbol] = {'amount': Decimal(balance)}
            exposure[symbol]['price'] = price
        except Exception as err:
            # Intentionally fail silently for wallet chains we can't handle yet
            print(f"{err}")
            pass

    # Finally, handle any manually managed balances
    sql = '''SELECT chain, symbol, exposure_symbol, amount, price
           FROM balance_current
           WHERE source = 'manual'
        '''
    results = db.query(sql)
    for r in results:
        exposure_symbol = r["exposure_symbol"]
        symbol = r["symbol"]
        amount = r["amount"]
        price = r["price"]

        if not price:
            try:
                price = get_price_by_symbol(symbol)
            except Exception as err:
                debug(err)
                continue

        # Only track this if we got a price for it somehow (manually or via symbol lookup)
        if price:
            if exposure_symbol in exposure:
                exposure[exposure_symbol]['amount'] += Decimal(amount)
            else:
                exposure[exposure_symbol] = {'amount': Decimal(amount)}
            exposure[exposure_symbol]['price'] = price

    ### Stables
    stables = [
        'agEUR',
        'am3CRV',
        'BUSD',
        'DAI',
        'FEI',
        'FRAX',
        'GHO',
        'GUSD',
        'LUSD',
        'MIM',
        'miMATIC',
        'mUSD',
        'RAI',
        'sUSD',
        'TUSD',
        'USDC',
        'USDD',
        'USDP',
        'USDN',
        'USDT',
        'VST',
    ]

    # Recalc Total Value
    total_usd_value = Decimal(0.0)
    for e in exposure:
        total_usd_value += Decimal(exposure[e]['amount']) * Decimal(exposure[e]['price'])

    # Print Total Stablecoin
    total_stables = Decimal(0.0)
    total_loans = Decimal(0.0)
    assets: List[ExposureRecord] = []
    loans: List[ExposureRecord] = []
    for e in sorted(exposure, key=lambda e: Decimal(exposure[e]['amount']) * Decimal(exposure[e]['price']),
                    reverse=True):
        amount = exposure[e]['amount']
        price = exposure[e]['price']
        usd_value = Decimal(amount) * Decimal(price)
        percent = 100 * Decimal(usd_value) / total_usd_value

        if e in stables:
            total_stables += Decimal(amount)

        # Formatted
        # f_usd_value = f'${usd_value:14,.2f}'
        # f_amount = f'{amount:12,.2f}'
        # f_price = f'${price:10,.2f}'
        # f_percent = f'{percent:5.2f}%'

        cutoff = 10  # Ignore values less than cutoff
        if usd_value >= cutoff:
            # TODO: format $USD and percentage
            assets.append(ExposureRecord(e, amount, price, usd_value, percent))

        # Loans
        if percent < 0:
            total_loans += Decimal(usd_value)
            f_percent = f'{-1 * percent:5.2f}%'
            loans.append(ExposureRecord(e, amount, price, usd_value, percent))

    return {
        "total_usd_value": total_usd_value,
        "total_stables": total_stables,
        "total_loans": total_loans,
        "assets": assets,
        "loans": loans,
    }


def formatted(record: ExposureRecord):
    record = record._asdict()
    return (
        f"""${record['usd_value']:14,.2f}""",
        f"""${record['amount']:12,.2f}""",
        f"""${record['price']:10,.2f}""",
        f"""${record['percent']:5.2f}%""",
    )


def main():
    entity_name = 'peepo'
    results = calculate(entity_name)
    print(f'Total Value:   ${results["total_usd_value"]:14,.2f}')
    print(f'Total Stables: ${results["total_stables"]:14,.2f}')
    print(f'Total Loans:   ${results["total_loans"]:14,.2f}')
    print()

    tabulate.PRESERVE_WHITESPACE = True
    print('> ASSETS')
    formatted_assets = [formatted(a) for a in results["assets"]]
    print(tabulate.tabulate(formatted_assets, headers=['Asset', 'Amount', 'Price', 'USD Value', '%']))

    print()

    # TODO Loans separate
    print('> LOANS')
    formatted_loans = [formatted(l) for l in results["loans"]]
    print(tabulate.tabulate(formatted_loans, headers=['Asset', 'Amount', 'Price', 'USD Value', '%']))

    make_graphs(results["assets"], results["loans"])


# Debank Data
def get_exposure(entity_name):
    total_usd_value = Decimal(0.0)
    exposure = defaultdict(lambda : dict(amount=Decimal(0), price=Decimal(0)))

    # Update from DB
    c = delegator.run(f"poetry run python balance-debank-updatedb.py {entity_name}")

    # Now let's get our exposure...
    sql = '''SELECT exposure_symbol, amount, price
             FROM balance_current, address, entity
             WHERE address.entity_id = entity.id
             AND balance_current.address = address.address
             AND entity.name = ?
             AND balance_current.source = 'debank'
             ORDER BY price ASC
          '''
    results = db.query(sql, entity_name)
    for a in results:
        amount = a["amount"]
        price = a["price"]
        price = 0 if price is None else price
        total_usd_value += amount * price
        exposure[a[0]]['amount'] += amount
        exposure[a[0]]['price'] = price

    # Manual asset tracking
    sql = '''SELECT exposure_symbol, amount, price
             FROM balance_current, address, entity
             WHERE address.entity_id = entity.id
             AND balance_current.address = address.address
             AND entity.name = ?
             AND balance_current.source = 'manual'
             ORDER BY price ASC
          '''
    results = db.query(sql, entity_name)
    for a in results:
        amount = a["amount"]
        price = a["price"]
        price = 0 if price is None else price
        total_usd_value += amount * price
        exposure[a[0]]['amount'] += amount
        exposure[a[0]]['price'] = price

    return dict(total_usd_value=total_usd_value, exposure=exposure)


# Old get class...
def get(URL):
    c = cache.get(URL, refresh_if=3600)
    return json.loads(c['value'])


def get_price(coingecko_id):
    now = int(time.time())
    return price_feed.get(coingecko_id, now)


def get_atom_balance(address):
    total = Decimal()

    BALANCE_URL = 'https://lcd-cosmos.cosmostation.io/cosmos/bank/v1beta1/balances/{}'.format(address)
    balance = Decimal()

    for b in get(BALANCE_URL)['balances']:
        balance += Decimal(b['amount']) / 1000000
        total += balance

    REWARDS_URL = 'https://lcd-cosmos.cosmostation.io/cosmos/distribution/v1beta1/delegators/{}/rewards'.format(address)
    rewards = Decimal(get(REWARDS_URL)['total'][0]['amount']) / 1000000
    total += rewards

    DELEGATED_URL = 'https://lcd-cosmos.cosmostation.io/cosmos/staking/v1beta1/delegations/{}'.format(address)
    delegated = Decimal()
    for d in get(DELEGATED_URL)['delegation_responses']:
        delegated += Decimal(d['balance']['amount']) / 1000000
        total += delegated

    return (total)


if __name__ == "__main__":
    main()
