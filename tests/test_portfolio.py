from solbot.db import Account, Fill, Position, session_scope
from solbot.execution.paper import PaperEngine
from solbot.portfolio import close_position, ensure_account, equity, open_position


def test_paper_buy_costs_are_charged(fresh_db):
    fill = PaperEngine(sleep=lambda s: None).buy("MINT", 50, 6, 0.001, 50_000)
    assert fill.ok and fill.quote_source == "jupiter"
    # prezzo effettivo peggiore del mercato: impatto 2% + MEV 1% + fee
    assert fill.price_eff > 0.001 * 1.03
    assert fill.fees_usd > 50 * 0.0025  # fee aggregatore + priority fee


def test_round_trip_loses_money_at_flat_price(fresh_db):
    with session_scope() as s:
        ensure_account(s)
    ok, msg, pid = open_position("MINT", 40, None, "test", None, ref_price=0.001, liquidity=50_000)
    assert ok, msg
    with session_scope() as s:
        acc = s.get(Account, 1)
        assert abs(acc.cash_usd - (1000 - 40)) < 1e-6
    ok, msg = close_position(pid, "test")
    assert ok, msg
    with session_scope() as s:
        p = s.get(Position, pid)
        acc = s.get(Account, 1)
        assert p.status == "closed" and p.pnl_usd < 0
        # prezzo invariato: perdita = costi di round-trip, plausibile tra 3% e 12%
        assert -12 < p.pnl_pct < -3
        assert abs(acc.cash_usd - (960 + p.proceeds_usd)) < 1e-6
        assert s.query(Fill).count() == 2


def test_profit_when_price_rises(fresh_db):
    with session_scope() as s:
        ensure_account(s)
    ok, _, pid = open_position("MINT", 40, None, "test", None, ref_price=0.001, liquidity=50_000)
    fresh_db.price["MINT"] = 0.002
    with session_scope() as s:
        s.get(Position, pid).last_price = 0.002
    close_position(pid, "tp")
    with session_scope() as s:
        assert s.get(Position, pid).pnl_pct > 80


def test_rug_sell_without_route_or_price_is_zero(fresh_db):
    with session_scope() as s:
        ensure_account(s)
    _, _, pid = open_position("MINT", 40, None, "test", None, ref_price=0.001, liquidity=50_000)
    fresh_db.sell_route = False
    with session_scope() as s:
        p = s.get(Position, pid)
        p.last_price = None
        p.last_liquidity = 0
    with session_scope() as s:
        s.query(Position).filter(Position.id == pid).update({"last_price": 0})
    close_position(pid, "rug")
    with session_scope() as s:
        assert s.get(Position, pid).pnl_pct <= -99


def test_equity_marks_conservatively(fresh_db):
    with session_scope() as s:
        ensure_account(s)
    open_position("MINT", 40, None, "test", None, ref_price=0.001, liquidity=50_000)
    with session_scope() as s:
        eq, pos_val, opens = equity(s)
        notional = opens[0].qty * opens[0].last_price
        assert pos_val < notional  # valore di liquidazione < nozionale
        assert eq < 1000
