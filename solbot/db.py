"""Schema SQLite (SQLAlchemy 2.x)."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Token(Base):
    __tablename__ = "tokens"
    mint: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(128))
    pair_address: Mapped[str | None] = mapped_column(String(64))
    dex_id: Mapped[str | None] = mapped_column(String(32))
    pair_created_at: Mapped[datetime | None] = mapped_column(DateTime)
    decimals: Mapped[int | None] = mapped_column(Integer)
    sources: Mapped[str | None] = mapped_column(String(256))  # es. "profiles,boosts,search"
    url: Mapped[str | None] = mapped_column(String(256))
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    track_until: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class Snapshot(Base):
    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    price_usd: Mapped[float | None] = mapped_column(Float)
    liquidity_usd: Mapped[float | None] = mapped_column(Float)
    mcap_usd: Mapped[float | None] = mapped_column(Float)
    fdv_usd: Mapped[float | None] = mapped_column(Float)
    vol_m5: Mapped[float | None] = mapped_column(Float)
    vol_h1: Mapped[float | None] = mapped_column(Float)
    vol_h6: Mapped[float | None] = mapped_column(Float)
    vol_h24: Mapped[float | None] = mapped_column(Float)
    buys_h1: Mapped[int | None] = mapped_column(Integer)
    sells_h1: Mapped[int | None] = mapped_column(Integer)
    chg_m5: Mapped[float | None] = mapped_column(Float)
    chg_h1: Mapped[float | None] = mapped_column(Float)
    chg_h6: Mapped[float | None] = mapped_column(Float)
    chg_h24: Mapped[float | None] = mapped_column(Float)
    holders: Mapped[int | None] = mapped_column(Integer)


class SecurityReport(Base):
    __tablename__ = "security_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    mint_authority: Mapped[str | None] = mapped_column(String(64))
    freeze_authority: Mapped[str | None] = mapped_column(String(64))
    score_norm: Mapped[float | None] = mapped_column(Float)
    rugged: Mapped[bool | None] = mapped_column(Boolean)
    holders: Mapped[int | None] = mapped_column(Integer)
    top10_pct: Mapped[float | None] = mapped_column(Float)
    max_holder_pct: Mapped[float | None] = mapped_column(Float)
    insider_pct: Mapped[float | None] = mapped_column(Float)
    insiders_detected: Mapped[int | None] = mapped_column(Integer)
    lp_locked_pct: Mapped[float | None] = mapped_column(Float)
    creator_pct: Mapped[float | None] = mapped_column(Float)
    transfer_fee_pct: Mapped[float | None] = mapped_column(Float)
    risks: Mapped[list | None] = mapped_column(JSON)
    decimals: Mapped[int | None] = mapped_column(Integer)
    launchpad: Mapped[str | None] = mapped_column(String(64))
    creator: Mapped[str | None] = mapped_column(String(64), index=True)


class Candidate(Base):
    """Ogni volta che un token viene valutato (filtri + eventuale decisione)."""

    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str | None] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    price_usd: Mapped[float | None] = mapped_column(Float)
    liquidity_usd: Mapped[float | None] = mapped_column(Float)
    mcap_usd: Mapped[float | None] = mapped_column(Float)
    age_minutes: Mapped[float | None] = mapped_column(Float)
    passed_filters: Mapped[bool] = mapped_column(Boolean, index=True)
    filter_reasons: Mapped[list | None] = mapped_column(JSON)
    features: Mapped[dict | None] = mapped_column(JSON)
    # filtered | pending | buy | skip | expired
    status: Mapped[str] = mapped_column(String(16), index=True)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"))
    # esiti oggettivi (rendimento % del prezzo di mercato, senza costi)
    ret_1h: Mapped[float | None] = mapped_column(Float)
    ret_6h: Mapped[float | None] = mapped_column(Float)
    ret_24h: Mapped[float | None] = mapped_column(Float)
    max_ret_24h: Mapped[float | None] = mapped_column(Float)
    min_ret_24h: Mapped[float | None] = mapped_column(Float)
    rugged_24h: Mapped[bool | None] = mapped_column(Boolean)
    # etichetta di apprendimento: True = rug (crollo/liquidità sparita entro 24h), False = no
    rug: Mapped[bool | None] = mapped_column(Boolean, index=True)
    rug_at: Mapped[datetime | None] = mapped_column(DateTime)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(8))  # buy | sell | skip
    reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    requested_usd: Mapped[float | None] = mapped_column(Float)
    decider: Mapped[str] = mapped_column(String(32))  # claude | baseline
    model: Mapped[str | None] = mapped_column(String(64))
    lessons_version: Mapped[int | None] = mapped_column(Integer)
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    position_id: Mapped[int | None] = mapped_column(Integer)


class Position(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mint: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(8), index=True)  # open | closed
    engine: Mapped[str] = mapped_column(String(8), default="paper")
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    qty: Mapped[float] = mapped_column(Float)  # unità token (UI)
    cost_usd: Mapped[float] = mapped_column(Float)  # USD totali spesi (inclusi costi)
    entry_price_eff: Mapped[float] = mapped_column(Float)  # cost_usd / qty
    entry_price_mkt: Mapped[float] = mapped_column(Float)  # prezzo di mercato al momento
    high_water_price: Mapped[float] = mapped_column(Float)
    last_price: Mapped[float | None] = mapped_column(Float)
    last_liquidity: Mapped[float | None] = mapped_column(Float)
    proceeds_usd: Mapped[float | None] = mapped_column(Float)
    pnl_usd: Mapped[float | None] = mapped_column(Float)
    pnl_pct: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    buy_decision_id: Mapped[int | None] = mapped_column(Integer)
    sell_decision_id: Mapped[int | None] = mapped_column(Integer)
    decider: Mapped[str | None] = mapped_column(String(32))
    lessons_version: Mapped[int | None] = mapped_column(Integer)


class Fill(Base):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[float] = mapped_column(Float)
    usd_gross: Mapped[float] = mapped_column(Float)  # prima delle fee
    fees_usd: Mapped[float] = mapped_column(Float)
    usd_net: Mapped[float] = mapped_column(Float)
    price_ref: Mapped[float] = mapped_column(Float)  # prezzo di mercato
    price_eff: Mapped[float] = mapped_column(Float)  # prezzo effettivo netto
    slippage_pct: Mapped[float] = mapped_column(Float)
    quote_source: Mapped[str] = mapped_column(String(16))
    delay_s: Mapped[float] = mapped_column(Float)


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cash_usd: Mapped[float] = mapped_column(Float)
    initial_capital_usd: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    halted_day: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD di stop giornaliero
    halted_reason: Mapped[str | None] = mapped_column(Text)
    day: Mapped[str | None] = mapped_column(String(10))
    day_start_equity: Mapped[float | None] = mapped_column(Float)
    live_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class EquitySnapshot(Base):
    __tablename__ = "equity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    equity_usd: Mapped[float] = mapped_column(Float)
    cash_usd: Mapped[float] = mapped_column(Float)
    positions_usd: Mapped[float] = mapped_column(Float)
    open_positions: Mapped[int] = mapped_column(Integer)


class ClaudeUsage(Base):
    __tablename__ = "claude_usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # decision | reflection
    model: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class LessonVersion(Base):
    __tablename__ = "lesson_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    content: Mapped[str] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    metrics: Mapped[dict | None] = mapped_column(JSON)  # metriche al momento della scrittura
    closed_trades: Mapped[int] = mapped_column(Integer, default=0)


class LearnedModel(Base):
    """Versioni del modello di rischio rug appreso dai dati."""

    __tablename__ = "learned_models"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    n_samples: Mapped[int] = mapped_column(Integer)
    n_rugs: Mapped[int] = mapped_column(Integer)
    base_rate: Mapped[float] = mapped_column(Float)
    model: Mapped[dict] = mapped_column(JSON)


class EventLog(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)


_engine = None
_Session = None


def init_db(url: str | None = None):
    global _engine, _Session
    from .config import env

    url = url or env.database_url
    _engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30}, pool_pre_ping=True)

    @event.listens_for(_engine, "connect")
    def _pragmas(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    Base.metadata.create_all(_engine)
    _add_missing_columns(_engine)
    _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def _add_missing_columns(engine) -> None:
    """Migrazione minima: aggiunge le colonne nuove alle tabelle esistenti (SQLite)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'))


@contextmanager
def session_scope():
    if _Session is None:
        init_db()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def log_event(level: str, kind: str, message: str) -> None:
    try:
        with session_scope() as s:
            s.add(EventLog(level=level, kind=kind, message=message[:4000]))
    except Exception:  # il logging su DB non deve mai rompere il bot
        pass
