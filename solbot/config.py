"""Configurazione di SolBot.

Due livelli:
- `Env`: segreti e parametri di processo letti da .env (mai modificabili da dashboard/agente).
- `Tunables`: soglie filtri, limiti di rischio, intervalli, modello. Default da .env,
  sovrascrivibili dall'utente dalla dashboard (tabella `settings`). L'agente NON ha
  alcun tool per modificarli.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = None
    helius_api_key: str | None = None
    birdeye_api_key: str | None = None
    gmgn_api_key: str | None = None

    database_url: str = f"sqlite:///{ROOT / 'data' / 'solbot.db'}"
    log_dir: Path = ROOT / "logs"
    lessons_path: Path = ROOT / "lezioni.md"
    kill_file: Path = ROOT / "KILL"
    host: str = "127.0.0.1"
    port: int = 8787

    # Modalità live: tutto disabilitato di default. La chiave privata NON viene mai
    # letta qui: la legge solo il LiveEngine al momento dell'uso.
    live_trading_enabled: bool = False

    # auto | claude | claude_cli | baseline
    # auto = API se c'è ANTHROPIC_API_KEY, altrimenti abbonamento via CLI `claude` se installata,
    # altrimenti baseline a regole.
    decider: str = "auto"
    claude_cli_path: str = "claude"


class Tunables(BaseSettings):
    """Parametri modificabili dall'utente (non dall'agente)."""

    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore", env_prefix="SB_")

    # --- Cicli (secondi) ---
    collect_interval_s: int = 180
    agent_interval_s: int = 180
    monitor_interval_s: int = 30
    evaluate_interval_s: int = 600

    # --- Claude ---
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"  # low | medium | high
    claude_fallbacks: bool = True  # fallback server-side in caso di refusal
    max_claude_calls_per_day: int = 400
    max_claude_tokens_per_day: int = 3_000_000
    max_claude_usd_per_day: float = 15.0
    max_candidates_per_cycle: int = 6
    reflect_every_n_closed_trades: int = 15

    # --- Claude via abbonamento (CLI `claude -p`) ---
    # Quota spalmata: al massimo N chiamate per finestra di ore (le chiamate vengono distanziate
    # in modo uniforme). 12 ogni 5h è una stima di ~25% di un piano Pro: regolala guardando /usage.
    cli_calls_per_window: int = 12
    cli_window_hours: float = 5.0
    cli_model: str = ""  # vuoto = modello di default del tuo abbonamento (es. "opus", "sonnet")
    cli_timeout_s: int = 300
    cli_pause_minutes_on_limit: int = 60
    cli_reflect_every_hours: float = 6.0
    cli_max_candidates: int = 8

    # --- Filtri hard (codice, non LLM) ---
    min_liquidity_usd: float = 15_000
    max_liquidity_usd: float = 5_000_000
    min_mcap_usd: float = 30_000
    max_mcap_usd: float = 50_000_000
    min_age_minutes: float = 10
    max_age_hours: float = 72
    min_volume_h1_usd: float = 5_000
    min_txns_h1: int = 40
    min_sells_h1: int = 5  # proxy anti-honeypot: qualcuno deve riuscire a vendere
    max_top10_pct: float = 35.0  # % supply nei top-10 holder (pool esclusi)
    max_single_holder_pct: float = 12.0
    max_insider_pct: float = 15.0  # proxy bundle/sniper (rete insider RugCheck)
    min_holders: int = 150
    max_rugcheck_score_norm: float = 30.0  # RugCheck: più alto = più rischioso
    require_no_mint_authority: bool = True
    require_no_freeze_authority: bool = True
    require_sell_route: bool = True  # Jupiter deve quotare token->SOL

    # --- Apprendimento dai rug (codice) ---
    rug_drop_pct: float = 80.0  # crollo dal prezzo del candidato che conta come rug
    rug_horizon_hours: float = 6.0  # finestra di osservazione per l'etichetta rug / non rug
    rug_liq_frac: float = 0.25  # liquidità sotto questa frazione di quella iniziale = rug
    learned_filter_enabled: bool = True
    learned_max_rug_prob: float = 0.5  # scarta se la probabilità di rug stimata supera questa
    learned_min_samples: int = 15  # campioni minimi in una fascia per usarla
    learned_min_total: int = 60  # token etichettati minimi prima di attivare il filtro
    learned_min_rugs: int = 8
    creator_blacklist_enabled: bool = True
    reflect_after_n_rugs: int = 3  # riflessione dopo N trade chiusi in rug

    # --- Paper portfolio / costi simulati (prudenti) ---
    initial_capital_usd: float = 1000.0
    swap_fee_pct: float = 0.25  # fee piattaforma/aggregatore oltre alla fee AMM già nella quote
    priority_fee_sol: float = 0.0015  # priority fee + jito tip per tx
    network_fee_sol: float = 0.000005
    mev_buffer_pct: float = 1.0  # penalità extra per lato (sandwich/sniper)
    execution_delay_s: float = 3.0  # ritardo simulato tra decisione e fill
    fallback_slippage_floor_pct: float = 1.5  # se manca la quote Jupiter

    # --- Protezioni hard-coded (fuori dall'agente) ---
    max_position_pct: float = 5.0  # % equity massima per trade
    min_position_usd: float = 10.0
    max_open_positions: int = 6
    stop_loss_pct: float = 25.0
    take_profit_pct: float = 60.0
    trailing_stop_pct: float = 25.0  # dal massimo, attivo dopo +30%
    trailing_activation_pct: float = 30.0
    max_hold_hours: float = 24.0
    daily_loss_limit_pct: float = 8.0
    min_liquidity_to_hold_usd: float = 5_000  # sotto: uscita forzata

    # --- Gate paper -> live ---
    gate_min_days: int = 21
    gate_min_trades: int = 150
    gate_min_pnl_usd: float = 0.0  # PnL netto dopo costi deve superare questo
    gate_max_drawdown_pct: float = 20.0
    gate_min_profit_factor: float = 1.3


env = Env()

_lock = threading.Lock()
_cache: tuple[float, Tunables] | None = None
EDITABLE_KEYS = set(Tunables.model_fields.keys())


def tunables(force: bool = False) -> Tunables:
    """Tunables correnti = default/.env + override salvati in DB (cache 5s)."""
    global _cache
    with _lock:
        if not force and _cache and time.time() - _cache[0] < 5:
            return _cache[1]
        base = Tunables()
        try:
            from .db import Setting, session_scope

            with session_scope() as s:
                overrides = {row.key: json.loads(row.value) for row in s.query(Setting).all()}
        except Exception:
            overrides = {}
        data = base.model_dump()
        for k, v in overrides.items():
            if k in EDITABLE_KEYS:
                data[k] = v
        t = Tunables.model_validate(data) if overrides else base
        # model_validate rilegge l'env: imponiamo i valori finali esplicitamente
        for k, v in data.items():
            object.__setattr__(t, k, v)
        _cache = (time.time(), t)
        return t


def invalidate_cache() -> None:
    global _cache
    with _lock:
        _cache = None
