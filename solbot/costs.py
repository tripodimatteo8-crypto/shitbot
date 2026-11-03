"""Tracciamento di token e costi Claude + budget giornaliero."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, true

from .config import tunables
from .db import ClaudeUsage, session_scope

# USD per milione di token: (input, output, cache read). Cache write = 1.25x input.
PRICING = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
DEFAULT_PRICE = (10.0, 50.0, 0.25)  # modello sconosciuto: stima pessimistica


def cost_usd(model: str, inp: int, out: int, cache_read: int, cache_write: int) -> float:
    pin, pout, pcr = PRICING.get(model, DEFAULT_PRICE)
    return (inp * pin + out * pout + cache_read * pcr + cache_write * pin * 1.25) / 1_000_000


def record_usage(purpose: str, model: str, usage) -> float:
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    c = cost_usd(model, inp, out, cr, cw)
    with session_scope() as s:
        s.add(ClaudeUsage(purpose=purpose, model=model, input_tokens=inp, output_tokens=out,
                          cache_read_tokens=cr, cache_write_tokens=cw, cost_usd=c))
    return c


def _local_midnight_utc() -> datetime:
    now_local = datetime.now()
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    return midnight_local - offset


def today_usage(api_only: bool = False) -> dict:
    since = _local_midnight_utc()
    with session_scope() as s:
        calls, inp, out, cr, cw, cost = s.query(
            func.count(ClaudeUsage.id), func.coalesce(func.sum(ClaudeUsage.input_tokens), 0),
            func.coalesce(func.sum(ClaudeUsage.output_tokens), 0), func.coalesce(func.sum(ClaudeUsage.cache_read_tokens), 0),
            func.coalesce(func.sum(ClaudeUsage.cache_write_tokens), 0), func.coalesce(func.sum(ClaudeUsage.cost_usd), 0.0),
        ).filter(ClaudeUsage.ts >= since, ~ClaudeUsage.purpose.like("%_cli") if api_only else true()).one()
    return {"calls": calls, "tokens": inp + out + cr + cw, "input": inp, "output": out, "cache_read": cr, "cache_write": cw, "usd": cost}


def budget_ok() -> tuple[bool, str]:
    t = tunables()
    u = today_usage(api_only=True)
    if u["calls"] >= t.max_claude_calls_per_day:
        return False, f"limite chiamate giornaliere ({u['calls']}/{t.max_claude_calls_per_day})"
    if u["tokens"] >= t.max_claude_tokens_per_day:
        return False, f"limite token giornalieri ({u['tokens']:,}/{t.max_claude_tokens_per_day:,})"
    if u["usd"] >= t.max_claude_usd_per_day:
        return False, f"limite spesa giornaliera ({u['usd']:.2f}/{t.max_claude_usd_per_day}$)"
    return True, "ok"
