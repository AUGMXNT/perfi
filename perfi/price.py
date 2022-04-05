from .cache import cache
from .db import db
from .settings import setting

from decimal import Decimal
import json
from collections import namedtuple, defaultdict, OrderedDict

from pprint import pprint
from pprint import pprint as pp
from datetime import datetime
import sys
import time

CoinPrice = namedtuple("CoinPrice", ["source", "coin_id", "epoch", "price"])

if "COINGECKO_KEY" in setting(db):
    key = setting(db).get("COINGECKO_KEY")
    COINGECKO_DATE_URL = (
        "https://pro-api.coingecko.com/api/v3/coins/{coin_id}/history?date={date_str}&x_cg_pro_api_key="
        + key
    )
    COINGECKO_RANGE_URL = (
        "https://pro-api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range?vs_currency={vs_currency}&from={from_epoch}&to={to_epoch}&x_cg_pro_api_key="
        + key
    )
else:
    COINGECKO_DATE_URL = (
        "https://api.coingecko.com/api/v3/coins/{coin_id}/history?date={date_str}"
    )
    COINGECKO_RANGE_URL = "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range?vs_currency={vs_currency}&from={from_epoch}&to={to_epoch}"

COINSTATS_HISTORIC_URL = (
    "https://api.coinstats.app/public/v1/charts?period=all&coinId={coin_id}"
)

# NOTE: Some assets like usd-coin-avalanche-bridged-usdc-e don't have Coingecko Prices from long ago, so we will define a list of
# mapped like-kind coin_ids we can try in the case of a failed Coingecko price fetch
COINGECKO_FALLBACK_PRICE_MAPPER = {
    "usd-coin-avalanche-bridged-usdc-e": "usd-coin",
}


def _add_price_to_db(db, coin_price):
    sql = """
        REPLACE INTO prices
        (coin_id, source, epoch, price)
        VALUES
        (?, ?, ?, ?)"""
    params = (coin_price.coin_id, coin_price.source, coin_price.epoch, coin_price.price)
    db.execute(sql, params)


def _get_latest_from_coinstats(coin_id):
    c = cache.get(COINSTATS_HISTORIC_URL.format(coin_id=coin_id))
    j = json.loads(c["value"])
    results = []
    for epoch, price, _, _ in j["chart"]:
        results.append(CoinPrice("coinstats", coin_id, epoch, price))
    return results


def _get_range_from_coingecko(coin_id, desired_epoch, plus_minus_seconds):
    from_epoch = desired_epoch - plus_minus_seconds
    to_epoch = desired_epoch + plus_minus_seconds
    c = cache.get(
        COINGECKO_RANGE_URL.format(
            coin_id=coin_id, vs_currency="usd", from_epoch=from_epoch, to_epoch=to_epoch
        ),
        refresh=True,
    )
    j = json.loads(c["value"])
    results = []
    for coingecko_epoch, price in j["prices"]:
        if len(str(coingecko_epoch)) > 10:
            # Coingecko returns milisecond epochs for their price timestamps, so let's be sane and truncate to seconds resolution for unix consistency for now
            epoch = int(str(coingecko_epoch)[0:10])
        results.append(CoinPrice("coingecko", coin_id, epoch, price))
    return results


def _refresh_db(db, coin_id, epoch):
    # print('Getting coinstats prices')
    # coinstats_prices = _get_latest_from_coinstats(coin_id)
    # for coin_price in coinstats_prices:
    #     _add_price_to_db(db, coin_price)

    print("Getting coingeckp prices")
    one_year_in_seconds = 60 * 60 * 24 * 365
    coingecko_prices = _get_range_from_coingecko(coin_id, epoch, one_year_in_seconds)
    print("Done getting coingeckp prices")
    for coin_price in coingecko_prices:
        _add_price_to_db(db, coin_price)


def get_coingecko_price_for_day(coin_id, epoch):
    date = datetime.fromtimestamp(epoch)
    date_str = date.strftime("%d-%m-%Y")
    c = cache.get(COINGECKO_DATE_URL.format(coin_id=coin_id, date_str=date_str))
    j = json.loads(c["value"])
    try:
        price = j["market_data"]["current_price"]["usd"]
        return ("coingecko", date.timestamp(), price)
    except KeyError:
        if coin_id in COINGECKO_FALLBACK_PRICE_MAPPER:
            coin_id = COINGECKO_FALLBACK_PRICE_MAPPER[coin_id]
            return get_coingecko_price_for_day(coin_id, epoch)


class PriceFeed:
    def __init__(self):
        self.prices = defaultdict(lambda: defaultdict(lambda: []))

    def get(self, coin_id, desired_epoch):
        try:
            source, actual_epoch, price = get_coingecko_price_for_day(
                coin_id, desired_epoch
            )
            return CoinPrice(coin_id, "coingecko", actual_epoch, price)
        except:
            pass

    def get_old(self, coin_id, desired_epoch):
        _refresh_db(db, coin_id, desired_epoch)
        sql = """
            SELECT coin_id, source, epoch, price
            FROM prices
            WHERE
                coin_id = ?
                AND epoch <= ?
            ORDER BY epoch DESC
            LIMIT 1"""
        params = [coin_id, desired_epoch]
        r = db.query(sql, params)
        source, coin_id, actual_epoch, price = r[0]
        return CoinPrice(coin_id, source, actual_epoch, price)


price_feed = PriceFeed()
