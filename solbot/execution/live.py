"""LiveEngine: STUB, disabilitato.

Si attiva solo se TUTTE le condizioni sono vere:
1. LIVE_TRADING_ENABLED=true in .env;
2. il gate di performance paper è superato (vedi `gate_status`);
3. l'utente ha confermato manualmente dalla dashboard (account.live_confirmed).
Anche così, oggi `buy`/`sell` sollevano NotImplementedError: l'esecuzione reale va
implementata e revisionata a parte (vedi README, sezione "Modalità live").

La chiave privata del wallet dedicato si legge SOLO qui, da SOLBOT_WALLET_PRIVATE_KEY,
al momento della firma; non viene mai loggata, salvata nel DB o esposta all'agente.
"""
from __future__ import annotations

from .base import ExecutionEngine, FillResult


def live_allowed() -> tuple[bool, str]:
    from ..config import env
    from ..db import Account, session_scope
    from ..evaluator import gate_status

    if not env.live_trading_enabled:
        return False, "LIVE_TRADING_ENABLED non attivo"
    g = gate_status()
    if not g["passed"]:
        return False, "gate di performance non superato"
    with session_scope() as s:
        acc = s.get(Account, 1)
        if not acc or not acc.live_confirmed:
            return False, "manca la conferma manuale dalla dashboard"
    return True, "ok"


class LiveEngine(ExecutionEngine):
    name = "live"

    def buy(self, mint, usd, decimals, ref_price, liquidity_usd) -> FillResult:
        raise NotImplementedError("LiveEngine non implementato: modalità live disabilitata")

    def sell(self, mint, qty, decimals, ref_price, liquidity_usd) -> FillResult:
        raise NotImplementedError("LiveEngine non implementato: modalità live disabilitata")
