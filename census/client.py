"""Throttled, cached client for the FastNEAR Transactions API (https://docs.fastnear.com/tx).

Every response is cached on disk (sqlite, zlib-compressed JSON) keyed by the request, so
interrupted collection runs resume for free and re-runs never hit the network twice.

Anonymous access is rate limited (about 2-3 requests/second sustained); setting
FASTNEAR_API_KEY raises the limit and the client then defaults to a higher request rate.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

def _load_dotenv() -> None:
    """Read KEY=VALUE lines from <repo>/.env into os.environ (without overriding real variables)."""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()
BASE = os.environ.get("CENSUS_TX_API", "https://tx.main.fastnear.com/v0/")
CACHE_PATH = Path(os.environ.get("CENSUS_CACHE", Path(__file__).resolve().parent.parent / "data" / "cache" / "http.sqlite"))


class ApiError(RuntimeError):
    pass


class Client:
    def __init__(self, cache_path: Path = CACHE_PATH, rps: float | None = None):
        self.api_key = os.environ.get("FASTNEAR_API_KEY")
        default_rps = 8.0 if self.api_key else 1.1
        self.rps = float(os.environ.get("CENSUS_RPS", rps or default_rps))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(cache_path), check_same_thread=False, timeout=60)
        self._db.execute("CREATE TABLE IF NOT EXISTS http (k TEXT PRIMARY KEY, v BLOB)")
        self._db.commit()
        self._db_lock = threading.Lock()
        self._rate_lock = threading.Lock()
        self._next_slot = 0.0
        self.network_calls = 0
        self.cache_hits = 0

    # -- cache ---------------------------------------------------------------------------
    @staticmethod
    def _key(path: str, body: dict) -> str:
        return hashlib.sha1((path + json.dumps(body, sort_keys=True)).encode()).hexdigest()

    def _get_cached(self, k: str):
        with self._db_lock:
            row = self._db.execute("SELECT v FROM http WHERE k=?", (k,)).fetchone()
        return json.loads(zlib.decompress(row[0])) if row else None

    def _put_cached(self, k: str, value) -> None:
        blob = zlib.compress(json.dumps(value, separators=(",", ":")).encode(), 6)
        with self._db_lock:
            self._db.execute("INSERT OR REPLACE INTO http VALUES (?, ?)", (k, blob))
            self._db.commit()

    # -- network -------------------------------------------------------------------------
    def _wait_for_slot(self) -> None:
        with self._rate_lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + 1.0 / self.rps
        if slot > now:
            time.sleep(slot - now)

    def post(self, path: str, body: dict, retries: int = 8):
        k = self._key(path, body)
        cached = self._get_cached(k)
        if cached is not None:
            self.cache_hits += 1
            return cached
        headers = {"Content-Type": "application/json", "User-Agent": "near-agent-census/1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(body).encode()
        delay = 2.0
        for attempt in range(retries):
            self._wait_for_slot()
            req = urllib.request.Request(BASE + path, data=data, headers=headers)
            try:
                self.network_calls += 1
                with urllib.request.urlopen(req, timeout=90) as resp:
                    value = json.loads(resp.read())
                self._put_cached(k, value)
                return value
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    # the API sends "Retry-After: 0", so never wait less than our own exponential backoff
                    try:
                        hinted = float(e.headers.get("Retry-After", 0))
                    except ValueError:
                        hinted = 0.0
                    time.sleep(min(max(hinted, delay), 60))
                    delay = min(delay * 2, 60)
                    continue
                raise ApiError(f"{path} {body}: HTTP {e.code}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(delay)
                delay = min(delay * 2, 60)
        raise ApiError(f"{path}: gave up after {retries} attempts")

    # -- typed helpers -------------------------------------------------------------------
    def block(self, height: int, with_transactions: bool = False) -> dict | None:
        res = self.post("block", {"block_id": height, "with_transactions": with_transactions})
        return res if res.get("block") else None

    def transactions(self, hashes: list[str]) -> list[dict]:
        return self.post("transactions", {"tx_hashes": hashes}).get("transactions", [])

    def account_signed(self, account_id: str, to_height: int, limit: int = 200) -> dict:
        """The account's most recent `limit` transactions it really signed (delegated included), ending before `to_height`."""
        return self.post("account", {
            "account_id": account_id, "is_real_signer": True, "desc": True,
            "limit": limit, "to_tx_block_height": to_height,
        })
