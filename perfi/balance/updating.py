from decimal import *
import json
from itertools import tee, filterfalse
from typing import Optional, List, Dict, Any, Iterable, Union

from devtools import debug

from perfi.cache import cache
from perfi.db import db
from perfi.settings import setting
from pprint import pprint
import sys
import time
import click
from perfi.ingest.chain import DeBankTransactionsFetcher


def partition(pred, iterable):
    "Use a predicate to partition entries into false entries and true entries"
    # partition(is_odd, range(10)) --> 0 2 4 6 8   and  1 3 5 7 9
    t1, t2 = tee(iterable)
    return filterfalse(pred, t1), filter(pred, t2)


@click.command
@click.option('--entity', default=None, help='Entity name - e.g. peepo')
@click.option('--timestamp', type=click.INT, default=None, help='Epoch timestamp in seconds. Imports historic balances at this time.')
def main(entity, timestamp):
    if len(sys.argv) == 2:
        update_entity_balances(sys.argv[-1], None)
    else:
        update_entity_balances(entity, timestamp)


# TODO:  We have address.chain = 'ethereum' hardcoded in places in this file. This will need to change when we get to other non-EVM chain handling...


def get_addresses(entity_name):
    sql = '''SELECT address.*
           FROM address, entity
           WHERE address.entity_id = entity.id
           AND entity.name = ?
           AND address.chain == 'ethereum'
           ORDER BY ord, label
        '''
    return db.query(sql, entity_name)



def update_entity_balances(entity_name, historic_timestamp: Optional[int] = None):
    print(f'Entity: {entity_name}')

    for address_rec in get_addresses(entity_name):
        address = address_rec["address"]
        update_wallet_balances(address, historic_timestamp)

    # TODO: move debank data fixups into lookup tables and set values at record insertion time instead of re-updating all every time
    debank_data_fixups()


def ingest_debank_token_list(address: str, debank_token_list: Union[List, Iterable], ingestion_timestamp: int, tables: List[str]):
    updated = ingestion_timestamp

    for token in list(debank_token_list):
        for table in tables:
            sql = f"""INSERT INTO {table}
                 (source, address, chain, symbol, exposure_symbol, protocol, price, amount, usd_value, updated, extra)
                 VALUES
                 (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
              """
            source = 'debank'
            protocol = 'wallet'
            usd_value = token['price'] * token['amount']
            extra = json.dumps(token)
            if(token['symbol'].strip() == ''):
                token['symbol'] = token['name'].replace(' ', '_')
            params = [source, address, token['chain'], token['symbol'], token['symbol'], protocol, token['price'],
                      token['amount'], usd_value, updated, extra]

            db.execute(sql, params)

        ###
        # TODO: we could update the 'price' table w/ debank price if we want...
        ###



def ingest_debank_complex_protocol_list(address: str, debank_protocol_list: List, ingestion_timestamp: int, tables: List[str]):
    '''
      common (staked, deposit)
        token_list
        reward_token_list
      locked
        unlock_at
      description (sSPELL)
      token_list
      supply_token_list
      borrow_token_list
      health_rate - aave, mai
      description - frax, lido
      debt_ratio - impermax
      unlock_at - mstable

    '''
    updated = ingestion_timestamp

    for protocol in debank_protocol_list:
        # print(f'    * {protocol["id"]}')

        # Lets look for for token lists...
        for portfolio_item in protocol['portfolio_item_list']:
            for detail in portfolio_item['detail'].keys():
                # These are token lists
                if detail in ['token_list', 'supply_token_list', 'borrow_token_list', 'reward_token_list']:
                    for token in portfolio_item['detail'][detail]:
                        for table in tables:
                            sql = f"""INSERT INTO {table}
                                     (source, address, chain, symbol, exposure_symbol, protocol, label, price, amount, usd_value, updated, type, locked, proxy, extra)
                                     VALUES
                                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                  """
                            # depends on type...
                            if detail == 'token_list':
                                type = 'deposit'
                            elif detail == 'supply_token_list':
                                type = 'deposit'
                            elif detail == 'borrow_token_list':
                                type = 'loan'
                                token['amount'] *= -1
                            elif detail == 'reward_token_list':
                                type = 'reward'

                            if portfolio_item['detail_types'][0] == 'reward':
                                type = 'reward'

                            if detail == 'supply_token_list' and portfolio_item['detail_types'][0] == 'common' and len(
                                    portfolio_item['detail'][detail]) > 1:
                                type = 'lp'

                            # print(f'      {detail}: {type}')

                            # parameters...
                            source = 'debank'
                            if 'description' in portfolio_item['detail']:
                                label = portfolio_item['detail']['description']
                            else:
                                label = type
                            usd_value = token['price'] * token['amount']
                            if 'unlock_at' in portfolio_item['detail']:
                                locked = portfolio_item['detail']['unlock_at']
                            else:
                                locked = None
                            if 'proxy_detail' in portfolio_item and portfolio_item['proxy_detail']:
                                proxy = json.dumps(portfolio_item['proxy_detail'])
                            else:
                                proxy = None
                            extra = json.dumps(portfolio_item)

                            params = [source, address, token['chain'], token['optimized_symbol'],
                                      token['optimized_symbol'],
                                      protocol['id'], label, token['price'], token['amount'], usd_value, updated, type,
                                      locked, proxy, extra]
                            db.execute(sql, params)


def update_wallet_balances(address: str, historic_timestamp: Optional[int]):
    print(f'  Updating current_balance for: {address} at timestamp {historic_timestamp}')
    # For now we will clear everything out of the DB from debank first
    # In the future we may make a balance_historical and can keep a synchronized and historical balances?
    sql = '''DELETE FROM balance_current
           WHERE address= ?
           AND source = 'debank'
        '''
    db.execute(sql, address)

    if not historic_timestamp:
        updated = int(time.time())
        tables = ['balance_current', 'balance_history']

        # Update balance tables with Wallet tokens
        # print('    * wallet')
        DEBANK_TOKENS_URL = f'https://openapi.debank.com/v1/user/token_list?id={address}&is_all=false'
        if sys.argv[-1] == 'refresh':
            c = cache.get(DEBANK_TOKENS_URL, refresh=True)
        else:
            c = cache.get(DEBANK_TOKENS_URL, refresh_if=3600)
        tokens = json.loads(c['value'])
        ingest_debank_token_list(address, tokens, updated, tables)

        # Update balance tables with Protocol tokens
        DEBANK_COMPLEX_PROTOCOL_URL = f'https://openapi.debank.com/v1/user/complex_protocol_list?&id={address}'
        if sys.argv[-1] == 'refresh':
            c = cache.get(DEBANK_COMPLEX_PROTOCOL_URL, True)
        else:
            c = cache.get(DEBANK_COMPLEX_PROTOCOL_URL, refresh_if=3600)
        protocol_list = json.loads(c['value'])
        ingest_debank_complex_protocol_list(address, protocol_list, updated, tables)

    else:
        # IMPORTANT: This won't work for arbitrary historic timestamps because debank only supports the moment apis (time_at) for the last 24 hours!
        # A historic timestamp was provided, so we're going to do things a bit differently:
        # 1. Hit the token_list endpoint with `time_at=timestamp` `is_all=true`  so we get all of the protocol tokens too
        # 2. For every token with a protocol_id, hit the protocol endpoint with `time_at=timestamp` so we get the balances for that protocol at that timestamp
        # 3. Insert all balances into balance_history only
        tables = ['balance_history']

        # Update historic balance table with Wallet tokens at specified timestamp
        DEBANK_TOKENS_URL = f'https://openapi.debank.com/v1/user/token_list?id={address}&is_all=true&time_at={historic_timestamp}'
        c = cache.get(DEBANK_TOKENS_URL)  # safe to cache this forever since it shouldn't change, right?
        tokens = json.loads(c['value'])
        # Split out the wallet tokens from the protocol tokens
        protocol_tokens, non_protocol_tokens = partition(lambda t: t["protocol_id"] == "", tokens)  # partition returns (false, true)
        ingest_debank_token_list(address, non_protocol_tokens, historic_timestamp, tables)

        # Get Update historic balance table with Protocol tokens at specified timestamp
        for t in protocol_tokens:
            DEBANK_PROTOCOL_URL = f'https://openapi.debank.com/v1/user/protocol?id={address}&protocol_id={t["protocol_id"]}&time_at={historic_timestamp}'
            c = cache.get(DEBANK_PROTOCOL_URL)  # safe to cache since this shouldn't change
            protocol_result = json.loads(c['value'])
            protocol_list = [protocol_result]
            ingest_debank_complex_protocol_list(address, protocol_list, historic_timestamp, tables)

    # quit after one wallet
    # sys.exit()


def debank_data_fixups():
    tables = ['balance_current', 'balance_history']
    # Fix Symbols
    fix = [
        # If we have symbols to fix
    ]
    for f in fix:
        for table in tables:
            sql = f"""UPDATE {table}
                     SET symbol = ?, exposure_symbol = ?
                     WHERE symbol = ?
                  """
            db.execute(sql, f)

    # Exposure
    exposure = [
        ['AAVE', 'stkAAVE'],
        ['AVAX', 'WAVAX'],
        ['AVAX', 'sAVAX'],
        ['AVAX', 'yyAVAX'],
        ['BTC', 'renBTC'],
        ['BTC', 'WBTC'],
        ['BTC', 'WBTC.e'],
        ['CRV', 'aCRV'],
        ['CRV', 'cvxCRV'],
        ['CRV', 'uCRV'],
        ['CRV', 'yveCRV-DAO'],
        ['DAI', 'DAI.e'],
        ['DAI', 'xDAI'],
        ['ETH', 'AETH'],
        ['ETH', 'avWETH'],
        ['ETH', 'eCRV'],
        ['ETH', 'stETH'],
        ['ETH', 'WETH'],
        ['ETH', 'WETH.e'],
        ['FTM', 'WFTM'],
        ['FTM', 'yvWFTM'],
        ['FXS', 'cvxFXS'],
        ['GMX', 'esGMX'],
        ['MATIC', 'amWMATIC'],
        ['MATIC', 'WMATIC'],
        ['SPELL', 'sSPELL'],
        ['USDC', 'USDC.e'],
        ['USDT', 'USDT.e'],
    ]
    for e in exposure:
        for table in tables:
            sql = f"""UPDATE {table}
                     SET exposure_symbol = ?
                     WHERE exposure_symbol = ?
                  """
            db.execute(sql, e)

    # Set stablecoins
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
    for s in stables:
        for table in tables:
            sql = f"""UPDATE {table}
                 SET stable = 1
                 WHERE exposure_symbol = ?
              """
            db.execute(sql, s)

if __name__ == "__main__":
    if len(sys.argv) == 2:
        update_entity_balances(sys.argv[-1], None)
    else:
        main()

