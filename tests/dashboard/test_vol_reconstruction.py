from __future__ import annotations

import math

from dashboard.vol_reconstruction import VolSeries, reconstruct_vol_series
from regime.config import RegimeConfig
from regime.funding_state import FundingStateConfig
from regime.vol_state import VolStateConfig

DAY_MS = 24 * 60 * 60 * 1000
START_MS = 1_700_000_000_000


def make_candles(n: int, daily_return: float, start_close: float = 100.0) -> list[list]:
    candles = []
    close = start_close
    for i in range(n + 1):
        ts = START_MS + i * DAY_MS
        candles.append([ts, close, close, close, close, 1000.0])
        close = close * (1 + daily_return)
    return candles


class FakeExchange:
    def __init__(self, candles_by_symbol: dict[str, list[list]]) -> None:
        self._candles_by_symbol = candles_by_symbol
        self.calls: list[tuple[str, str, int]] = []

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        self.calls.append((symbol, timeframe, limit))
        return self._candles_by_symbol[symbol]


REGIME_CONFIG = RegimeConfig(
    vol_by_asset={
        "BTC": VolStateConfig(ewma_span=32, enter_threshold=0.8711, exit_threshold=0.5940),
        "ETH": VolStateConfig(ewma_span=32, enter_threshold=0.9990, exit_threshold=0.8301),
    },
    funding_by_asset={
        "ETH": FundingStateConfig(enter_threshold=0.0005, exit_threshold=0.0002),
    },
)


def test_reconstruct_vol_series_reuses_fetch_latest_returns_and_compute_ewma_vol():
    exchange = FakeExchange({"BTC/USDT": make_candles(200, 0.01)})

    series = reconstruct_vol_series(exchange, "BTC", REGIME_CONFIG, limit=200)

    assert isinstance(series, VolSeries)
    assert series.asset == "BTC"
    assert exchange.calls == [("BTC/USDT", "1d", 200)]
    assert len(series.vol) == 200
    # rendimento costante 0.01 -> vol EWMA costante = 0.01*sqrt(365) fin dal primo punto
    # (proprieta' di ewm(adjust=False) su serie costante, gia' usata altrove nei test)
    expected_vol = 0.01 * math.sqrt(365)
    assert abs(series.vol.iloc[-1] - expected_vol) < 1e-9


def test_reconstruct_vol_series_carries_thresholds_from_regime_config():
    exchange = FakeExchange({"ETH/USDT": make_candles(200, 0.0)})

    series = reconstruct_vol_series(exchange, "ETH", REGIME_CONFIG, limit=200)

    assert series.enter_threshold == 0.9990
    assert series.exit_threshold == 0.8301


def test_reconstruct_vol_series_uses_ewma_span_from_regime_config_not_hardcoded():
    """Verifica diretta per confronto con una computazione di riferimento
    (compute_ewma_vol chiamata a mano con lo stesso span) — una serie a
    rendimento costante non basta (l'EWM con adjust=False converge alla
    stessa costante fin dal primo punto indipendentemente dallo span),
    quindi uso due blocchi di rendimento diverso: uno shock che span
    diversi assorbono a velocita' visibilmente diversa."""
    from regime.vol_state import compute_ewma_vol

    candles = make_candles(50, 0.005) + make_candles(50, 0.03, start_close=100 * 1.005**50)[1:]
    exchange = FakeExchange({"BTC/USDT": candles})
    custom_config = RegimeConfig(
        vol_by_asset={"BTC": VolStateConfig(ewma_span=5, enter_threshold=1.0, exit_threshold=0.5)},
        funding_by_asset={},
    )

    series = reconstruct_vol_series(exchange, "BTC", custom_config, limit=len(candles))

    from components.regime_daemon import fetch_latest_returns

    reference_returns = fetch_latest_returns(exchange, "BTC", limit=len(candles))
    reference_vol = compute_ewma_vol(reference_returns, span=5)

    assert series.vol.equals(reference_vol)
