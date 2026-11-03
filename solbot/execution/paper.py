"""Esecuzione simulata prudente.

Ordine di preferenza per il prezzo di esecuzione:
1. quote reale Jupiter presa DOPO il ritardo simulato (include impatto di prezzo e fee AMM);
2. se Jupiter non quota: modello constant-product sulla liquidità DexScreener con slippage minimo.
Sopra a questo aggiungiamo sempre: buffer MEV/sniper per lato, fee aggregatore, priority fee + fee rete.
Il paper trading resta OTTIMISTICO rispetto al reale: questi costi sono volutamente pessimisti.
"""
from __future__ import annotations

import logging
import time

from ..config import tunables
from ..providers import get_provider
from .base import ExecutionEngine, FillResult

log = logging.getLogger("solbot.paper")


def model_slippage_pct(usd: float, liquidity_usd: float | None, floor_pct: float) -> float:
    """Slippage stimato per uno swap di `usd` su un pool constant-product.

    La liquidità DexScreener è il totale dei due lati; il lato quote vale ~metà.
    Impatto x/(x+y) in percentuale, mai sotto `floor_pct`. Liquidità ignota = 50%.
    """
    if not liquidity_usd or liquidity_usd <= 0:
        return 50.0
    side = liquidity_usd / 2
    impact = usd / (side + usd) * 100
    return max(floor_pct, impact)


class PaperEngine(ExecutionEngine):
    name = "paper"

    def __init__(self, sleep=time.sleep):
        self._sleep = sleep

    def _fixed_fees_usd(self) -> float:
        t = tunables()
        sol = get_provider().sol_price_usd() or 150.0  # fallback prudente se manca il prezzo
        return (t.priority_fee_sol + t.network_fee_sol) * sol

    def buy(self, mint, usd, decimals, ref_price, liquidity_usd) -> FillResult:
        t = tunables()
        if usd <= 0 or ref_price <= 0:
            return FillResult(ok=False, side="buy", error="importo o prezzo non validi")
        self._sleep(t.execution_delay_s)
        fixed = self._fixed_fees_usd()
        platform_fee = usd * t.swap_fee_pct / 100
        swap_usd = usd - fixed - platform_fee
        if swap_usd <= 0:
            return FillResult(ok=False, side="buy", error="importo inferiore ai costi")
        q = get_provider().quote_buy(mint, swap_usd, decimals)
        if q and q.out_amount > 0:
            qty, source = q.out_amount, "jupiter"
        else:
            slip = model_slippage_pct(swap_usd, liquidity_usd, t.fallback_slippage_floor_pct)
            qty, source = swap_usd / ref_price * (1 - slip / 100), "model"
        qty *= 1 - t.mev_buffer_pct / 100
        if qty <= 0:
            return FillResult(ok=False, side="buy", error="quantità nulla")
        price_swap = swap_usd / qty
        return FillResult(
            ok=True, side="buy", qty=qty, usd_gross=swap_usd, fees_usd=fixed + platform_fee, usd_net=usd,
            price_ref=ref_price, price_eff=usd / qty, slippage_pct=(price_swap / ref_price - 1) * 100,
            quote_source=source, delay_s=t.execution_delay_s,
        )

    def sell(self, mint, qty, decimals, ref_price, liquidity_usd) -> FillResult:
        t = tunables()
        if qty <= 0:
            return FillResult(ok=False, side="sell", error="quantità non valida")
        self._sleep(t.execution_delay_s)
        q = get_provider().quote_sell(mint, qty, decimals)
        if q and q.out_amount > 0:
            gross, source = q.out_amount, "jupiter"
        elif ref_price and ref_price > 0:
            notional = qty * ref_price
            slip = model_slippage_pct(notional, liquidity_usd, t.fallback_slippage_floor_pct)
            gross, source = notional * (1 - slip / 100), "model"
        else:
            gross, source = 0.0, "none"  # nessun prezzo e nessuna route: valore zero (rug)
        gross *= 1 - t.mev_buffer_pct / 100
        fixed = self._fixed_fees_usd()
        platform_fee = gross * t.swap_fee_pct / 100
        net = max(0.0, gross - platform_fee - fixed)
        slip = ((gross / qty) / ref_price - 1) * 100 if ref_price and qty else -100.0
        return FillResult(
            ok=True, side="sell", qty=qty, usd_gross=gross, fees_usd=min(gross, platform_fee + fixed), usd_net=net,
            price_ref=ref_price or 0.0, price_eff=net / qty, slippage_pct=slip, quote_source=source, delay_s=t.execution_delay_s,
        )
