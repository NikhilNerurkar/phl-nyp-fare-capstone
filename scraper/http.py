"""Shared HTTP client: polite delays, jitter, retry with backoff.

Every source goes through this so rate limiting is enforced in one place and
we never accidentally hammer a site from inside a loop.
"""
from __future__ import annotations

import random
import time
from typing import Any

import httpx

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

BASE_HEADERS = {
    "User-Agent": DESKTOP_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


class PoliteClient:
    """Thin wrapper over httpx with a floor on request spacing."""

    def __init__(self, min_delay: float = 1.5, max_delay: float = 4.0,
                 max_retries: int = 3, timeout: float = 30.0,
                 headers: dict | None = None) -> None:
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self._last_request = 0.0
        self.queries = 0
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={**BASE_HEADERS, **(headers or {})},
        )

    def _wait(self) -> None:
        delay = random.uniform(self.min_delay, self.max_delay)
        elapsed = time.monotonic() - self._last_request
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request = time.monotonic()

    def get_json(self, url: str, **kw) -> Any:
        r = self.request("GET", url, **kw)
        return r.json()

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._wait()
            try:
                self.queries += 1
                r = self.client.request(method, url, **kw)
                if r.status_code in (429, 503):
                    # Explicit throttle signal: back off hard and retry.
                    time.sleep((2 ** attempt) * 5 + random.uniform(0, 3))
                    last_exc = httpx.HTTPStatusError(
                        f"{r.status_code} throttled", request=r.request, response=r)
                    continue
                r.raise_for_status()
                return r
            except Exception as e:  # noqa: BLE001 - we retry everything once
                last_exc = e
                if attempt < self.max_retries - 1:
                    time.sleep((2 ** attempt) * 2 + random.uniform(0, 2))
        raise last_exc  # type: ignore[misc]

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
