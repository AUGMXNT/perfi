from .db import DB
from .constants.paths import CACHEDB_PATH, CACHEDB_SCHEMA_PATH


from collections import defaultdict
import httpx
import lzma
import os
import time
from urllib.parse import urlparse
import json
import hashlib
import time


class CacheGet404Exception(Exception):
    def __init__(self, message, req_content):
        self.message = message
        self.request_content = req_content


class Cache:
    def __init__(self, noproxy=False, use_mem=True):
        self.db = DB(CACHEDB_PATH)

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
            self.client = httpx.Client(proxies=self.proxy)
            return self.client

    def set_cookies_for_requests(self, hostname, cookies):
        for k, v in cookies.items():
            print("Setting cookie -- %s | %s : %s" % (hostname, k, v))
            self.hostname_cookies_map[hostname][k] = v

    def get(self, url, refresh=False, refresh_if=False):
        client = self._client()

        result = {}
        # Get cached version
        r = self.db.query(
            "SELECT key, value_lzma, saved, expire FROM cache WHERE key = ? ORDER BY saved DESC LIMIT 1",
            url,
        )
        # Conditional Refresh - refresh if record is older than refresh_if
        if len(r) and refresh_if and time.time() - r[0][2] > refresh_if:
            refresh = True

        if r and not refresh:
            # print(f'CACHED: {url}')
            result["status"] = "cached"
            result["key"] = r[0][0]
            result["saved"] = r[0][2]

            # Decompress LZMA'd value
            value_lzma = r[0][1]
            lzmad = lzma.LZMADecompressor()
            result["value"] = lzmad.decompress(value_lzma)  # type: ignore
        else:
            # Get
            self.headers["Referer"] = f"https://{urlparse(url).hostname}/"
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
                        headers=self.headers,
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
                    self.headers["Referer"] = f"https://{urlparse(url).hostname}/"
                    req = client.get(
                        url,
                        cookies=self.hostname_cookies_map[urlparse(url).hostname],
                        headers=self.headers,
                        timeout=10.0,
                    )
                    t = int(time.time())
                    retry_count += 1

            if req.status_code == 200:
                # Compress value for storage
                lzmac = lzma.LZMACompressor()
                value_lzma = lzmac.compress(req.content)
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
