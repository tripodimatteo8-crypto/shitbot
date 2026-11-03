import json
from datetime import datetime

import pytest

from solbot import config, db
from solbot.providers.base import DataProvider, MarketData, Quote, SecurityData
from solbot.providers.composite import set_provider


class FakeProvider(DataProvider):
    def __init__(self):
        self.price = {"MINT": 0.001}
        self.impact = 0.02
        self.sell_route = True

    def discover(self):
        return {}

    def market_data(self, mints):
        return {m: MarketData(mint=m, price_usd=self.price.get(m), liquidity_usd=50_000) for m in mints if m in self.price}

    def security(self, mint):
        return SecurityData(mint=mint, decimals=6)

    def sol_price_usd(self):
        return 100.0

    def quote_buy(self, mint, usd, decimals):
        return Quote(usd, usd / self.price[mint] * (1 - self.impact), self.impact * 100, "jupiter")

    def quote_sell(self, mint, qty, decimals):
        if not self.sell_route:
            return None
        return Quote(qty, qty * self.price[mint] * (1 - self.impact), self.impact * 100, "jupiter")


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config.env, "kill_file", tmp_path / "KILL")
    monkeypatch.setattr(config.env, "lessons_path", tmp_path / "lezioni.md")
    db.init_db(f"sqlite:///{tmp_path / 'test.db'}")
    with db.session_scope() as s:
        s.add(db.Setting(key="execution_delay_s", value=json.dumps(0)))
    config.invalidate_cache()
    from solbot import learning

    learning._model = None
    learning._creators_cache = None
    prov = FakeProvider()
    set_provider(prov)
    yield prov
    config.invalidate_cache()
    set_provider(None)


@pytest.fixture()
def now():
    return datetime(2026, 11, 3, 12, 0, 0)
