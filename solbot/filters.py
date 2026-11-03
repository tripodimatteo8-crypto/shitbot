"""Filtri hard in codice: scartano rug/honeypot/token rischiosi PRIMA di chiamare Claude."""
from __future__ import annotations

from datetime import datetime

from .config import Tunables
from .providers.base import MarketData, SecurityData

DANGER_RISK_KEYWORDS = ("honeypot", "freeze", "mint authority", "copycat", "rugged", "mutable transfer", "permanent delegate")


def market_prefilter(md: MarketData, t: Tunables, now: datetime) -> list[str]:
    """Filtri economici sui soli dati di mercato (nessuna chiamata extra). Ritorna i motivi di scarto."""
    r: list[str] = []
    if md.price_usd is None or md.price_usd <= 0:
        r.append("prezzo assente")
    if md.liquidity_usd is None:
        r.append("liquidità sconosciuta (bonding curve o pool non indicizzato)")
    elif md.liquidity_usd < t.min_liquidity_usd:
        r.append(f"liquidità {md.liquidity_usd:,.0f}$ < {t.min_liquidity_usd:,.0f}$")
    elif md.liquidity_usd > t.max_liquidity_usd:
        r.append(f"liquidità {md.liquidity_usd:,.0f}$ > {t.max_liquidity_usd:,.0f}$ (non memecoin)")
    mcap = md.mcap_usd or md.fdv_usd
    if mcap is None:
        r.append("market cap sconosciuta")
    elif mcap < t.min_mcap_usd:
        r.append(f"mcap {mcap:,.0f}$ < {t.min_mcap_usd:,.0f}$")
    elif mcap > t.max_mcap_usd:
        r.append(f"mcap {mcap:,.0f}$ > {t.max_mcap_usd:,.0f}$")
    age = md.age_minutes(now)
    if age is None:
        r.append("età sconosciuta")
    elif age < t.min_age_minutes:
        r.append(f"troppo nuovo ({age:.0f} min)")
    elif age > t.max_age_hours * 60:
        r.append(f"troppo vecchio ({age / 60:.0f} h)")
    if (md.vol_h1 or 0) < t.min_volume_h1_usd:
        r.append(f"volume 1h {md.vol_h1 or 0:,.0f}$ < {t.min_volume_h1_usd:,.0f}$")
    txns = (md.buys_h1 or 0) + (md.sells_h1 or 0)
    if txns < t.min_txns_h1:
        r.append(f"transazioni 1h {txns} < {t.min_txns_h1}")
    if (md.sells_h1 or 0) < t.min_sells_h1:
        r.append(f"vendite 1h {md.sells_h1 or 0} < {t.min_sells_h1} (possibile honeypot)")
    return r


def security_filter(sec: SecurityData | None, t: Tunables) -> list[str]:
    """Filtri di sicurezza su report RugCheck. Report mancante = scarto (prudenza)."""
    if sec is None:
        return ["report di sicurezza non disponibile"]
    r: list[str] = []
    if sec.rugged:
        r.append("segnalato come RUGGED")
    if t.require_no_mint_authority and sec.mint_authority:
        r.append("mint authority attiva")
    if t.require_no_freeze_authority and sec.freeze_authority:
        r.append("freeze authority attiva")
    if sec.transfer_fee_pct and sec.transfer_fee_pct > 0:
        r.append(f"transfer fee {sec.transfer_fee_pct}%")
    if sec.top10_pct is None:
        r.append("concentrazione holder sconosciuta")
    elif sec.top10_pct > t.max_top10_pct:
        r.append(f"top-10 holder {sec.top10_pct:.1f}% > {t.max_top10_pct}%")
    if sec.max_holder_pct is not None and sec.max_holder_pct > t.max_single_holder_pct:
        r.append(f"singolo holder {sec.max_holder_pct:.1f}% > {t.max_single_holder_pct}%")
    if sec.insider_pct is not None and sec.insider_pct > t.max_insider_pct:
        r.append(f"insider/bundle {sec.insider_pct:.1f}% > {t.max_insider_pct}%")
    if sec.holders is not None and sec.holders < t.min_holders:
        r.append(f"holder {sec.holders} < {t.min_holders}")
    if sec.score_norm is not None and sec.score_norm > t.max_rugcheck_score_norm:
        r.append(f"rischio RugCheck {sec.score_norm:.0f} > {t.max_rugcheck_score_norm:.0f}")
    for risk in sec.risks:
        name = (risk.get("name") or "").lower()
        if risk.get("level") == "danger" and any(k in name for k in DANGER_RISK_KEYWORDS):
            r.append(f"rischio critico: {risk.get('name')}")
    return r


def features(md: MarketData, sec: SecurityData | None, now: datetime) -> dict:
    """Feature compatte salvate per ogni candidato (usate da valutatore e riflessione)."""
    txns = (md.buys_h1 or 0) + (md.sells_h1 or 0)
    return {
        "age_min": round(md.age_minutes(now) or 0, 1),
        "liq": md.liquidity_usd,
        "mcap": md.mcap_usd or md.fdv_usd,
        "vol_h1": md.vol_h1,
        "vol_liq_h1": round((md.vol_h1 or 0) / md.liquidity_usd, 3) if md.liquidity_usd else None,
        "buy_ratio_h1": round((md.buys_h1 or 0) / txns, 3) if txns else None,
        "chg_m5": md.chg_m5,
        "chg_h1": md.chg_h1,
        "chg_h6": md.chg_h6,
        "dex": md.dex_id,
        "socials": md.has_socials,
        "boosted": md.boosted,
        "sources": sorted(md.sources),
        "holders": sec.holders if sec else None,
        "top10": sec.top10_pct if sec else None,
        "insider": sec.insider_pct if sec else None,
        "rug_score": sec.score_norm if sec else None,
    }
