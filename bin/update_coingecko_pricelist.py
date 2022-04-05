import json
from perfi.cache import cache
from perfi.db import db
from perfi.settings import setting
from pprint import pprint
import sys
from tqdm import tqdm


def main():
    # Get prices token list
    if "COINGECKO_KEY" in setting(db):
        key = setting(db).get("COINGECKO_KEY")
        COINGECKO_TOKENLIST_URL = f"https://pro-api.coingecko.com/api/v3/coins/list?include_platform=true&x_cg_pro_api_key={key}"
    else:
        COINGECKO_TOKENLIST_URL = (
            "https://api.coingecko.com/api/v3/coins/list?include_platform=true"
        )
    # if older than 1 day, force a refresh
    c = cache.get(COINGECKO_TOKENLIST_URL, refresh_if=86400)
    j = json.loads(c["value"])

    for i in tqdm(j, desc=f"Coingecko Token List", disable=None):
        if i["id"]:
            # Make all lower-case symbols upper-case. Leave mixed-case symbols alone
            symbol = i["symbol"]
            if symbol.lower() == symbol:
                symbol = symbol.upper()
            # print(f"{i['id']}: {symbol}")
            sql = """REPLACE INTO asset_price
               (id, source, symbol, name, raw_data)
               VALUES
               (?, ?, ?, ?, ?)
            """
            params = [i["id"], "coingecko", symbol, i["name"], json.dumps(i)]
            db.execute(sql, params)

    # Update Top 500 marketcap (for ordering)
    update_market_cap(1)
    update_market_cap(2)


def update_market_cap(page=1):
    # Can get up to the top 250, should be good enough
    if "COINGECKO_KEY" in setting(db):
        key = setting(db).get("COINGECKO_KEY")
        CG_MARKET_URL = f"https://pro-api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}&sparkline=false&x_cg_pro_api_key={key}"
    else:
        CG_MARKET_URL = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}&sparkline=false"
    # get rankings, if older than a day refresh rankings
    c = cache.get(CG_MARKET_URL, refresh_if=86400)
    j = json.loads(c["value"])

    # We store market_cap instead of rank so we can sort queries by DESC properly later for ranking
    for coin in tqdm(
        j, desc=f"Updating asset_price.market_cap (Page {page})", disable=None
    ):
        market_cap = coin["market_cap"]
        id = coin["id"]

        sql = """UPDATE asset_price SET market_cap = ? WHERE id = ?"""
        params = [market_cap, id]
        db.execute(sql, params)


if __name__ == "__main__":
    main()
