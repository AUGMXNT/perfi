import json
import logging
import lzma
import re
import sys
import time
from collections import namedtuple
from datetime import datetime
from decimal import Decimal
from pprint import pprint, pformat

import arrow
import chromedriver_binary  # noqa
from bs4 import BeautifulSoup
from lxml import etree, html
from seleniumwire import webdriver
from seleniumwire.utils import decode
from tqdm import tqdm

from ..cache import cache, CacheGet404Exception
from ..db import db
from ..settings import setting

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# LATER: figure out if we need to make these configurable
REFRESH_INDEXES = False
REFRESH_DETAILS = False


TxChain = namedtuple(
    "TxChain", ["chain", "address", "hash", "timestamp", "raw_data_lzma"]
)


def _scrape_token_transferred_li_for_erc721(li):
    to_address = (
        li.xpath('.//span[contains(@class, "hash-tag-custom-to-721")]')[0]
        .text_content()
        .strip()
    )
    from_address = (
        li.xpath('.//span[contains(@class, "hash-tag-custom-from-721")]')[0]
        .text_content()
        .strip()
    )
    token_id = li.xpath(".//a")[2].text_content()

    token_name_and_symbol = li.xpath(".//a")[3].text_content()
    token_name = token_name_and_symbol.split("(")[0].strip()
    token_symbol = token_name_and_symbol.split("(")[1].replace(")", "").strip()

    if "..." in token_name_and_symbol:
        token_name = li.xpath(".//a")[3].text_content().split(" ")[0]
        token_symbol = li.xpath(".//a")[3].xpath(".//span")[0].attrib["title"]

    # TODO: should we have an explicit amount of 1 here?
    return dict(
        to_address=to_address,
        from_address=from_address,
        token_id=token_id,
        token_name=token_name,
        token_symbol=token_symbol,
    )


def _scrape_token_transferred_li_for_erc20(li):
    to_address = (
        li.xpath('.//span[contains(@class, "hash-tag-custom-to")]')[0]
        .text_content()
        .strip()
    )
    from_address = (
        li.xpath('.//span[contains(@class, "hash-tag-custom-from")]')[0]
        .text_content()
        .strip()
    )

    amount = li.xpath(".//span[6]")[0].text_content()

    try:
        token_name_and_symbol = li.xpath(".//a")[2].text_content()
    except:
        all_words = li.xpath(".//div")[0].text_content().split(" ")
        token_name_and_symbol = " ".join(all_words[-2:])

    token_name = token_name_and_symbol.split("(")[0].strip()
    token_symbol = token_name_and_symbol.split("(")[1].replace(")", "").strip()

    if "..." in token_name:
        token_name = li.xpath(".//a")[2].xpath(".//span")[0].attrib["title"].strip()
    if "..." in token_symbol:
        try:
            token_symbol = (
                li.xpath(".//a")[2].xpath(".//span")[1].attrib["title"].strip()
            )
        except:
            try:
                token_symbol = (
                    li.xpath(".//a")[2].xpath(".//span")[0].attrib["title"].strip()
                )
            except:
                token_symbol = li.xpath(".//span[@title]")[2].attrib["title"].strip()

    # print('%s | %s' % (token_name, token_symbol))

    d = dict(
        to_address=to_address,
        from_address=from_address,
        amount=amount,
        token_name=token_name,
        token_symbol=token_symbol,
    )
    for k, v in d.items():
        if v == "" or v is None:
            logging.error(f"Empty values in: {pformat(d.items())}")
    return d


class MyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            # pprint(obj); sys.exit()
            return str(obj, encoding="utf-8")
        if isinstance(obj, Decimal):
            return str(obj)
        return json.JSONEncoder.default(self, obj)


def normalized_chain_value(chain):
    # LATER: update dynamically with https://openapi.debank.com/v1/chain/list
    # https://docs.cloud.debank.com/en/readme/api-pro-reference/chain#returns-1
    vals = dict(
        arb="arbitrum",
        astar="astar",
        aurora="aurora",
        avax="avalanche",
        base="base",
        bsc="binancesc",
        btt="btt",
        boba="boba",
        brise="bitgert",
        canto="canto",
        celo="celo",
        cfx="conflux",
        ckb="godwoken",
        core="core",
        cro="cronos",
        dfk="dfk",
        doge="dogechain",
        eos="eos-evm",
        era="zksync-era",
        eth="ethereum",
        etc="ethereum-classic",
        evmos="evmos",
        flr="flare",
        ftm="fantom",
        fsn="fusion",
        fuse="fuse",
        heco="heco",
        hmy="harmony",
        iotx="iotex",
        kava="kava",
        kcc="kcc",
        klay="klaytn",
        linea="linea",
        loot="loot",
        lyx="lukso",
        mada="milkomeda-c1",
        manta="manta",
        matic="polygon",
        metis="metis",
        mobm="moonbeam",
        movr="moonriver",
        mnt="mantle",
        mtr="meter",
        nova="arbitrum-nova",
        oas="oasys",
        op="optimism",
        opbnb="opbnb",
        okt="okc",
        palm="palm",
        pls="pulse",
        pgn="pgn",
        pze="polygon-zkevm",
        ron="ronin",
        rose="oasis-emerald",
        rsk="rsk",
        sbch="smartbch",
        sgb="songbird",
        shib="shibarium",
        sdn="shiden",
        step="step",
        tenet="tenet",
        tlos="telos",
        tomb="tomb",
        wan="wanchain",
        wemix="wemix",
        xdai="xdai",
        zora="zora",
    )
    vals_with_normalized = vals.copy()
    for _, v in vals.items():
        vals_with_normalized[v] = v
    return vals_with_normalized[chain]


def _get_address_and_name_from_etherscan_td(td):
    td_a = td.xpath(".//a")
    _address = ""
    _address_name = ""
    if len(td_a) > 0:
        _address = td_a[0].xpath("@href")[0][9:]  # Chop off the /address/ part
        _address_name = td_a[0].text_content()
    else:
        _address = td.text_content()
        _address = _address.split("#")[0]
        _address_name = _address_name.split("#")[0].strip()
    return _address, _address_name


def _etherscan_timestamp_to_epoch(timestamp):
    try:
        parts = timestamp.split(" ")
        date = parts[0]
        hour, min, sec = parts[1].split(":")
        if int(hour) < 10:
            hour = "0" + hour
        iso_formatted = date + "T" + ":".join([hour, min, sec]) + "Z"
        return arrow.get(iso_formatted).timestamp()
    except Exception:
        print("Error parsing etherscan timestamp: %s" % timestamp)
        raise


class TransactionsFetcher:
    def _log_tx(self, tx):
        """
        The goal would be to be able to log details like a timestamp for a tx after it was fetched
        """
        datestamp = datetime.utcfromtimestamp(tx["_epoch_timestamp"]).isoformat()
        hash = tx["hash"]
        logger.info(f"{type(self)} Scraped {datestamp} - {hash}")


class EtherscanTransactionsFetcher(TransactionsFetcher):
    # CONSIDER: should we use xpath selectors (more powerful) or switch to css selectors (more familiar to devs)?
    def __init__(self, db=None):
        self.db = db
        self.ETHERSCAN_KEY = setting(self.db).get("ETHERSCAN_KEY")

    def _scrape_token_transferred_li_for_erc1155(self, li):
        to_address = (
            li.xpath('.//span[contains(@class, "hash-tag-custom-to")]')[0]
            .text_content()
            .strip()
        )
        from_address = (
            li.xpath('.//span[contains(@class, "hash-tag-custom-from")]')[0]
            .text_content()
            .strip()
        )

        token_name = "__ERC1155__"  # TODO: does this make sense to just use a placeholder value? Do ERC1155 tokens even have specific names?
        token_symbol = "__ERC1155__"  # TODO: same as above
        try:
            amount_and_token_id_str = li.xpath(".//span[3]")[0].text_content()
            # 1 of Token ID [2]
            matches = re.match("(\d+) of Token ID \[(\d+)\]", amount_and_token_id_str)
            if matches:
                amount = matches.group(1)
                token_id = matches.group(2)
            else:
                raise
        except:
            amount = li.xpath(".//span")[7].xpath(".//span")[0].text_content()
            token_id = li.xpath(".//span")[7].xpath(".//a")[0].text_content()

        return dict(
            to_address=to_address,
            from_address=from_address,
            amount=amount,
            token_name=token_name,
            token_symbol=token_symbol,
            token_id=token_id,
        )

    def _scrape_transaction_details(self, hash):
        URL = "https://etherscan.io/tx/%s" % hash.strip()
        # print('Scraping %s' % URL, file=sys.stderr)
        c = cache.get(URL, REFRESH_DETAILS)
        doc = html.document_fromstring(c["value"])

        tx_details = dict(actions=[], tokens_transferred=[])

        try:
            span = doc.xpath(
                '//*[@id="ContentPlaceHolder1_maintable"]//span[contains(@class, "u-label--success")]'
            )[0]
            status = "Success"
        except:
            status = "Failed"
        tx_details["status"] = status

        block = doc.xpath('//a[contains(@href, "/block/")]')[0].text_content()
        tx_details["block"] = block

        tx_gas_usage = doc.xpath('//span[@id="ContentPlaceHolder1_spanGasUsedByTxn"]')[
            0
        ].text_content()
        gas_used = int(tx_gas_usage.split("(")[0].strip().replace(",", ""))
        tx_details["gas_used"] = gas_used

        fee_with_usd = doc.xpath('//span[@id="ContentPlaceHolder1_spanTxFee"]')[
            0
        ].text_content()
        fee = fee_with_usd.split("(")[0].strip()
        tx_details["fee"] = fee

        gas_price_with_usd = doc.xpath(
            '//span[@id="ContentPlaceHolder1_spanGasPrice"]'
        )[0].text_content()
        gas_price = gas_price_with_usd.split("(")[0].strip()
        tx_details["gas_price"] = gas_price

        tx_action_divs = doc.xpath(
            '//div[div[div[i/@data-content="Highlighted events of the transaction"]]]/*/ul[@id="wrapperContent"]/li/div[@class="media-body"]'
        )
        for div in tx_action_divs:
            parts = div.xpath("*")
            contents = [part.text_content() for part in parts]
            tx_details["actions"].append(" ".join(contents))

        tx_tokens_transferred_lis = doc.xpath(
            '//*[contains(text(), "Tokens Transferred")]/ancestor::div[contains(@class, "row")]/div[2]//li'
        )
        for li in tx_tokens_transferred_lis:
            try:
                scraper_func = _scrape_token_transferred_li_for_erc20
                scraper_func = (
                    _scrape_token_transferred_li_for_erc721
                    if "ERC-721" in li.text_content()
                    else scraper_func
                )
                scraper_func = (
                    self._scrape_token_transferred_li_for_erc1155
                    if "ERC-1155" in li.text_content()
                    else scraper_func
                )
                tokens_transferred = scraper_func.__call__(li)

                tx_details["tokens_transferred"].append(tokens_transferred)
            except Exception as err:
                pprint(hash)
                print(etree.tostring(li))
                raise

        value = doc.xpath('//*[@id="ContentPlaceHolder1_spanValue"]')[0].text_content()
        tx_details["value"] = value.split("(")[0].strip()

        # look for labels too
        tx_details["labels"] = []
        for label_a in doc.xpath("//a[starts-with(@href, '/txs/label')]"):
            tx_details["labels"].append(label_a.text_content().strip())

        tx_details["_etherscan_html"] = c["value"]
        return tx_details

    def scrape_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://etherscan.io/txs?ps=100&zero=false&a=%s&p=%s" % (
                address,
                page_num,
            )
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath('//*[@id="paywall_mask"]/table/tbody/tr')
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break
                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                txn_dict = dict(
                    hash=tx[1].strip(),
                    block=tx[3],
                    timestamp=tx[4],
                    direction=tx[7].replace("\xa0", ""),
                    # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    value=tx[9],
                    fee=tx[10],
                    gasPrice=tx[11],
                )

                method = tds[2].xpath(".//span[1]/@title")
                txn_dict["method"] = method[0]

                from_td = tds[6]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[8]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                txn_dict["_type"] = "normal"
                txn_dict["_epoch_timestamp"] = _etherscan_timestamp_to_epoch(
                    txn_dict["timestamp"]
                )

                tx_details = self._scrape_transaction_details(txn_dict["hash"])
                txn_dict["details"] = tx_details

                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

                txn_dict["_etherscan_item_row_html"] = etree.tostring(tx_row)

                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1
        transactions = self._add_extended_info(transactions)
        return transactions

    def scrape_internal_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = (
                "https://etherscan.io/txsInternal?ps=100&zero=false&a=%s&valid=all&p=%s"
                % (address, page_num)
            )
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath(
                '//div[contains(@class, "table-responsive")]/table/tbody/tr'
            )
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break

                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                try:
                    txn_dict = dict(
                        block=tx[0],
                        timestamp=tx[1],
                        parent_hash=tx[3].strip(),
                        type=tx[4],
                        value=tx[8],
                    )
                except:
                    pprint(URL)
                    pprint(tx)
                    raise

                from_td = tds[5]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[7]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                txn_dict["_type"] = "internal"
                txn_dict["_epoch_timestamp"] = _etherscan_timestamp_to_epoch(
                    txn_dict["timestamp"]
                )

                tx_details = self._scrape_transaction_details(txn_dict["parent_hash"])
                txn_dict["details"] = tx_details
                txn_dict["value"] = tx_details["value"]
                txn_dict["block"] = tx_details["block"]
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1
        transactions = self._add_extended_info(transactions)
        return transactions

    def scrape_token_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://etherscan.io/tokentxns?ps=100&zero=false&a=%s&p=%s" % (
                address,
                page_num,
            )
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath(
                '//div[div[@id="ContentPlaceHolder1_divTopPagination"]]//table//tbody/tr'
            )
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break
                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                txn_dict = dict(
                    hash=tx[1].strip(),
                    timestamp=tx[2],
                    direction=tx[5].replace("\xa0", ""),
                    # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    value=tx[7],
                )

                from_td = tds[4]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[6]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                token_td = tds[8]
                # HACK: This is ugly. if the token name is short enough it comes through without a span,
                # but if it's long like 'Wrapped Ethereum' it shows up in a span. So we need to treat
                # these cases differently
                token_name_span = token_td.xpath("a/span/@title")
                if len(token_name_span) > 0:
                    # In these cases, the token name is on a title attribute and
                    # the (TOKEN_SYMBOL) part of the text is only in the text node,
                    # so find and add that too...
                    txn_dict["token_name"] = token_td.xpath("a/span/@title")[0]
                    matches = re.search("\((\w*)\)", token_td.text_content())
                    if matches:
                        txn_dict["token_symbol"] = matches.group(1)
                else:
                    pattern = "(.+) \((.+)\)"
                    matches = re.search(pattern, token_td.text_content())
                    if matches:
                        txn_dict["token_name"] = matches.group(1)
                        txn_dict["token_symbol"] = matches.group(2)
                    else:
                        raise Exception(
                            "Got a Token Name/Symbol string we couldn't parse: %s"
                            % token_td.text_content()
                        )

                txn_dict["_type"] = "token"
                txn_dict["_epoch_timestamp"] = _etherscan_timestamp_to_epoch(
                    txn_dict["timestamp"]
                )
                tx_details = self._scrape_transaction_details(txn_dict["hash"])
                txn_dict["details"] = tx_details
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1
        transactions = self._add_extended_info(transactions)
        return transactions

    def scrape_nft_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://etherscan.io/tokentxns-nft?ps=100&zero=false&a=%s&p=%s" % (
                address,
                page_num,
            )
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath("//div//table//tbody/tr")
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break
                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                txn_dict = dict(
                    hash=tx[1].strip(),
                    timestamp=tx[2],
                    direction=tx[5].replace("\xa0", ""),
                    # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    token_id=tx[7],
                )

                from_td = tds[4]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[6]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                token_td = tds[8]
                token_name = None
                try:
                    token_name = token_td.xpath(
                        './/span[@data-toggle="tooltip"]/@title'
                    )[0]
                except:
                    token_name = token_td.text_content().split("(")[0]
                txn_dict["token"] = token_name

                txn_dict["_type"] = "nft"
                txn_dict["_epoch_timestamp"] = _etherscan_timestamp_to_epoch(
                    txn_dict["timestamp"]
                )
                self._log_tx(txn_dict)
                transactions.append(txn_dict)

                tx_details = self._scrape_transaction_details(txn_dict["hash"])
                txn_dict["details"] = tx_details
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

            page_num += 1
        transactions = self._add_extended_info(transactions)
        return transactions

    def scrape_erc1155_transactions(self, address):
        # TODO scrape from https://etherscan.io/tokentxns-nft1155?a=X
        pass

    def _etherscan_api_fetch(self, address, type):
        # NOTE: currently unused
        # TODO handle pagination (if results == max results, try to get next page)
        # TODO handle errors (meessage != 'OK' in top level of response)

        # This method is unused for now (since we moved to scraping HTML instead of API.
        # Leaving these URLs here for reference
        urls = dict(
            API_NORMAL_TX="https://api.etherscan.io/api?module=account&action=txlist&address={ADDRESS}&startblock=0&endblock=99999999&page=1&offset=0&sort=asc&apikey={API_KEY}",
            API_INTERNAL_TX="https://api.etherscan.io/api?module=account&action=txlistinternal&address={ADDRESS}&startblock=0&endblock=99999999&page=1&offset=0&sort=asc&apikey={API_KEY}",
            API_TOKEN_TX="https://api.etherscan.io/api?module=account&action=tokentx&address={ADDRESS}&startblock=0&endblock=99999999&page=1&offset=0&sort=asc&apikey={API_KEY}",
            API_NFT_TX="https://api.etherscan.io/api?module=account&action=tokennfttx&address={ADDRESS}&startblock=0&endblock=99999999&page=1&offset=0&sort=asc&apikey={API_KEY}",
        )

        c = cache.get(urls[type].format(API_KEY=self.ETHERSCAN_KEY, ADDRESS=address))
        j = json.loads(c["value"])
        r = j["result"]
        for tx in r:
            tx["__eth_type"] = type
            tx["__direction"] = "IN" if tx["to"] == address else "OUT"
            tx["__datetime"] = datetime.utcfromtimestamp(
                int(tx["timestamp"])
            ).isoformat()

            # Time to get stuff via HTML
            URL = "https://etherscan.io/tx/%s" % tx["hash"]
            c = cache.get(URL, REFRESH_DETAILS)
            soup = BeautifulSoup(c["value"], "html.parser")
            actions_container = soup.find(
                attrs={"data-content": "Highlighted events of the transaction"}
            )
            if actions_container:
                action_lis = actions_container.find_parent(
                    attrs={"class": "row"}
                ).select("ul#wrapperContent li .media-body")
                transaction_action_strings = []
                for li in action_lis:
                    word_spans = li.select("span")
                    transaction_action_strings.append(
                        " ".join(span.text for span in word_spans)
                    )
                pprint(transaction_action_strings)

        return r

    def _add_extended_info(self, txs):
        for tx in txs:
            try:
                tx["_source"] = "etherscan"
                tx["_chain"] = "ethereum"
                tx["_chain_id"] = 1
                hash = tx["hash"].strip() if "hash" in tx else tx["parent_hash"].strip()
                tx["_id"] = hash
                tx["_api_responses"] = self._get_ethereum_transaction_details_from_APIs(
                    hash
                )
            except Exception as err:
                raise Exception(str(err) + "\n" + str(tx))
        return txs

    def _get_ethereum_transaction_details_from_APIs(self, hash):
        try:
            covalent_url = "https://api.covalenthq.com/v1/1/transaction_v2/{HASH}/?quote-currency=USD&format=JSON&no-logs=false&key={KEY}".format(
                KEY=setting(self.db)["COVALENT_KEY"], HASH=hash
            )
            unmarshall_url = "https://api.unmarshal.com/v1/ethereum/transactions/{HASH}?auth_key={KEY}".format(
                KEY=setting(self.db)["UNMARSHALL_KEY"], HASH=hash
            )
            # alchemy_url = "https://api.unmarshal.com/v1/ethereum/transactions/{HASH}?auth_key={KEY}".format(KEY=setting(self.db)['UNMARSHALL_KEY'], HASH=hash)
            api_responses = dict(
                covalent=cache.get(covalent_url)["value"],
                # unmarshall=cache.get(unmarshall_url)['value'],
                # alchemy=cache.get(alchemy_url)['value'],
            )
            return api_responses
        except:
            return {}


class AvalancheTransactionsFetcher(TransactionsFetcher):
    def __init__(self, db=None):
        self.db = db
        self.SNOWTRACE_KEY = setting(self.db).get("SNOWTRACE_KEY")

    def scrape_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://snowtrace.io/txs?a=%s&p=%s" % (address, page_num)
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath('//*[@id="paywall_mask"]/table/tbody/tr')
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break
                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                txn_dict = dict(
                    hash=tx[1],
                    block=tx[3],
                    timestamp=tx[4],
                    direction=tx[7].replace("\xa0", ""),
                    # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    value=tx[9],
                    fee=tx[10],
                    gasPrice=tx[11],
                )

                method = tds[2].xpath(".//span[1]/@title")
                txn_dict["method"] = method[0]

                from_td = tds[6]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[8]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                txn_dict["_type"] = "normal"
                # txn_dict['_epoch_timestamp'] = _etherscan_timestamp_to_epoch(txn_dict['timestamp'])

                tx_details = self._scrape_transaction_details(txn_dict["hash"])
                txn_dict["details"] = tx_details

                txn_dict["value"] = tx_details["value"]
                txn_dict["block"] = tx_details["block"]
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

                txn_dict["_epoch_timestamp"] = tx_details["epoch"]

                txn_dict["_snowtrace_item_row_html"] = etree.tostring(tx_row)

                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1

        transactions = self._add_extended_info(transactions)
        return transactions

    def _scrape_transaction_details(self, hash):
        URL = "https://snowtrace.io/tx/%s" % hash.strip()
        # print('Scraping %s' % URL, file=sys.stderr)
        c = cache.get(URL, REFRESH_DETAILS)
        doc = html.document_fromstring(c["value"])

        tx_details = dict(tokens_transferred=[])

        tx_block_parent_div = doc.xpath(
            '//div[contains(text(), "Block:")]/ancestor::div[contains(@class, "row")]'
        )[0]
        tx_details["block"] = tx_block_parent_div.xpath("./div[2]/a")[0].text_content()

        timestamp_str = (
            doc.xpath(
                '//div[contains(text(), "Timestamp:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .text_content()
        )
        timestamp_str = timestamp_str[
            timestamp_str.find("(") + 1 : timestamp_str.find(")")
        ]
        format_str = "%b-%d-%Y %I:%M:%S %p +UTC"
        timestamp = datetime.strptime(timestamp_str, format_str).timestamp()
        tx_details["epoch"] = timestamp

        value = doc.xpath('//*[@id="ContentPlaceHolder1_spanValue"]')[0].text_content()
        tx_details["value"] = value.split("(")[0].strip()

        fee_with_usd = (
            doc.xpath(
                '//div[contains(text(), "Transaction Fee:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .xpath('.//span[@id="ContentPlaceHolder1_spanTxFee"]')[0]
            .text_content()
        )
        fee = fee_with_usd.split("(")[0].strip()
        tx_details["fee"] = fee

        block = (
            doc.xpath(
                '//div[contains(text(), "Block:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .xpath(".//a")[0]
            .text_content()
        )
        tx_details["block"] = block

        gas_price_with_usd = (
            doc.xpath(
                '//div[contains(text(), "Gas Price:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .xpath('.//span[@id="ContentPlaceHolder1_spanGasPrice"]')[0]
            .text_content()
        )
        gas_price = gas_price_with_usd.split("(")[0].strip()
        tx_details["gas_price"] = gas_price

        tx_details["actions"] = []

        tx_gas_usage = doc.xpath('//span[@id="ContentPlaceHolder1_spanGasUsedByTxn"]')[
            0
        ].text_content()
        gas_used = int(tx_gas_usage.split("(")[0].strip().replace(",", ""))
        tx_details["gas_used"] = gas_used

        try:
            span = doc.xpath(
                '//*[@id="ContentPlaceHolder1_maintable"]//span[contains(@class, "u-label--success")]'
            )[0].text_content()
            status = "Success"
        except:
            status = "Failed"
        tx_details["status"] = status

        tx_action_divs = doc.xpath(
            '//div[div[div[i/@data-content="Highlighted events of the transaction"]]]/*/ul[@id="wrapperContent"]/li/div[@class="media-body"]'
        )
        for div in tx_action_divs:
            parts = div.xpath("*")
            contents = [part.text_content() for part in parts]
            tx_details["actions"].append(" ".join(contents))

        tx_tokens_transferred_lis = doc.xpath(
            '//*[contains(text(), "Tokens Transferred")]/ancestor::div[contains(@class, "row")]/div[2]//li'
        )
        for li in tx_tokens_transferred_lis:
            try:
                scraper_func = (
                    _scrape_token_transferred_li_for_erc721
                    if "ERC-721 TokenID" in li.text_content()
                    else _scrape_token_transferred_li_for_erc20
                )
                tokens_transferred = scraper_func.__call__(li)

                tx_details["tokens_transferred"].append(tokens_transferred)
            except Exception as err:
                pprint(hash)
                print(etree.tostring(li))
                raise

        # TODO: find a transaction that has these for Snowtrace, if any?
        # look for labels too
        # tx_details['labels'] = []
        # for label_a in doc.xpath("//a[starts-with(@href, '/txs/label')]"):
        #     tx_details['labels'].append(label_a.text_content().strip())

        tx_details["_snowtrace_html"] = c["value"]
        return tx_details

    def scrape_internal_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://snowtrace.io/txsInternal?a=%s&p=%s" % (address, page_num)
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath(
                '//div[contains(@class, "table-responsive")]/table/tbody/tr'
            )
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break

                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]

                # IMPORTANT: If this transaction row belongs to the same block as the previous row,
                # it's first two cells will be empty and its third cell, NOT fourth, is the one with parent hash
                parent_hash = tx[3].strip() if tx[0] != "" else tx[2].strip()
                txn_dict = dict(
                    parent_hash=parent_hash,
                    type=tx[4],
                )

                from_td = tds[5]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[7]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                txn_dict["_type"] = "internal"

                tx_details = self._scrape_transaction_details(txn_dict["parent_hash"])
                txn_dict["details"] = tx_details
                txn_dict["value"] = tx_details["value"]
                txn_dict["block"] = tx_details["block"]
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]
                txn_dict["_epoch_timestamp"] = tx_details["epoch"]

                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1

        transactions = self._add_extended_info(transactions)
        return transactions

    def scrape_token_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://snowtrace.io/tokentxns?a=%s&p=%s" % (address, page_num)
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath(
                '//div[contains(@class, "table-responsive")]//table//tbody/tr'
            )
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break
                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                txn_dict = dict(
                    hash=tx[1],
                    timestamp=tx[2],
                    direction=tx[5].replace("\xa0", ""),
                    # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    value=tx[7],
                )

                from_td = tds[4]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[6]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                token_td = tds[8]
                # HACK: This is ugly. if the token name is short enough it comes through without a span,
                # but if it's long like 'Wrapped Ethereum' it shows up in a span. So we need to treat
                # these cases differently
                token_name_span = token_td.xpath("a/span/@title")
                if len(token_name_span) > 0:
                    # In these cases, the token name is on a title attribute and
                    # the (TOKEN_SYMBOL) part of the text is only in the text node,
                    # so find and add that too...
                    txn_dict["token_name"] = token_td.xpath("a/span/@title")[0]
                    matches = re.search("\((\w*)\)", token_td.text_content())
                    if matches:
                        txn_dict["token_symbol"] = matches.group(1)
                else:
                    pattern = "(.+) \((.+)\)"
                    matches = re.search(pattern, token_td.text_content())
                    if matches:
                        txn_dict["token_name"] = matches.group(1)
                        txn_dict["token_symbol"] = matches.group(2)
                    else:
                        raise Exception(
                            "Got a Token Name/Symbol string we couldn't parse: %s"
                            % token_td.text_content()
                        )

                txn_dict["_type"] = "token"
                tx_details = self._scrape_transaction_details(txn_dict["hash"])
                txn_dict["details"] = tx_details

                # TODO: Snowscan has unreliable output for value/block/timestamp rows on the index pages
                # so we pull these from tx_details now. Consider this for the other scanners to standardize this behavior.
                txn_dict["value"] = tx_details["value"]
                txn_dict["block"] = tx_details["block"]
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]
                txn_dict["_epoch_timestamp"] = tx_details["epoch"]

                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1

        transactions = self._add_extended_info(transactions)
        return transactions

    def scrape_nft_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://snowtrace.io/tokentxns-nft?a=%s&p=%s" % (address, page_num)
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath("//div//table//tbody/tr")
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break
                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                txn_dict = dict(
                    hash=tx[1],
                    timestamp=tx[2],
                    direction=tx[5].replace("\xa0", ""),
                    # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    token_id=tx[7],
                )

                from_td = tds[4]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[6]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                token_td = tds[8]
                token_name = token_td.xpath('.//span[@data-toggle="tooltip"]/@title')[0]
                txn_dict["token"] = token_name

                txn_dict["_type"] = "nft"
                self._log_tx(txn_dict)
                transactions.append(txn_dict)

                tx_details = self._scrape_transaction_details(txn_dict["hash"])
                txn_dict["details"] = tx_details

                txn_dict["value"] = tx_details["value"]
                txn_dict["block"] = tx_details["block"]
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

                txn_dict["_epoch_timestamp"] = tx_details["epoch"]

            page_num += 1
        transactions = self._add_extended_info(transactions)
        return transactions

    def _add_extended_info(self, txs):
        for tx in txs:
            try:
                tx["_source"] = "snowtrace"
                tx["_chain"] = "avalanche"
                tx["_chain_id"] = 43114
                hash = tx["hash"].strip() if "hash" in tx else tx["parent_hash"].strip()
                tx["_id"] = hash
                tx[
                    "_api_responses"
                ] = self._get_avalanche_transaction_details_from_APIs(hash)
            except Exception as err:
                raise Exception(str(err) + "\n" + str(tx))
        return txs

    def _get_avalanche_transaction_details_from_APIs(self, hash):
        try:
            covalent_url = "https://api.covalenthq.com/v1/43114/transaction_v2/{HASH}/?quote-currency=USD&format=JSON&no-logs=false&key={KEY}".format(
                KEY=setting(self.db)["COVALENT_KEY"], HASH=hash
            )
            api_responses = dict(
                covalent=cache.get(covalent_url)["value"],
            )
            return api_responses
        except:
            return {}


class PolygonTransactionsFetcher(TransactionsFetcher):
    def __init__(self, db=None):
        self.db = db

    def scrape_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://polygonscan.com/txs?a=%s&p=%s" % (address, page_num)
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath('//*[@id="paywall_mask"]/table/tbody/tr')
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break
                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                txn_dict = dict(
                    hash=tx[1].strip(),
                    block=tx[3],
                    timestamp=tx[4],
                    direction=tx[7].replace("\xa0", ""),
                    # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    value=tx[9],
                    fee=tx[10],
                    gasPrice=tx[11],
                )

                method = tds[2].xpath(".//span[1]/@title")
                txn_dict["method"] = method[0]

                from_td = tds[6]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[8]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                txn_dict["_type"] = "normal"
                txn_dict["_epoch_timestamp"] = _etherscan_timestamp_to_epoch(
                    txn_dict["timestamp"]
                )

                tx_details = self._scrape_transaction_details(txn_dict["hash"])
                txn_dict["details"] = tx_details

                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

                txn_dict["_polygonscan_item_row_html"] = etree.tostring(tx_row)
                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1

        transactions = self._add_extended_info(transactions)
        return transactions

    def _scrape_transaction_details(self, hash):
        URL = "https://polygonscan.com/tx/%s" % hash.strip()
        # print('Scraping %s' % URL, file=sys.stderr)
        c = cache.get(URL, REFRESH_DETAILS)
        doc = html.document_fromstring(c["value"])
        tx_details = dict(tokens_transferred=[])

        tx_gas_usage = doc.xpath('//span[@id="ContentPlaceHolder1_spanGasUsedByTxn"]')[
            0
        ].text_content()
        gas_used = (
            int(tx_gas_usage.split("(")[0].strip().replace(",", ""))
            if tx_gas_usage != ""
            else 0
        )
        tx_details["gas_used"] = gas_used

        try:
            span = doc.xpath(
                '//*[@id="ContentPlaceHolder1_maintable"]//span[contains(@class, "u-label--success")]'
            )[0].text_content()
            status = "Success"
        except:
            status = "Failed"
        tx_details["status"] = status

        tx_details["actions"] = []

        tx_block_parent_div = doc.xpath(
            '//div[contains(text(), "Block:")]/ancestor::div[contains(@class, "row")]'
        )[0]
        tx_details["block"] = tx_block_parent_div.xpath("./div[2]/a")[0].text_content()

        timestamp_str = (
            doc.xpath(
                '//div[contains(text(), "Timestamp:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .text_content()
        )
        timestamp_str = timestamp_str[
            timestamp_str.find("(") + 1 : timestamp_str.find(")")
        ]
        format_str = "%b-%d-%Y %I:%M:%S %p +UTC"
        timestamp = datetime.strptime(timestamp_str, format_str).timestamp()
        tx_details["epoch"] = timestamp

        value = doc.xpath('//*[@id="ContentPlaceHolder1_spanValue"]')[0].text_content()
        tx_details["value"] = value.split("(")[0].strip()

        fee_with_usd = (
            doc.xpath(
                '//div[contains(text(), "Transaction Fee:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .xpath('.//span[@id="ContentPlaceHolder1_spanTxFee"]')[0]
            .text_content()
        )
        fee = fee_with_usd.split("(")[0].strip()
        tx_details["fee"] = fee

        gas_price_with_usd = (
            doc.xpath(
                '//div[contains(text(), "Gas Price:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .xpath('.//span[@id="ContentPlaceHolder1_spanGasPrice"]')[0]
            .text_content()
        )
        gas_price = gas_price_with_usd.split("(")[0].strip()
        tx_details["gas_price"] = gas_price

        tx_action_divs = doc.xpath(
            '//div[div[div[i/@data-content="Highlighted events of the transaction"]]]/*/ul[@id="wrapperContent"]/li/div[@class="media-body"]'
        )
        for div in tx_action_divs:
            parts = div.xpath("*")
            contents = [part.text_content() for part in parts]
            tx_details["actions"].append(" ".join(contents))

        tx_tokens_transferred_lis = doc.xpath(
            '//*[contains(text(), "Tokens Transferred")]/ancestor::div[contains(@class, "row")]/div[2]//li'
        )
        for li in tx_tokens_transferred_lis:
            try:
                scraper_func = _scrape_token_transferred_li_for_erc20
                scraper_func = (
                    _scrape_token_transferred_li_for_erc721
                    if "ERC-721 TokenID" in li.text_content()
                    else scraper_func
                )
                tokens_transferred = scraper_func.__call__(li)

                tx_details["tokens_transferred"].append(tokens_transferred)
            except Exception as err:
                pprint(hash)
                print(BeautifulSoup(etree.tostring(li)).prettify())
                raise

        # TODO: find a transaction that has these for Snowtrace, if any?
        # look for labels too
        # tx_details['labels'] = []
        # for label_a in doc.xpath("//a[starts-with(@href, '/txs/label')]"):
        #     tx_details['labels'].append(label_a.text_content().strip())

        tx_details["_polygonscan_html"] = c["value"]
        return tx_details

    def scrape_internal_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://polygonscan.com/txsInternal?a=%s&p=%s" % (address, page_num)
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath(
                '//div[contains(@class, "table-responsive")]/table/tbody/tr'
            )
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break

                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]

                # IMPORTANT: If this transaction row belongs to the same block as the previous row,
                # it's first two cells will be empty and its third cell, NOT fourth, is the one with parent hash
                parent_hash = None
                type = None
                if tx[0] != "":
                    parent_hash = tx[3].strip()
                    type = tx[4].strip()
                else:
                    parent_hash = tx[2].strip()
                    type = tx[3]
                txn_dict = dict(
                    parent_hash=parent_hash,
                    type=type,
                )
                if parent_hash == "call":
                    raise Exception("Got parent_hash call for %s" % address)

                from_td = tds[5]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[7]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                txn_dict["_type"] = "internal"

                tx_details = self._scrape_transaction_details(txn_dict["parent_hash"])
                txn_dict["details"] = tx_details
                txn_dict["value"] = tx_details["value"]
                txn_dict["block"] = tx_details["block"]
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

                txn_dict["_epoch_timestamp"] = tx_details["epoch"]

                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1

        transactions = self._add_extended_info(transactions)
        return transactions

    def scrape_token_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://polygonscan.com/tokentxns?a=%s&p=%s" % (address, page_num)
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath(
                '//div[contains(@class, "table-responsive")]//table//tbody/tr'
            )
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break
                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                txn_dict = dict(
                    hash=tx[1].strip(),
                    timestamp=tx[2],
                    direction=tx[5].replace("\xa0", ""),
                    # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    value=tx[7],
                )

                from_td = tds[4]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[6]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                token_td = tds[8]
                # HACK: This is ugly. if the token name is short enough it comes through without a span,
                # but if it's long like 'Wrapped Ethereum' it shows up in a span. So we need to treat
                # these cases differently
                token_name_span = token_td.xpath("a/span/@title")
                if len(token_name_span) > 0:
                    # In these cases, the token name is on a title attribute and
                    # the (TOKEN_SYMBOL) part of the text is only in the text node,
                    # so find and add that too...
                    txn_dict["token_name"] = token_td.xpath("a/span/@title")[0]
                    matches = re.search("\((\w*)\)", token_td.text_content())
                    if matches:
                        txn_dict["token_symbol"] = matches.group(1)
                else:
                    pattern = "(.+) \((.+)\)"
                    matches = re.search(pattern, token_td.text_content())
                    if matches:
                        txn_dict["token_name"] = matches.group(1)
                        txn_dict["token_symbol"] = matches.group(2)
                    else:
                        raise Exception(
                            "Got a Token Name/Symbol string we couldn't parse: %s"
                            % token_td.text_content()
                        )

                txn_dict["_type"] = "token"
                tx_details = self._scrape_transaction_details(txn_dict["hash"])
                txn_dict["details"] = tx_details
                txn_dict["value"] = tx_details["value"]
                txn_dict["block"] = tx_details["block"]
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

                txn_dict["_epoch_timestamp"] = tx_details["epoch"]

                txn_dict["details"] = tx_details
                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1

        transactions = self._add_extended_info(transactions)
        return transactions

    def scrape_nft_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://polygonscan.com/tokentxns-nft?a=%s&p=%s" % (
                address,
                page_num,
            )
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath("//div//table//tbody/tr")
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break
                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                txn_dict = dict(
                    hash=tx[1].strip(),
                    timestamp=tx[2],
                    direction=tx[5].replace("\xa0", ""),
                    # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    token_id=tx[7],
                )

                from_td = tds[4]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[6]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                token_td = tds[8]
                token_name = None
                try:
                    token_name = token_td.xpath(
                        './/span[@data-toggle="tooltip"]/@title'
                    )[0]
                except:
                    token_name = token_td.text_content().split("(")[0]
                txn_dict["token"] = token_name

                txn_dict["_type"] = "nft"

                tx_details = self._scrape_transaction_details(txn_dict["hash"])
                txn_dict["details"] = tx_details
                txn_dict["value"] = tx_details["value"]
                txn_dict["block"] = tx_details["block"]
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

                txn_dict["_epoch_timestamp"] = tx_details["epoch"]

                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1
        transactions = self._add_extended_info(transactions)
        return transactions

    # TODO: scrape ERC-1155 transactions (polygonscan lists them separately)

    def _add_extended_info(self, txs):
        for tx in txs:
            try:
                tx["_source"] = "polygonscan"
                tx["_chain"] = "polygon"
                tx["_chain_id"] = 137
                hash = tx["hash"].strip() if "hash" in tx else tx["parent_hash"].strip()
                tx["_id"] = hash
                tx["_api_responses"] = self._get_polygon_transaction_details_from_APIs(
                    hash
                )
            except Exception as err:
                raise Exception(str(err) + "\n" + str(tx))
        return txs

    def _get_polygon_transaction_details_from_APIs(self, hash):
        try:
            covalent_url = "https://api.covalenthq.com/v1/137/transaction_v2/{HASH}/?quote-currency=USD&format=JSON&no-logs=false&key={KEY}".format(
                KEY=setting(self.db)["COVALENT_KEY"], HASH=hash
            )

            # TODO: standardize this covalent 404 handling in other scrapers
            try:
                covalent_response = (cache.get(covalent_url)["value"],)
            except CacheGet404Exception as err:
                covalent_response = err.request_content
            api_responses = dict(covalent=covalent_response)
            return api_responses
        except:
            return {}


class FantomTransactionsFetcher(TransactionsFetcher):
    def __init__(self, db=None):
        self.db = db

    def scrape_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        URL = None
        while has_tx_rows:
            try:
                URL = "https://ftmscan.com/txs?a=%s&p=%s" % (address, page_num)
                c = cache.get(URL, REFRESH_INDEXES)
                soup = BeautifulSoup(c["value"], "html.parser")
                doc = html.fromstring(str(soup))
                tx_rows = doc.xpath('//*[@id="paywall_mask"]/table/tbody/tr')
                for tx_row in tx_rows:
                    if "There are no matching entries" in tx_row.text_content():
                        has_tx_rows = False
                        break
                    tds = tx_row.xpath(".//td")
                    tx = [td.text_content() for td in tds]
                    txn_dict = dict(
                        hash=tx[1].strip(),
                        block=tx[3],
                        timestamp=tx[4],
                        direction=tx[7].replace("\xa0", ""),
                        # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                        value=tx[9],
                        fee=tx[10],
                    )

                    method = tds[2].xpath(".//span[1]/@title")
                    txn_dict["method"] = method[0]

                    from_td = tds[6]
                    from_address, from_name = _get_address_and_name_from_etherscan_td(
                        from_td
                    )
                    txn_dict["from_address"] = from_address
                    txn_dict["from_address_name"] = from_name

                    to_td = tds[8]
                    to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                    txn_dict["to_address"] = to_address
                    txn_dict["to_address_name"] = to_name

                    txn_dict["_type"] = "normal"
                    txn_dict["_epoch_timestamp"] = _etherscan_timestamp_to_epoch(
                        txn_dict["timestamp"]
                    )

                    tx_details = self._scrape_transaction_details(txn_dict["hash"])
                    txn_dict["details"] = tx_details

                    txn_dict["fee"] = tx_details["fee"]
                    txn_dict["gas_price"] = tx_details["gas_price"]

                    txn_dict["_ftmscan_item_row_html"] = etree.tostring(tx_row)
                    self._log_tx(txn_dict)
                    transactions.append(txn_dict)
            except:
                pprint(URL)
                raise
            page_num += 1

        transactions = self._add_extended_info(transactions)
        return transactions

    def _scrape_transaction_details(self, hash):
        URL = "https://ftmscan.com/tx/%s" % hash.strip()
        # print('Scraping %s' % URL, file=sys.stderr)
        c = cache.get(URL, REFRESH_DETAILS)
        doc = html.document_fromstring(c["value"])
        tx_details = dict(tokens_transferred=[])

        timestamp_str = (
            doc.xpath(
                '//div[contains(text(), "Timestamp:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .text_content()
        )
        timestamp_str = timestamp_str[
            timestamp_str.find("(") + 1 : timestamp_str.find(")")
        ]
        format_str = "%b-%d-%Y %I:%M:%S %p +UTC"
        timestamp = datetime.strptime(timestamp_str, format_str).timestamp()
        tx_details["epoch"] = timestamp

        tx_gas_usage = doc.xpath('//span[@id="ContentPlaceHolder1_spanGasUsedByTxn"]')[
            0
        ].text_content()
        gas_used = int(tx_gas_usage.split("(")[0].strip().replace(",", ""))
        tx_details["gas_used"] = gas_used

        try:
            span = doc.xpath(
                '//*[@id="ContentPlaceHolder1_maintable"]//span[contains(@class, "u-label--success")]'
            )[0].text_content()
            status = "Success"
        except:
            status = "Failed"
        tx_details["status"] = status

        block = (
            doc.xpath(
                '//div[contains(text(), "Block:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .xpath(".//a")[0]
            .text_content()
        )
        tx_details["block"] = block

        fee_with_usd = (
            doc.xpath(
                '//div[contains(text(), "Transaction Fee:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .xpath('.//span[@id="ContentPlaceHolder1_spanTxFee"]')[0]
            .text_content()
        )
        fee = fee_with_usd.split("(")[0].strip()
        tx_details["fee"] = fee

        gas_price_with_usd = (
            doc.xpath(
                '//div[contains(text(), "Gas Price:")]/ancestor::div[contains(@class, "row")]'
            )[0]
            .xpath("./div[2]")[0]
            .xpath('.//span[@id="ContentPlaceHolder1_spanGasPrice"]')[0]
            .text_content()
        )
        gas_price = gas_price_with_usd.split("(")[0].strip()
        tx_details["gas_price"] = gas_price

        tx_details["actions"] = []
        tx_action_divs = doc.xpath(
            '//div[div[div[i/@data-content="Highlighted events of the transaction"]]]/*/ul[@id="wrapperContent"]/li/div[@class="media-body"]'
        )
        for div in tx_action_divs:
            parts = div.xpath("*")
            contents = [part.text_content() for part in parts]
            tx_details["actions"].append(" ".join(contents))

        tx_tokens_transferred_lis = doc.xpath(
            '//*[contains(text(), "Tokens Transferred")]/ancestor::div[contains(@class, "row")]/div[2]//li'
        )
        for li in tx_tokens_transferred_lis:
            try:
                scraper_func = _scrape_token_transferred_li_for_erc20
                scraper_func = (
                    _scrape_token_transferred_li_for_erc721
                    if "ERC-721 TokenID" in li.text_content()
                    else scraper_func
                )
                tokens_transferred = scraper_func.__call__(li)

                tx_details["tokens_transferred"].append(tokens_transferred)
            except Exception as err:
                pprint(hash)
                print(BeautifulSoup(etree.tostring(li)).prettify())
                raise

        value = doc.xpath('//*[@id="ContentPlaceHolder1_spanValue"]')[0].text_content()
        tx_details["value"] = value.split("(")[0].strip()

        # TODO: find a transaction that has these for Snowtrace, if any?
        # look for labels too
        # tx_details['labels'] = []
        # for label_a in doc.xpath("//a[starts-with(@href, '/txs/label')]"):
        #     tx_details['labels'].append(label_a.text_content().strip())

        tx_details["_ftmscan_html"] = c["value"]
        return tx_details

    def scrape_internal_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://ftmscan.com/txsInternal?a=%s&p=%s" % (address, page_num)
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath(
                '//div[contains(@class, "table-responsive")]/table/tbody/tr'
            )
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break

                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]

                # IMPORTANT: If this transaction row belongs to the same block as the previous row,
                # it's first two cells will be empty and its third cell, NOT fourth, is the one with parent hash
                parent_hash = None
                type = None
                if tx[0] != "":
                    parent_hash = tx[3].strip()
                    type = tx[4].strip()
                else:
                    parent_hash = tx[2].strip()
                    type = tx[3]
                txn_dict = dict(
                    parent_hash=parent_hash,
                    type=type,
                )
                if parent_hash == "call":
                    raise Exception("Got parent_hash call for %s" % address)

                from_td = tds[5]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[7]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                txn_dict["_type"] = "internal"

                tx_details = self._scrape_transaction_details(txn_dict["parent_hash"])
                txn_dict["details"] = tx_details
                txn_dict["value"] = tx_details["value"]
                txn_dict["block"] = tx_details["block"]
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]
                txn_dict["_epoch_timestamp"] = tx_details["epoch"]

                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1

        transactions = self._add_extended_info(transactions)
        return transactions

    def scrape_token_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://ftmscan.com/tokentxns?a=%s&p=%s" % (address, page_num)
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath(
                '//div[contains(@class, "table-responsive")]//table//tbody/tr'
            )
            for tx_row in tx_rows:
                if "There are no matching entries" in tx_row.text_content():
                    has_tx_rows = False
                    break
                tds = tx_row.xpath(".//td")
                tx = [td.text_content() for td in tds]
                txn_dict = dict(
                    hash=tx[1].strip(),
                    timestamp=tx[2],
                    direction=tx[5].replace("\xa0", ""),
                    # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    value=tx[7],
                )

                from_td = tds[4]
                from_address, from_name = _get_address_and_name_from_etherscan_td(
                    from_td
                )
                txn_dict["from_address"] = from_address
                txn_dict["from_address_name"] = from_name

                to_td = tds[6]
                to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                txn_dict["to_address"] = to_address
                txn_dict["to_address_name"] = to_name

                token_td = tds[8]
                # HACK: This is ugly. if the token name is short enough it comes through without a span,
                # but if it's long like 'Wrapped Ethereum' it shows up in a span. So we need to treat
                # these cases differently
                token_name_span = token_td.xpath("a/span/@title")
                if len(token_name_span) > 0:
                    # In these cases, the token name is on a title attribute and
                    # the (TOKEN_SYMBOL) part of the text is only in the text node,
                    # so find and add that too...
                    txn_dict["token_name"] = token_td.xpath("a/span/@title")[0]
                    matches = re.search("\((\w*)\)", token_td.text_content())
                    if matches:
                        txn_dict["token_symbol"] = matches.group(1)
                else:
                    pattern = "(.+) \((.+)\)"
                    matches = re.search(pattern, token_td.text_content())
                    if matches:
                        txn_dict["token_name"] = matches.group(1)
                        txn_dict["token_symbol"] = matches.group(2)
                    else:
                        raise Exception(
                            "Got a Token Name/Symbol string we couldn't parse: %s"
                            % token_td.text_content()
                        )

                txn_dict["_type"] = "token"
                txn_dict["_epoch_timestamp"] = _etherscan_timestamp_to_epoch(
                    txn_dict["timestamp"]
                )

                tx_details = self._scrape_transaction_details(txn_dict["hash"])
                txn_dict["details"] = tx_details
                txn_dict["fee"] = tx_details["fee"]
                txn_dict["gas_price"] = tx_details["gas_price"]

                self._log_tx(txn_dict)
                transactions.append(txn_dict)
            page_num += 1

        transactions = self._add_extended_info(transactions)
        return transactions

    def scrape_nft_transactions(self, address):
        # TODO handle errors
        page_num = 1
        has_tx_rows = True
        transactions = []
        while has_tx_rows:
            URL = "https://ftmscan.com/tokentxns-nft?a=%s&p=%s" % (address, page_num)
            c = cache.get(URL, REFRESH_INDEXES)
            soup = BeautifulSoup(c["value"], "html.parser")
            doc = html.fromstring(str(soup))
            tx_rows = doc.xpath("//div//table//tbody/tr")
            for tx_row in tx_rows:
                try:
                    if "There are no matching entries" in tx_row.text_content():
                        has_tx_rows = False
                        break
                    tds = tx_row.xpath(".//td")
                    tx = [td.text_content() for td in tds]
                    txn_dict = dict(
                        hash=tx[1].strip(),
                        timestamp=tx[2],
                        direction=tx[5].replace("\xa0", ""),
                        # HACK: IN has these &nbsps; where OUT doesn't so we clean them here
                    )

                    from_td = tds[4]
                    from_address, from_name = _get_address_and_name_from_etherscan_td(
                        from_td
                    )
                    txn_dict["from_address"] = from_address
                    txn_dict["from_address_name"] = from_name

                    to_td = tds[6]
                    to_address, to_name = _get_address_and_name_from_etherscan_td(to_td)
                    txn_dict["to_address"] = to_address
                    txn_dict["to_address_name"] = to_name

                    token_id = tds[7].text_content()
                    txn_dict["token_id"] = token_id

                    token_name = tds[8].text_content()
                    txn_dict["token_name"] = token_name

                    txn_dict["_type"] = "nft"
                    txn_dict["_epoch_timestamp"] = _etherscan_timestamp_to_epoch(
                        txn_dict["timestamp"]
                    )

                    tx_details = self._scrape_transaction_details(txn_dict["hash"])
                    txn_dict["fee"] = tx_details["fee"]
                    txn_dict["gas_price"] = tx_details["gas_price"]
                    txn_dict["details"] = tx_details

                    self._log_tx(txn_dict)
                    transactions.append(txn_dict)
                except:
                    pprint(URL)
                    raise
            page_num += 1
        transactions = self._add_extended_info(transactions)
        return transactions

    def _add_extended_info(self, txs):
        for tx in txs:
            try:
                tx["_source"] = "ftmscan"
                tx["_chain"] = "fantom"
                tx["_chain_id"] = 250
                hash = tx["hash"].strip() if "hash" in tx else tx["parent_hash"].strip()
                tx["_id"] = hash
                tx["_api_responses"] = self._get_fantom_transaction_details_from_APIs(
                    hash
                )
            except Exception as err:
                raise Exception(str(err) + "\n" + str(tx))
        return txs

    def _get_fantom_transaction_details_from_APIs(self, hash):
        try:
            covalent_url = "https://api.covalenthq.com/v1/250/transaction_v2/{HASH}/?quote-currency=USD&format=JSON&no-logs=false&key={KEY}".format(
                KEY=setting(self.db)["COVALENT_KEY"], HASH=hash
            )
            api_responses = dict(
                covalent=cache.get(covalent_url)["value"],
            )
            return api_responses
        except:
            return {}


class HarmonyTransactionsFetcher(TransactionsFetcher):
    def __init__(self, db):
        self.db = db

    def _scrape_transaction_details(self, hash):
        return get_harmony_tx(hash.strip())


"""
As of Sep 15 2022 (https://twitter.com/DeBankCloud/status/1570383634812801026) the free OpenAPI has discontinued.
The API has shifted to become a part of "DeBank Cloud" which has a pay/tx model.

As of 2022-12, you pay 200 USDC for 1M "compute units" ($0.0002/unit) with each API call costing an arbitrary # of units. https://cloud.debank.com/#section-openapi
* Tx History = 20 items for 5 units ($0.00005/tx, $0.05/1000txs)

As a stopgap, we are defaulting to the DeBankBrowserTransactionsFetcher for pulling transaction history.
"""


class DeBankTransactionsFetcher:
    def __init__(self, db=None):
        self.db = db
        self.DEBANK_KEY = setting(self.db).get("DEBANK_KEY")
        self.headers = {
            "accept": "application/json",
            "AccessKey": self.DEBANK_KEY,
        }

    def scrape_history(self, address):
        fetch_more = True
        transactions = []
        projects = {}
        tokens = {}
        start_time = 0

        if not self.DEBANK_KEY:
            raise Exception(
                "No DEBANK_KEY in settings. You can't use the DeBank OpenAPI without paid compute units"
            )

        while fetch_more:
            URL = (
                "https://pro-openapi.debank.com/v1/user/all_history_list?start_time=%s&id=%s"
                % (int(start_time), address)
            )
            c = cache.get(URL, True, headers=self.headers)
            j = json.loads(c["value"])

            if "error_code" in j:
                raise Exception(
                    "Got error from DeBank API. URL:`%s` RESPONSE: `%s`" % (URL, j)
                )

            if "project_dict" in j:
                for id in j["project_dict"]:
                    projects[id] = j["project_dict"][id]

            if "token_dict" in j:
                for id in j["token_dict"]:
                    tokens[id] = j["token_dict"][id]

            for tx in j["history_list"]:
                # Update start_time which we use for paginating full history from DeBank API
                start_time = tx["time_at"]

                if "project_id" in tx and tx["project_id"] in projects:
                    tx["_project"] = projects[tx["project_id"]]

                for r in tx["receives"]:
                    if "token_id" in r and r["token_id"] in tokens:
                        r["_token"] = tokens[r["token_id"]]

                for r in tx["sends"]:
                    if "token_id" in r and r["token_id"] in tokens:
                        r["_token"] = tokens[r["token_id"]]

                if tx["cate_id"] == "approve":
                    tx["_token"] = tokens[tx["token_approve"]["token_id"]]

                transactions.append(tx)

            if len(j["history_list"]) == 0:
                fetch_more = False

        for t in transactions:
            t["_source"] = "debank"
            t["_epoch_timestamp"] = int(t["time_at"])
            t["_id"] = t["id"].strip()
            t["_chain"] = normalized_chain_value(t["chain"])

        return transactions


class DeBankBrowserTransactionsFetcher:
    def __init__(self, db=None):
        self.db = db
        self.driver = webdriver.Chrome()
        self.driver.implicitly_wait(20)

    def scrape_history(self, address, until_date=None):
        transactions = []
        projects = {}
        tokens = {}

        # Stop scraping at this string date...
        # until_date = '2022'
        # until_date = '2022-09-01'
        try:
            until_epoch = arrow.get(until_date).timestamp()
        except:
            until_epoch = 0

        for history_response in self.scrape_all_history_responses(address, until_epoch):
            if not history_response:
                print("Empty Response, moving on...")
                # DeBank Browser Scraping API can just decide to stop...
                break

            # Skip invlid JSON responses...
            try:
                j = json.loads(history_response)
            except:
                print("JSON Decode Error, skipping...")
                pprint(history_response)
                continue

            if j["error_code"] != 0:
                raise Exception(
                    f"Got error from DeBank History Scraping via browser. RESPONSE: `{j}`"
                )
            else:
                j = j["data"]

            for id in j["project_dict"]:
                projects[id] = j["project_dict"][id]

            for id in j["token_dict"]:
                tokens[id] = j["token_dict"][id]

            for tx in j["history_list"]:
                if "project_id" in tx and tx["project_id"] in projects:
                    tx["_project"] = projects[tx["project_id"]]

                for r in tx["receives"]:
                    if "token_id" in r and r["token_id"] in tokens:
                        r["_token"] = tokens[r["token_id"]]

                for r in tx["sends"]:
                    if "token_id" in r and r["token_id"] in tokens:
                        r["_token"] = tokens[r["token_id"]]

                if tx["cate_id"] == "approve":
                    tx["_token"] = tokens[tx["token_approve"]["token_id"]]

                transactions.append(tx)

        for t in transactions:
            t["_source"] = "debank"
            t["_epoch_timestamp"] = int(t["time_at"])
            t["_id"] = t["id"].strip()
            t["_chain"] = normalized_chain_value(t["chain"])

        return transactions

    def scrape_all_history_responses(self, address, until_epoch=0):
        url = f"https://debank.com/profile/{address}/history"
        xpath = """//button[normalize-space()="Load More"]"""

        print("Getting History...")
        self.driver.get(url)
        button = self.driver.find_element("xpath", xpath)
        url_to_capture = "https://api.debank.com/history/list"

        while button:
            try:
                button = self.driver.find_element("xpath", xpath)
            except:
                button = None

            # Look at the last history_list request to see if we should stop at until_epoch
            requests = [
                r for r in self.driver.requests if r.url.startswith(url_to_capture)
            ]
            r = requests[-1]
            history_response = decode(
                r.response.body, r.response.headers.get("Content-Encoding", "identity")
            )
            j = json.loads(history_response)
            for tx in j["data"]["history_list"]:
                if tx["time_at"] <= until_epoch:
                    print("Stopping at until_epoch")
                    button = None
                    break

            # OK, let's click
            if button:
                print("Fetching more...")
                button.click()
            time.sleep(2)

        # Sat to do this again, but that's life...
        requests = [r for r in self.driver.requests if r.url.startswith(url_to_capture)]
        responses = [
            decode(
                r.response.body, r.response.headers.get("Content-Encoding", "identity")
            )
            for r in requests
        ]
        self.driver.close()

        # Responses now contains a list of all the JSON API responses
        return responses


class TransactionsUnifier:
    def __init__(self, chain, address):
        self.etherscan = EtherscanTransactionsFetcher(db)
        self.avalanche = AvalancheTransactionsFetcher(db)
        self.polygon = PolygonTransactionsFetcher(db)
        self.fantom = FantomTransactionsFetcher(db)

        if setting(db).get("DEBANK_KEY"):
            self.debank = DeBankTransactionsFetcher(db)
        else:
            self.debank = DeBankBrowserTransactionsFetcher()

        self.chain = chain
        self.address = address

    def all_transactions(self):
        # TODO: as we support ingesting from more chains, add them in here.
        if self.chain not in "ethereum":
            return []
        txns = [
            # self.etherscan.scrape_transactions(self.address),
            # self.etherscan.scrape_internal_transactions(self.address),
            # self.etherscan.scrape_token_transactions(self.address),
            # self.etherscan.scrape_nft_transactions(self.address),
            # self.avalanche.scrape_transactions(self.address),
            # self.avalanche.scrape_internal_transactions(self.address),
            # self.avalanche.scrape_token_transactions(self.address),
            # self.avalanche.scrape_nft_transactions(self.address),
            # self.polygon.scrape_transactions(self.address),
            # self.polygon.scrape_internal_transactions(self.address),
            # self.polygon.scrape_token_transactions(self.address),
            # self.polygon.scrape_nft_transactions(self.address),
            # self.fantom.scrape_transactions(self.address),
            # self.fantom.scrape_internal_transactions(self.address),
            # self.fantom.scrape_token_transactions(self.address),
            # self.fantom.scrape_nft_transactions(self.address),
            self.debank.scrape_history(self.address),
        ]
        flattened_txs = []
        for sublist in txns:
            flattened_txs.extend(sublist)
        flattened_txs.sort(key=lambda tx: tx["_epoch_timestamp"])

        return flattened_txs

    def unified_transactions(self):
        def unified_key(t):
            try:
                id = t.get("_id") or t.get("parent_hash")
                return str(t["_chain"]) + ":" + str(id)
            except:
                pprint(elide_transaction(t))
                raise

        #  this is a dict where key is unified_key ('avalanche:12345') and the value is a dict transaction thing { }
        unified_transactions_by_hash = {}

        all_transactions = self.all_transactions()

        for t in all_transactions:
            try:
                unified = {}

                if unified_key(t) in unified_transactions_by_hash:
                    # If we have seen the transaction before, get the current unified version of it
                    unified = unified_transactions_by_hash[unified_key(t)]

                    # If this tx exists for this source, we have a problem if we clobber it...
                    # This can happen if the txn was seen in the normal txns list and then also in the erc20 txns list, for example
                    # In this case, we will only overwrite if the tx['_type'] != 'normal' since the 'normal' one is the one we know we got from the
                    # normal txns index, which has a better chance of having the address book information for the addresses
                    if t["_source"] in unified_transactions_by_hash[unified_key(t)]:
                        existing_t = unified_transactions_by_hash[unified_key(t)][
                            t["_source"]
                        ]
                        if existing_t["_type"] == "normal":
                            print(
                                f"Skipping duplicate transaction {t['_id']} of type {t['_type']}"
                            )
                            continue

                t_source = t["_source"]
                unified[t_source] = t
                unified_transactions_by_hash[unified_key(t)] = unified
            except Exception as err:
                pprint(elide_transaction(t))
                raise

        def get_tx_attr(tx, attr):
            keys = ["debank", "etherscan", "snowtrace", "polygonscan", "ftmscan"]
            try:
                if isinstance(attr, str):
                    for k in keys:
                        if k in tx:
                            return tx[k][attr]

                if isinstance(attr, list):
                    for k in keys:
                        if k not in tx:
                            continue
                        o = tx.copy()[k]
                        ac = attr.copy()
                        found = False
                        while len(ac) > 0:
                            try:
                                o = o[ac[0]]
                                ac = ac[1:]
                                found = True
                            except:
                                break
                        if found:
                            return o
            except:
                print(
                    "Couldn't get attr %s from any of these keys %s in tx %s"
                    % (attr, keys, elide_transaction(tx))
                )
                raise

        for id, ut in unified_transactions_by_hash.items():
            try:
                # Add some root level attrs for each transaction
                # They shoudl exist on each source, so just use the debank value for each, which assumes that we get a debank response for each
                # chain = ut.get('debank') or ut.get('etherscan') or ut.get('snowtrace') or or ut.get('polygonscan') or ut.get('ftmscan')

                chain = get_tx_attr(ut, "_chain")
                ut["chain"] = normalized_chain_value(chain)
                ut["address"] = self.address
                timestamp = get_tx_attr(ut, "_epoch_timestamp")
                ut["timestamp"] = int(timestamp)
                ut["hash"] = get_tx_attr(ut, "_id")
                ut["status"] = get_tx_attr(ut, ["details", "status"])
            except:
                pprint(elide_transaction(ut))
                raise

        return unified_transactions_by_hash


def write_to_file(unified_transactions, filename):
    with open(f"./{filename}", "w") as f:
        for _, t in unified_transactions.items():
            f.write(
                json.dumps(
                    elide_transaction(t),
                    cls=MyEncoder,
                    indent=4,
                    sort_keys=True,
                    ensure_ascii=True,
                )
                + "\n\n"
            )


def save_to_db(unified_transactions):
    # TODO: consider combining into one (or chunk to multiple) transactions for speed
    sql = """REPLACE INTO tx_chain
             (chain, address, hash, timestamp, raw_data_lzma)
             VALUES
             (?, ?, ?, ?, ?)
          """
    items_params = []
    for hash in tqdm(unified_transactions, desc="Saving unified txs to db"):
        if len(items_params) == 1000:
            db.execute_many(sql, items_params)
            items_params = []
        else:
            tx = unified_transactions[hash]
            raw_data_json = json.dumps(
                tx, cls=MyEncoder, indent=4, sort_keys=True, ensure_ascii=False
            ).encode("utf8")
            lzmac = lzma.LZMACompressor()
            raw_data_lzma = lzmac.compress(raw_data_json)
            raw_data_lzma += lzmac.flush()

            params = [
                tx["chain"],
                tx["address"],
                tx["hash"],
                tx["timestamp"],
                raw_data_lzma,
            ]
            items_params.append(params)
    db.execute_many(sql, items_params)


def scrape_entity_transactions(entity_name):
    print(f"Entity: {entity_name}")
    print("---")
    # Get List of Accounts
    sql = """SELECT address.label, address.chain, address.address
           FROM address, entity
           WHERE address.entity_id = entity.id
           AND entity.name = ?
           AND address.chain not like 'import.%'  -- Don't scrape imported 'addresses' (these are there to properly link imported txns to TxLedgers)
           ORDER BY ord, label
        """
    results = db.query(sql, entity_name)

    for wallet in results:
        label = wallet[0]
        chain = wallet[1]
        address = wallet[2]

        print(f"Processsing {label} ({chain}: {address} )")
        tu = TransactionsUnifier(chain, address)
        unifieds = tu.unified_transactions()

        save_to_db(unifieds)


chain_mappings = dict(
    ethereum=1,
    polygon=137,
    avalanche=43114,
    fantom=250,
)


def chain_id(name):
    return chain_mappings[name]


def elide_transaction(d):
    keys_to_elide = [
        "_etherscan_html",
        "_snowtrace_html",
        "_polygonscan_html",
        "_ftmscan_html",
        "_etherscan_item_row_html",
        "_snowtrace_item_row_html",
        "_polygonscan_item_row_html",
        "_ftmscan_item_row_html",
        "_api_responses",
    ]
    for k in d:
        if k in keys_to_elide:
            d[k] = "__ELIDED__"
        if isinstance(d[k], dict):
            elide_transaction(d[k])
        if isinstance(d[k], list):
            [elide_transaction(j) for j in d[k] if isinstance(j, dict)]
    return d


def get_covalent_tx(api_key, chain_id_or_name, hash):
    cid = (
        chain_id(chain_id_or_name)
        if isinstance(chain_id_or_name, str)
        else chain_id_or_name
    )
    url = f"https://api.covalenthq.com/v1/{cid}/transaction_v2/{hash}/?quote-currency=USD&format=JSON&no-logs=false&key={api_key}"
    return cache.get(url)["value"]


""" For our other chain API fetchers, here are the attributes we need to return so that the chain-generate-ledgertxs can consume their data easily:
    from_address
    to_address
    details
        - fee
        - gas_price
        - gas_used
"""


def get_harmony_tx(hash):
    """Harmony API Docs https://documenter.getpostman.com/view/6221615/Szt7BB28#ff4b8f6a-7723-472c-97e3-06c4221de383"""

    # Common URL and Headers
    url = "https://api.s0.t.hmny.io"
    headers = {"Content-Type": "application/json"}

    # Get to/from/gas_price from the Transaction
    data = {
        "jsonrpc": "2.0",
        "method": "hmyv2_getTransactionByHash",
        "params": [hash],
        "id": 1,
    }
    j = json.loads(
        cache.get_v2(url, method="POST", headers=headers, data=data)["value"]
    )["result"]
    gas_price = j["gasPrice"]
    to_address = j["to"]
    from_address = j["from"]

    # Get gas_used from the Receipt
    data = {
        "jsonrpc": "2.0",
        "method": "hmyv2_getTransactionReceipt",
        "params": [hash],
        "id": 1,
    }
    j = json.loads(
        cache.get_v2(url, method="POST", headers=headers, data=data)["value"]
    )["result"]
    gas_used = j["gasUsed"]

    # Return a result with the keys care about
    return dict(
        from_address=from_address,
        to_address=to_address,
        details=dict(
            gas_used=gas_used, gas_price=gas_price, fee=((gas_used * gas_price) * 1e-18)
        ),
    )


def get_optimism_tx(hash):
    """
    Optimism API via Alchemy: https://docs.alchemy.com/alchemy/apis/optimism-api
    """

    # Common URL and Headers
    url = f"https://opt-mainnet.g.alchemy.com/v2/{setting['ALCHEMY_KEY']}"
    headers = {"Content-Type": "application/json"}

    # Get to/from/gas_price from the Transaction
    data = {
        "jsonrpc": "2.0",
        "method": "eth_getTransactionByHash",
        "params": [hash],
        "id": 0,
    }
    j = json.loads(
        cache.get_v2(url, method="POST", headers=headers, data=data)["value"]
    )["result"]
    to_address = j["to"]
    from_address = j["from"]
    gas_price = int(j["gas"], 16)

    # Get gas_used from the Receipt
    data = {
        "jsonrpc": "2.0",
        "method": "eth_getTransactionReceipt",
        "params": [hash],
        "id": 0,
    }
    j = json.loads(
        cache.get_v2(url, method="POST", headers=headers, data=data)["value"]
    )["result"]
    gas_used = int(j["gasUsed"], 16)

    # Return a result with the keys care about
    # TODO - this doesn't look right. Optimism has L1 and L2 fees. What do we do here?
    return dict(
        from_address=from_address,
        to_address=to_address,
        details=dict(
            gas_used=gas_used, gas_price=gas_price, fee=((gas_used * gas_price) * 1e-18)
        ),
    )


def get_tx_chain(db, hash):
    sql = """SELECT chain, address, hash, timestamp, raw_data_lzma
           FROM tx_chain
           WHERE hash = ?
        """
    results = db.query(sql, hash)

    result = results[0]
    chain = result[0]
    hash = result[2]
    timestamp = result[3]

    lzmad = lzma.LZMADecompressor()
    raw_data_str = lzmad.decompress(result[4])
    raw_data = json.loads(raw_data_str)

    return dict(chain=chain, hash=hash, timestamp=timestamp, raw_data=raw_data)
