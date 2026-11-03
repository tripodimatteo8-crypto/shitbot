"""API FastAPI per la dashboard (+ serve la build React)."""
from __future__ import annotations

import json
import threading
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func

from . import scheduler
from .agent import choose_decider
from .config import EDITABLE_KEYS, ROOT, Tunables, env, invalidate_cache, tunables
from .costs import today_usage
from .db import (Account, Candidate, ClaudeUsage, Decision, EquitySnapshot, EventLog, Fill, LessonVersion, Position,
                 Setting, init_db, log_event, session_scope, utcnow)
from .evaluator import gate_status, metrics
from .lessons import current_lessons
from .portfolio import close_position, ensure_account, equity
from .risk import halt_reason, kill_switch_active


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as s:
        ensure_account(s)
    current_lessons()
    scheduler.start()
    log_event("info", "system", f"SolBot avviato (decider={choose_decider()})")
    yield
    scheduler.shutdown()


app = FastAPI(title="SolBot", lifespan=lifespan)


def _iso(d):
    return d.isoformat() + "Z" if d else None


@app.get("/api/overview")
def overview():
    t = tunables()
    with session_scope() as s:
        acc = ensure_account(s)
        eq, pos_val, opens = equity(s)
        unreal = sum(((p.last_price or 0) * p.qty) - p.cost_usd for p in opens)
        res = {
            "equity_usd": round(eq, 2), "cash_usd": round(acc.cash_usd, 2), "positions_usd": round(pos_val, 2),
            "initial_capital_usd": acc.initial_capital_usd, "pnl_usd": round(eq - acc.initial_capital_usd, 2),
            "pnl_pct": round((eq / acc.initial_capital_usd - 1) * 100, 2), "unrealized_mkt_usd": round(unreal, 2),
            "open_positions": len(opens), "kill_switch": kill_switch_active(acc), "halt": halt_reason(acc),
            "day_start_equity": acc.day_start_equity, "started_at": _iso(acc.created_at),
        }
    m = metrics()
    res.update({
        "trades": m["trades"], "max_drawdown_pct": m["max_drawdown_pct"], "decider": choose_decider(),
        "model": t.claude_model, "jobs": scheduler.jobs_status(), "costs_today": today_usage(),
        "live_enabled": env.live_trading_enabled, "engine": "paper",
    })
    return res


@app.get("/api/metrics")
def get_metrics(days: float | None = None):
    return metrics(days)


@app.get("/api/equity")
def get_equity(days: float = 7):
    with session_scope() as s:
        rows = s.query(EquitySnapshot).filter(EquitySnapshot.ts >= utcnow() - timedelta(days=days)).order_by(EquitySnapshot.ts).all()
        return [{"ts": _iso(r.ts), "equity": round(r.equity_usd, 2), "cash": round(r.cash_usd, 2), "open": r.open_positions} for r in rows]


def _pos_dict(p: Position, decs: dict) -> dict:
    bd, sd = decs.get(p.buy_decision_id), decs.get(p.sell_decision_id)
    mkt_pnl = ((p.last_price or 0) * p.qty - p.cost_usd) if p.status == "open" else p.pnl_usd
    return {
        "id": p.id, "mint": p.mint, "symbol": p.symbol, "status": p.status, "opened_at": _iso(p.opened_at),
        "closed_at": _iso(p.closed_at), "cost_usd": round(p.cost_usd, 2), "qty": p.qty,
        "entry_price_mkt": p.entry_price_mkt, "entry_price_eff": p.entry_price_eff, "last_price": p.last_price,
        "last_liquidity": p.last_liquidity, "proceeds_usd": p.proceeds_usd, "pnl_usd": round(mkt_pnl or 0, 2),
        "pnl_pct": round(((mkt_pnl or 0) / p.cost_usd) * 100, 2) if p.cost_usd else 0, "exit_reason": p.exit_reason,
        "decider": p.decider, "buy_reason": bd.reason if bd else None, "buy_confidence": bd.confidence if bd else None,
        "sell_reason": sd.reason if sd else None, "lessons_version": p.lessons_version,
    }


@app.get("/api/positions")
def get_positions(status: str = "open", limit: int = 200):
    with session_scope() as s:
        q = s.query(Position).filter(Position.status == status)
        q = q.order_by(Position.opened_at.desc() if status == "open" else Position.closed_at.desc()).limit(limit)
        rows = q.all()
        ids = {i for p in rows for i in (p.buy_decision_id, p.sell_decision_id) if i}
        decs = {d.id: d for d in s.query(Decision).filter(Decision.id.in_(ids)).all()} if ids else {}
        fills = {}
        for f in s.query(Fill).filter(Fill.position_id.in_([p.id for p in rows])).all():
            fills.setdefault(f.position_id, []).append({"side": f.side, "usd_net": round(f.usd_net, 2), "fees_usd": round(f.fees_usd, 2),
                                                         "slippage_pct": round(f.slippage_pct, 2), "source": f.quote_source})
        return [{**_pos_dict(p, decs), "fills": fills.get(p.id, [])} for p in rows]


@app.post("/api/positions/{pid}/close")
def post_close(pid: int):
    ok, msg = close_position(pid, "chiusura manuale da dashboard")
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "message": msg}


@app.post("/api/close_all")
def post_close_all():
    with session_scope() as s:
        ids = [p.id for p in s.query(Position).filter(Position.status == "open").all()]
    return {"results": [close_position(i, "chiusura manuale (tutte)") for i in ids]}


@app.get("/api/decisions")
def get_decisions(limit: int = 100):
    with session_scope() as s:
        rows = s.query(Decision).order_by(Decision.ts.desc()).limit(limit).all()
        return [{"id": d.id, "ts": _iso(d.ts), "mint": d.mint, "symbol": d.symbol, "action": d.action, "reason": d.reason,
                 "confidence": d.confidence, "decider": d.decider, "model": d.model, "executed": d.executed,
                 "blocked_reason": d.blocked_reason, "requested_usd": d.requested_usd} for d in rows]


@app.get("/api/candidates")
def get_candidates(limit: int = 150, passed: bool | None = None):
    with session_scope() as s:
        q = s.query(Candidate)
        if passed is not None:
            q = q.filter(Candidate.passed_filters == passed)
        rows = q.order_by(Candidate.ts.desc()).limit(limit).all()
        ids = [c.decision_id for c in rows if c.decision_id]
        decs = {d.id: d for d in s.query(Decision).filter(Decision.id.in_(ids)).all()} if ids else {}
        return [{
            "id": c.id, "ts": _iso(c.ts), "mint": c.mint, "symbol": c.symbol, "price_usd": c.price_usd,
            "liquidity_usd": c.liquidity_usd, "mcap_usd": c.mcap_usd, "age_minutes": c.age_minutes,
            "passed": c.passed_filters, "reasons": c.filter_reasons, "status": c.status, "features": c.features,
            "decision_reason": decs[c.decision_id].reason if c.decision_id in decs else None,
            "decision_confidence": decs[c.decision_id].confidence if c.decision_id in decs else None,
            "ret_1h": c.ret_1h, "ret_6h": c.ret_6h, "ret_24h": c.ret_24h, "max_ret_24h": c.max_ret_24h,
        } for c in rows]


@app.get("/api/candidates/stats")
def candidate_stats(hours: float = 24):
    with session_scope() as s:
        since = utcnow() - timedelta(hours=hours)
        total = s.query(func.count(Candidate.id)).filter(Candidate.ts >= since).scalar()
        passed = s.query(func.count(Candidate.id)).filter(Candidate.ts >= since, Candidate.passed_filters.is_(True)).scalar()
        reasons: dict[str, int] = {}
        for (r,) in s.query(Candidate.filter_reasons).filter(Candidate.ts >= since, Candidate.passed_filters.is_(False)).all():
            if r:
                key = r[0].split(" ")[0] if r[0] else "?"
                key = {"liquidità": "liquidità", "troppo": "età"}.get(key, key)
                reasons[key] = reasons.get(key, 0) + 1
        return {"total": total, "passed": passed, "top_reject_reasons": sorted(reasons.items(), key=lambda x: -x[1])[:10]}


@app.get("/api/lessons")
def get_lessons():
    with session_scope() as s:
        rows = s.query(LessonVersion).order_by(LessonVersion.id.desc()).all()
        out = []
        for v in rows:
            after = metrics_after_version(s, v)
            out.append({"id": v.id, "ts": _iso(v.ts), "trigger": v.trigger, "model": v.model, "content": v.content,
                        "metrics_before": (v.metrics or {}).get("trades"), "metrics_after": after,
                        "closed_trades": v.closed_trades})
        return out


def metrics_after_version(s, v: LessonVersion) -> dict:
    """Statistiche dei trade aperti mentre questa versione delle lezioni era attiva."""
    ps = s.query(Position).filter(Position.lessons_version == v.id, Position.status == "closed").all()
    if not ps:
        return {"n": 0}
    pnl = [p.pnl_usd or 0 for p in ps]
    wins = [x for x in pnl if x > 0]
    return {"n": len(ps), "win_rate": round(len(wins) / len(ps) * 100, 1), "pnl_usd": round(sum(pnl), 2),
            "expectancy_usd": round(sum(pnl) / len(ps), 2)}


@app.post("/api/reflect")
def post_reflect():
    from .reflection import reflect

    threading.Thread(target=reflect, args=("manual",), daemon=True).start()
    return {"started": True}


@app.get("/api/costs")
def get_costs(days: int = 30):
    with session_scope() as s:
        rows = s.query(
            func.date(ClaudeUsage.ts), ClaudeUsage.purpose, func.count(ClaudeUsage.id), func.sum(ClaudeUsage.input_tokens),
            func.sum(ClaudeUsage.output_tokens), func.sum(ClaudeUsage.cache_read_tokens), func.sum(ClaudeUsage.cache_write_tokens),
            func.sum(ClaudeUsage.cost_usd),
        ).filter(ClaudeUsage.ts >= utcnow() - timedelta(days=days)).group_by(func.date(ClaudeUsage.ts), ClaudeUsage.purpose).all()
    days_map: dict[str, dict] = {}
    for day, purpose, n, i, o, cr, cw, c in rows:
        d = days_map.setdefault(day, {"day": day, "calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "usd": 0.0, "decision_usd": 0.0, "reflection_usd": 0.0})
        d["calls"] += n
        d["input"] += i or 0
        d["output"] += o or 0
        d["cache_read"] += cr or 0
        d["cache_write"] += cw or 0
        d["usd"] = round(d["usd"] + (c or 0), 4)
        d[f"{purpose}_usd"] = round(d.get(f"{purpose}_usd", 0) + (c or 0), 4)
    return {"days": sorted(days_map.values(), key=lambda x: x["day"]), "today": today_usage()}


@app.get("/api/settings")
def get_settings():
    t = tunables(force=True)
    defaults = Tunables().model_dump()
    return {"values": t.model_dump(), "defaults": defaults}


@app.put("/api/settings")
def put_settings(values: dict = Body(...)):
    bad = [k for k in values if k not in EDITABLE_KEYS]
    if bad:
        raise HTTPException(400, f"chiavi non modificabili: {bad}")
    merged = {**tunables(force=True).model_dump(), **values}
    try:
        Tunables.model_validate(merged)
    except Exception as e:
        raise HTTPException(400, str(e))
    with session_scope() as s:
        for k, v in values.items():
            row = s.get(Setting, k)
            if row is None:
                s.add(Setting(key=k, value=json.dumps(v)))
            else:
                row.value = json.dumps(v)
                row.updated_at = utcnow()
    invalidate_cache()
    scheduler.reschedule()
    log_event("info", "settings", f"Impostazioni aggiornate: {values}")
    return get_settings()


@app.post("/api/settings/reset")
def reset_settings():
    with session_scope() as s:
        s.query(Setting).delete()
    invalidate_cache()
    scheduler.reschedule()
    return get_settings()


@app.post("/api/kill")
def post_kill(active: bool = Body(..., embed=True)):
    with session_scope() as s:
        acc = ensure_account(s)
        acc.kill_switch = active
    if not active and env.kill_file.exists():
        env.kill_file.unlink()
    log_event("warning", "risk", f"Kill switch {'ATTIVATO' if active else 'disattivato'} da dashboard")
    return {"kill_switch": active}


@app.post("/api/resume_day")
def resume_day():
    """Sblocca manualmente lo stop giornaliero (decisione umana)."""
    with session_scope() as s:
        acc = ensure_account(s)
        acc.halted_day = None
        acc.halted_reason = None
        eq, _, _ = equity(s)
        acc.day_start_equity = eq
    log_event("warning", "risk", "Stop giornaliero rimosso manualmente")
    return {"ok": True}


@app.get("/api/live/gate")
def get_gate():
    g = gate_status()
    g["live_trading_enabled_env"] = env.live_trading_enabled
    return g


@app.post("/api/live/confirm")
def post_live_confirm(confirm: bool = Body(..., embed=True)):
    g = gate_status()
    if confirm and not g["passed"]:
        raise HTTPException(400, "Gate di performance non superato: conferma non consentita")
    with session_scope() as s:
        acc = ensure_account(s)
        acc.live_confirmed = confirm
    log_event("warning", "live", f"Conferma live impostata a {confirm}")
    return {"manual_confirmed": confirm}


@app.get("/api/events")
def get_events(limit: int = 100):
    with session_scope() as s:
        rows = s.query(EventLog).order_by(EventLog.id.desc()).limit(limit).all()
        return [{"ts": _iso(e.ts), "level": e.level, "kind": e.kind, "message": e.message} for e in rows]


DIST = ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
else:
    @app.get("/", response_class=HTMLResponse)
    def fallback_home():
        return ("<html><body style='background:#0b0f17;color:#e5e7eb;font-family:sans-serif;padding:2rem'>"
                "<h1>SolBot</h1><p>La dashboard non è ancora stata compilata: esegui <code>scripts/start.sh</code> "
                "(compila <code>web/</code>) oppure usa <code>/api/overview</code> e <code>python -m solbot report</code>.</p></body></html>")
