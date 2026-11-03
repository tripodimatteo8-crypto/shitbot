"""Valutatore oggettivo (in codice): esiti dei candidati e metriche di performance.

L'agente non si autovaluta: tutto ciò che legge nella riflessione viene da qui.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import timedelta

from .config import tunables
from .db import Account, Candidate, EquitySnapshot, Position, Snapshot, session_scope, utcnow

log = logging.getLogger("solbot.evaluator")
HORIZONS = {"ret_1h": 1, "ret_6h": 6, "ret_24h": 24}
WINDOW_MIN = 45  # tolleranza per trovare uno snapshot dopo l'orizzonte
EST_ROUNDTRIP_COST_PCT = 6.0  # stima prudente usata per giudicare i candidati non comprati


def _ret(p0: float | None, snap: Snapshot) -> float | None:
    if not p0:
        return None
    if snap.price_usd is None:
        return -100.0 if (snap.liquidity_usd or 0) == 0 else None
    return (snap.price_usd / p0 - 1) * 100


def evaluate_candidates() -> int:
    """Calcola gli esiti a 1h/6h/24h di tutti i candidati (anche filtrati, saltati, scaduti)."""
    now = utcnow()
    updated = 0
    with session_scope() as s:
        todo = s.query(Candidate).filter(
            Candidate.ts < now - timedelta(hours=1), Candidate.ts > now - timedelta(hours=27),
            (Candidate.ret_1h.is_(None)) | (Candidate.ret_6h.is_(None)) | (Candidate.ret_24h.is_(None)),
        ).all()
        by_mint: dict[str, list[Candidate]] = defaultdict(list)
        for c in todo:
            by_mint[c.mint].append(c)
        for mint, cs in by_mint.items():
            t0 = min(c.ts for c in cs)
            snaps = s.query(Snapshot).filter(Snapshot.mint == mint, Snapshot.ts >= t0).order_by(Snapshot.ts).all()
            for c in cs:
                changed = False
                for col, h in HORIZONS.items():
                    if getattr(c, col) is not None or now < c.ts + timedelta(hours=h):
                        continue
                    target = c.ts + timedelta(hours=h)
                    snap = next((x for x in snaps if target <= x.ts <= target + timedelta(minutes=WINDOW_MIN)), None)
                    if snap is None:
                        # nessuno snapshot nella finestra: se il token è sparito prima, è un rug
                        prev = [x for x in snaps if c.ts < x.ts <= target]
                        if prev and prev[-1].price_usd is None and (prev[-1].liquidity_usd or 0) == 0:
                            snap = prev[-1]
                    if snap is not None:
                        r = _ret(c.price_usd, snap)
                        if r is not None:
                            setattr(c, col, round(r, 2))
                            changed = True
                if c.ret_24h is not None and c.max_ret_24h is None:
                    window = [x for x in snaps if c.ts <= x.ts <= c.ts + timedelta(hours=24, minutes=WINDOW_MIN)]
                    rets = [r for r in (_ret(c.price_usd, x) for x in window) if r is not None]
                    if rets:
                        c.max_ret_24h, c.min_ret_24h = round(max(rets), 2), round(min(rets), 2)
                    c.rugged_24h = c.ret_24h <= -90
                    changed = True
                updated += changed
    if updated:
        log.info("Valutatore: aggiornati esiti di %d candidati", updated)
    return updated


def _trade_stats(trades: list[Position]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0}
    pnls = [p.pnl_usd or 0 for p in trades]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    return {
        "n": n,
        "win_rate": round(len(wins) / n * 100, 1),
        "pnl_usd": round(sum(pnls), 2),
        "avg_win_usd": round(gross_win / len(wins), 2) if wins else 0,
        "avg_loss_usd": round(-gross_loss / len(losses), 2) if losses else 0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_win > 0 else 0),
        "expectancy_usd": round(sum(pnls) / n, 2),
        "avg_pnl_pct": round(sum(p.pnl_pct or 0 for p in trades) / n, 2),
    }


def max_drawdown_pct(values: list[float]) -> float:
    peak, mdd = -math.inf, 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100)
    return round(mdd, 2)


def _cohort(cs: list[Candidate]) -> dict:
    out = {"n": len(cs)}
    for col in HORIZONS:
        vals = [getattr(c, col) for c in cs if getattr(c, col) is not None]
        if vals:
            out[col] = {
                "n": len(vals),
                "mean": round(sum(vals) / len(vals), 1),
                "median": round(sorted(vals)[len(vals) // 2], 1),
                "pct_above_costs": round(sum(v > EST_ROUNDTRIP_COST_PCT for v in vals) / len(vals) * 100, 1),
            }
    rug = [c for c in cs if c.rugged_24h is not None]
    if rug:
        out["rug_rate_24h"] = round(sum(c.rugged_24h for c in rug) / len(rug) * 100, 1)
    return out


def metrics(since_days: float | None = None) -> dict:
    with session_scope() as s:
        q = s.query(Position).filter(Position.status == "closed")
        cq = s.query(Candidate)
        eq_q = s.query(EquitySnapshot.equity_usd).order_by(EquitySnapshot.ts)
        if since_days:
            since = utcnow() - timedelta(days=since_days)
            q = q.filter(Position.closed_at >= since)
            cq = cq.filter(Candidate.ts >= since)
            eq_q = eq_q.filter(EquitySnapshot.ts >= since)
        closed = q.all()
        cands = cq.all()
        eqs = [e for (e,) in eq_q.all()]
        acc = s.get(Account, 1)
        by_decider: dict[str, list[Position]] = defaultdict(list)
        by_reason: dict[str, list[Position]] = defaultdict(list)
        for p in closed:
            by_decider[p.decider or "?"].append(p)
            by_reason[(p.exit_reason or "?").split(" (")[0].split(":")[0]].append(p)
        cohorts = defaultdict(list)
        for c in cands:
            cohorts[c.status].append(c)
        return {
            "trades": _trade_stats(closed),
            "by_decider": {k: _trade_stats(v) for k, v in by_decider.items()},
            "by_exit_reason": {k: _trade_stats(v) for k, v in by_reason.items()},
            "max_drawdown_pct": max_drawdown_pct(eqs),
            "equity_usd": round(eqs[-1], 2) if eqs else None,
            "initial_capital_usd": acc.initial_capital_usd if acc else None,
            "candidates": {k: _cohort(v) for k, v in cohorts.items()},
            "est_roundtrip_cost_pct": EST_ROUNDTRIP_COST_PCT,
        }


def gate_status() -> dict:
    """Gate di promozione paper -> live. Tutte le condizioni devono essere vere."""
    t = tunables()
    m = metrics()
    with session_scope() as s:
        acc = s.get(Account, 1)
        days = (utcnow() - acc.created_at).total_seconds() / 86400 if acc else 0
        confirmed = bool(acc and acc.live_confirmed)
    tr = m["trades"]
    checks = {
        f"giorni >= {t.gate_min_days}": days >= t.gate_min_days,
        f"trade chiusi >= {t.gate_min_trades}": tr.get("n", 0) >= t.gate_min_trades,
        f"PnL netto > {t.gate_min_pnl_usd}$": tr.get("pnl_usd", 0) > t.gate_min_pnl_usd,
        f"drawdown max <= {t.gate_max_drawdown_pct}%": m["max_drawdown_pct"] <= t.gate_max_drawdown_pct,
        f"profit factor >= {t.gate_min_profit_factor}": (tr.get("profit_factor") or 0) >= t.gate_min_profit_factor,
    }
    return {"passed": all(checks.values()), "checks": checks, "days": round(days, 1), "manual_confirmed": confirmed}
