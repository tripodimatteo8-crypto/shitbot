"""Jupiter: quote reali di swap (per simulare l'esecuzione) e prezzo SOL.

Docs: https://dev.jup.ag/docs/swap-api  (lite-api.jup.ag è il tier gratuito senza chiave)
"""
from __future__ import annotations

import time

from .base import Quote
from .http import get_json

BASE = "https://lite-api.jup.ag"
SOL = "So11111111111111111111111111111111111111112"


class Jupiter:
    _sol_cache: tuple[float, float] | None = None

    def sol_price_usd(self) -> float | None:
        if self._sol_cache and time.time() - self._sol_cache[0] < 60:
            return self._sol_cache[1]
        d = get_json(f"{BASE}/price/v3", params={"ids": SOL})
        try:
            p = float(d[SOL]["usdPrice"])
            Jupiter._sol_cache = (time.time(), p)
            return p
        except (TypeError, KeyError, ValueError):
            return self._sol_cache[1] if self._sol_cache else None

    def _quote(self, input_mint: str, output_mint: str, amount_raw: int):
        d = get_json(
            f"{BASE}/swap/v1/quote",
            params={"inputMint": input_mint, "outputMint": output_mint, "amount": str(amount_raw), "slippageBps": 1500},
        )
        if not isinstance(d, dict) or "outAmount" not in d:
            return None
        return d

    def quote_buy(self, mint: str, usd: float, decimals: int) -> Quote | None:
        sol = self.sol_price_usd()
        if not sol:
            return None
        lamports = int(usd / sol * 1e9)
        d = self._quote(SOL, mint, lamports)
        if not d:
            return None
        return Quote(
            in_amount=usd,
            out_amount=int(d["outAmount"]) / 10**decimals,
            price_impact_pct=abs(float(d.get("priceImpactPct") or 0)) * 100,
            source="jupiter",
        )

    def quote_sell(self, mint: str, qty: float, decimals: int) -> Quote | None:
        sol = self.sol_price_usd()
        if not sol:
            return None
        raw = int(qty * 10**decimals)
        if raw <= 0:
            return None
        d = self._quote(mint, SOL, raw)
        if not d:
            return None
        return Quote(
            in_amount=qty,
            out_amount=int(d["outAmount"]) / 1e9 * sol,
            price_impact_pct=abs(float(d.get("priceImpactPct") or 0)) * 100,
            source="jupiter",
        )
