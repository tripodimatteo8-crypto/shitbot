"""Agente decisionale: Claude con tool use (o baseline a regole se manca la chiave)."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

import anthropic

from .collector import get_security
from .config import env, tunables
from .costs import budget_ok, record_usage
from .db import Candidate, Decision, Position, Snapshot, log_event, session_scope, utcnow
from .lessons import current_lessons
from .portfolio import close_position, ensure_account, equity, open_position
from .risk import halt_reason

log = logging.getLogger("solbot.agent")

SYSTEM_PROMPT = """Sei SolBot, un trader di memecoin Solana che opera in PAPER TRADING (soldi finti, prezzi reali) per imparare.

Contesto:
- Ricevi candidati che hanno GIÀ superato filtri di sicurezza in codice (authority, concentrazione holder, insider, liquidità, route di vendita). I filtri riducono i rug evidenti, non li eliminano.
- I costi sono simulati in modo prudente: impatto di prezzo reale (quote Jupiter), buffer MEV/sniper ~1% per lato, fee aggregatore, priority fee, ritardo di esecuzione. Un round-trip costa spesso 3-8%: un trade ha senso solo se ti aspetti un movimento ben superiore.
- Stop loss, take profit, trailing stop, tempo massimo di holding, dimensione massima per trade e limite di perdita giornaliera sono applicati dal codice: non puoi cambiarli. La size che chiedi può essere ridotta.
- Orizzonte: trading di BREVE periodo, minuti. Ogni posizione viene chiusa dal codice al massimo dopo 1 ora. Valuta quindi il rischio e il potenziale nei prossimi 5-60 minuti, non nei prossimi giorni.
- La maggior parte delle memecoin va a zero: saltare è spesso la scelta giusta. Ma senza trade non si impara: quando l'evidenza è ragionevole, prendi posizioni piccole.
- Per ogni candidato ricevi, quando ci sono abbastanza dati, `rug_prob_appresa` e `dump_prob_appresa`: probabilità misurate dal codice che il token crolli (rug) o scenda fino allo stop loss (dump) entro 1 ora, con le fasce che le determinano. Non sono certezze: usale come indicatori di rischio.

Il tuo compito in ogni ciclo:
1. Per OGNI candidato elencato devi chiamare esattamente uno tra `paper_buy` e `skip_token`.
2. Per le posizioni aperte puoi chiamare `paper_sell` se la tesi è invalidata (altrimenti lasciale gestire al codice).
3. Usa `get_token_data` / `get_security_report` / `get_portfolio` solo se ti servono dettagli in più rispetto al riepilogo.
4. Ogni decisione richiede `reason` (in italiano, concreta, cita i numeri che ti hanno convinto e, se pertinente, la lezione applicata) e `confidence` tra 0 e 1 (probabilità stimata che il trade chiuda in profitto DOPO i costi).
5. Rispetta le lezioni apprese qui sotto: sono regole derivate dai dati. Quelle marcate "ipotesi" hanno pochi campioni: usale ma non come dogmi.
Quando hai deciso per tutti i candidati, termina con una riga di riepilogo.

## Lezioni apprese (lezioni.md)
"""

TOOLS = [
    {
        "name": "get_token_data",
        "description": "Dati di mercato dettagliati di un token: prezzo, liquidità, mcap, volumi, transazioni, variazioni e storico prezzi recente (snapshot ogni pochi minuti).",
        "input_schema": {"type": "object", "properties": {"mint": {"type": "string", "description": "Indirizzo mint del token"}}, "required": ["mint"], "additionalProperties": False},
    },
    {
        "name": "get_security_report",
        "description": "Report di sicurezza (RugCheck): mint/freeze authority, holder, concentrazione top-10, insider/bundle, rischi, LP bloccata.",
        "input_schema": {"type": "object", "properties": {"mint": {"type": "string"}}, "required": ["mint"], "additionalProperties": False},
    },
    {
        "name": "get_portfolio",
        "description": "Stato del portafoglio paper: cash, equity, posizioni aperte con PnL, limiti di rischio in vigore.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "paper_buy",
        "description": "Compra un candidato nel portafoglio paper. La size viene limitata dal risk manager.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "mint": {"type": "string"},
                "usd_amount": {"type": "number", "description": "USD da investire (verrà limitato al massimo consentito)"},
                "reason": {"type": "string"},
                "confidence": {"type": "number", "description": "0-1"},
            },
            "required": ["mint", "usd_amount", "reason", "confidence"],
            "additionalProperties": False,
        },
    },
    {
        "name": "paper_sell",
        "description": "Chiude interamente una posizione aperta.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"mint": {"type": "string"}, "reason": {"type": "string"}, "confidence": {"type": "number"}},
            "required": ["mint", "reason", "confidence"],
            "additionalProperties": False,
        },
    },
    {
        "name": "skip_token",
        "description": "Decide di NON comprare un candidato.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"mint": {"type": "string"}, "reason": {"type": "string"}, "confidence": {"type": "number", "description": "fiducia nella scelta di saltare, 0-1"}},
            "required": ["mint", "reason", "confidence"],
            "additionalProperties": False,
        },
    },
]


# ---------------------------------------------------------------- tool impl
def _clamp_conf(x) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.0


def tool_get_token_data(mint: str) -> dict:
    with session_scope() as s:
        snaps = s.query(Snapshot).filter(Snapshot.mint == mint, Snapshot.ts > utcnow() - timedelta(hours=3)).order_by(Snapshot.ts).all()
        cand = s.query(Candidate).filter(Candidate.mint == mint).order_by(Candidate.ts.desc()).first()
        if not snaps:
            return {"error": "nessun dato per questo mint"}
        last = snaps[-1]
        step = max(1, len(snaps) // 20)
        hist = [{"t": x.ts.strftime("%H:%M"), "p": x.price_usd, "liq": round(x.liquidity_usd or 0)} for x in snaps[::step]]
        return {
            "mint": mint, "symbol": cand.symbol if cand else None, "price_usd": last.price_usd, "liquidity_usd": last.liquidity_usd,
            "mcap_usd": last.mcap_usd, "vol": {"m5": last.vol_m5, "h1": last.vol_h1, "h6": last.vol_h6, "h24": last.vol_h24},
            "txns_h1": {"buys": last.buys_h1, "sells": last.sells_h1},
            "price_change_pct": {"m5": last.chg_m5, "h1": last.chg_h1, "h6": last.chg_h6, "h24": last.chg_h24},
            "features": cand.features if cand else None, "history_utc": hist,
        }


def tool_get_security_report(mint: str) -> dict:
    sec = get_security(mint)
    return sec.to_dict() if sec else {"error": "report non disponibile"}


def tool_get_portfolio() -> dict:
    t = tunables()
    with session_scope() as s:
        acc = ensure_account(s)
        eq, pos_val, opens = equity(s)
        return {
            "cash_usd": round(acc.cash_usd, 2), "equity_usd": round(eq, 2), "initial_capital_usd": acc.initial_capital_usd,
            "open_positions": [
                {"mint": p.mint, "symbol": p.symbol, "cost_usd": round(p.cost_usd, 2),
                 "pnl_mkt_pct": round((p.last_price / p.entry_price_eff - 1) * 100, 1) if p.last_price else None,
                 "held_min": round((utcnow() - p.opened_at).total_seconds() / 60)} for p in opens
            ],
            "limits": {"max_position_usd": round(eq * t.max_position_pct / 100, 2), "max_open_positions": t.max_open_positions,
                       "stop_loss_pct": t.stop_loss_pct, "take_profit_pct": t.take_profit_pct,
                       "trailing_stop_pct": t.trailing_stop_pct, "max_hold_hours": t.max_hold_hours},
            "halt": halt_reason(acc),
        }


class CycleContext:
    def __init__(self, decider: str, model: str | None, lessons_version: int | None, candidate_ids: dict[str, int]):
        self.decider = decider
        self.model = model
        self.lessons_version = lessons_version
        self.candidate_ids = candidate_ids  # mint -> candidate id
        self.decided: set[str] = set()


def _save_decision(ctx: CycleContext, mint: str, action: str, reason: str, conf: float, usd: float | None) -> int:
    with session_scope() as s:
        cid = ctx.candidate_ids.get(mint)
        cand = s.get(Candidate, cid) if cid else None
        d = Decision(mint=mint, symbol=cand.symbol if cand else None, action=action, reason=reason, confidence=conf,
                     requested_usd=usd, decider=ctx.decider, model=ctx.model, lessons_version=ctx.lessons_version)
        s.add(d)
        s.flush()
        if cand and action in ("buy", "skip"):
            cand.status = action
            cand.decision_id = d.id
        return d.id


def execute_tool(ctx: CycleContext, name: str, args: dict) -> dict:
    if name == "get_token_data":
        return tool_get_token_data(args.get("mint", ""))
    if name == "get_security_report":
        return tool_get_security_report(args.get("mint", ""))
    if name == "get_portfolio":
        return tool_get_portfolio()
    mint = args.get("mint", "")
    reason = (args.get("reason") or "").strip()
    conf = _clamp_conf(args.get("confidence"))
    if not reason:
        return {"error": "reason obbligatorio"}
    if name == "paper_buy":
        if mint not in ctx.candidate_ids:
            return {"error": "puoi comprare solo i candidati di questo ciclo"}
        if mint in ctx.decided:
            return {"error": "decisione già presa per questo token"}
        usd = float(args.get("usd_amount") or 0)
        did = _save_decision(ctx, mint, "buy", reason, conf, usd)
        ctx.decided.add(mint)
        ok, msg, pid = open_position(mint, usd, did, ctx.decider, ctx.lessons_version)
        return {"executed": ok, "message": msg, "position_id": pid}
    if name == "skip_token":
        if mint not in ctx.candidate_ids:
            return {"error": "mint non tra i candidati"}
        if mint in ctx.decided:
            return {"error": "decisione già presa per questo token"}
        _save_decision(ctx, mint, "skip", reason, conf, None)
        ctx.decided.add(mint)
        return {"ok": True}
    if name == "paper_sell":
        with session_scope() as s:
            pos = s.query(Position).filter(Position.mint == mint, Position.status == "open").first()
            pid = pos.id if pos else None
        if not pid:
            return {"error": "nessuna posizione aperta su questo mint"}
        did = _save_decision(ctx, mint, "sell", reason, conf, None)
        ok, msg = close_position(pid, f"agente: {reason[:200]}", did)
        return {"executed": ok, "message": msg}
    return {"error": f"tool sconosciuto {name}"}


# ---------------------------------------------------------------- cycle
def _pending_candidates(limit: int) -> list[Candidate]:
    with session_scope() as s:
        return (s.query(Candidate).filter(Candidate.status == "pending")
                .order_by(Candidate.ts.desc(), Candidate.liquidity_usd.desc()).limit(limit).all())


def rug_summary() -> str:
    from .learning import summary_for_prompt

    try:
        return summary_for_prompt()
    except Exception:
        return ""


def _summary_line(c: Candidate) -> dict:
    from .learning import rug_probability

    f = c.features or {}
    p, why = rug_probability(f)
    pd, why_d = rug_probability(f, target="dump")
    extra = {"rug_prob_appresa": round(p, 2), "rug_fasce": why} if p is not None else {}
    if pd is not None:
        extra.update({"dump_prob_appresa": round(pd, 2), "dump_fasce": why_d})
    return {**extra, "mint": c.mint, "symbol": c.symbol, "price_usd": c.price_usd, "liq_usd": round(c.liquidity_usd or 0),
            "mcap_usd": round(c.mcap_usd or 0), "age_min": round(c.age_minutes or 0), **{k: f.get(k) for k in (
                "vol_h1", "vol_liq_h1", "buy_ratio_h1", "chg_m5", "chg_h1", "chg_h6", "holders", "top10", "insider",
                "rug_score", "dex", "socials", "boosted", "sources")}}


def choose_decider() -> str:
    """claude (API) | claude_cli (abbonamento via Claude Code) | baseline (regole)."""
    from . import claude_cli

    d = env.decider
    if d == "baseline":
        return "baseline"
    if d == "claude":
        return "claude" if env.anthropic_api_key else "baseline"
    if d == "claude_cli":
        return "claude_cli" if claude_cli.available() else "baseline"
    if env.anthropic_api_key:
        return "claude"
    return "claude_cli" if claude_cli.available() else "baseline"


def run_cycle() -> dict:
    from . import claude_cli

    t = tunables()
    decider = choose_decider()
    with session_scope() as s:
        acc = ensure_account(s)
        halted = halt_reason(acc)
        n_open = s.query(Position).filter(Position.status == "open").count()
    if halted:
        with session_scope() as s:
            s.query(Candidate).filter(Candidate.status == "pending").update({"status": "expired"})
        log.warning("Agente fermo: %s", halted)
        return {"skipped": halted}
    if decider == "claude_cli":
        ok, why = claude_cli.can_call()
        if not ok:
            log.info("Agente (abbonamento) in attesa: %s", why)
            return {"skipped": why}
    limit = t.cli_max_candidates if decider == "claude_cli" else t.max_candidates_per_cycle
    cands = _pending_candidates(limit)
    if not cands:
        log.info("Agente: nessun candidato nuovo (%d posizioni aperte)", n_open)
        return {"candidates": 0}
    lessons, lv = current_lessons()
    model = t.claude_model if decider == "claude" else (t.cli_model or "abbonamento") if decider == "claude_cli" else None
    ctx = CycleContext(decider, model, lv, {c.mint: c.id for c in cands})
    if decider == "claude":
        ok, why = budget_ok()
        if not ok:
            log.warning("Budget Claude esaurito (%s): candidati lasciati scadere", why)
            log_event("warning", "budget", why)
            return {"skipped": why}
        try:
            _run_claude(ctx, cands, lessons)
        except anthropic.APIStatusError as e:
            log.error("Errore API Claude %s: %s", e.status_code, e.message)
            log_event("error", "agent", f"Errore API Claude {e.status_code}: {e.message}")
        except anthropic.APIConnectionError as e:
            log.error("Connessione a Claude fallita: %s", e)
    elif decider == "claude_cli":
        _run_cli(ctx, cands, lessons)
    else:
        _run_baseline(ctx, cands)
    # candidati senza decisione: restano pending fino a scadenza (verranno ripresi al prossimo ciclo)
    log.info("Ciclo %s: %d candidati, %d decisi", decider, len(cands), len(ctx.decided))
    return {"candidates": len(cands), "decided": len(ctx.decided), "decider": decider}


CLI_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "mint": {"type": "string"},
                    "action": {"type": "string", "enum": ["buy", "skip"]},
                    "usd_amount": {"type": "number"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["mint", "action", "reason", "confidence"],
            },
        },
        "sells": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"mint": {"type": "string"}, "reason": {"type": "string"}, "confidence": {"type": "number"}},
                "required": ["mint", "reason", "confidence"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["decisions"],
}

CLI_INSTRUCTIONS = """
## Formato di risposta (modalità senza strumenti)
In questa modalità non hai strumenti: tutti i dati che ti servono sono nel messaggio (riepilogo, report di sicurezza e storico prezzi di ogni candidato, portafoglio).
Rispondi SOLO con un oggetto JSON:
{"decisions": [{"mint": "...", "action": "buy" | "skip", "usd_amount": numero (solo per buy), "reason": "...", "confidence": 0-1}, ...],
 "sells": [{"mint": "...", "reason": "...", "confidence": 0-1}],   // solo posizioni aperte da chiudere ora, altrimenti []
 "summary": "una riga"}
Una voce in "decisions" per OGNI candidato elencato.
"""


def _run_cli(ctx: CycleContext, cands: list[Candidate], lessons: str) -> None:
    from . import claude_cli

    details = []
    for c in cands:
        d = _summary_line(c)
        sec = get_security(c.mint)
        if sec:
            d["security"] = {k: v for k, v in sec.to_dict().items() if k not in ("mint", "sniper_pct", "bundle_pct", "smart_money_buys")}
        hist = tool_get_token_data(c.mint).get("history_utc")
        if hist:
            d["history_utc"] = hist[-12:]
        details.append(d)
    prompt = (
        f"Ora (UTC): {utcnow().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Portafoglio:\n{json.dumps(tool_get_portfolio(), ensure_ascii=False)}\n\n"
        f"{rug_summary()}\n\n"
        f"Candidati di questo ciclo ({len(cands)}), già filtrati:\n"
        + "\n".join(json.dumps(d, ensure_ascii=False, default=str) for d in details)
        + "\n\nRispondi con il JSON richiesto."
    )
    system = SYSTEM_PROMPT.replace("Il tuo compito in ogni ciclo:", "Il tuo compito in ogni ciclo (vedi formato di risposta in fondo):") + lessons + CLI_INSTRUCTIONS
    out = claude_cli.run(prompt, system, CLI_SCHEMA, "decision_cli")
    if not out:
        return
    if out.get("summary"):
        log.info("Claude (abbonamento): %s", str(out["summary"])[:400])
    for d in out.get("decisions") or []:
        mint = d.get("mint")
        if mint not in ctx.candidate_ids:
            continue
        if d.get("action") == "buy":
            res = execute_tool(ctx, "paper_buy", {"mint": mint, "usd_amount": d.get("usd_amount") or 0,
                                                  "reason": d.get("reason", ""), "confidence": d.get("confidence")})
        else:
            res = execute_tool(ctx, "skip_token", {"mint": mint, "reason": d.get("reason", ""), "confidence": d.get("confidence")})
        if "error" in res:
            log.warning("Decisione scartata per %s: %s", mint[:6], res["error"])
    for sdec in out.get("sells") or []:
        res = execute_tool(ctx, "paper_sell", {"mint": sdec.get("mint", ""), "reason": sdec.get("reason", ""), "confidence": sdec.get("confidence")})
        if "error" in res:
            log.warning("Vendita scartata: %s", res["error"])


def _run_claude(ctx: CycleContext, cands: list[Candidate], lessons: str) -> None:
    t = tunables()
    client = anthropic.Anthropic(api_key=env.anthropic_api_key, max_retries=3, timeout=180)
    system = [{"type": "text", "text": SYSTEM_PROMPT + lessons, "cache_control": {"type": "ephemeral"}}]
    portfolio = tool_get_portfolio()
    user = (
        f"Ora (UTC): {utcnow().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Portafoglio:\n{json.dumps(portfolio, ensure_ascii=False)}\n\n"
        f"{rug_summary()}\n\n"
        f"Candidati di questo ciclo ({len(cands)}), già filtrati:\n"
        + "\n".join(json.dumps(_summary_line(c), ensure_ascii=False) for c in cands)
        + "\n\nDecidi per ciascun candidato (paper_buy o skip_token)."
    )
    messages: list[dict] = [{"role": "user", "content": user}]
    kwargs = dict(
        model=t.claude_model, max_tokens=16000, system=system, tools=TOOLS, messages=messages,
        thinking={"type": "adaptive"}, output_config={"effort": t.claude_effort},
    )
    for _ in range(12):
        if t.claude_fallbacks:
            resp = client.beta.messages.create(**kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            resp = client.messages.create(**kwargs)
        record_usage("decision", resp.model or t.claude_model, resp.usage)
        if resp.stop_reason == "refusal":
            log.warning("Claude ha rifiutato la richiesta: %s", getattr(resp, "stop_details", None))
            return
        messages.append({"role": "assistant", "content": resp.content})
        for b in resp.content:
            if b.type == "text" and b.text.strip():
                log.info("Claude: %s", b.text.strip()[:500])
        if resp.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            missing = set(ctx.candidate_ids) - ctx.decided
            if missing and resp.stop_reason == "end_turn":
                messages.append({"role": "user", "content": f"Mancano decisioni per: {', '.join(missing)}. Chiama paper_buy o skip_token per ciascuno."})
                continue
            return
        results = []
        for tu in tool_uses:
            try:
                out = execute_tool(ctx, tu.name, dict(tu.input or {}))
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(out, ensure_ascii=False, default=str)})
            except Exception as e:  # un tool rotto non deve fermare il ciclo
                log.exception("Errore tool %s", tu.name)
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": f"errore: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})
        if not (set(ctx.candidate_ids) - ctx.decided) and resp.stop_reason != "tool_use":
            return


def _run_baseline(ctx: CycleContext, cands: list[Candidate]) -> None:
    """Strategia a regole usata senza chiave API (e come termine di paragone)."""
    with session_scope() as s:
        eq, _, _ = equity(s)
    for c in cands:
        f = c.features or {}
        br, ch1, vl = f.get("buy_ratio_h1") or 0, f.get("chg_h1") or 0, f.get("vol_liq_h1") or 0
        from .learning import rug_probability

        p_rug, _ = rug_probability(f)
        p_dump, _ = rug_probability(f, target="dump")
        ch6 = f.get("chg_h6") or 0
        conds = {
            "0.55<buy_ratio_h1<=0.8": 0.55 < br <= 0.8,  # >0.8 = acquisti gonfiati da bot (pump & dump)
            "0<chg_h1<80": 0 < ch1 < 80,
            "0.5<vol/liq_h1<=4": 0.5 < vl <= 4,  # >4 = probabile wash trading
            "chg_h6<300": ch6 < 300,
            "socials": bool(f.get("socials")),
            "rug_prob<30%": p_rug is None or p_rug < 0.3,
            "dump_prob<50%": p_dump is None or p_dump < 0.5,
        }
        okc = [k for k, v in conds.items() if v]
        if all(conds.values()):
            reason = f"baseline: tutte le condizioni vere ({', '.join(okc)}); br={br}, chg_h1={ch1}, vol/liq={vl}"
            execute_tool(ctx, "paper_buy", {"mint": c.mint, "usd_amount": eq * 0.03, "reason": reason, "confidence": 0.5})
        else:
            fail = [k for k, v in conds.items() if not v]
            execute_tool(ctx, "skip_token", {"mint": c.mint, "reason": f"baseline: condizioni non soddisfatte: {', '.join(fail)}", "confidence": 0.5})
