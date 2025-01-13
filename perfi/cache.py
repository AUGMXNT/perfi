from typing import Callable, Any

from devtools import debug
from web3.types import RPCEndpoint, RPCResponse

from .db import DB
from .constants.paths import CACHEDB_PATH, CACHEDB_SCHEMA_PATH


from web3 import Web3
from collections import defaultdict
import httpx
import lzma
import os
from urllib.parse import urlparse
import json
import hashlib
import collections
from collections.abc import Generator
import time
import pickle

from eth_utils import (
    is_boolean,
    is_bytes,
    is_dict,
    is_list_like,
    is_null,
    is_number,
    is_text,
    to_bytes,
)


def generate_cache_key(value: Any) -> str:
    """
    Generates a cache key for the *args and **kwargs
    """
    if is_bytes(value):
        return hashlib.md5(value).hexdigest()
    elif is_text(value):
        return generate_cache_key(to_bytes(text=value))
    elif is_boolean(value) or is_null(value) or is_number(value):
        return generate_cache_key(repr(value))
    elif is_dict(value):
        return generate_cache_key(((key, value[key]) for key in sorted(value.keys())))
    elif is_list_like(value) or isinstance(value, collections.abc.Generator):
        return generate_cache_key("".join((generate_cache_key(item) for item in value)))
    else:
        raise TypeError(
            f"Cannot generate cache key for value {value} of type {type(value)}"
        )


def web3_db_cache_middleware(
    make_request: Callable[[RPCEndpoint, Any], RPCResponse], w3: "Web3"
) -> Callable[[RPCEndpoint, Any], RPCResponse]:
    rpc_whitelist = ["eth_getTransactionReceipt"]

    def middleware(method: RPCEndpoint, params: Any) -> RPCResponse:
        if method in rpc_whitelist:
            cache_key = generate_cache_key((method, params))
            r = cache._get_val(cache_key)
            if not r:
                print(f"Web3 cache key {cache_key} not in our cache.")
                t = int(time.time())
                response = make_request(method, params)
                cache._set_val(cache_key, pickle.dumps(response), t)
                return response
            print(f"Web3 cache key {cache_key} IS IN our cache.")
            return pickle.loads(r["value"])
        else:
            print(f"Web3 NOT CACHING {method}")
            return make_request(method, params)

    return middleware


class CacheGet404Exception(Exception):
    def __init__(self, message, req_content):
        self.message = message
        self.request_content = req_content


class Cache:
    def __init__(self, noproxy=False, use_mem=True):
        self.db = DB(CACHEDB_PATH, same_thread=False)

        # If a new cache db we'll load the cache schema
        cache_is_empty = len(self.db.query("select * from sqlite_master")) == 0
        if cache_is_empty:
            self.db.create_db(CACHEDB_SCHEMA_PATH)

        self.proxy = None
        self.hostname_cookies_map = defaultdict(dict)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:96.0) Gecko/20100101 Firefox/96.0",
            "Cache-Control": "max-age=0",
        }
        if not noproxy:
            self.proxy = os.getenv("PROXY")

        # Use memory cache
        if use_mem:
            self.db.use_mem()

        self.client = None

    def _client(self):
        if self.client:
            return self.client
        else:
            if self.proxy:
                proxies = {"http://": self.proxy, "https://": self.proxy}
                self.client = httpx.Client(proxies=proxies)
            else:
                self.client = httpx.Client()
            return self.client

    def _get_val(self, key, refresh_if=None):
        r = self.db.query(
            "SELECT key, value_lzma, saved, expire FROM cache WHERE key = ? ORDER BY saved DESC LIMIT 1",
            key,
        )
        if len(r):
            if refresh_if and time.time() - r[0]["saved"] > refresh_if:
                return None
            else:
                result = {}
                result["status"] = "cached"
                result["key"] = r[0][0]
                result["saved"] = r[0][2]
                # Decompress LZMA'd value
                value_lzma = r[0][1]
                lzmad = lzma.LZMADecompressor()
                result["value"] = lzmad.decompress(value_lzma)  # type: ignore
                return result
        return None

    def _set_val(self, key, value, timestamp):
        if type(value) is str:
            value = value.encode("utf-8")
        # Compress value for storage
        lzmac = lzma.LZMACompressor()
        value_lzma = lzmac.compress(value)
        value_lzma += lzmac.flush()

        sql = """REPLACE INTO cache
         (key, value_lzma, saved)
         VALUES
         (?, ?, ?)"""
        params = (key, value_lzma, timestamp)
        self.db.execute(sql, params)

    def set_cookies_for_requests(self, hostname, cookies):
        for k, v in cookies.items():
            print("Setting cookie -- %s | %s : %s" % (hostname, k, v))
            self.hostname_cookies_map[hostname][k] = v

    def get(self, url, refresh=False, refresh_if=False, headers={}):
        client = self._client()

        result = {}
        # Get cached version
        r = self._get_val(url)
        # Conditional Refresh - refresh if record is older than refresh_if
        if r and refresh_if and time.time() - r["saved"] > refresh_if:
            refresh = True

        if r and not refresh:
            # print(f'CACHED: {url}')
            return r
        else:
            # Get
            headers.update(self.headers)
            headers["Referer"] = f"https://{urlparse(url).hostname}/"
            retry_count = 1
            got_response = False
            req = None
            t = None
            while retry_count < 10 and not got_response:
                try:
                    # print(url)
                    req = client.get(
                        url,
                        cookies=self.hostname_cookies_map[urlparse(url).hostname],
                        headers=headers,
                        timeout=10.0,
                    )
                    t = int(time.time())
                    if req.cookies:
                        self.set_cookies_for_requests(
                            urlparse(url).hostname, req.cookies
                        )
                    got_response = True
                except httpx.ReadTimeout:
                    print("Request to %s timed out. Retrying... " % url)
                    time.sleep(1)
                    retry_count += 1
            if retry_count == 10:
                raise Exception("Failed to request %s after 10 tries." % url)

            if req.status_code == 404:
                raise CacheGet404Exception(
                    "Got 404 response requesting %s" % url, req.content
                )

            # Try a few more times if not 200...
            retry_count = 1
            if req.status_code != 200:
                while req.status_code != 200 and retry_count < 10:
                    print(
                        "Got response status %s when requesting %s ; Sleeping for %s seconds...."
                        % (req.status_code, url, 10 * retry_count)
                    )
                    time.sleep(10 * retry_count)
                    headers["Referer"] = f"https://{urlparse(url).hostname}/"
                    req = client.get(
                        url,
                        cookies=self.hostname_cookies_map[urlparse(url).hostname],
                        headers=headers,
                        timeout=10.0,
                    )
                    t = int(time.time())
                    retry_count += 1

            if req.status_code == 200:
                self._set_val(url, req.content, t)

                result["status"] = "cached"
                result["key"] = url
                result["value"] = req.content  # type: ignore
                result["saved"] = t
            else:
                if r:
                    result["status"] = "stale"
                    result["key"] = r[0][0]
                    result["value"] = r[0][1]
                    result["saved"] = r[0][2]
                else:
                    result["status"] = "error"
                    result["status_code"] = req.status_code
                    result["value"] = None  # TODO does this make sense?
                    raise Exception(f"ERROR {result['status_code']}fetching: {url}")

        return result

    def get_v2(self, url, refresh=False, method="GET", headers=None, data=None):
        if headers is None:
            headers = dict()
        if data is None:
            data = dict()
        result = {}
        client = self._client()

        cache_key = url
        if method == "POST" and data:
            cache_key += hashlib.sha256(json.dumps(data).encode()).hexdigest()

        # Get cached version
        r = self.db.query(
            "SELECT key, value_lzma, saved, expire FROM cache WHERE key = ? ORDER BY saved DESC LIMIT 1",
            cache_key,
        )

        if r and not refresh:
            result["status"] = "cached"
            result["key"] = r[0][0]
            result["saved"] = r[0][2]

            # Decompress LZMA'd value
            value_lzma = r[0][1]
            lzmad = lzma.LZMADecompressor()
            result["value"] = lzmad.decompress(value_lzma)
        else:
            # Get
            client.headers["Referer"] = f"https://{urlparse(url).hostname}/"
            if headers:
                for k, v in headers.items():
                    client.headers[k] = v

            request = client.get if method == "GET" else client.post

            retry_count = 1
            got_response = False
            req = None
            t = None
            while retry_count < 10 and not got_response:
                try:
                    kwargs = dict(json=data) if data else {}
                    req = request(
                        url,
                        cookies=self.hostname_cookies_map[urlparse(url).hostname],
                        headers=self.headers | headers,
                        timeout=10.0,
                        **kwargs,
                    )
                    t = int(time.time())
                    if req.cookies:
                        self.set_cookies_for_requests(
                            urlparse(url).hostname, req.cookies
                        )
                    got_response = True
                except httpx.ReadTimeout:
                    print("Request to %s timed out. Retrying... " % url)
                    time.sleep(1)
                    retry_count += 1
            if retry_count == 10:
                raise Exception("Failed to request %s after 10 tries." % url)

            if req.status_code == 404:  # type: ignore
                raise CacheGet404Exception("Got 404 response requesting %s" % url, req.content)  # type: ignore

            # Try a few more times if not 200...
            retry_count = 1
            if req.status_code != 200:  # type: ignore
                while req.status_code != 200 and retry_count < 10:  # type: ignore
                    print("Got response status %s when requesting %s. Sleeping for %s seconds...." % (req.status_code, url, 10 * retry_count))  # type: ignore
                    time.sleep(10 * retry_count)
                    self.headers["Referer"] = f"https://{urlparse(url).hostname}/"
                    req = request(url, cookies=self.hostname_cookies_map[urlparse(url).hostname], headers=self.headers, timeout=10.0, **kwargs)  # type: ignore
                    t = int(time.time())
                    retry_count += 1

            if req.status_code == 200:  # type: ignore
                # Compress value for storage
                lzmac = lzma.LZMACompressor()
                value_lzma = lzmac.compress(req.content)  # type: ignore
                value_lzma += lzmac.flush()

                sql = """REPLACE INTO cache
                 (key, value_lzma, saved)
                 VALUES
                 (?, ?, ?)"""
                params = (url, value_lzma, t)
                self.db.execute(sql, params)

                result["status"] = "cached"
                result["key"] = url
                result["value"] = req.content  # type: ignore
                result["saved"] = t
            else:
                if r:
                    result["status"] = "stale"
                    result["key"] = r[0][0]
                    result["value"] = r[0][1]
                    result["saved"] = r[0][2]
                else:
                    result["status"] = "error"
                    result["status_code"] = req.status_code  # type: ignore
                    result["value"] = None  # TODO does this make sense?
                    raise Exception(f"ERROR {result['status_code']}fetching: {url}")

        return result


### Make cache available as a singleton
cache = Cache()
