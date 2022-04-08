from .cache import cache
from .constants import assets
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

    def get_by_asset_tx_id(self, chain, asset_tx_id, timestamp):
        asset_price = self.map_asset(chain, asset_tx_id)

        if asset_price:
            try:
                return self.get(asset_price["asset_price_id"], timestamp)
            except:
                raise Exception(
                    f"Failed to get price from pricefeed despite having an asset_price record of: {asset_price} for asset_tx_id {asset_tx_id}"
                )
        else:
            return None

    def map_asset(self, chain, asset_tx_id, symbol_fallback=False):
        # We want things like usdc_on_avax -> usdc_core
        # This will be differen from our asset_tx_id -> asset_price_id mapping because that goes for the most specific asset_price_id it can find, but for costbasis, we want to group all the variants together for LOT MATCHING purposes. This mapping can be used for exposure mapping as well (we need to do additional mappings for exposure since that needs to split LP amounts and account for ib multipliers)

        # This allows up to use our manual COSTBASIS_LIKEKIND matching for imported asset_tx_ids
        if chain.startswith("import."):
            chain = "import"

        tx_key = f"{chain}:{asset_tx_id}"
        canonical_key = None
        symbol = None
        if tx_key in assets.COSTBASIS_LIKEKIND:
            canonical_key = assets.COSTBASIS_LIKEKIND[tx_key]
            sql = """SELECT symbol
                     FROM asset_price
                     WHERE id = ?
                  """
            r = db.query(sql, canonical_key)
            symbol = r[0][0]
        else:
            sql = """SELECT asset_price_id, symbol
                     FROM asset_tx
                     WHERE chain = ?
                     AND id = ?
                  """
            params = (chain, asset_tx_id)
            r = db.query(sql, params)
            if r:
                canonical_key = r[0][0]
                symbol = r[0][1]

        if canonical_key and symbol:
            return {
                "asset_price_id": canonical_key,
                "symbol": symbol,
            }
        # Only if asked to do a symbol_fallback do we try to match by symbol...
        elif symbol_fallback:
            """
            LATER: Make sure we have guards to protect against known different assets with the same symbol (like QI and QI)
                   Also make sure we skip any type of LPs or deposit receipts...
                   ??? Are LP tokens really receipts?
            """
            if symbol:
                sql = """SELECT * FROM asset_price
                         WHERE symbol = ?
                         AND market_cap IS NOT NULL
                         ORDER BY market_cap DESC
                      """
                r = db.query(sql, symbol)
                if r:
                    return {
                        "asset_price_id": r[0][0],
                        "symbol": symbol,
                    }

        return None


price_feed = PriceFeed()
