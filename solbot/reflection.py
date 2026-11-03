"""Riflessione: Claude rilegge decisioni + esiti oggettivi e riscrive lezioni.md."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

import anthropic

from .config import env, tunables
from .costs import budget_ok, record_usage
from .db import Candidate, Decision, LessonVersion, Position, log_event, session_scope, utcnow
from .evaluator import metrics
from .lessons import current_lessons, save_lessons

log = logging.getLogger("solbot.reflection")

REFLECT_SYSTEM = """Sei il modulo di riflessione di SolBot, un agente di paper trading su memecoin Solana.
Ricevi: le lezioni attuali, metriche oggettive calcolate dal codice, i trade chiusi con il motivo dell'agente, e gli esiti a 1h/6h/24h dei candidati (comprati, saltati, scartati dai filtri, scaduti).
Riscrivi lezioni.md in italiano, in Markdown:
- Regole brevi e operative, ciascuna con evidenza numerica (es. "n=23, rendimento medio 6h -12%").
- Marca ogni regola con [ipotesi, n=X] se i campioni sono meno di 30, [confermata, n=X] solo se n>=30 e l'effetto è netto e coerente.
- Rimuovi o declassa le regole smentite dai dati; non inventare numeri che non sono nei dati.
- Includi una sezione "Rug: come riconoscerli" basata sui trade finiti in rug e sul modello rug (quali fasce di vol/liq, quota acquisti, pump recente, età, holder li precedono), una "Errori ricorrenti" e una "Cosa testare".
- Ricorda che i costi di round-trip stimati sono circa il {cost}% e che il paper trading sovrastima i risultati reali.
- Massimo ~60 righe. Rispondi SOLO con il contenuto del nuovo lezioni.md."""


def _closed_since_last_reflection() -> tuple[int, int]:
    with session_scope() as s:
        total = s.query(Position).filter(Position.status == "closed").count()
        last = s.query(LessonVersion).filter(LessonVersion.trigger.in_(["daily", "trades"])).order_by(LessonVersion.id.desc()).first()
        return total, total - (last.closed_trades if last else 0)


def maybe_reflect_on_trades() -> None:
    total, new = _closed_since_last_reflection()
    if new >= tunables().reflect_every_n_closed_trades:
        reflect("trades")


FEATURE_KEYS = ("age_min", "liq", "mcap", "vol_liq_h1", "buy_ratio_h1", "chg_h1", "chg_h6", "holders", "top10", "insider", "socials", "dex")


def _features_at_buy(s, p: Position) -> dict | None:
    c = s.query(Candidate).filter(Candidate.decision_id == p.buy_decision_id).first() if p.buy_decision_id else None
    if c is None:
        c = s.query(Candidate).filter(Candidate.mint == p.mint, Candidate.ts <= p.opened_at).order_by(Candidate.ts.desc()).first()
    return {k: (c.features or {}).get(k) for k in FEATURE_KEYS} if c else None


def _dataset(days: int = 7) -> dict:
    since = utcnow() - timedelta(days=days)
    with session_scope() as s:
        trades = s.query(Position).filter(Position.status == "closed", Position.closed_at >= since).order_by(Position.closed_at.desc()).limit(80).all()
        dec = {d.id: d for d in s.query(Decision).filter(Decision.ts >= since).all()}
        cands = s.query(Candidate).filter(Candidate.ts >= since, (Candidate.ret_6h.isnot(None)) | (Candidate.rug.isnot(None))).order_by(Candidate.ts.desc()).limit(400).all()
        tr = [{
            "symbol": p.symbol, "pnl_pct": round(p.pnl_pct or 0, 1), "pnl_usd": round(p.pnl_usd or 0, 2),
            "held_min": round(((p.closed_at or utcnow()) - p.opened_at).total_seconds() / 60),
            "exit": p.exit_reason, "decider": p.decider,
            "buy_reason": dec[p.buy_decision_id].reason[:300] if p.buy_decision_id in dec else None,
            "buy_conf": dec[p.buy_decision_id].confidence if p.buy_decision_id in dec else None,
            "f_at_buy": _features_at_buy(s, p),
        } for p in trades]
        cs = [{
            "status": c.status, "symbol": c.symbol, "r1h": c.ret_1h, "r6h": c.ret_6h, "r24h": c.ret_24h,
            "max24": c.max_ret_24h, "rug": c.rug,
            "filter": (c.filter_reasons or [None])[0],
            "skip_reason": dec[c.decision_id].reason[:160] if c.decision_id in dec and c.status == "skip" else None,
            "f": {k: (c.features or {}).get(k) for k in ("age_min", "liq", "mcap", "vol_liq_h1", "buy_ratio_h1", "chg_h1", "holders", "top10", "insider", "socials", "dex")},
        } for c in cands]
        rug_trades = [x for x in tr if (x["pnl_pct"] or 0) <= -50]
    return {"trades": tr, "candidates": cs, "rug_trades": rug_trades}


def reflect(trigger: str) -> int | None:
    from .agent import choose_decider

    backend = choose_decider()
    if backend == "baseline":
        log.info("Riflessione saltata: né ANTHROPIC_API_KEY né CLI `claude` disponibili")
        return None
    if backend == "claude_cli":
        from . import claude_cli

        ok, why = claude_cli.can_call(min_spacing=False)
    else:
        ok, why = budget_ok()
    if not ok:
        log.warning("Riflessione saltata: %s", why)
        return None
    t = tunables()
    lessons, _ = current_lessons()
    m = metrics()
    data = _dataset()
    m_week = metrics(since_days=7)
    from .learning import summary_for_prompt

    rug_text = summary_for_prompt(max_lines=24)
    prompt = (
        f"## Lezioni attuali\n{lessons}\n\n## Metriche complessive\n{json.dumps(m, ensure_ascii=False)}\n\n"
        f"## Metriche ultimi 7 giorni\n{json.dumps(m_week, ensure_ascii=False)}\n\n"
        f"## Trade chiusi (recenti)\n{json.dumps(data['trades'], ensure_ascii=False)}\n\n"
        f"## Trade finiti in rug (perdita >= 50%)\n{json.dumps(data['rug_trades'], ensure_ascii=False)}\n\n"
        f"## Modello rug appreso dal codice\n{rug_text}\n\n"
        f"## Esiti candidati (recenti; campo rug = crollo >=80% o liquidità sparita entro 6h)\n{json.dumps(data['candidates'], ensure_ascii=False)}"
    )
    system = REFLECT_SYSTEM.format(cost=m["est_roundtrip_cost_pct"])
    if backend == "claude_cli":
        return _reflect_cli(prompt, system, trigger, m)
    client = anthropic.Anthropic(api_key=env.anthropic_api_key, max_retries=3, timeout=600)
    kwargs = dict(
        model=t.claude_model, max_tokens=32000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"}, output_config={"effort": "high"},
    )
    try:
        if t.claude_fallbacks:
            with client.beta.messages.stream(**kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default") as st:
                resp = st.get_final_message()
        else:
            with client.messages.stream(**kwargs) as st:
                resp = st.get_final_message()
    except anthropic.APIError as e:
        log.error("Riflessione fallita: %s", e)
        return None
    record_usage("reflection", resp.model or t.claude_model, resp.usage)
    if resp.stop_reason == "refusal":
        log.warning("Riflessione rifiutata dal modello")
        return None
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    if not text or len(text) < 50:
        log.warning("Riflessione vuota, lezioni invariate")
        return None
    total, _ = _closed_since_last_reflection()
    vid = save_lessons(text + "\n", trigger, resp.model or t.claude_model, m, total)
    log.info("Nuova versione di lezioni.md (v%d, trigger=%s)", vid, trigger)
    log_event("info", "reflection", f"lezioni.md aggiornato alla versione {vid} ({trigger})")
    return vid


def _save(text: str, trigger: str, model: str, m: dict) -> int | None:
    text = (text or "").strip()
    if len(text) < 50:
        log.warning("Riflessione vuota, lezioni invariate")
        return None
    total, _ = _closed_since_last_reflection()
    vid = save_lessons(text + "\n", trigger, model, m, total)
    log.info("Nuova versione di lezioni.md (v%d, trigger=%s)", vid, trigger)
    log_event("info", "reflection", f"lezioni.md aggiornato alla versione {vid} ({trigger})")
    return vid


def _reflect_cli(prompt: str, system: str, trigger: str, m: dict) -> int | None:
    from . import claude_cli

    schema = {"type": "object", "properties": {"lessons_md": {"type": "string"}}, "required": ["lessons_md"]}
    system += "\nRestituisci un oggetto JSON con un solo campo `lessons_md` che contiene il nuovo lezioni.md completo."
    out = claude_cli.run(prompt, system, schema, "reflection_cli", timeout=900)
    if not out:
        return None
    return _save(out.get("lessons_md", ""), trigger, tunables().cli_model or "abbonamento", m)
