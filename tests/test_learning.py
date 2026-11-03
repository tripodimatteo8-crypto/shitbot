import sqlite3
from datetime import timedelta

from solbot import learning
from solbot.db import Candidate, SecurityReport, Snapshot, init_db, session_scope, utcnow


def _cand(s, mint, t0, price, features, liq=50_000):
    c = Candidate(mint=mint, symbol=mint, ts=t0, price_usd=price, liquidity_usd=liq, passed_filters=True,
                  status="skip", features=features)
    s.add(c)
    return c


def _seed(n_rug=30, n_ok=30):
    """Token pompati (vol/liq alto, buy ratio alto) che fanno rug, e token sani che no."""
    t0 = utcnow() - timedelta(hours=25)
    with session_scope() as s:
        for i in range(n_rug):
            m = f"RUG{i}"
            _cand(s, m, t0, 1.0, {"vol_liq_h1": 6.0, "buy_ratio_h1": 0.88, "chg_h6": 200, "holders": 2500})
            s.add(Snapshot(mint=m, ts=t0 + timedelta(minutes=40), price_usd=0.05, liquidity_usd=1_500))
            s.add(SecurityReport(mint=m, creator=f"CREATOR{i % 3}"))
        for i in range(n_ok):
            m = f"OK{i}"
            _cand(s, m, t0, 1.0, {"vol_liq_h1": 0.8, "buy_ratio_h1": 0.6, "chg_h6": 20, "holders": 2500})
            s.add(Snapshot(mint=m, ts=t0 + timedelta(minutes=50), price_usd=0.9, liquidity_usd=45_000))


def test_labels_rug_and_non_rug(fresh_db):
    _seed(3, 3)
    learning.label_rugs()
    with session_scope() as s:
        labels = {c.mint: c.rug for c in s.query(Candidate).all()}
    assert labels["RUG0"] is True and labels["OK0"] is False


def test_liquidity_drain_counts_as_rug(fresh_db):
    t0 = utcnow() - timedelta(hours=7)
    with session_scope() as s:
        _cand(s, "DRAIN", t0, 1.0, {})
        s.add(Snapshot(mint="DRAIN", ts=t0 + timedelta(minutes=30), price_usd=0.7, liquidity_usd=5_000))
    learning.label_rugs()
    with session_scope() as s:
        assert s.query(Candidate).one().rug is True


def test_young_candidate_without_crash_stays_unlabeled(fresh_db):
    t0 = utcnow() - timedelta(minutes=30)
    with session_scope() as s:
        _cand(s, "YOUNG", t0, 1.0, {})
        s.add(Snapshot(mint="YOUNG", ts=t0 + timedelta(minutes=20), price_usd=1.1, liquidity_usd=50_000))
    learning.label_rugs()
    with session_scope() as s:
        assert s.query(Candidate).one().rug is None  # orizzonte non concluso: nessuna etichetta


def test_model_learns_pump_profile_and_filters(fresh_db):
    _seed()
    learning.update()
    pumped = {"vol_liq_h1": 7.0, "buy_ratio_h1": 0.9, "chg_h6": 250, "holders": 2600}
    healthy = {"vol_liq_h1": 0.7, "buy_ratio_h1": 0.62, "chg_h6": 15, "holders": 2600}
    p_bad, why = learning.rug_probability(pumped)
    p_good, _ = learning.rug_probability(healthy)
    assert p_bad > 0.8 and p_good < 0.2
    assert any("volume 1h / liquidità" in w for w in why)
    assert learning.learned_filter(pumped, None)
    assert learning.learned_filter(healthy, None) == []


def test_filter_inactive_with_few_data(fresh_db):
    _seed(2, 2)
    learning.update()
    assert learning.rug_probability({"vol_liq_h1": 7.0})[0] is None


def test_creator_blacklist(fresh_db):
    _seed(3, 3)
    learning.label_rugs()
    learning._creators_cache = None
    assert "CREATOR1" in learning.rug_creators()
    assert any("blacklist" in r for r in learning.learned_filter({}, "CREATOR1"))
    assert learning.learned_filter({}, "SCONOSCIUTO") == []


def test_migration_adds_new_columns(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE candidates (id INTEGER PRIMARY KEY, mint VARCHAR(64), ts DATETIME, passed_filters BOOLEAN, status VARCHAR(16))")
    con.commit()
    con.close()
    init_db(f"sqlite:///{db}")
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(candidates)")}
    assert {"rug", "rug_at", "features"} <= cols


def test_dump_label_short_horizon(fresh_db):
    t0 = utcnow() - timedelta(hours=2)
    with session_scope() as s:
        _cand(s, "DIP", t0, 1.0, {})
        s.add(Snapshot(mint="DIP", ts=t0 + timedelta(minutes=10), price_usd=0.75, liquidity_usd=45_000))  # -25%: stop loss
        s.add(Snapshot(mint="DIP", ts=t0 + timedelta(minutes=50), price_usd=1.05, liquidity_usd=50_000))
    learning.label_rugs()
    with session_scope() as s:
        c = s.query(Candidate).one()
        assert c.rug is False and c.dump is True


def test_short_horizon_outcomes(fresh_db):
    from solbot.evaluator import evaluate_candidates

    t0 = utcnow() - timedelta(minutes=70)
    with session_scope() as s:
        _cand(s, "FAST", t0, 1.0, {})
        for mins, p in ((5, 1.1), (15, 1.3), (30, 0.9), (60, 0.8)):
            s.add(Snapshot(mint="FAST", ts=t0 + timedelta(minutes=mins, seconds=30), price_usd=p, liquidity_usd=50_000))
    evaluate_candidates()
    with session_scope() as s:
        c = s.query(Candidate).one()
        assert (round(c.ret_5m), round(c.ret_15m), round(c.ret_30m), round(c.ret_1h)) == (10, 30, -10, -20)
        assert round(c.max_ret_1h) == 30 and round(c.min_ret_1h) == -20
