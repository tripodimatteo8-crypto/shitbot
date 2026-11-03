"""Interfaccia astratta per le fonti dati. Cambiare fonte = nuova implementazione."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class MarketData:
    mint: str
    symbol: str | None = None
    name: str | None = None
    pair_address: str | None = None
    dex_id: str | None = None
    url: str | None = None
    pair_created_at: datetime | None = None
    price_usd: float | None = None
    liquidity_usd: float | None = None
    mcap_usd: float | None = None
    fdv_usd: float | None = None
    vol_m5: float | None = None
    vol_h1: float | None = None
    vol_h6: float | None = None
    vol_h24: float | None = None
    buys_m5: int | None = None
    sells_m5: int | None = None
    buys_h1: int | None = None
    sells_h1: int | None = None
    buys_h24: int | None = None
    sells_h24: int | None = None
    chg_m5: float | None = None
    chg_h1: float | None = None
    chg_h6: float | None = None
    chg_h24: float | None = None
    has_socials: bool = False
    boosted: bool = False
    sources: set[str] = field(default_factory=set)

    def age_minutes(self, now: datetime) -> float | None:
        if not self.pair_created_at:
            return None
        return (now - self.pair_created_at).total_seconds() / 60

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sources"] = sorted(self.sources)
        if self.pair_created_at:
            d["pair_created_at"] = self.pair_created_at.isoformat()
        return d


@dataclass
class SecurityData:
    mint: str
    mint_authority: str | None = None
    freeze_authority: str | None = None
    score_norm: float | None = None
    rugged: bool | None = None
    holders: int | None = None
    top10_pct: float | None = None
    max_holder_pct: float | None = None
    insider_pct: float | None = None
    insiders_detected: int | None = None
    lp_locked_pct: float | None = None
    creator_pct: float | None = None
    transfer_fee_pct: float | None = None
    risks: list[dict] = field(default_factory=list)
    decimals: int | None = None
    launchpad: str | None = None
    # Non disponibili gratis oggi (GMGN/Birdeye/Helius in futuro):
    sniper_pct: float | None = None
    bundle_pct: float | None = None
    smart_money_buys: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Quote:
    """Esito di una quote reale (o stimata) per uno swap."""

    in_amount: float  # USD (buy) o token (sell)
    out_amount: float  # token (buy) o USD (sell), già al netto della fee AMM
    price_impact_pct: float
    source: str  # "jupiter" | "model"


class DataProvider(ABC):
    @abstractmethod
    def discover(self) -> dict[str, set[str]]:
        """Mint dei token nuovi/trending -> insieme delle fonti che li hanno segnalati."""

    @abstractmethod
    def market_data(self, mints: list[str]) -> dict[str, MarketData]: ...

    @abstractmethod
    def security(self, mint: str) -> SecurityData | None: ...

    @abstractmethod
    def sol_price_usd(self) -> float | None: ...

    @abstractmethod
    def quote_buy(self, mint: str, usd: float, decimals: int) -> Quote | None: ...

    @abstractmethod
    def quote_sell(self, mint: str, qty: float, decimals: int) -> Quote | None: ...
