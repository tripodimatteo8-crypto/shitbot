"""Apprendimento automatico dai rug (in codice, gira anche senza Claude).

Il trading è di breve periodo (minuti): gli indicatori di rischio si imparano su un orizzonte breve.

1. Etichetta: ogni candidato (comprato, saltato o scartato) viene marcato come rug se entro
   l'orizzonte (default 1h) il prezzo crolla di almeno `rug_drop_pct` o la liquidità scende sotto
   `rug_liq_frac` di quella iniziale; come non-rug se l'orizzonte passa senza crollo.
   In più come "dump" se nello stesso orizzonte scende di almeno `dump_drop_pct` (= stop loss colpito).
   Le etichette si assegnano solo a orizzonte concluso, per non sovrastimare i casi negativi.
2. Modello: per ogni feature (vol/liq, % acquisti, variazione 6h, età, holder, top-10, mcap...)
   calcola il tasso di rug e di dump per fascia, con smoothing. Le fasce con abbastanza campioni si combinano
   (naive Bayes) in una probabilità di rug per ogni nuovo candidato.
3. Filtro appreso: scarta i candidati con probabilità di rug >= soglia. I candidati scartati
   continuano a essere misurati, quindi il modello si corregge da solo se sbaglia.
4. Blacklist creator: i creator di token che hanno fatto rug vengono bloccati.
"""
from __future__ import annotations

import logging
import math
import threading
from datetime import timedelta

from .config import tunables
from .db import Candidate, LearnedModel, SecurityReport, Snapshot, log_event, session_scope, utcnow

log = logging.getLogger("solbot.learning")

# fasce per feature: (nome, etichetta leggibile, limiti)
BINS: list[tuple[str, str, list[float]]] = [
    ("vol_liq_h1", "volume 1h / liquidità", [0, 0.5, 1, 2, 4, 8]),
    ("buy_ratio_h1", "quota acquisti 1h", [0, 0.5, 0.6, 0.7, 0.8, 0.9]),
    ("chg_h1", "variazione 1h %", [-100, -20, 0, 20, 50, 100, 300]),
    ("chg_h6", "variazione 6h %", [-100, 0, 50, 150, 400, 1000]),
    ("age_min", "età (min)", [0, 60, 180, 720, 1440, 2880]),
    ("liq", "liquidità $", [0, 20_000, 40_000, 80_000, 200_000, 1_000_000]),
    ("mcap", "market cap $", [0, 100_000, 300_000, 1_000_000, 5_000_000]),
    ("holders", "holder", [0, 300, 1000, 3000, 10_000]),
    ("top10", "top-10 %", [0, 10, 20, 30, 50]),
    ("insider", "insider %", [0, 0.01, 5, 15]),
    ("socials", "ha social", None),
    ("dex", "dex", None),
]

_lock = threading.Lock()
_model: dict | None = None


def _bucket(edges: list[float] | None, v) -> str | None:
    if v is None:
        return None
    if edges is None:
        return str(v)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    for lo, hi in zip(edges, edges[1:]):
        if lo <= v < hi:
            return f"{lo:g}–{hi:g}"
    return f"≥{edges[-1]:g}" if v >= edges[-1] else f"<{edges[0]:g}"


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


# ------------------------------------------------------------------ labeling
def label_rugs() -> int:
    """Etichetta come rug / non rug i candidati il cui orizzonte di osservazione è concluso.

    Entrambe le etichette si assegnano solo dopo `rug_horizon_hours`: se i rug venissero marcati
    subito e i "sani" solo dopo, il modello vedrebbe all'inizio quasi solo rug (bias).
    """
    t = tunables()
    now = utcnow()
    h = timedelta(hours=t.rug_horizon_hours)
    n = 0
    with session_scope() as s:
        todo = s.query(Candidate).filter(Candidate.rug.is_(None), Candidate.ts <= now - h,
                                         Candidate.ts > now - h - timedelta(hours=30),
                                         Candidate.price_usd.isnot(None)).all()
        by_mint: dict[str, list[Candidate]] = {}
        for c in todo:
            by_mint.setdefault(c.mint, []).append(c)
        for mint, cs in by_mint.items():
            t0 = min(c.ts for c in cs)
            snaps = s.query(Snapshot).filter(Snapshot.mint == mint, Snapshot.ts > t0).order_by(Snapshot.ts).all()
            for c in cs:
                after = [x for x in snaps if c.ts < x.ts <= c.ts + h]
                hit = None
                for x in after:
                    gone = x.price_usd is None and (x.liquidity_usd or 0) == 0
                    crash = x.price_usd is not None and x.price_usd <= c.price_usd * (1 - t.rug_drop_pct / 100)
                    liq_drain = c.liquidity_usd and x.liquidity_usd is not None and x.liquidity_usd < c.liquidity_usd * t.rug_liq_frac
                    if gone or crash or liq_drain:
                        hit = x
                        break
                dumped = hit is not None or any(
                    x.price_usd is not None and x.price_usd <= c.price_usd * (1 - t.dump_drop_pct / 100) for x in after)
                if hit is not None:
                    c.rug, c.rug_at, c.dump = True, hit.ts, True
                    n += 1
                elif any(x.ts >= c.ts + h / 2 for x in after):  # osservato abbastanza a lungo
                    c.rug, c.dump = False, dumped
                    n += 1
    if n:
        log.info("Apprendimento: etichettati %d candidati (rug / non rug)", n)
    return n


# ------------------------------------------------------------------ model
def _build(rows: list[tuple[dict, bool, str]]) -> dict:
    """Tassi per fascia per un'etichetta binaria. rows = (features, etichetta, mint)."""
    # un token può comparire più volte: lo contiamo una volta per fascia per non gonfiare i numeri
    total = len({m for _, _, m in rows})
    pos = len({m for _, r, m in rows if r})
    base = (pos + 1) / (total + 2)
    feats: dict[str, dict[str, dict]] = {}
    for key, label, edges in BINS:
        seen: dict[str, dict[str, bool]] = {}
        for f, r, m in rows:
            b = _bucket(edges, (f or {}).get(key))
            if b is None:
                continue
            seen.setdefault(b, {})
            seen[b][m] = seen[b].get(m, False) or bool(r)
        feats[key] = {}
        for b, mints in seen.items():
            n = len(mints)
            k = sum(mints.values())
            rate = (k + 4 * base) / (n + 4)  # smoothing verso il tasso base (prior di 4 campioni)
            feats[key][b] = {"n": n, "rugs": k, "rate": round(rate, 4)}
    return {"n": total, "rugs": pos, "base_rate": round(base, 4), "features": feats}


def rebuild_model() -> dict:
    """Ricalcola i tassi di rug e di dump per fascia su tutti i candidati etichettati (ultimi 14 giorni)."""
    global _model
    since = utcnow() - timedelta(days=14)
    with session_scope() as s:
        rows = s.query(Candidate.features, Candidate.rug, Candidate.dump, Candidate.mint).filter(
            Candidate.rug.isnot(None), Candidate.ts > since).all()
    model = _build([(f, r, m) for f, r, d, m in rows])
    model["dump"] = _build([(f, d, m) for f, r, d, m in rows if d is not None])
    model["ts"] = utcnow().isoformat()
    with _lock:
        _model = model
    with session_scope() as s:
        s.add(LearnedModel(n_samples=model["n"], n_rugs=model["rugs"], base_rate=model["base_rate"], model=model))
    log.info("Modello rischio aggiornato: %d token etichettati, %d rug (%.0f%%), %d dump (%.0f%%)", model["n"], model["rugs"],
             model["base_rate"] * 100, model["dump"]["rugs"], model["dump"]["base_rate"] * 100)
    return model


def current_model() -> dict | None:
    global _model
    with _lock:
        if _model is not None:
            return _model
    with session_scope() as s:
        row = s.query(LearnedModel).order_by(LearnedModel.id.desc()).first()
        if row:
            with _lock:
                _model = row.model
    return _model


def rug_probability(features: dict, model: dict | None = None, target: str = "rug") -> tuple[float | None, list[str]]:
    """Probabilità stimata (rug o dump entro l'orizzonte breve) + spiegazione (fasce che pesano di più)."""
    t = tunables()
    model = model or current_model()
    if model and target == "dump":
        model = model.get("dump")
    if not model or model["n"] < t.learned_min_total or model["rugs"] < t.learned_min_rugs:
        return None, []
    base = model["base_rate"]
    z = _logit(base)
    contrib = []
    for key, label, edges in BINS:
        b = _bucket(edges, features.get(key))
        st = model["features"].get(key, {}).get(b) if b else None
        if not st or st["n"] < t.learned_min_samples:
            continue
        d = _logit(st["rate"]) - _logit(base)
        z += d
        contrib.append((d, f"{label} {b}: {st['rugs']}/{st['n']} {target}"))
    p = 1 / (1 + math.exp(-z))
    contrib.sort(reverse=True)
    return p, [c for d, c in contrib if d > 0][:3]


def learned_filter(features: dict, creator: str | None) -> list[str]:
    """Motivi di scarto appresi (vuoto = ok)."""
    t = tunables()
    reasons = []
    if t.creator_blacklist_enabled and creator and creator in rug_creators():
        reasons.append("creator già autore di un rug (blacklist appresa)")
    if t.learned_filter_enabled:
        p, why = rug_probability(features)
        if p is not None and p >= t.learned_max_rug_prob:
            reasons.append(f"rischio rug appreso {p:.0%} ({'; '.join(why) or 'combinazione di fasce'})")
    return reasons


_creators_cache: tuple[float, set[str]] | None = None


def rug_creators() -> set[str]:
    global _creators_cache
    import time

    if _creators_cache and time.time() - _creators_cache[0] < 300:
        return _creators_cache[1]
    with session_scope() as s:
        rug_mints = {m for (m,) in s.query(Candidate.mint).filter(Candidate.rug.is_(True)).distinct().all()}
        creators = {c for (c,) in s.query(SecurityReport.creator).filter(SecurityReport.mint.in_(rug_mints), SecurityReport.creator.isnot(None)).distinct().all()} if rug_mints else set()
    _creators_cache = (time.time(), creators)
    return creators


def _bands(m: dict, max_lines: int) -> tuple[list[str], list[str]]:
    t = tunables()
    rows = []
    for key, label, _ in BINS:
        for b, st in m["features"].get(key, {}).items():
            if st["n"] >= t.learned_min_samples:
                rows.append((st["rate"], f"{label} {b}: {st['rugs']}/{st['n']} ({st['rate']:.0%})"))
    rows.sort(reverse=True)
    return [r for _, r in rows[: max_lines // 2]], [r for _, r in rows[-(max_lines // 2):]][::-1]


def summary_for_prompt(max_lines: int = 12) -> str:
    """Le fasce più e meno rischiose (rug e dump entro l'orizzonte breve), compatte per Claude."""
    t = tunables()
    m = current_model()
    if not m or m["n"] < 20:
        return "Statistiche di rischio a breve: dati ancora insufficienti."
    h = f"{t.rug_horizon_hours:g}h"
    out = [f"Statistiche di rischio misurate dal codice (ultimi 14 giorni, {m['n']} token, orizzonte {h}):"]
    risky, safe = _bands(m, max_lines)
    out.append(f"RUG (crollo >= {t.rug_drop_pct:g}% o liquidità sparita entro {h}), tasso base {m['base_rate']:.0%}.")
    out.append("Fasce più rischiose:\n- " + "\n- ".join(risky or ["(poche fasce con campioni sufficienti)"]))
    out.append("Fasce meno rischiose:\n- " + "\n- ".join(safe or ["-"]))
    d = m.get("dump")
    if d and d["n"] >= 20:
        risky, safe = _bands(d, max_lines)
        out.append(f"DUMP (calo >= {t.dump_drop_pct:g}% entro {h}, cioè stop loss colpito), tasso base {d['base_rate']:.0%}.")
        out.append("Fasce con più dump:\n- " + "\n- ".join(risky or ["-"]))
        out.append("Fasce con meno dump:\n- " + "\n- ".join(safe or ["-"]))
    return "\n".join(out)


def update() -> None:
    """Job periodico: etichetta e ricostruisce il modello."""
    before = current_model()
    label_rugs()
    m = rebuild_model()
    if before and m["rugs"] > before.get("rugs", 0):
        log_event("info", "learning", f"Modello rischio: {m['rugs']} rug e {m['dump']['rugs']} dump su {m['n']} token")
