"""Portafoglio (paper): apertura/chiusura posizioni attraverso l'ExecutionEngine e il RiskManager."""
from __future__ import annotations

import logging
import threading

from sqlalchemy.orm import Session

from .config import tunables
from .db import Account, Decision, EquitySnapshot, Fill, Position, SecurityReport, Snapshot, Token, log_event, session_scope, utcnow
from .execution import get_engine, model_slippage_pct
from .risk import check_buy, halt_reason, update_daily_guard

log = logging.getLogger("solbot.portfolio")
LOCK = threading.RLock()  # serializza tutte le operazioni sul portafoglio


def ensure_account(s: Session) -> Account:
    acc = s.get(Account, 1)
    if acc is None:
        t = tunables()
        acc = Account(id=1, cash_usd=t.initial_capital_usd, initial_capital_usd=t.initial_capital_usd)
        s.add(acc)
        s.flush()
    return acc


def liquidation_value(pos: Position) -> float:
    """Valore prudente di una posizione: prezzo * qty meno slippage stimato e buffer MEV."""
    if not pos.last_price:
        return 0.0
    t = tunables()
    notional = pos.qty * pos.last_price
    slip = model_slippage_pct(notional, pos.last_liquidity, 0.5)
    return notional * (1 - slip / 100) * (1 - t.mev_buffer_pct / 100) * (1 - t.swap_fee_pct / 100)


def equity(s: Session) -> tuple[float, float, list[Position]]:
    acc = ensure_account(s)
    opens = s.query(Position).filter(Position.status == "open").all()
    pos_val = sum(liquidation_value(p) for p in opens)
    return acc.cash_usd + pos_val, pos_val, opens


def _decimals(s: Session, mint: str) -> int:
    rep = s.query(SecurityReport).filter(SecurityReport.mint == mint).order_by(SecurityReport.ts.desc()).first()
    if rep and rep.decimals is not None:
        return rep.decimals
    tok = s.get(Token, mint)
    return tok.decimals if tok and tok.decimals is not None else 6


def _latest_snapshot(s: Session, mint: str) -> Snapshot | None:
    return s.query(Snapshot).filter(Snapshot.mint == mint).order_by(Snapshot.ts.desc()).first()


def open_position(mint: str, requested_usd: float, decision_id: int | None, decider: str, lessons_version: int | None,
                  ref_price: float | None = None, liquidity: float | None = None) -> tuple[bool, str, int | None]:
    with LOCK:
        with session_scope() as s:
            acc = ensure_account(s)
            eq, _, opens = equity(s)
            chk = check_buy(acc, opens, eq, mint, requested_usd)
            dec = s.get(Decision, decision_id) if decision_id else None
            if not chk.ok:
                if dec:
                    dec.blocked_reason = chk.reason
                return False, chk.reason, None
            snap = _latest_snapshot(s, mint)
            ref_price = ref_price or (snap.price_usd if snap else None)
            liquidity = liquidity or (snap.liquidity_usd if snap else None)
            if not ref_price:
                return False, "prezzo di riferimento assente", None
            decimals = _decimals(s, mint)
            tok = s.get(Token, mint)
        # esecuzione (con ritardo simulato) fuori dalla sessione DB
        fill = get_engine().buy(mint, chk.usd, decimals, ref_price, liquidity)
        if not fill.ok:
            return False, f"esecuzione fallita: {fill.error}", None
        with session_scope() as s:
            acc = ensure_account(s)
            acc.cash_usd -= fill.usd_net
            pos = Position(
                mint=mint, symbol=tok.symbol if tok else None, status="open", engine=get_engine().name,
                qty=fill.qty, cost_usd=fill.usd_net, entry_price_eff=fill.price_eff, entry_price_mkt=ref_price,
                high_water_price=ref_price, last_price=ref_price, last_liquidity=liquidity,
                buy_decision_id=decision_id, decider=decider, lessons_version=lessons_version,
            )
            s.add(pos)
            s.flush()
            s.add(Fill(position_id=pos.id, side="buy", qty=fill.qty, usd_gross=fill.usd_gross, fees_usd=fill.fees_usd,
                       usd_net=fill.usd_net, price_ref=fill.price_ref, price_eff=fill.price_eff,
                       slippage_pct=fill.slippage_pct, quote_source=fill.quote_source, delay_s=fill.delay_s))
            dec = s.get(Decision, decision_id) if decision_id else None
            if dec:
                dec.executed = True
                dec.position_id = pos.id
                if chk.reason != "ok":
                    dec.blocked_reason = chk.reason
            pid = pos.id
        msg = (f"BUY {tok.symbol if tok else mint[:6]} {fill.usd_net:.2f}$ -> {fill.qty:,.0f} token "
               f"(slippage {fill.slippage_pct:+.2f}%, fee {fill.fees_usd:.2f}$, fonte {fill.quote_source})")
        log.info(msg)
        log_event("info", "trade", msg)
        return True, msg, pid


def close_position(position_id: int, reason: str, decision_id: int | None = None) -> tuple[bool, str]:
    with LOCK:
        with session_scope() as s:
            pos = s.get(Position, position_id)
            if not pos or pos.status != "open":
                return False, "posizione non aperta"
            snap = _latest_snapshot(s, pos.mint)
            ref = pos.last_price or (snap.price_usd if snap else None) or 0.0
            liq = pos.last_liquidity or (snap.liquidity_usd if snap else None)
            decimals = _decimals(s, pos.mint)
            mint, qty, sym = pos.mint, pos.qty, pos.symbol
        fill = get_engine().sell(mint, qty, decimals, ref, liq)
        if not fill.ok:
            return False, f"esecuzione fallita: {fill.error}"
        with session_scope() as s:
            pos = s.get(Position, position_id)
            acc = ensure_account(s)
            acc.cash_usd += fill.usd_net
            pos.status = "closed"
            pos.closed_at = utcnow()
            pos.proceeds_usd = fill.usd_net
            pos.pnl_usd = fill.usd_net - pos.cost_usd
            pos.pnl_pct = (fill.usd_net / pos.cost_usd - 1) * 100 if pos.cost_usd else 0
            pos.exit_reason = reason
            pos.sell_decision_id = decision_id
            s.add(Fill(position_id=pos.id, side="sell", qty=qty, usd_gross=fill.usd_gross, fees_usd=fill.fees_usd,
                       usd_net=fill.usd_net, price_ref=fill.price_ref, price_eff=fill.price_eff,
                       slippage_pct=fill.slippage_pct, quote_source=fill.quote_source, delay_s=fill.delay_s))
            if decision_id:
                dec = s.get(Decision, decision_id)
                if dec:
                    dec.executed = True
                    dec.position_id = pos.id
            pnl, pnl_pct = pos.pnl_usd, pos.pnl_pct
        msg = f"SELL {sym or mint[:6]} -> {fill.usd_net:.2f}$ PnL {pnl:+.2f}$ ({pnl_pct:+.1f}%) motivo: {reason}"
        log.info(msg)
        log_event("info", "trade", msg)
        return True, msg


def record_equity() -> dict:
    with LOCK, session_scope() as s:
        acc = ensure_account(s)
        eq, pos_val, opens = equity(s)
        halted = update_daily_guard(acc, eq)
        if halted:
            log.warning("STOP GIORNALIERO: %s", halted)
            log_event("warning", "risk", f"Stop giornaliero attivato: {halted}")
        s.add(EquitySnapshot(equity_usd=eq, cash_usd=acc.cash_usd, positions_usd=pos_val, open_positions=len(opens)))
        return {"equity": eq, "cash": acc.cash_usd, "positions": pos_val, "open": len(opens), "halt": halt_reason(acc)}
