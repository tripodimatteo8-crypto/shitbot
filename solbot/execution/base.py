from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class FillResult:
    ok: bool
    side: str
    qty: float = 0.0  # token
    usd_gross: float = 0.0  # USD scambiati prima delle fee fisse
    fees_usd: float = 0.0
    usd_net: float = 0.0  # buy: USD totali spesi; sell: USD incassati netti
    price_ref: float = 0.0  # prezzo di mercato di riferimento
    price_eff: float = 0.0  # prezzo effettivo per token (netto costi)
    slippage_pct: float = 0.0  # peggioramento vs prezzo di riferimento (incl. impatto + MEV)
    quote_source: str = ""
    delay_s: float = 0.0
    error: str | None = None


class ExecutionEngine(ABC):
    name = "abstract"

    @abstractmethod
    def buy(self, mint: str, usd: float, decimals: int, ref_price: float, liquidity_usd: float | None) -> FillResult: ...

    @abstractmethod
    def sell(self, mint: str, qty: float, decimals: int, ref_price: float, liquidity_usd: float | None) -> FillResult: ...
