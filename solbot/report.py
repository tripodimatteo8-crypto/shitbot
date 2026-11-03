"""Report da terminale (Fase 1)."""
from __future__ import annotations

from .agent import choose_decider
from .costs import today_usage
from .db import Candidate, Decision, Position, session_scope, utcnow
from .evaluator import metrics
from .portfolio import ensure_account, equity
from .risk import halt_reason


def print_report() -> None:
    with session_scope() as s:
        acc = ensure_account(s)
        eq, pos_val, opens = equity(s)
        print(f"\n=== SolBot — {utcnow():%Y-%m-%d %H:%M} UTC — decider: {choose_decider()} ===")
        print(f"Equity {eq:.2f}$  cash {acc.cash_usd:.2f}$  posizioni {pos_val:.2f}$  PnL {eq - acc.initial_capital_usd:+.2f}$")
        h = halt_reason(acc)
        if h:
            print(f"!! FERMO: {h}")
        print(f"\nPosizioni aperte ({len(opens)}):")
        for p in opens:
            chg = (p.last_price / p.entry_price_mkt - 1) * 100 if p.last_price else 0
            print(f"  #{p.id} {p.symbol or p.mint[:6]:<12} costo {p.cost_usd:7.2f}$  mercato {chg:+6.1f}%  aperta {p.opened_at:%m-%d %H:%M}")
        closed = s.query(Position).filter(Position.status == "closed").order_by(Position.closed_at.desc()).limit(10).all()
        print("\nUltimi trade chiusi:")
        for p in closed:
            print(f"  #{p.id} {p.symbol or p.mint[:6]:<12} PnL {p.pnl_usd:+7.2f}$ ({p.pnl_pct:+6.1f}%)  {p.exit_reason}")
        decs = s.query(Decision).order_by(Decision.ts.desc()).limit(8).all()
        print("\nUltime decisioni:")
        for d in decs:
            print(f"  {d.ts:%H:%M} {d.action.upper():<4} {d.symbol or d.mint[:6]:<12} conf {d.confidence:.2f} [{d.decider}] {d.reason[:110]}")
        n_c = s.query(Candidate).count()
        n_p = s.query(Candidate).filter(Candidate.passed_filters.is_(True)).count()
    m = metrics()
    tr = m["trades"]
    print(f"\nCandidati valutati: {n_c} (passano i filtri: {n_p})")
    if tr.get("n"):
        print(f"Trade chiusi {tr['n']}  win rate {tr['win_rate']}%  PnL {tr['pnl_usd']:+.2f}$  PF {tr['profit_factor']}  "
              f"expectancy {tr['expectancy_usd']:+.2f}$  max DD {m['max_drawdown_pct']}%")
    u = today_usage()
    print(f"Claude oggi: {u['calls']} chiamate, {u['tokens']:,} token, {u['usd']:.2f}$")
    from .config import tunables
    from .learning import current_model, rug_creators, summary_for_prompt

    t = tunables()
    lm = current_model()
    print("\n--- Apprendimento dai rug ---")
    if not lm or lm["n"] == 0:
        print(f"Nessun token ancora etichettato: le etichette arrivano {t.rug_horizon_hours:g}h dopo che il bot vede un token.")
    else:
        active = lm["n"] >= t.learned_min_total and lm["rugs"] >= t.learned_min_rugs
        print(f"Token etichettati {lm['n']}, rug {lm['rugs']} (tasso base {lm['base_rate']:.0%}), creator in blacklist {len(rug_creators())}")
        print("Filtro appreso: " + ("ATTIVO" if active else f"in raccolta dati (servono {t.learned_min_total} token e {t.learned_min_rugs} rug)"))
        print(summary_for_prompt())
    print()
