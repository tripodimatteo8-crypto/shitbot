"""Provider composito: DexScreener + RugCheck + Jupiter. Sostituibile con GMGN/Birdeye/Helius."""
from __future__ import annotations

from .base import DataProvider, MarketData, Quote, SecurityData
from .dexscreener import DexScreener
from .jupiter import Jupiter
from .rugcheck import RugCheck


class CompositeProvider(DataProvider):
    def __init__(self):
        self.dex = DexScreener()
        self.rug = RugCheck()
        self.jup = Jupiter()

    def discover(self) -> dict[str, set[str]]:
        return self.dex.discover()

    def market_data(self, mints: list[str]) -> dict[str, MarketData]:
        return self.dex.market_data(mints)

    def security(self, mint: str) -> SecurityData | None:
        return self.rug.security(mint)

    def sol_price_usd(self) -> float | None:
        return self.jup.sol_price_usd()

    def quote_buy(self, mint: str, usd: float, decimals: int) -> Quote | None:
        return self.jup.quote_buy(mint, usd, decimals)

    def quote_sell(self, mint: str, qty: float, decimals: int) -> Quote | None:
        return self.jup.quote_sell(mint, qty, decimals)


_provider: DataProvider | None = None


def get_provider() -> DataProvider:
    global _provider
    if _provider is None:
        _provider = CompositeProvider()
    return _provider


def set_provider(p: DataProvider) -> None:
    """Per i test o per cambiare fonte a runtime."""
    global _provider
    _provider = p
