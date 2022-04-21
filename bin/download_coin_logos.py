import json
import shelve

import httpx

from perfi.cache import cache
from perfi.db import db
from perfi.settings import setting
from pprint import pprint
import sys
from tqdm import tqdm

import pathlib

COINGECKO_CONTRACT_INFO_URL_TEMPLATE = (
    "https://api.coingecko.com/api/v3/coins/{CHAIN}/contract/{CONTRACT}"
)
COINGECKO_COIN_INFO_URL_TEMPLATE = "https://api.coingecko.com/api/v3/coins/{COIN_ID}"

if "COINGECKO_KEY" in setting(db):
    print("got coingecko key from db. using pro api...")
    key = setting(db).get("COINGECKO_KEY")
    COINGECKO_CONTRACT_INFO_URL_TEMPLATE = (
        "https://pro-api.coingecko.com/api/v3/coins/{CHAIN}/contract/{CONTRACT}?x_cg_pro_api_key="
        + key
    )
    COINGECKO_COIN_INFO_URL_TEMPLATE = (
        "https://pro-api.coingecko.com/api/v3/coins/{COIN_ID}?x_cg_pro_api_key=" + key
    )


# def map(tx):
#     mappings = { "eth": "ethereum" }
#     if tx["asset_tx_id"]


def main():
    completed_items = set()
    logos_dir = (
        pathlib.Path(__file__).resolve().joinpath("../../data/coin_logos/").resolve()
    )
    print(logos_dir)
    logos = logos_dir.glob("*.png")
    for l in logos:
        chain, contract = l.parts[-1].split("_")
        contract = contract[0:-4]
        pair = (chain, contract)
        completed_items.add(pair)

    completed_urls = set()
    failed_urls = set()
    failed_items = set()
    with shelve.open(str(logos_dir / "shelf.db")) as shelf:
        # db['completed_items'] = completed_items
        # completed_urls = db.get('completed_urls', set())
        failed_items = shelf.get("failed_items", set())

    print("Completed Items:")
    print(completed_items)

    print("Failed Items:")
    print(failed_items)

    sql = f"""SELECT count(*) as count, tx.chain, tx.asset_tx_id, a.asset_price_id
              FROM tx_ledger tx
              JOIN asset_tx a on tx.asset_tx_id = a.id
              group by tx.chain, tx.asset_tx_id, a.asset_price_id
              order by 1 desc
              """
    results = db.query(sql)
    for result in results:
        result = dict(**result)
        if result["count"] <= 3:
            continue

        chain = result["chain"]
        price_id = result.get("asset_price_id", None)
        contract = result["asset_tx_id"]
        if (chain, contract) in completed_items:
            continue

        # print(price_id)
        # print(contract)
        url = (
            COINGECKO_COIN_INFO_URL_TEMPLATE.format(COIN_ID=price_id)
            if price_id
            else COINGECKO_CONTRACT_INFO_URL_TEMPLATE.format(
                CHAIN=chain, CONTRACT=contract
            )
        )
        # print(url)
        if url in completed_urls:
            continue
        try:
            c = cache.get(url, refresh_if=86400)
            j = json.loads(c["value"])
            image_url = j["image"]["small"]
            # print(image_url)
            filename = pathlib.Path(
                pathlib.Path(__file__)
                .resolve()
                .joinpath("../../data/coin_logos/" + f"{chain}_{contract}.png")
            ).resolve()
            with open(filename, "wb") as f:
                with httpx.stream("GET", image_url) as r:
                    for data in r.iter_bytes():
                        f.write(data)
            # completed_urls.add(url)
            print("SUCCESS: " + url)
        except Exception as ex:
            failed_items.add((chain, contract))
            print("FAIL: " + url)

    with shelve.open(str(logos_dir / "shelf.db")) as shelf:
        shelf["failed_items"] = failed_items

    print("DONE")

    # - fetch coingecko details for it
    # - download image


if __name__ == "__main__":
    main()
