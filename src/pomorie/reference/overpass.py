"""Small Overpass API client with retries (the public instance often answers 502/504)."""

from __future__ import annotations

import time
from typing import Any

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "pomorie-data-platform/0.1 (portfolio project; reference data download)"
ATTRIBUTION = "© OpenStreetMap contributors, available under the Open Database Licence (ODbL)"

_RETRY_STATUS = {429, 502, 503, 504}


def query(ql: str, attempts: int = 6, timeout: float = 180) -> dict[str, Any]:
    for attempt in range(1, attempts + 1):
        response = httpx.post(
            OVERPASS_URL, data={"data": ql}, headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
        if response.status_code not in _RETRY_STATUS or attempt == attempts:
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
        time.sleep(min(60, 5 * 2 ** (attempt - 1)))  # 5, 10, 20, 40, 60 s
    raise AssertionError("unreachable")
