import lzma
import json

import arrow

from bin.map_assets import main as map_assets_main
from perfi.ingest.chain import MyEncoder
from perfi.asset import update_assets_from_txchain
from perfi.price import CoinPrice, PriceFeed


def setup_entity(test_db, name, addresses):
    test_db.execute("INSERT INTO entity (name) VALUES (?)", name)
    entity_id = test_db.query("SELECT id from entity where name = ?", name)[0][0]
    for chain, addr in addresses:
        test_db.execute(
            "INSERT INTO address (chain, address, entity_id) VALUES (?, ?, ?)",
            [chain, addr, entity_id],
        )


class MockPriceFeed:
    def __init__(self):
        self.stubs = dict()
        self.price_feed = PriceFeed()

    def stub_key(self, epoch, coin_id):
        return f"{epoch}:{coin_id}"

    def stub_price(self, epoch_or_datestr, coin_id, price):
        if type(epoch_or_datestr) == str:
            epoch = int(arrow.get(epoch_or_datestr).timestamp())
        else:
            epoch = int(epoch_or_datestr)

        key = self.stub_key(epoch, coin_id)
        self.stubs[key] = CoinPrice("stubbed_price_feed", coin_id, epoch, price)

    def get(self, coin_id, epoch):
        key = self.stub_key(epoch, coin_id)
        try:
            return self.stubs[key]
        except KeyError:
            raise Exception(f"No stubbed price for {key}")

    def clear_stubs(self):
        self.stubs = dict()

    def map_asset(self, chain, asset_tx_id, symbol_fallback=False):
        return self.price_feed.map_asset(chain, asset_tx_id, symbol_fallback)

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


class TxFactory:
    def __init__(self, db=None, address=None, chain=None, asset_map=None):
        self.address = address
        self.chain = chain
        self.db = db
        self.fake_hash_counter = 0
        self.asset_map = asset_map

    def get_asset_tx_id(self, symbol):
        manual_maps = {
            "avalanche:AVAX": "avax",
            "ethereum:ETH": "eth",
            "fantom:FTM": "ftm",
            "polygon:MATIC": "matic",
            "avalanche:avWAVAX": "0xdfe521292ece2a4f44242efbcd66bc594ca9714b",
        }
        key = f"{self.chain}:{symbol}"
        if key in manual_maps:
            return manual_maps[key]
        try:
            return self.asset_map[f"{self.chain}:{symbol}"]
        except KeyError:
            raise Exception(f"Couldnt get asset_tx_id for {self.chain}:{symbol}")

    def tx(self, **kwargs):
        chain = kwargs.get("chain") or self.chain
        timestamp = kwargs.get("timestamp") or 1
        to_address = kwargs.get("to_address") or self.address
        from_address = kwargs.get("from_address") or self.address
        to_address_name = kwargs.get("to_address_name")
        from_address_name = kwargs.get("from_address_name") or None
        fee = kwargs.get("fee") or 0.00
        fee_usd = kwargs.get("fee_usd") or 0.00
        gas_price = kwargs.get("gas_price") or 1
        gas_used = kwargs.get("gas_used") or 1
        hash = kwargs.get("hash")
        if not hash:
            self.fake_hash_counter += 1
            hash = f"__FAKE_HASH_{self.fake_hash_counter}__"

        if (kwargs.get("direction") == "IN" or kwargs.get("ins")) and not to_address:
            to_address = kwargs.get("to_address") or self.address

        if (
            kwargs.get("direction") == "OUT" or kwargs.get("outs")
        ) and not from_address:
            from_address = kwargs.get("from_address") or self.address

        def debank_tx():
            receives = []
            sends = []
            native_coin = dict(
                ethereum="ETH",
                avalanche="AVAX",
                fantom="FTM",
                polygon="MATIC",
            )
            tok = lambda amount, symbol, tx_asset_id: dict(
                from_addr=from_address,
                to_addr=to_address,
                amount=amount,
                _token=dict(
                    id=tx_asset_id if tx_asset_id else self.get_asset_tx_id(symbol),
                    chain=chain,
                    symbol=symbol,
                    name=f"__TOKEN_NAME_FOR__{symbol}__",
                ),
            )

            if "ins" in kwargs:
                for s in kwargs["ins"]:
                    tx_asset_id = None
                    amount, symbol_andmaybe_assetid = s.split(" ")
                    if "|" in symbol_andmaybe_assetid:
                        symbol, tx_asset_id = symbol_andmaybe_assetid.split("|")
                    else:
                        symbol = symbol_andmaybe_assetid
                    amount = float(amount)
                    receives.append(tok(amount, symbol, tx_asset_id))
            elif kwargs.get("direction") == "IN":
                amount = kwargs["amount"]
                symbol = native_coin[self.chain]
                receives.append(tok(amount, symbol))

            if "outs" in kwargs:
                for s in kwargs["outs"]:
                    tx_asset_id = None
                    amount, symbol_andmaybe_assetid = s.split(" ")
                    if "|" in symbol_andmaybe_assetid:
                        symbol, tx_asset_id = symbol_andmaybe_assetid.split("|")
                    else:
                        symbol = symbol_andmaybe_assetid
                    amount = float(amount)
                    sends.append(tok(amount, symbol, tx_asset_id))
            elif kwargs.get("direction") == "OUT":
                amount = kwargs["amount"]
                symbol = native_coin[self.chain]
                sends.append(tok(amount, symbol))

            debank_name = kwargs.get("debank_name")
            if not debank_name:
                if "ins" in kwargs and "outs" not in kwargs:
                    debank_name = "receive"
                if "ins" not in kwargs and "outs" in kwargs:
                    debank_name = "send"

            return dict(
                tx=dict(
                    name=debank_name,
                    from_addr=from_address,
                    to_addr=to_address,
                    eth_gas_fee=fee,
                    usd_gas_fee=fee_usd,
                ),
                receives=receives,
                sends=sends,
                cate_id=None,
            )

        tx = dict(
            chain=self.chain,
            address=self.address,
            hash=hash,
            timestamp=timestamp,
            __explorer_name__=dict(
                from_address=from_address,
                to_address=to_address,
                from_address_name=from_address_name,
                to_address_name=to_address_name,
                details=dict(
                    fee=fee,
                    gas_price=gas_price,
                    gas_used=gas_used,
                ),
            ),
            debank=debank_tx(),
        )

        explorer_mapping = {
            "ethereum": "etherscan",
            "avalanche": "snowtrace",
            "polygon": "polygonscan",
            "fantom": "ftmscan",
        }

        explorer_key = explorer_mapping[self.chain]
        tx[explorer_key] = tx["__explorer_name__"]
        tx.pop("__explorer_name__")

        self._save_chain_tx(tx)
        return tx

    def _save_chain_tx(self, tx):
        raw_data_json = json.dumps(
            tx, cls=MyEncoder, indent=4, sort_keys=True, ensure_ascii=False
        ).encode("utf8")
        lzmac = lzma.LZMACompressor()
        raw_data_lzma = lzmac.compress(raw_data_json)
        raw_data_lzma += lzmac.flush()
        sql = """REPLACE INTO tx_chain
                 (chain, address, hash, timestamp, raw_data_lzma)
                 VALUES
                 (?, ?, ?, ?, ?)
              """
        params = [
            tx["chain"],
            tx["address"],
            tx["hash"],
            tx["timestamp"],
            raw_data_lzma,
        ]
        self.db.execute(sql, params)


def map_assets():
    map_assets_main()
