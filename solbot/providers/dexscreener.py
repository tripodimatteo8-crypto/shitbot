"""DexScreener: universo token Solana (nuovi profili, boost/trending, ricerche) e dati di mercato.

Docs: https://docs.dexscreener.com/api/reference  (pubblica, senza chiave, rate limit 60-300 req/min)
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from .base import MarketData
from .http import get_json

log = logging.getLogger("solbot.dexscreener")
BASE = "https://api.dexscreener.com"
QUOTE_MINTS = {
    "So11111111111111111111111111111111111111112",  # wSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G9wEGGkLwyTDt1v",  # USDC
}
STABLE_OR_MAJOR = QUOTE_MINTS | {"Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCQ8JZq3sG"}  # USDT
SEARCH_QUERIES = ["pumpswap", "pump.fun", "raydium", "meteora", "solana meme"]


def _f(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


class DexScreener:
    def __init__(self):
        # mint interrogati con risposta valida nell'ultima chiamata di QUESTO thread
        # (per distinguere "delistato" da "errore di rete")
        self._tls = threading.local()

    @property
    def last_ok_mints(self) -> set[str]:
        return getattr(self._tls, "ok", set())

    def discover(self) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}

        def add(mint: str | None, src: str):
            if mint and mint not in STABLE_OR_MAJOR:
                found.setdefault(mint, set()).add(src)

        for path, src in [
            ("/token-profiles/latest/v1", "new_profile"),
            ("/token-boosts/latest/v1", "boost_latest"),
            ("/token-boosts/top/v1", "boost_top"),
            ("/community-takeovers/latest/v1", "cto"),
        ]:
            data = get_json(BASE + path)
            if isinstance(data, list):
                for item in data:
                    if item.get("chainId") == "solana":
                        add(item.get("tokenAddress"), src)
        for q in SEARCH_QUERIES:
            data = get_json(BASE + "/latest/dex/search", params={"q": q})
            if isinstance(data, dict):
                for p in data.get("pairs") or []:
                    if p.get("chainId") == "solana":
                        src = "pumpfun_curve" if p.get("dexId") == "pumpfun" else ("pumpswap_migrated" if p.get("dexId") == "pumpswap" else "search")
                        add((p.get("baseToken") or {}).get("address"), src)
        return found

    def market_data(self, mints: list[str]) -> dict[str, MarketData]:
        out: dict[str, MarketData] = {}
        ok: set[str] = set()
        for i in range(0, len(mints), 30):
            chunk = mints[i : i + 30]
            data = get_json(f"{BASE}/tokens/v1/solana/{','.join(chunk)}")
            if not isinstance(data, list):
                continue
            ok.update(chunk)
            best: dict[str, dict] = {}
            for p in data:
                base = (p.get("baseToken") or {}).get("address")
                quote = (p.get("quoteToken") or {}).get("address")
                if base not in chunk or quote not in QUOTE_MINTS:
                    continue
                liq = _f((p.get("liquidity") or {}).get("usd")) or 0
                if base not in best or liq > (_f((best[base].get("liquidity") or {}).get("usd")) or 0):
                    best[base] = p
            for mint, p in best.items():
                out[mint] = self._parse(mint, p)
        self._tls.ok = ok
        return out

    @staticmethod
    def _parse(mint: str, p: dict) -> MarketData:
        tx = p.get("txns") or {}
        vol = p.get("volume") or {}
        chg = p.get("priceChange") or {}
        created = p.get("pairCreatedAt")
        info = p.get("info") or {}
        return MarketData(
            mint=mint,
            symbol=(p.get("baseToken") or {}).get("symbol"),
            name=(p.get("baseToken") or {}).get("name"),
            pair_address=p.get("pairAddress"),
            dex_id=p.get("dexId"),
            url=p.get("url"),
            pair_created_at=datetime.fromtimestamp(created / 1000, tz=timezone.utc).replace(tzinfo=None) if created else None,
            price_usd=_f(p.get("priceUsd")),
            liquidity_usd=_f((p.get("liquidity") or {}).get("usd")),
            mcap_usd=_f(p.get("marketCap")),
            fdv_usd=_f(p.get("fdv")),
            vol_m5=_f(vol.get("m5")),
            vol_h1=_f(vol.get("h1")),
            vol_h6=_f(vol.get("h6")),
            vol_h24=_f(vol.get("h24")),
            buys_m5=(tx.get("m5") or {}).get("buys"),
            sells_m5=(tx.get("m5") or {}).get("sells"),
            buys_h1=(tx.get("h1") or {}).get("buys"),
            sells_h1=(tx.get("h1") or {}).get("sells"),
            buys_h24=(tx.get("h24") or {}).get("buys"),
            sells_h24=(tx.get("h24") or {}).get("sells"),
            chg_m5=_f(chg.get("m5")),
            chg_h1=_f(chg.get("h1")),
            chg_h6=_f(chg.get("h6")),
            chg_h24=_f(chg.get("h24")),
            has_socials=bool(info.get("socials") or info.get("websites")),
            boosted=bool((p.get("boosts") or {}).get("active")),
        )
