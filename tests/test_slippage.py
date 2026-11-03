from solbot.execution.paper import model_slippage_pct


def test_slippage_grows_with_size():
    small = model_slippage_pct(10, 100_000, 0.0)
    big = model_slippage_pct(5_000, 100_000, 0.0)
    assert 0 < small < big
    # 5000$ su un lato da 50k$: impatto 5000/55000 ≈ 9.1%
    assert abs(big - 9.09) < 0.05


def test_slippage_floor_and_unknown_liquidity():
    assert model_slippage_pct(1, 10_000_000, 1.5) == 1.5
    assert model_slippage_pct(100, None, 1.5) == 50.0
    assert model_slippage_pct(100, 0, 1.5) == 50.0


def test_slippage_falls_with_liquidity():
    assert model_slippage_pct(500, 20_000, 0) > model_slippage_pct(500, 200_000, 0)
