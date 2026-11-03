"""Protezioni hard-coded, FUORI dal controllo dell'agente.

L'agente non ha tool per modificare questi limiti: può solo proporre operazioni,
che vengono ridimensionate o bloccate qui.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .config import Tunables, env, tunables
from .db import Account, Position


def today_str() -> str:
    return date.today().isoformat()  # ora locale del Mac


def kill_switch_active(acc: Account | None) -> bool:
    return bool((acc and acc.kill_switch) or env.kill_file.exists())


def halt_reason(acc: Account | None) -> str | None:
    if kill_switch_active(acc):
        return "KILL SWITCH attivo"
    if acc and acc.halted_day == today_str():
        return f"stop giornaliero: {acc.halted_reason}"
    return None


@dataclass
class BuyCheck:
    ok: bool
    usd: float
    reason: str


def check_buy(acc: Account, open_positions: list[Position], equity_usd: float, mint: str, requested_usd: float, t: Tunables | None = None) -> BuyCheck:
    t = t or tunables()
    h = halt_reason(acc)
    if h:
        return BuyCheck(False, 0, h)
    if any(p.mint == mint for p in open_positions):
        return BuyCheck(False, 0, "posizione già aperta su questo token")
    if len(open_positions) >= t.max_open_positions:
        return BuyCheck(False, 0, f"max posizioni aperte raggiunto ({t.max_open_positions})")
    cap = equity_usd * t.max_position_pct / 100
    usd = min(requested_usd, cap, acc.cash_usd)
    if usd < t.min_position_usd:
        return BuyCheck(False, 0, f"size {usd:.2f}$ sotto il minimo {t.min_position_usd}$ (cash {acc.cash_usd:.2f}$)")
    note = "ok" if usd >= requested_usd - 1e-9 else f"ridotta da {requested_usd:.2f}$ a {usd:.2f}$ (limite {t.max_position_pct}% equity/cash)"
    return BuyCheck(True, round(usd, 2), note)


def update_daily_guard(acc: Account, equity_usd: float, t: Tunables | None = None) -> str | None:
    """Aggiorna l'equity di inizio giornata e attiva lo stop se la perdita supera il limite."""
    t = t or tunables()
    today = today_str()
    if acc.day != today:
        acc.day = today
        acc.day_start_equity = equity_usd
    if acc.day_start_equity and acc.halted_day != today:
        loss_pct = (acc.day_start_equity - equity_usd) / acc.day_start_equity * 100
        if loss_pct >= t.daily_loss_limit_pct:
            acc.halted_day = today
            acc.halted_reason = f"perdita giornaliera {loss_pct:.1f}% >= {t.daily_loss_limit_pct}%"
            return acc.halted_reason
    return None


def exit_signal(pos: Position, price: float | None, liquidity: float | None, now: datetime, t: Tunables | None = None) -> str | None:
    """Uscite automatiche eseguite dal codice (non dall'agente)."""
    t = t or tunables()
    if price is None or price <= 0:
        return None
    chg = (price / pos.entry_price_mkt - 1) * 100
    if chg <= -t.stop_loss_pct:
        return f"stop loss ({chg:.1f}%)"
    if chg >= t.take_profit_pct:
        return f"take profit (+{chg:.1f}%)"
    hw = max(pos.high_water_price, price)
    hw_gain = (hw / pos.entry_price_mkt - 1) * 100
    if hw_gain >= t.trailing_activation_pct:
        dd = (price / hw - 1) * 100
        if dd <= -t.trailing_stop_pct:
            return f"trailing stop ({dd:.1f}% dal massimo, max +{hw_gain:.0f}%)"
    if (now - pos.opened_at).total_seconds() / 3600 >= t.max_hold_hours:
        return f"tempo massimo di holding ({t.max_hold_hours}h)"
    if liquidity is not None and liquidity < t.min_liquidity_to_hold_usd:
        return f"liquidità crollata ({liquidity:,.0f}$)"
    return None
