import csv
import io
import re
from decimal import Decimal

import arrow
import openpyxl

from .chain import save_to_db
from ..constants.assets import FIAT_SYMBOLS
from ..price import PriceFeed

price_feed = PriceFeed()


def normalize_asset_tx_id(str):
    if str.upper() in FIAT_SYMBOLS:
        return f"FIAT:{str.upper()}"
    return str.lower()


# Sometimes our price unit is not in USD (could be other fiat or even other crypto).
# This function takes in a price_symbol, a price_value, and a timestamp and gives back a price_usd and a price_source string.
def get_price_usd_and_source(price_symbol: str, price_value: Decimal, timestamp: int):
    if price_symbol.upper() == "USD":
        # Price is USD already so just take it in as-is
        price_usd = price_value
        price_source = "exchange_file_usd"
    elif price_symbol.upper() in FIAT_SYMBOLS:
        # Price is in another fiat, so convert to USD
        price_usd, price_source = price_feed.convert_fiat(
            price_symbol.upper(), "USD", price_value, timestamp
        )
        price_source = "exchange_file_converted_from_fiat"
    else:
        mapped_asset = price_feed.map_asset("import", price_symbol.lower(), True)
        coin_price = price_feed.get(mapped_asset["asset_price_id"], timestamp)
        price_usd = Decimal(coin_price.price) * price_value
        price_source = coin_price.source
    return price_usd, price_source


class BitcoinTaxImporter:
    def raw_transactions_csv_to_chain_txns(
        self, csv_file, entity_address_for_imports=None, exchange_account_id=None
    ):
        txns = []
        reader = csv.DictReader(csv_file)
        for r in reader:
            # From CSV
            date = arrow.get(r["Date"], "YYYY-MM-DD HH:mm:ss")
            timestamp = int(date.timestamp())
            symbol = r["Symbol"]
            account = r["Account"]
            amount = Decimal(r["Volume"])
            price = Decimal(r["Price"])
            price_currency = r["Currency"]
            basis = Decimal(r["Total"])
            fee_symbol = r["FeeCurrency"]
            fee_amount = r["Fee"]

            # Fixup for symbols
            if symbol == "GNT":
                symbol = "GLM"

            asset_map = {
                "BAT": "0x0d8775f648430679a709e98d2b0cb6250d2887ef",
                "GLM": "0x7dd9c5cba05e151c895fde1cf355c9a1d5da6429",
                "USDT": "0xdac17f958d2ee523a2206206994597c13d831ec7",
                "ZRX": "0xe41d2489571d322189246dafa5ebde1f4699f498",
            }

            # Vars that must be assigned and put into the tx dict below
            chain = "import.bitcointax"
            hash = f"bitcoin.tax:{entity_address_for_imports}:{account}:{timestamp}:{symbol}:{amount}:{price}:{basis}"
            direction = "IN"
            if symbol in asset_map:
                asset_tx_id = asset_map[symbol]
            else:
                asset_tx_id = symbol.lower()
            # amount
            # timestamp
            tx_ledger_type = f"BitcoinTax.costbasis"
            # symbol

            # Useful for from/to
            default_from_to = f"BitcoinTax:{exchange_account_id}"

            ### Unlike other exchange importer classes, we never have any SELLS, because the Bitcoin.tax costbasis importer takes starting positions for the year to give you existing costbasis lots

            # Receive - will always be the asset
            receives = [
                dict(
                    asset_tx_id=asset_tx_id,
                    amount=abs(amount),
                    tx_ledger_type=tx_ledger_type,
                    symbol=symbol,
                    from_address=default_from_to,
                    to_address=default_from_to,
                    isfee=0,
                )
            ]

            sends = []
            # Fiat paid out...
            sends = [
                dict(
                    asset_tx_id=normalize_asset_tx_id(price_currency),
                    amount=abs(amount * price),
                    tx_ledger_type=tx_ledger_type,
                    symbol=price_currency,
                    from_address=default_from_to,
                    to_address=default_from_to,
                    isfee=0,
                )
            ]
            # Sends - if fee
            if Decimal(fee_amount) > 0:
                sends.append(
                    dict(
                        asset_tx_id=normalize_asset_tx_id(fee_symbol),
                        amount=abs(Decimal(fee_amount)),
                        tx_ledger_type="fee",
                        symbol=fee_symbol,
                        from_address=default_from_to,
                        to_address=default_from_to,
                        isfee=1,
                    )
                )

            tx = dict(
                # Required for TxLedger
                # chain must start with 'import.' e.g. 'import.bitcointax'
                chain=chain,
                address=entity_address_for_imports,
                hash=hash,
                timestamp=timestamp,
                asset_tx_id=normalize_asset_tx_id(asset_tx_id),
                amount=abs(amount),
                direction=direction,
                tx_ledger_type=tx_ledger_type,
                symbol=symbol,
                isfee=0,
                from_address=default_from_to,
                to_address=default_from_to,
                sends=sends,
                receives=receives,
                # If there is a fee, add:
                fee_amount=fee_amount,
                fee_symbol=fee_symbol,
                # Not required for a TxLedger but putting here since we have it, why not keep it in raw_data
                costbasis_usd=basis,
                price=price,
                price_currency=price_currency,
                account=account,
            )
            txns.append(tx)

        return txns

    def do_import(self, csv_file, entity_address_for_imports, exchange_account_id):
        txns = self.raw_transactions_csv_to_chain_txns(
            csv_file,
            entity_address_for_imports=entity_address_for_imports,
            exchange_account_id=exchange_account_id,
        )
        # Convert to unified transaction format
        unifieds = {}
        for tx in txns:
            unifieds[f"{tx['chain']}:{tx['hash']}"] = tx
        save_to_db(unifieds)


class KrakenImporter:
    # For info on the export format, see https://support.kraken.com/hc/en-us/articles/360001169383-How-to-interpret-Ledger-history-fields
    asset_code_mapping = {
        # https://support.kraken.com/hc/en-us/articles/360001185506-How-to-interpret-asset-codes
        # Kraken Asset -> [symbol, asset_price_id]
        "XETC": ["etc", "ethereum-classic"],
        "XETH": ["eth", "ethereum"],
        "XICN": None,  # Unsure how to map this
        "XLTC": ["ltc", "litecoin"],
        "XMLN": ["mln", "enzyme"],
        "XNMC": ["mnc", "namecoin"],
        "XREP": ["rep", "augur"],
        "XREPV2": ["rep", "augur"],
        "XXBT": ["btc", "bitcoin"],
        "XXDG": ["doge", "dogecoin"],
        "XXLM": ["xlm", "stellar"],
        "XXMR": ["mnr", "monero"],
        "XXRP": ["xrp", "xrp"],
        "XXTZ": ["xtz", "tezos"],
        "XXVN": None,  # Unsure how to map this
        "XZEC": ["zec", "zcash"],
    }

    def get_symbol(self, asset):
        if asset.startswith("Z"):
            # Kraken docs say assets with Z are fiat currency, so see if we know how to track this currency.
            symbol = asset[1:]
            if symbol in FIAT_SYMBOLS:
                return symbol
            else:
                raise Exception(
                    f"This asset code in Kraken represents a fiat currency that we don't know how to convert prices for yet. Don't know what to do so throwing exception. Asset: {asset}"
                )
        try:
            return self.asset_code_mapping[asset][0].upper()
        except:
            return asset.upper()

    def ledgers_csv_to_chain_txns(
        self,
        csv_file,
        entity_address_for_imports=None,
        exchange_account_id=None,
        db=None,
    ):
        txns = []
        reader = csv.DictReader(csv_file)
        last_row_trade = None
        for r in reader:
            txid = r["txid"]
            refid = r["refid"]
            time = r["time"]
            type = r["type"]
            asset = r["asset"]
            fee = Decimal(r["fee"])  # this is always in asset

            chain = "import.kraken"
            hash = f"{chain}_{refid}"
            asset_tx_id = self.get_symbol(asset).lower()
            amount = Decimal(r["amount"])
            direction = "IN" if amount > 0 else "OUT"
            timestamp = arrow.get(time.replace(" ", "T") + "Z").timestamp()
            tx_ledger_type = f"Kraken.{type}"
            symbol = self.get_symbol(asset).upper()
            default_from_to = f"Kraken:{exchange_account_id}"

            if type == "trade" and last_row_trade is None:
                last_row_trade = r
                continue

            if last_row_trade:
                if type != "trade":
                    raise Exception(
                        "Kraken import last row was trade, expected this row to be trade too but isnt",
                        r,
                    )
                else:
                    last_row_from_asset_tx_id = self.get_symbol(
                        last_row_trade["asset"]
                    ).lower()
                    last_row_from_amount = abs(Decimal(last_row_trade["amount"]))
                    last_row_transaction_type = f"Kraken.{last_row_trade['type']}"
                    last_row_direction = (
                        "IN" if Decimal(last_row_trade["amount"]) > 0 else "OUT"
                    )

                    this_row_t = dict(
                        asset_tx_id=normalize_asset_tx_id(asset_tx_id),
                        amount=abs(amount),
                        direction=direction,
                        tx_ledger_type=tx_ledger_type,
                        symbol=symbol,
                        from_address=default_from_to,
                        to_address=default_from_to,
                        isfee=0,
                    )
                    last_row_t = dict(
                        asset_tx_id=normalize_asset_tx_id(last_row_from_asset_tx_id),
                        amount=abs(last_row_from_amount),
                        direction=last_row_direction,
                        tx_ledger_type=last_row_transaction_type,
                        symbol=last_row_from_asset_tx_id.upper(),
                        from_address=default_from_to,
                        to_address=default_from_to,
                        isfee=0,
                    )

                    receives = []
                    sends = []
                    if this_row_t["direction"] == "IN":
                        receives.append(this_row_t)
                        sends.append(last_row_t)
                    else:
                        receives.append(last_row_t)
                        sends.append(this_row_t)

                    # Add on the fee
                    fee_amount = Decimal(r["fee"])
                    if fee_amount > 0:
                        amount = abs(Decimal(fee_amount))
                        symbol = this_row_t["symbol"]
                        total_price_usd, price_source = get_price_usd_and_source(
                            symbol, amount, int(timestamp)
                        )
                        price_usd = total_price_usd / abs(fee_amount)
                        sends.append(
                            dict(
                                asset_tx_id=normalize_asset_tx_id(
                                    this_row_t["asset_tx_id"]
                                ),
                                amount=abs(Decimal(r["fee"])),
                                direction="OUT",
                                tx_ledger_type="fee",
                                symbol=this_row_t["symbol"],
                                from_address=default_from_to,
                                to_address=default_from_to,
                                isfee=1,
                                price_usd=price_usd,
                                price_source=price_source,
                            )
                        )

                    if Decimal(last_row_trade["fee"]) > 0:
                        sends.append(
                            dict(
                                asset_tx_id=normalize_asset_tx_id(
                                    last_row_t["asset_tx_id"]
                                ),
                                amount=abs(Decimal(last_row_trade["fee"])),
                                direction="OUT",
                                tx_ledger_type="fee",
                                symbol=last_row_t["symbol"],
                                from_address=default_from_to,
                                to_address=default_from_to,
                                isfee=1,
                            )
                        )

                    tx = dict(
                        chain=chain,
                        address=entity_address_for_imports,
                        timestamp=timestamp,
                        hash=f"{chain}_{refid}_trade_{last_row_from_asset_tx_id}_{asset_tx_id}",
                        receives=receives,
                        sends=sends,
                    )
                    txns.append(tx)
                    last_row_trade = None  # we're done with this special holder var until the next time we see another trade row
                    continue

            # Non-swap case
            transaction_types_for_receive = ["deposit", "receive"]
            transaction_types_for_send = ["transfer", "withdrawal", "staking", "spend"]
            receives = []
            sends = []
            t = dict(
                asset_tx_id=normalize_asset_tx_id(asset_tx_id),
                amount=Decimal(amount),
                tx_ledger_type=tx_ledger_type,
                symbol=asset_tx_id.upper(),
                from_address=default_from_to,
                to_address=default_from_to,
            )
            if type in transaction_types_for_receive:
                receives.append(t)
            elif type in transaction_types_for_send:
                sends.append(t)
            else:
                raise Exception(
                    "Dont know how to decide if this Kraken import is a send or receive",
                    r,
                )
            tx = dict(
                chain=chain,
                address=entity_address_for_imports,
                hash=hash,
                timestamp=timestamp,
                receives=receives,
                sends=sends,
            )
            txns.append(tx)

        return txns

    def do_import(self, csv_file, entity_address_for_imports, exchange_account_id):
        txns = self.ledgers_csv_to_chain_txns(
            csv_file,
            entity_address_for_imports=entity_address_for_imports,
            exchange_account_id=exchange_account_id,
        )
        # Convert to unified transaction format
        unifieds = {}
        for tx in txns:
            unifieds[f"{tx['chain']}:{tx['hash']}"] = tx
        save_to_db(unifieds)


class GeminiImporter:
    def xls_to_csv(self, xls_file):
        output = io.StringIO()
        wb = openpyxl.load_workbook(filename=xls_file)
        # sheet = wb.sheet_by_index(0)
        sheet = wb.active

        writer = csv.writer(output)
        for r in sheet.rows:
            writer.writerow([cell.value for cell in r])

        return output.getvalue()

    def xls_to_chain_txns(
        self, xls_file=None, entity_address_for_imports=None, exchange_account_id=None
    ):
        def decimal_from_str(str):
            if not str:
                return None
            # 0. Detects if this is representing a negative amount from Gemini e.g. (1,234.567 DAI) represents negative.
            sign = -1 if "(" in str else 1
            # 1. Locate any scientific notation exponent like 3.1e-06
            exponent = 0
            parts = str.split("e", 2)
            if len(parts) == 2:
                exponent = Decimal(parts[1])
                str = parts[0]
            # 2. Removes anything after the first space character
            str = str.split(" ")[0]
            # 3. Removes all " and , and () characters
            str = str.replace(",", "")
            str = str.replace('"', "")
            str = str.replace("(", "")
            str = str.replace(")", "")
            str = re.sub("[^0-9.]", "", str)
            return Decimal(str) * sign * (Decimal(10) ** exponent)

        csv_file = self.xls_to_csv(xls_file)
        reader = csv.DictReader(io.StringIO(csv_file))
        txns = []
        for r in reader:
            date = r["Date"]
            if not date:
                continue
            time = r["Time (UTC)"]
            type = r["Type"]
            original_symbol_length = len(r["Symbol"])

            # Symbol can be things like 'DAI', 'MATIC', 'SGD', 'MATICSGD'
            # this is frustrating for figuring out what assert we're dealing with here.
            currencies = FIAT_SYMBOLS
            symbol = r["Symbol"]
            symbol_left = None
            if len(symbol) >= 6:
                currency_found = None
                for c in currencies:
                    if symbol.endswith(c):
                        currency_found = c
                        break
                if currency_found:
                    symbol_left = symbol[0 : -len(currency_found)]
                else:
                    raise Exception(f"Couldnt figure out left_symbol in {symbol}")
            else:
                symbol_left = r["Symbol"]

            symbol_right = r["Symbol"][len(symbol_left) :]
            amount_key = f"{symbol_left} Amount {symbol_left}"
            amount = Decimal(decimal_from_str(r[amount_key]))
            from_address = f"Gemini:{exchange_account_id}"
            to_address = r.get("Withdrawal Destination") or from_address
            direction = "IN" if amount > 0 else "OUT"
            trade_id = r["Trade ID"]
            order_id = r["Order ID"]

            amount_key_template = "{symbol} Amount {symbol}"
            symbol_right_amount_key = amount_key_template.format(symbol=symbol_right)
            symbol_right_amount = decimal_from_str(r.get(symbol_right_amount_key))

            fee_key_template = "Fee ({fiat_symbol}) {fiat_symbol}"
            amount_key_template = "{fiat_symbol} Amount {fiat_symbol}"
            fee_fiat = None
            amount_fiat = None
            fiat_symbol_actual = None
            for fiat_symbol in currencies:
                fee_key = fee_key_template.format(fiat_symbol=fiat_symbol)
                amount_key = amount_key_template.format(fiat_symbol=fiat_symbol)
                if r.get(fee_key):
                    fee_fiat = Decimal(decimal_from_str(r[fee_key]))
                if r.get(amount_key):
                    amount_fiat = Decimal(decimal_from_str(r[amount_key]))
                    fiat_symbol_actual = fiat_symbol
                if fee_fiat or amount_fiat:
                    break

            asset_tx_id = symbol_left.lower()
            tx_ledger_type = f"Gemini.{type}"
            chain = "import.gemini"
            timestamp = arrow.get(date).timestamp()

            fallback_hash = f"{chain}_{timestamp}_{type}_{symbol}"
            fee_symbol = fiat_symbol_actual.upper() if fiat_symbol_actual else ""
            fee_amount = abs(fee_fiat) if fee_fiat else 0
            hash = f"{chain}_{r['Tx Hash']}" if r.get("Tx Hash") else fallback_hash
            transaction_types_for_receive = ["Credit", "Buy"]
            transaction_types_for_send = ["Debit", "Sell"]

            # calculate unit price based on amount
            price_usd = None
            price_source = None
            if amount_fiat and amount:
                total_price_usd, price_source = get_price_usd_and_source(
                    fiat_symbol_actual, abs(amount_fiat), int(timestamp)
                )
                price_usd = total_price_usd / abs(Decimal(amount))

            side_asset = dict(
                asset_tx_id=symbol_left.lower(),
                amount=abs(amount),
                tx_ledger_type=tx_ledger_type,
                symbol=symbol_left.upper(),
                from_address=from_address,
                to_address=to_address,
                isfee=0,
                price_usd=price_usd,
                price_source=price_source,
            )

            price_asset = None
            if symbol_right:
                price_asset = dict(
                    asset_tx_id=normalize_asset_tx_id(symbol_right),
                    amount=abs(Decimal(symbol_right_amount)),
                    tx_ledger_type=tx_ledger_type,
                    symbol=symbol_right.upper(),
                    from_address=from_address,
                    to_address=to_address,
                    isfee=0,
                )

            receives = []
            sends = []
            if type == "Sell":
                sends.append(side_asset)
                receives.append(price_asset)
            elif type == "Buy":
                sends.append(price_asset)
                receives.append(side_asset)
            if type == "Credit":
                receives.append(side_asset)
            if type == "Debit":
                sends.append(side_asset)

            # Add on the fee
            if fee_amount > 0:
                amount = abs(Decimal(fee_amount))
                total_price_usd, price_source = get_price_usd_and_source(
                    fee_symbol, amount, int(timestamp)
                )
                price_usd = total_price_usd / abs(fee_amount)

                sends.append(
                    dict(
                        asset_tx_id=normalize_asset_tx_id(fee_symbol),
                        amount=abs(Decimal(fee_amount)),
                        tx_ledger_type="fee",
                        symbol=fee_symbol.upper(),
                        from_address=from_address,
                        to_address="Gemini",
                        isfee=1,
                        price_usd=price_usd,
                        price_source=price_source,
                    )
                )

            tx = dict(
                chain=chain,
                address=entity_address_for_imports,
                hash=hash,
                timestamp=timestamp,
                receives=receives,
                sends=sends,
            )
            txns.append(tx)

        return txns

    def do_import(
        self,
        xls_file=None,
        entity_address_for_imports=None,
        exchange_account_id=None,
    ):
        txns = self.xls_to_chain_txns(
            xls_file=xls_file,
            entity_address_for_imports=entity_address_for_imports,
            exchange_account_id=exchange_account_id,
        )
        # Convert to unified transaction format
        unifieds = {}
        for tx in txns:
            unifieds[f"{tx['chain']}:{tx['hash']}"] = tx
        save_to_db(unifieds)


class CoinbaseImporter:
    # TODO - Treat Coinbase.Interest as Income ?
    # TODO - Treat Coinbase.Reward as Income?

    def raw_transactions_csv_to_chain_txns(
        self, csv_file, entity_address_for_imports=None, exchange_account_id=None
    ):
        txns = []
        reader = csv.DictReader(csv_file)

        # Figure out what currency we are working with
        proceeds_field = reader.fieldnames[-1]
        proceeds_field_regexp = "Proceeds.+\(([A-Z]+)\)"
        matches = re.match(proceeds_field_regexp, proceeds_field)
        if not matches:
            raise Exception(
                "Coinbase file should end with a column type that looks like 'Proceeds...(SYM)' but it doesnt.",
                proceeds_field,
            )
        fiat_symbol = matches.group(1)

        last_row_converted_from = None
        for r in reader:
            # Pull values out of the row
            quantity_acquired = (
                Decimal(r["Quantity Acquired (Bought, Received, etc)"])
                if r["Quantity Acquired (Bought, Received, etc)"]
                else None
            )
            asset_acquired = r["Asset Acquired"]
            quantity_disposed = (
                Decimal(r["Quantity Disposed"]) if r["Quantity Disposed"] else None
            )
            asset_disposed = r["Asset Disposed (Sold, Sent, etc)"]
            transaction_type = r["Transaction Type"]
            chain = "import.coinbase"
            direction = "IN" if quantity_acquired else "OUT"
            asset_tx_id = (
                normalize_asset_tx_id(asset_acquired)
                if direction == "IN"
                else normalize_asset_tx_id(asset_disposed)
            )
            amount = quantity_acquired if direction == "IN" else quantity_disposed
            timestamp = arrow.get(r["Date & time"]).timestamp()
            tx_ledger_type = f"Coinbase.{r['Transaction Type']}"
            symbol = (
                asset_acquired.upper() if direction == "IN" else asset_disposed.upper()
            )
            default_from_to = f"Coinbase:{exchange_account_id}"
            costbasis_usd = (
                Decimal(r["Cost Basis (incl. fees paid) (USD)"])
                if r["Cost Basis (incl. fees paid) (USD)"]
                else None
            )
            proceeds_usd = (
                Decimal(r["Proceeds (excl. fees paid) (USD)"])
                if r["Proceeds (excl. fees paid) (USD)"]
                else None
            )
            hash = f"{chain}_{timestamp}_{transaction_type}_{asset_tx_id}"

            # Converted from / Converted to are tricky because a converted from should always be followed by a converted to on the next line.
            # So we'll start with checking for this special case to handle it right...
            if transaction_type == "Converted from":
                if last_row_converted_from:
                    raise Exception(
                        "Last row was Converted from and now we have another Converted from. This shouldn't happen.",
                        r,
                    )
                else:
                    last_row_converted_from = r
                    continue

            if transaction_type == "Converted to":
                if not last_row_converted_from:
                    raise Exception(
                        "Last row was NOT Converted from and we are currently looking at Converted to. This shouldn't happen.",
                        r,
                    )
                else:
                    last_row_from_asset_tx_id = normalize_asset_tx_id(
                        last_row_converted_from["Asset Disposed (Sold, Sent, etc)"]
                    )
                    last_row_from_amount = Decimal(
                        last_row_converted_from["Quantity Disposed"]
                    )
                    last_row_transaction_type = (
                        f"Coinbase.{last_row_converted_from['Transaction Type']}"
                    )
                    last_row_proceeds = last_row_converted_from[
                        "Proceeds (excl. fees paid) (USD)"
                    ]

                    tx = dict(
                        chain=chain,
                        address=entity_address_for_imports,
                        timestamp=timestamp,
                        hash=f"{chain}_{timestamp}_ConvertedFromTo_{last_row_from_asset_tx_id}_{asset_tx_id}",
                        receives=[
                            dict(
                                asset_tx_id=asset_tx_id,
                                amount=abs(amount),
                                direction="IN",
                                tx_ledger_type="Coinbase.ConvertedFromTo",
                                symbol=symbol,
                                from_address=default_from_to,
                                to_address=default_from_to,
                                cost_basis_including_fees_usd=costbasis_usd,
                                isfee=0,
                            )
                        ],
                        sends=[
                            dict(
                                asset_tx_id=last_row_from_asset_tx_id,
                                amount=abs(last_row_from_amount),
                                direction="OUT",
                                tx_ledger_type="Coinbase.ConvertedFromTo",
                                symbol=last_row_from_asset_tx_id.upper(),
                                from_address=default_from_to,
                                to_address=default_from_to,
                                isfee=0,
                                proceeds_after_fees_usd=last_row_proceeds,
                            )
                        ],
                    )
                    txns.append(tx)
                    last_row_converted_from = None  # we're done with this special holder var until the next time we see another Converted from row.
                    continue

            if transaction_type == "Buy":
                tx = dict(
                    chain=chain,
                    address=entity_address_for_imports,
                    hash=hash,
                    timestamp=timestamp,
                    receives=[
                        dict(
                            asset_tx_id=asset_tx_id,
                            amount=abs(quantity_acquired),
                            direction="IN",
                            tx_ledger_type=tx_ledger_type,
                            symbol=symbol,
                            from_address=default_from_to,
                            to_address=default_from_to,
                            is_fee=0,
                            costbasis_including_fees_usd=costbasis_usd,
                        )
                    ],
                    sends=[
                        dict(
                            asset_tx_id=normalize_asset_tx_id(fiat_symbol),
                            amount=abs(costbasis_usd),
                            direction="OUT",
                            tx_ledger_type=tx_ledger_type,
                            symbol=fiat_symbol.upper(),
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=0,
                        )
                    ],
                )
                txns.append(tx)
                continue

            if transaction_type == "Sell":
                tx = dict(
                    chain=chain,
                    address=entity_address_for_imports,
                    hash=hash,
                    timestamp=timestamp,
                    receives=[
                        dict(
                            asset_tx_id=normalize_asset_tx_id(fiat_symbol),
                            amount=abs(proceeds_usd),
                            tx_ledger_type=tx_ledger_type,
                            symbol=fiat_symbol.upper(),
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=0,
                        )
                    ],
                    sends=[
                        dict(
                            asset_tx_id=asset_tx_id,
                            amount=abs(quantity_disposed),
                            tx_ledger_type=tx_ledger_type,
                            symbol=symbol,
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=0,
                            proceeds_after_fees_usd=proceeds_usd,
                        )
                    ],
                )
                txns.append(tx)
                continue

            # Non-swap case
            transaction_types_for_receive = [
                "Airdrop",
                "Deposit",
                "Fork",
                "Incoming",
                "Interest",
                "Receive",
                "Reward",
            ]
            transaction_types_for_send = ["Transfer", "Withdrawal", "Send"]
            receives = []
            sends = []
            t = dict(
                asset_tx_id=asset_tx_id,
                amount=amount,
                tx_ledger_type=tx_ledger_type,
                symbol=asset_tx_id.upper(),
                from_address=default_from_to,
                to_address=default_from_to,
                isfee=0,
            )
            if r["Transaction Type"] in transaction_types_for_receive:
                t["cost_basis_including_fees_usd"] = costbasis_usd
                receives.append(t)
            elif r["Transaction Type"] in transaction_types_for_send:
                t["proceeds_after_fees_usd"] = proceeds_usd
                sends.append(t)
            else:
                raise Exception(
                    "Dont know how to decide if this Coinbase import is a send or receive",
                    r,
                )
            tx = dict(
                chain=chain,
                address=entity_address_for_imports,
                hash=hash,
                timestamp=timestamp,
                receives=receives,
                sends=sends,
            )
            txns.append(tx)

        return txns

    def do_import(self, csv_file, entity_address_for_imports, exchange_account_id):
        txns = self.raw_transactions_csv_to_chain_txns(
            csv_file,
            entity_address_for_imports=entity_address_for_imports,
            exchange_account_id=exchange_account_id,
        )
        # Convert to unified transaction format
        unifieds = {}
        for tx in txns:
            unifieds[f"{tx['chain']}:{tx['hash']}"] = tx
        save_to_db(unifieds)


class CoinbaseTransactionHistoryImporter:
    def transaction_history_csv_to_chain_txns(
        self,
        csv_file: io.StringIO,
        entity_address_for_imports=None,
        exchange_account_id=None,
    ):
        txns = []
        lines_after_header = csv_file.readlines()[7:]
        cleaned_csv = io.StringIO("\n".join(lines_after_header))
        reader = csv.DictReader(cleaned_csv)

        for r in reader:
            # Pull values out of the row
            timestamp = int(arrow.get(r["Timestamp"]).timestamp())
            transaction_type = r["Transaction Type"]
            symbol = r["Asset"].upper()
            amount = r["Quantity Transacted"]
            price_symbol = r["Spot Price Currency"]
            price_usd = r["Spot Price at Transaction"]
            price_source = "exchange_export_spot_price"
            subtotal = r["Subtotal"]
            total_with_fees = r["Total (inclusive of fees)"]
            fee = r["Fees"]
            notes = r["Notes"]

            chain = "import.coinbase"
            asset_tx_id = normalize_asset_tx_id(symbol)
            tx_ledger_type = f"Coinbase.{transaction_type}"
            default_from_to = f"Coinbase:{exchange_account_id}"
            hash = f"{chain}_{timestamp}_{transaction_type}_{asset_tx_id}"

            # Converted is a special transaction type for handling because we need to parse the Notes field in order to know what we converted INTO
            if transaction_type == "Convert":
                # Notes field looks like this:
                # Converted 0.4997288 BCH to 650.1690543 XLM
                _, amount_out, symbol_out, _, amount_in, symbol_in = notes.split(" ")
                tx = dict(
                    chain=chain,
                    address=entity_address_for_imports,
                    timestamp=timestamp,
                    hash=f"{chain}_{timestamp}_Convert_{symbol_out}_{symbol_in}",
                    receives=[
                        dict(
                            asset_tx_id=normalize_asset_tx_id(symbol_in),
                            amount=Decimal(amount_in.replace(",", "")),
                            direction="IN",
                            tx_ledger_type="Coinbase.Convert",
                            symbol=symbol_in.upper(),
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=0,
                            price_usd=Decimal(subtotal)
                            / Decimal(amount_in.replace(",", "")),
                            price_source="exchange_export_infered_from_other_side_of_convert",
                        )
                    ],
                    sends=[
                        # the out
                        dict(
                            asset_tx_id=normalize_asset_tx_id(symbol_out),
                            amount=Decimal(amount_out.replace(",", "")),
                            direction="OUT",
                            tx_ledger_type="Coinbase.Convert",
                            symbol=symbol_out.upper(),
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=0,
                            price_usd=price_usd,
                            price_source=price_source,
                        ),
                        # and the fee
                        dict(
                            asset_tx_id=normalize_asset_tx_id(price_symbol),
                            amount=fee,
                            tx_ledger_type="fee",
                            symbol=price_symbol.upper(),
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=1,
                        ),
                    ],
                )
                txns.append(tx)
                continue

            if transaction_type in ["Buy", "Advanced Trade Buy"]:
                tx = dict(
                    chain=chain,
                    address=entity_address_for_imports,
                    hash=hash,
                    timestamp=timestamp,
                    receives=[
                        dict(
                            asset_tx_id=asset_tx_id,
                            amount=amount,
                            direction="IN",
                            tx_ledger_type=tx_ledger_type,
                            symbol=symbol,
                            from_address=default_from_to,
                            to_address=default_from_to,
                            is_fee=0,
                            price_usd=price_usd,
                            price_source=price_source,
                        )
                    ],
                    sends=[
                        # the money going out
                        dict(
                            asset_tx_id=normalize_asset_tx_id(price_symbol),
                            amount=subtotal,
                            direction="OUT",
                            tx_ledger_type=tx_ledger_type,
                            symbol=price_symbol.upper(),
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=0,
                            price_source=price_source,
                        ),
                        # And the feee
                        dict(
                            asset_tx_id=normalize_asset_tx_id(price_symbol),
                            amount=fee,
                            tx_ledger_type="fee",
                            symbol=price_symbol.upper(),
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=1,
                        ),
                    ],
                )
                txns.append(tx)
                continue

            if transaction_type in ["Sell", "Advanced Trade Sell"]:
                tx = dict(
                    chain=chain,
                    address=entity_address_for_imports,
                    hash=hash,
                    timestamp=timestamp,
                    receives=[
                        dict(
                            asset_tx_id=normalize_asset_tx_id(price_symbol),
                            amount=subtotal,
                            tx_ledger_type=tx_ledger_type,
                            symbol=price_symbol.upper(),
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=0,
                            price_source=price_source,
                        )
                    ],
                    sends=[
                        # the asset we sold
                        dict(
                            asset_tx_id=asset_tx_id,
                            amount=amount,
                            tx_ledger_type=tx_ledger_type,
                            symbol=symbol,
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=0,
                            price_usd=price_usd,
                            price_source=price_source,
                        ),
                        # and the fee
                        dict(
                            asset_tx_id=normalize_asset_tx_id(price_symbol),
                            amount=fee,
                            tx_ledger_type="fee",
                            symbol=price_symbol.upper(),
                            from_address=default_from_to,
                            to_address=default_from_to,
                            isfee=1,
                        ),
                    ],
                )
                txns.append(tx)
                continue

            # Non-swap case
            transaction_types_for_receive = [
                "Airdrop",
                "Coinbase Earn",
                "Rewards Income",
                "Receive",
            ]
            transaction_types_for_send = [
                "Send",
            ]
            receives = []
            sends = []
            t = dict(
                asset_tx_id=asset_tx_id,
                amount=amount,
                tx_ledger_type=tx_ledger_type,
                symbol=asset_tx_id.upper(),
                from_address=default_from_to,
                to_address=default_from_to,
                isfee=0,
                price_usd=price_usd,
                price_source=price_source,
            )
            if r["Transaction Type"] in transaction_types_for_receive:
                receives.append(t)
            elif r["Transaction Type"] in transaction_types_for_send:
                sends.append(t)
            else:
                raise Exception(
                    "Dont know how to decide if this Coinbase import row is a send or receive",
                    r,
                )
            tx = dict(
                chain=chain,
                address=entity_address_for_imports,
                hash=hash,
                timestamp=timestamp,
                receives=receives,
                sends=sends,
            )
            txns.append(tx)

        return txns

    def do_import(self, csv_file, entity_address_for_imports, exchange_account_id):
        txns = self.transaction_history_csv_to_chain_txns(
            csv_file,
            entity_address_for_imports=entity_address_for_imports,
            exchange_account_id=exchange_account_id,
        )
        # Convert to unified transaction format
        unifieds = {}
        for tx in txns:
            unifieds[f"{tx['chain']}:{tx['hash']}"] = tx
        save_to_db(unifieds)


# NOTE: the coinbasepro account statement importer is currently broken. we will continue to use CoinbaseProImporter
# which uses the fills file, since it works and we don't _need_ the deposit/withdrawal entries from the account statement format
class BROKEN_CoinbaseProAccountStatementImporter:
    def csv_to_chain_txns(
        self, csv_file, entity_address_for_imports=None, exchange_account_id=None
    ):
        txns = []
        reader = csv.DictReader(csv_file)

        last_row_trade_id = None
        trade_fee = None
        trade_out = None
        trade_in = None
        trade_timestamp = None
        trade_hash = None
        last_row_conversion = None
        chain = "import.coinbase_pro"
        for r in reader:
            portfolio = r["portfolio"]
            type = r["type"]
            time = r["time"]
            amount = Decimal(r["amount"])
            unit = r["amount/balance unit"]
            transfer_id = r["transfer id"]
            trade_id = r["trade id"]

            asset_tx_id = unit.lower()
            timestamp = arrow.get(time).timestamp()
            tx_ledger_type = (
                f"CoinbasePro.trade"
                if type in ["match", "fee"]
                else f"CoinbasePro.{type}"
            )
            symbol = unit.upper()
            default_from_to = f"CoinbasePro:{exchange_account_id}"

            hash_suffix = ""
            hash_type = type
            if type in ["withdrawal", "deposit"]:
                hash_suffix = transfer_id
            if type in ["match", "fee"]:
                hash_suffix = trade_id
                hash_type = "trade"
            if type == "conversion":
                hash_suffix = time
            hash = f"{portfolio}_{hash_type}_{hash_suffix}"

            # First see if we just finished reading rows for a trade (the 3 lines above)
            if last_row_trade_id != trade_id and last_row_trade_id is not None:
                # Create the consolidated transaction with sends/receives first
                tx = dict(
                    chain=chain,
                    address=entity_address_for_imports,
                    timestamp=trade_timestamp,
                    hash=trade_hash + trade_out["symbol"] + trade_in["symbol"],
                    receives=[trade_in],
                    sends=[trade_out],
                )
                if trade_fee:
                    tx["sends"].append(trade_fee)
                txns.append(tx)
                trade_in = None
                trade_out = None
                trade_fee = None
                trade_timestamp = None
                trade_hash = None

            # Simple case of deposit or withdrawl
            if type in ["deposit", "withdrawal"]:
                t = dict(
                    asset_tx_id=normalize_asset_tx_id(asset_tx_id),
                    amount=abs(amount),
                    tx_ledger_type=tx_ledger_type,
                    symbol=symbol,
                    from_address=default_from_to,
                    to_address=default_from_to,
                    isfee=0,
                )
                receives = []
                sends = []
                if type == "deposit":
                    receives.append(t)
                elif type == "withdrawal":
                    sends.append(t)

                tx = dict(
                    chain=chain,
                    address=entity_address_for_imports,
                    timestamp=timestamp,
                    hash=hash,
                    receives=receives,
                    sends=sends,
                )
                txns.append(tx)
                trade_in = None
                trade_out = None
                trade_fee = None
                trade_hash = None
                trade_timestamp = None
                continue

            elif type == "conversion":
                if last_row_conversion is None:
                    last_row_conversion = r
                    continue
                else:
                    # This is presumably the second row of a conversion (from/to) so write the tx
                    is_this_row_out = amount < 0
                    this_row_t = dict(
                        asset_tx_id=normalize_asset_tx_id(asset_tx_id),
                        amount=abs(amount),
                        tx_ledger_type=tx_ledger_type,
                        symbol=symbol,
                        from_address=default_from_to,
                        to_address=default_from_to,
                        isfee=0,
                    )

                    type = last_row_conversion["type"]
                    time = last_row_conversion["time"]
                    amount = Decimal(last_row_conversion["amount"])
                    unit = last_row_conversion["amount/balance unit"]
                    asset_tx_id = unit.lower()
                    timestamp = arrow.get(time).timestamp()
                    tx_ledger_type = (
                        f"CoinbasePro.trade"
                        if type in ["match", "fee"]
                        else f"CoinbasePro.{type}"
                    )
                    symbol = unit.upper()
                    last_row_t = dict(
                        asset_tx_id=normalize_asset_tx_id(asset_tx_id),
                        amount=abs(amount),
                        tx_ledger_type=tx_ledger_type,
                        symbol=symbol,
                        from_address=default_from_to,
                        to_address=default_from_to,
                        isfee=0,
                    )

                    receives = []
                    sends = []
                    if is_this_row_out:
                        sends.append(this_row_t)
                        receives.append(last_row_t)
                    else:
                        sends.append(last_row_t)
                        receives.append(this_row_t)
                    tx = dict(
                        chain=chain,
                        address=entity_address_for_imports,
                        timestamp=timestamp,
                        hash=hash,
                        receives=receives,
                        sends=sends,
                    )
                    txns.append(tx)

            # More complicated if we are in match or fee.
            elif type in ["match", "fee"]:
                trade_timestamp = timestamp
                trade_hash = hash

                # Store the info for this new trade
                last_row_trade_id = trade_id

                if type == "match" and amount > 0:
                    # its the trade in
                    trade_in = dict(
                        asset_tx_id=normalize_asset_tx_id(asset_tx_id),
                        amount=abs(amount),
                        tx_ledger_type=tx_ledger_type,
                        symbol=symbol,
                        from_address=default_from_to,
                        to_address=default_from_to,
                        isfee=0,
                    )
                elif type == "match" and amount < 0:
                    # its the trade out
                    trade_out = dict(
                        asset_tx_id=normalize_asset_tx_id(asset_tx_id),
                        amount=abs(amount),
                        tx_ledger_type=tx_ledger_type,
                        symbol=symbol,
                        from_address=default_from_to,
                        to_address=default_from_to,
                        isfee=0,
                    )
                elif type == "fee":
                    # its the fee
                    trade_fee = dict(
                        asset_tx_id=normalize_asset_tx_id(asset_tx_id),
                        amount=abs(amount),
                        tx_ledger_type="fee",
                        symbol=symbol,
                        from_address=default_from_to,
                        to_address=default_from_to,
                        isfee=1,
                    )
                else:
                    raise Exception(
                        f"Dont know how to handle type {type} with amount {amount}", r
                    )
                continue

            else:
                raise Exception("Dont know how to handle row of type {type}", r)

        # Before we finish, if our last row is part of the current trade context, write it out (assuming it is complete)
        # Create the consolidated transaction with sends/receives
        tx = dict(
            chain=chain,
            address=entity_address_for_imports,
            timestamp=trade_timestamp,
            hash=trade_hash,
            receives=[trade_in],
            sends=[trade_out],
        )
        if trade_fee:
            tx["sends"].append(trade_fee)
        txns.append(tx)

        return txns

    def do_import(self, csv_file, entity_address_for_imports, exchange_account_id, db):
        txns = self.csv_to_chain_txns(
            csv_file,
            entity_address_for_imports=entity_address_for_imports,
            exchange_account_id=exchange_account_id,
        )
        # Convert to unified transaction format
        unifieds = {}
        for tx in txns:
            unifieds[f"{tx['chain']}:{tx['hash']}"] = tx
        save_to_db(unifieds)


class CoinbaseProImporter:
    def fills_csv_to_chain_txns(
        self, csv_file, entity_address_for_imports=None, exchange_account_id=None
    ):
        txns = []
        reader = csv.DictReader(csv_file)
        for r in reader:
            chain = "import.coinbase_pro"
            side = r["side"]
            asset_tx_id = r["size unit"].lower()
            amount = Decimal(r["size"])
            timestamp = int(arrow.get(r["created at"]).timestamp())
            tx_ledger_type = f"CoinbasePro.{r['side']}"
            symbol = r["size unit"].upper()
            default_from_to = f"CoinbasePro:{exchange_account_id}"
            fee_amount = Decimal(r["fee"])
            price_unit = r["price/fee/total unit"]
            price = Decimal(r["price"])
            price_total = abs(Decimal(r["total"]))
            trade_id = r["trade id"]
            product = r["product"]
            portfolio = r["portfolio"]
            hash = f"{portfolio}_{trade_id}_{product}_{side}"

            # NOTE: price is not always in USD, so we need to convert to USD if it's not USD...
            price_usd, price_source = get_price_usd_and_source(
                price_unit, price, timestamp
            )

            side_asset = dict(
                asset_tx_id=asset_tx_id,
                amount=abs(amount),
                tx_ledger_type=tx_ledger_type,
                symbol=symbol,
                from_address=default_from_to,
                to_address=default_from_to,
                isfee=0,
                price_usd=price_usd,
                price_source=price_source,
            )

            price_asset = dict(
                asset_tx_id=normalize_asset_tx_id(price_unit),
                amount=abs(price * amount),
                tx_ledger_type=tx_ledger_type,
                symbol=price_unit.upper(),
                from_address=default_from_to,
                to_address=default_from_to,
                isfee=0,
            )

            receives = []
            sends = []
            if side == "SELL":
                sends.append(side_asset)
                receives.append(price_asset)
            else:
                sends.append(price_asset)
                receives.append(side_asset)

            # Add on the fee
            if fee_amount > 0:
                # price_usd needs to be a unit price so get the total in usd and divide by the amount
                total_price_usd, price_source = get_price_usd_and_source(
                    price_unit, abs(fee_amount), timestamp
                )
                price_usd = total_price_usd / abs(fee_amount)
                sends.append(
                    dict(
                        asset_tx_id=normalize_asset_tx_id(price_unit),
                        amount=abs(fee_amount),
                        tx_ledger_type="fee",
                        symbol=price_unit.upper(),
                        from_address=default_from_to,
                        to_address=default_from_to,
                        isfee=1,
                        price_usd=price_usd,
                        price_source=price_source,
                    )
                )

            tx = dict(
                chain=chain,
                address=entity_address_for_imports,
                timestamp=timestamp,
                hash=hash,
                receives=receives,
                sends=sends,
            )
            txns.append(tx)

        return txns

    def do_import(self, csv_file, entity_address_for_imports, exchange_account_id):
        txns = self.fills_csv_to_chain_txns(
            csv_file,
            entity_address_for_imports=entity_address_for_imports,
            exchange_account_id=exchange_account_id,
        )
        # Convert to unified transaction format
        unifieds = {}
        for tx in txns:
            unifieds[f"{tx['chain']}:{tx['hash']}"] = tx
        save_to_db(unifieds)
