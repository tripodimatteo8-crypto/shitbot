"""Cicli periodici (APScheduler)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .agent import run_cycle
from .collector import collect, refresh_open_positions
from .config import tunables
from .db import Position, Snapshot, log_event, session_scope, utcnow
from .evaluator import evaluate_candidates
from .portfolio import close_position, record_equity
from .reflection import maybe_reflect_on_trades, reflect
from .risk import exit_signal

log = logging.getLogger("solbot.scheduler")
_sched: BackgroundScheduler | None = None


def _safe(name, fn):
    def run():
        try:
            fn()
        except Exception as e:  # nessun job deve far cadere il processo
            log.exception("Job %s fallito", name)
            log_event("error", "job", f"{name}: {e}")
    run.__name__ = name
    return run


def monitor_positions() -> None:
    """SL/TP/trailing/tempo massimo eseguiti dal codice, sempre attivi (anche col kill switch)."""
    rows = refresh_open_positions()
    if not rows:
        return
    now = utcnow()
    closed_any = False
    for pid, price, liq in rows:
        with session_scope() as s:
            pos = s.get(Position, pid)
            reason = exit_signal(pos, price, liq, now) if pos and pos.status == "open" else None
        if reason:
            ok, _ = close_position(pid, reason)
            closed_any |= ok
    if closed_any:
        maybe_reflect_on_trades()


def prune() -> None:
    cutoff = utcnow() - timedelta(days=14)
    with session_scope() as s:
        n = s.query(Snapshot).filter(Snapshot.ts < cutoff).delete()
    log.info("Pulizia: rimossi %d snapshot più vecchi di 14 giorni", n)


def heartbeat() -> None:
    st = record_equity()
    log.info("Equity %.2f$ (cash %.2f$, posizioni %.2f$, %d aperte)%s", st["equity"], st["cash"], st["positions"], st["open"],
             f" | FERMO: {st['halt']}" if st["halt"] else "")


def start() -> BackgroundScheduler:
    global _sched
    t = tunables()
    s = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 120})
    now = datetime.now()
    s.add_job(_safe("collect", collect), "interval", seconds=t.collect_interval_s, id="collect", next_run_time=now)
    s.add_job(_safe("agent", run_cycle), "interval", seconds=t.agent_interval_s, id="agent", next_run_time=now + timedelta(seconds=45))
    s.add_job(_safe("monitor", monitor_positions), "interval", seconds=t.monitor_interval_s, id="monitor", next_run_time=now + timedelta(seconds=20))
    s.add_job(_safe("evaluate", evaluate_candidates), "interval", seconds=t.evaluate_interval_s, id="evaluate")
    s.add_job(_safe("equity", heartbeat), "interval", seconds=300, id="equity", next_run_time=now + timedelta(seconds=5))
    s.add_job(_safe("reflect_daily", lambda: reflect("daily")), "cron", hour=3, minute=17, id="reflect_daily")
    s.add_job(_safe("prune", prune), "cron", hour=4, minute=41, id="prune")
    s.start()
    _sched = s
    log.info("Scheduler avviato: collect %ss, agent %ss, monitor %ss", t.collect_interval_s, t.agent_interval_s, t.monitor_interval_s)
    return s


def reschedule() -> None:
    if not _sched:
        return
    t = tunables(force=True)
    for jid, sec in (("collect", t.collect_interval_s), ("agent", t.agent_interval_s), ("monitor", t.monitor_interval_s), ("evaluate", t.evaluate_interval_s)):
        _sched.reschedule_job(jid, trigger="interval", seconds=sec)


def jobs_status() -> list[dict]:
    if not _sched:
        return []
    return [{"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None} for j in _sched.get_jobs()]


def shutdown() -> None:
    if _sched:
        _sched.shutdown(wait=False)
