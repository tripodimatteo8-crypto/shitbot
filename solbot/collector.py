"""Collector: scopre token, salva snapshot, applica i filtri e crea i candidati."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func

from .config import tunables
from .db import Candidate, Position, SecurityReport, Snapshot, Token, log_event, session_scope, utcnow
from .filters import features, market_prefilter, security_filter
from .learning import learned_filter
from .providers import get_provider
from .providers.base import MarketData, SecurityData

log = logging.getLogger("solbot.collector")

TRACK_HOURS = 26  # continuiamo a fotografare i token per valutare gli esiti a 24h
RECHECK_MINUTES = 30  # un token può tornare candidato dopo questo intervallo
PENDING_TTL_MINUTES = 10  # trading di breve: una decisione su dati vecchi non vale
SECURITY_CACHE_MINUTES = 30


def _sec_from_row(r: SecurityReport) -> SecurityData:
    return SecurityData(
        mint=r.mint, mint_authority=r.mint_authority, freeze_authority=r.freeze_authority, score_norm=r.score_norm,
        rugged=r.rugged, holders=r.holders, top10_pct=r.top10_pct, max_holder_pct=r.max_holder_pct,
        insider_pct=r.insider_pct, insiders_detected=r.insiders_detected, lp_locked_pct=r.lp_locked_pct,
        creator_pct=r.creator_pct, transfer_fee_pct=r.transfer_fee_pct, risks=r.risks or [], decimals=r.decimals,
        launchpad=r.launchpad, creator=r.creator,
    )


def get_security(mint: str, max_age_min: int = SECURITY_CACHE_MINUTES) -> SecurityData | None:
    with session_scope() as s:
        row = s.query(SecurityReport).filter(SecurityReport.mint == mint).order_by(SecurityReport.ts.desc()).first()
        if row and utcnow() - row.ts < timedelta(minutes=max_age_min):
            return _sec_from_row(row)
    sec = get_provider().security(mint)
    if sec:
        with session_scope() as s:
            s.add(SecurityReport(
                mint=mint, mint_authority=sec.mint_authority, freeze_authority=sec.freeze_authority,
                score_norm=sec.score_norm, rugged=sec.rugged, holders=sec.holders, top10_pct=sec.top10_pct,
                max_holder_pct=sec.max_holder_pct, insider_pct=sec.insider_pct, insiders_detected=sec.insiders_detected,
                lp_locked_pct=sec.lp_locked_pct, creator_pct=sec.creator_pct, transfer_fee_pct=sec.transfer_fee_pct,
                risks=sec.risks, decimals=sec.decimals, launchpad=sec.launchpad, creator=sec.creator,
            ))
            tok = s.get(Token, mint)
            if tok and sec.decimals is not None:
                tok.decimals = sec.decimals
    return sec


def _save_snapshot(s, md: MarketData) -> None:
    s.add(Snapshot(
        mint=md.mint, price_usd=md.price_usd, liquidity_usd=md.liquidity_usd, mcap_usd=md.mcap_usd, fdv_usd=md.fdv_usd,
        vol_m5=md.vol_m5, vol_h1=md.vol_h1, vol_h6=md.vol_h6, vol_h24=md.vol_h24, buys_h1=md.buys_h1,
        sells_h1=md.sells_h1, chg_m5=md.chg_m5, chg_h1=md.chg_h1, chg_h6=md.chg_h6, chg_h24=md.chg_h24,
    ))


def collect() -> dict:
    """Un giro di raccolta. Ritorna statistiche sintetiche."""
    t = tunables()
    p = get_provider()
    now = utcnow()
    discovered = p.discover()

    with session_scope() as s:
        for mint, srcs in discovered.items():
            tok = s.get(Token, mint)
            if tok is None:
                tok = Token(mint=mint, sources=",".join(sorted(srcs)), first_seen=now)
                s.add(tok)
            else:
                tok.sources = ",".join(sorted(set((tok.sources or "").split(",")) - {""} | srcs))
            tok.last_seen = now
            tok.track_until = now + timedelta(hours=TRACK_HOURS)
        s.flush()
        tracked = [m for (m,) in s.query(Token.mint).filter(Token.track_until > now).all()]
        held = {m for (m,) in s.query(Position.mint).filter(Position.status == "open").all()}
        last_snap = dict(s.query(Snapshot.mint, func.max(Snapshot.ts)).filter(Snapshot.mint.in_(tracked)).group_by(Snapshot.mint).all()) if tracked else {}
        first_seen = dict(s.query(Token.mint, Token.first_seen).filter(Token.mint.in_(tracked)).all()) if tracked else {}

    # frequenza snapshot: ogni giro per token nuovi (<2h) o in portafoglio, altrimenti ogni ~9 min
    to_fetch = []
    for m in set(tracked) | held:
        ls = last_snap.get(m)
        young = first_seen.get(m) and now - first_seen[m] < timedelta(hours=2)
        if m in discovered or m in held or young or ls is None or now - ls >= timedelta(minutes=9):
            to_fetch.append(m)
    md_all = p.market_data(to_fetch)
    ok_mints = getattr(getattr(p, "dex", None), "last_ok_mints", set(md_all))

    with session_scope() as s:
        for m in to_fetch:
            md = md_all.get(m)
            if md:
                md.sources = discovered.get(m, set())
                _save_snapshot(s, md)
                tok = s.get(Token, m)
                if tok:
                    tok.symbol = md.symbol or tok.symbol
                    tok.name = md.name or tok.name
                    tok.pair_address = md.pair_address
                    tok.dex_id = md.dex_id
                    tok.url = md.url
                    tok.pair_created_at = md.pair_created_at
            elif m in ok_mints:
                # interrogato con successo ma nessuna coppia: delistato/ruggato
                s.add(Snapshot(mint=m, price_usd=None, liquidity_usd=0.0))
        # scadenza candidati pendenti non decisi
        s.query(Candidate).filter(Candidate.status == "pending", Candidate.ts < now - timedelta(minutes=PENDING_TTL_MINUTES)).update({"status": "expired"})
        recent = {m for (m,) in s.query(Candidate.mint).filter(Candidate.ts > now - timedelta(minutes=RECHECK_MINUTES)).all()}

    # valutazione dei candidati (solo token appena segnalati dalle fonti)
    n_cand = n_pass = 0
    for mint, srcs in discovered.items():
        md = md_all.get(mint)
        if not md or mint in recent or mint in held:
            continue
        md.sources = srcs
        reasons = market_prefilter(md, t, now)
        sec = None
        if not reasons:
            sec = get_security(mint)
            reasons = security_filter(sec, t)
            if not reasons:
                reasons = learned_filter(features(md, sec, now), sec.creator if sec else None)
            if not reasons and t.require_sell_route and md.price_usd:
                dec = sec.decimals if sec and sec.decimals is not None else 6
                q = p.quote_sell(mint, 20 / md.price_usd, dec)
                if not q or q.out_amount <= 0:
                    reasons = ["nessuna route di vendita su Jupiter (possibile honeypot)"]
                elif q.out_amount < 20 * 0.7:
                    reasons = [f"vendita test 20$ restituisce solo {q.out_amount:.2f}$ (tassa/honeypot)"]
        passed = not reasons
        n_cand += 1
        n_pass += passed
        with session_scope() as s:
            s.add(Candidate(
                mint=mint, symbol=md.symbol, ts=now, price_usd=md.price_usd, liquidity_usd=md.liquidity_usd,
                mcap_usd=md.mcap_usd or md.fdv_usd, age_minutes=md.age_minutes(now), passed_filters=passed,
                filter_reasons=reasons, features=features(md, sec, now), status="pending" if passed else "filtered",
            ))
    stats = {"discovered": len(discovered), "snapshots": len(md_all), "candidates": n_cand, "passed": n_pass}
    log.info("Collector: %d token scoperti, %d snapshot, %d candidati valutati, %d passano i filtri", *stats.values())
    if n_pass:
        log_event("info", "collector", f"{n_pass} nuovi candidati passano i filtri (su {n_cand})")
    return stats


def refresh_open_positions() -> list[tuple[int, float | None, float | None]]:
    """Prezzi freschi per le posizioni aperte (usato dal monitor SL/TP)."""
    with session_scope() as s:
        opens = s.query(Position).filter(Position.status == "open").all()
        mints = list({p.mint for p in opens})
    if not mints:
        return []
    p = get_provider()
    md = p.market_data(mints)
    ok = getattr(getattr(p, "dex", None), "last_ok_mints", set(md))
    out = []
    with session_scope() as s:
        for pos in s.query(Position).filter(Position.status == "open").all():
            d = md.get(pos.mint)
            if d and d.price_usd:
                pos.last_price = d.price_usd
                pos.last_liquidity = d.liquidity_usd
                pos.high_water_price = max(pos.high_water_price, d.price_usd)
                _save_snapshot(s, d)
            elif pos.mint in ok:
                pos.last_liquidity = 0.0  # sparito da DexScreener
            out.append((pos.id, pos.last_price, pos.last_liquidity))
    return out


def fast_track() -> int:
    """Snapshot ogni minuto dei candidati visti di recente: servono per misurare gli esiti a 5/15/30 min
    e per imparare gli indicatori di rischio di breve periodo."""
    t = tunables()
    now = utcnow()
    with session_scope() as s:
        mints = [m for (m,) in s.query(Candidate.mint).filter(Candidate.ts > now - timedelta(minutes=t.fast_track_minutes)).distinct().all()]
        held = {m for (m,) in s.query(Position.mint).filter(Position.status == "open").all()}
    mints = [m for m in mints if m not in held]  # le posizioni aperte le aggiorna già il monitor
    if not mints:
        return 0
    p = get_provider()
    md = p.market_data(mints)
    ok = getattr(getattr(p, "dex", None), "last_ok_mints", set(md))
    with session_scope() as s:
        for m in mints:
            if m in md:
                _save_snapshot(s, md[m])
            elif m in ok:
                s.add(Snapshot(mint=m, price_usd=None, liquidity_usd=0.0))
    return len(md)
