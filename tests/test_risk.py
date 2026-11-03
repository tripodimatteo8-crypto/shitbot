from datetime import timedelta

from solbot.config import Tunables
from solbot.db import Account, Position, session_scope
from solbot.portfolio import ensure_account, open_position
from solbot.risk import check_buy, exit_signal, update_daily_guard


def acc(cash=1000.0):
    return Account(id=1, cash_usd=cash, initial_capital_usd=1000)


def pos(now, entry=1.0, hw=1.0, hours=1):
    return Position(mint="M", status="open", qty=1, cost_usd=1, entry_price_eff=1, entry_price_mkt=entry,
                    high_water_price=hw, opened_at=now - timedelta(hours=hours))


def test_size_capped_to_max_pct():
    t = Tunables()
    r = check_buy(acc(), [], 1000, "M", 500, t)
    assert r.ok and r.usd == 1000 * t.max_position_pct / 100


def test_max_open_positions():
    t = Tunables()
    opens = [Position(mint=f"X{i}") for i in range(t.max_open_positions)]
    assert not check_buy(acc(), opens, 1000, "M", 10, t).ok


def test_no_double_position():
    assert not check_buy(acc(), [Position(mint="M")], 1000, "M", 10, Tunables()).ok


def test_min_size_and_cash():
    assert not check_buy(acc(cash=3), [], 1000, "M", 50, Tunables()).ok


def test_kill_switch_blocks(fresh_db):
    a = acc()
    a.kill_switch = True
    assert "KILL" in check_buy(a, [], 1000, "M", 10, Tunables()).reason


def test_kill_file_blocks(fresh_db):
    from solbot.config import env

    env.kill_file.write_text("stop")
    assert not check_buy(acc(), [], 1000, "M", 10, Tunables()).ok


def test_daily_loss_limit_halts(fresh_db):
    t = Tunables()
    a = acc()
    assert update_daily_guard(a, 1000, t) is None
    assert update_daily_guard(a, 1000 * (1 - (t.daily_loss_limit_pct + 0.5) / 100), t)
    assert not check_buy(a, [], 900, "M", 10, t).ok


def test_exit_signals(now):
    t = Tunables()
    assert "stop loss" in exit_signal(pos(now), 1 - (t.stop_loss_pct + 1) / 100, 50_000, now, t)
    assert "take profit" in exit_signal(pos(now), 1 + (t.take_profit_pct + 1) / 100, 50_000, now, t)
    assert "trailing" in exit_signal(pos(now, hw=1.5), 1.5 * (1 - (t.trailing_stop_pct + 1) / 100), 50_000, now, t)
    assert "tempo" in exit_signal(pos(now, hours=t.max_hold_hours + 1), 1.0, 50_000, now, t)
    assert "liquidità" in exit_signal(pos(now), 1.0, 100, now, t)
    assert exit_signal(pos(now), 1.05, 50_000, now, t) is None


def test_open_position_respects_risk_manager(fresh_db):
    with session_scope() as s:
        ensure_account(s)
    ok, msg, _ = open_position("MINT", 10_000, None, "test", None, ref_price=0.001, liquidity=50_000)
    assert ok
    with session_scope() as s:
        p = s.query(Position).one()
        assert p.cost_usd <= 1000 * Tunables().max_position_pct / 100 + 1e-6
    ok, msg, _ = open_position("MINT", 10, None, "test", None, ref_price=0.001, liquidity=50_000)
    assert not ok and "già aperta" in msg


def test_live_engine_disabled(fresh_db):
    from solbot.execution import PaperEngine, get_engine
    from solbot.execution.live import live_allowed

    ok, why = live_allowed()
    assert not ok
    assert isinstance(get_engine(), PaperEngine)
