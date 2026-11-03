"""RugCheck: report di sicurezza (authority, holder, insider, rischi).

Docs: https://api.rugcheck.xyz/swagger/index.html  (endpoint report pubblico)
"""
from __future__ import annotations

import logging

from .base import SecurityData
from .http import get_json

log = logging.getLogger("solbot.rugcheck")
BASE = "https://api.rugcheck.xyz/v1"


class RugCheck:
    def security(self, mint: str) -> SecurityData | None:
        d = get_json(f"{BASE}/tokens/{mint}/report")
        if not isinstance(d, dict) or "__error__" in d:
            return None
        token = d.get("token") or {}
        supply = float(token.get("supply") or 0)
        decimals = token.get("decimals")
        # account da escludere dalla concentrazione: pool AMM, locker, account noti (es. bonding curve)
        excluded = set()
        for m in d.get("markets") or []:
            excluded.add(m.get("pubkey"))
            for k in ("liquidityA", "liquidityB"):
                if isinstance(m.get(k), str):
                    excluded.add(m[k])
        excluded |= set((d.get("knownAccounts") or {}).keys())
        excluded |= set((d.get("lockers") or {}).keys())
        holders = d.get("topHolders") or []
        real = [h for h in holders if h.get("owner") not in excluded and h.get("address") not in excluded]
        pcts = sorted((float(h.get("pct") or 0) for h in real), reverse=True)
        insider_pct = sum(float(h.get("pct") or 0) for h in real if h.get("insider"))
        creator_bal = float(d.get("creatorBalance") or 0)
        creator_pct = (creator_bal / supply * 100) if supply else None
        tf = d.get("transferFee") or {}
        markets = d.get("markets") or []
        lp_locked = None
        if markets:
            lp_locked = max(float(((m.get("lp") or {}).get("lpLockedPct")) or 0) for m in markets)
        return SecurityData(
            mint=mint,
            mint_authority=token.get("mintAuthority") or d.get("mintAuthority"),
            freeze_authority=token.get("freezeAuthority") or d.get("freezeAuthority"),
            score_norm=float(d["score_normalised"]) if d.get("score_normalised") is not None else None,
            rugged=bool(d.get("rugged")),
            holders=d.get("totalHolders"),
            top10_pct=round(sum(pcts[:10]), 2) if holders else None,
            max_holder_pct=round(pcts[0], 2) if pcts else None,
            insider_pct=round(insider_pct, 2),
            insiders_detected=d.get("graphInsidersDetected"),
            lp_locked_pct=lp_locked,
            creator_pct=round(creator_pct, 3) if creator_pct is not None else None,
            transfer_fee_pct=float(tf.get("pct") or 0),
            risks=[{"name": r.get("name"), "level": r.get("level"), "score": r.get("score")} for r in (d.get("risks") or [])],
            decimals=decimals,
            creator=d.get("creator"),
            launchpad=(d.get("launchpad") or {}).get("name") if isinstance(d.get("launchpad"), dict) else d.get("deployPlatform"),
        )
