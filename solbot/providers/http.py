"""Client HTTP condiviso con rate limit semplice e retry gentili (niente scraping aggressivo)."""
from __future__ import annotations

import logging
import threading
import time

import httpx

log = logging.getLogger("solbot.http")

_client: httpx.Client | None = None
_lock = threading.Lock()
_last_call: dict[str, float] = {}
# intervallo minimo tra chiamate per host (secondi)
MIN_INTERVAL = {
    "api.dexscreener.com": 0.25,  # limite pubblico ~300 req/min sugli endpoint pair/token, 60 su profili
    "api.rugcheck.xyz": 0.6,
    "lite-api.jup.ag": 1.1,  # tier gratuito
}


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=20, headers={"User-Agent": "solbot/0.1 (paper-trading research)"}, follow_redirects=True)
    return _client


def get_json(url: str, params: dict | None = None, retries: int = 2):
    host = httpx.URL(url).host
    for attempt in range(retries + 1):
        with _lock:
            wait = MIN_INTERVAL.get(host, 0.2) - (time.time() - _last_call.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            _last_call[host] = time.time()
        try:
            r = client().get(url, params=params)
            if r.status_code == 429:
                time.sleep(2 + attempt * 3)
                continue
            if r.status_code >= 500:
                time.sleep(1 + attempt)
                continue
            if r.status_code >= 400:
                return {"__error__": r.status_code, "__body__": r.text[:300]}
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.debug("HTTP %s fallita (%s), tentativo %d", url, e, attempt + 1)
            time.sleep(1 + attempt)
    return None
