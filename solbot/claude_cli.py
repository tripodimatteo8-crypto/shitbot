"""Backend Claude via CLI di Claude Code (`claude -p`): usa l'abbonamento Pro/Max dell'utente.

- Nessuna API key: il processo figlio NON eredita ANTHROPIC_API_KEY, così la CLI usa il login
  dell'abbonamento (fatto una volta con `claude` nel Terminale).
- Nessuno strumento (`--tools ""`): Claude riceve tutti i dati nel prompt e risponde con un JSON
  validato da `--json-schema`. Ogni azione poi passa dal risk manager come per l'API.
- Quota: massimo N chiamate per finestra di ore (default 12 ogni 5h, ~25% di un piano Pro: regolabile).
  Se la CLI segnala il limite raggiunto, il bot si mette in pausa e riprova più tardi.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from datetime import timedelta
from pathlib import Path

from .config import ROOT, env, tunables
from .db import ClaudeUsage, log_event, session_scope, utcnow

log = logging.getLogger("solbot.claude_cli")
SANDBOX = ROOT / "data" / "cli_sandbox"
_lock = threading.Lock()
_paused_until = None  # datetime UTC
_last_call = None
LIMIT_PATTERNS = re.compile(r"(usage limit|rate limit|limit reached|limit will reset|out of extra usage|5-hour limit|weekly limit)", re.I)


def cli_path() -> str | None:
    p = env.claude_cli_path
    if os.path.sep in p:
        return p if Path(p).exists() else None
    found = shutil.which(p)
    if found:
        return found
    # percorsi tipici su macOS (launchd non carica il PATH della shell)
    for cand in (
        Path.home() / ".claude" / "local" / "claude",
        Path.home() / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
        *sorted((Path.home() / ".nvm" / "versions" / "node").glob("*/bin/claude"), reverse=True),
    ):
        if cand.exists():
            return str(cand)
    return None


def available() -> bool:
    return cli_path() is not None


def window_calls() -> int:
    t = tunables()
    since = utcnow() - timedelta(hours=t.cli_window_hours)
    with session_scope() as s:
        return s.query(ClaudeUsage).filter(ClaudeUsage.ts >= since, ClaudeUsage.purpose.like("%_cli")).count()


def quota_status() -> dict:
    t = tunables()
    used = window_calls()
    return {
        "used": used, "max": t.cli_calls_per_window, "window_hours": t.cli_window_hours,
        "paused_until": _paused_until.isoformat() + "Z" if _paused_until and _paused_until > utcnow() else None,
        "available": available(),
    }


def can_call(min_spacing: bool = True) -> tuple[bool, str]:
    """Quota della finestra + distanza minima tra chiamate (per spalmare l'uso nella finestra)."""
    t = tunables()
    now = utcnow()
    if _paused_until and now < _paused_until:
        return False, f"limite abbonamento raggiunto, pausa fino alle {_paused_until:%H:%M} UTC"
    used = window_calls()
    if used >= t.cli_calls_per_window:
        return False, f"quota finestra esaurita ({used}/{t.cli_calls_per_window} in {t.cli_window_hours}h)"
    if min_spacing and _last_call:
        spacing = t.cli_window_hours * 3600 / max(1, t.cli_calls_per_window)
        wait = spacing - (now - _last_call).total_seconds()
        if wait > 0:
            return False, f"prossima chiamata tra {wait / 60:.0f} min (quota spalmata sulla finestra)"
    return True, "ok"


def _extract_json(text: str):
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except ValueError:
            return None
    return None


def parse_output(stdout: str) -> dict:
    """Interpreta l'output di `claude -p --output-format json`."""
    data = _extract_json(stdout) or {}
    result_text = data.get("result") if isinstance(data, dict) else None
    structured = data.get("structured_output") if isinstance(data, dict) else None
    if structured is None and isinstance(result_text, str):
        structured = _extract_json(result_text)
    return {
        "is_error": bool(data.get("is_error")) if isinstance(data, dict) else True,
        "result": result_text if isinstance(result_text, str) else (stdout or "")[:2000],
        "structured": structured,
        "usage": data.get("usage") or {},
        "cost_usd": float(data.get("total_cost_usd") or 0),
        "model": next(iter((data.get("modelUsage") or {}).keys()), None) if isinstance(data, dict) else None,
    }


def run(prompt: str, system: str, schema: dict | None, purpose: str, timeout: int | None = None) -> dict | None:
    """Esegue una chiamata. Ritorna l'output strutturato (dict) o None."""
    global _paused_until, _last_call
    path = cli_path()
    if not path:
        log.warning("CLI 'claude' non trovata: installa Claude Code e fai il login (comando `claude`)")
        return None
    t = tunables()
    SANDBOX.mkdir(parents=True, exist_ok=True)
    cmd = [path, "-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
           "--strict-mcp-config", "--system-prompt", system]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    if t.cli_model:
        cmd += ["--model", t.cli_model]
    child_env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    with _lock:
        _last_call = utcnow()
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=SANDBOX, env=child_env,
                                  timeout=timeout or t.cli_timeout_s)
        except subprocess.TimeoutExpired:
            log.error("CLI Claude: timeout")
            return None
    out = parse_output(proc.stdout)
    u = out["usage"]
    with session_scope() as s:
        s.add(ClaudeUsage(
            purpose=purpose, model=out["model"] or (t.cli_model or "claude-code"),
            input_tokens=int(u.get("input_tokens") or 0), output_tokens=int(u.get("output_tokens") or 0),
            cache_read_tokens=int(u.get("cache_read_input_tokens") or 0),
            cache_write_tokens=int(u.get("cache_creation_input_tokens") or 0),
            cost_usd=out["cost_usd"],  # equivalente API stimato dalla CLI: NON addebitato sull'abbonamento
        ))
    text = f"{out['result']} {proc.stderr or ''}"
    if proc.returncode != 0 or out["is_error"]:
        if LIMIT_PATTERNS.search(text):
            _paused_until = utcnow() + timedelta(minutes=t.cli_pause_minutes_on_limit)
            msg = f"Limite dell'abbonamento Claude raggiunto: pausa di {t.cli_pause_minutes_on_limit} min"
            log.warning(msg)
            log_event("warning", "budget", msg)
        elif re.search(r"(not logged in|login|authenticate|invalid api key)", text, re.I):
            log.error("CLI Claude non autenticata: apri il Terminale e lancia `claude`, poi /login")
            log_event("error", "agent", "CLI Claude non autenticata: esegui `claude` e fai il login")
        else:
            log.error("CLI Claude errore (rc=%s): %s", proc.returncode, text[:400])
        return None
    if out["structured"] is None:
        log.error("CLI Claude: risposta non in JSON: %s", (out["result"] or "")[:300])
        return None
    return out["structured"]
