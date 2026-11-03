from datetime import timedelta

from solbot.config import Tunables
from solbot.filters import market_prefilter, security_filter
from solbot.providers.base import MarketData, SecurityData


def good_md(now):
    return MarketData(mint="M", price_usd=0.001, liquidity_usd=40_000, mcap_usd=300_000,
                      pair_created_at=now - timedelta(hours=3), vol_h1=30_000, buys_h1=200, sells_h1=150)


def good_sec():
    return SecurityData(mint="M", top10_pct=20, max_holder_pct=4, insider_pct=0, holders=800, score_norm=5)


def test_good_token_passes(now):
    t = Tunables()
    assert market_prefilter(good_md(now), t, now) == []
    assert security_filter(good_sec(), t) == []


def test_low_liquidity_rejected(now):
    md = good_md(now)
    md.liquidity_usd = 2_000
    assert any("liquidità" in r for r in market_prefilter(md, Tunables(), now))


def test_unknown_liquidity_rejected(now):
    md = good_md(now)
    md.liquidity_usd = None
    assert market_prefilter(md, Tunables(), now)


def test_no_sells_honeypot_rejected(now):
    md = good_md(now)
    md.sells_h1 = 0
    assert any("honeypot" in r for r in market_prefilter(md, Tunables(), now))


def test_too_young_and_too_old(now):
    md = good_md(now)
    md.pair_created_at = now - timedelta(minutes=2)
    assert any("nuovo" in r for r in market_prefilter(md, Tunables(), now))
    md.pair_created_at = now - timedelta(days=10)
    assert any("vecchio" in r for r in market_prefilter(md, Tunables(), now))


def test_authorities_rejected():
    sec = good_sec()
    sec.mint_authority = "X"
    sec.freeze_authority = "Y"
    r = security_filter(sec, Tunables())
    assert any("mint authority" in x for x in r) and any("freeze authority" in x for x in r)


def test_concentration_insider_rug_rejected():
    t = Tunables()
    for field, val, word in [("top10_pct", 60, "top-10"), ("max_holder_pct", 30, "singolo"),
                             ("insider_pct", 40, "insider"), ("rugged", True, "RUGGED"), ("holders", 20, "holder")]:
        sec = good_sec()
        setattr(sec, field, val)
        assert any(word in x for x in security_filter(sec, t)), field


def test_missing_report_rejected():
    assert security_filter(None, Tunables()) == ["report di sicurezza non disponibile"]


def test_danger_risk_rejected():
    sec = good_sec()
    sec.risks = [{"name": "Freeze Authority still enabled", "level": "danger"}]
    assert security_filter(sec, Tunables())
