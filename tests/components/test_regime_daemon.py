from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from components.regime_daemon import (
    RegimeDaemonStates,
    build_sinks,
    fetch_latest_returns,
    run_loop,
    run_once,
)
from regime.config import RegimeConfig
from regime.funding_state import FundingStateConfig
from regime.store import RegimeStateStore, build_snapshot
from regime.vol_state import VolStateConfig

DAY_MS = 24 * 60 * 60 * 1000
START_MS = 1_700_000_000_000  # ancoraggio arbitrario, solo per avere timestamp crescenti


def make_candles(n: int, daily_return: float, start_close: float = 100.0) -> list[list]:
    """Genera n+1 candele con rendimento giornaliero COSTANTE `daily_return`
    — con `ewm(adjust=False)` la media EWM di una serie costante è quella
    stessa costante fin dal primo valore, quindi il vol risultante è
    deterministico e prevedibile (utile per test che devono attraversare
    soglie precise senza dipendere da rumore)."""
    candles = []
    close = start_close
    for i in range(n + 1):
        ts = START_MS + i * DAY_MS
        candles.append([ts, close, close, close, close, 1000.0])
        close = close * (1 + daily_return)
    return candles


def vol_for_daily_return(daily_return: float) -> float:
    return abs(daily_return) * math.sqrt(365)


class FakeExchange:
    def __init__(self, candles_by_symbol: dict[str, list[list]]) -> None:
        self._candles_by_symbol = candles_by_symbol
        self.calls: list[tuple[str, str, int]] = []

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        self.calls.append((symbol, timeframe, limit))
        return self._candles_by_symbol[symbol]


class FailingExchange:
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]:
        raise ConnectionError("OKX non raggiungibile")


class FakeFundingSource:
    def __init__(self, rate: float) -> None:
        self._rate = rate
        self.calls: list[str] = []

    def fetch(self, asset: str) -> float:
        self.calls.append(asset)
        return self._rate


REGIME_CONFIG = RegimeConfig(
    vol_by_asset={
        "BTC": VolStateConfig(ewma_span=32, enter_threshold=0.8711, exit_threshold=0.5940),
        "ETH": VolStateConfig(ewma_span=32, enter_threshold=0.9990, exit_threshold=0.8301),
    },
    funding_by_asset={
        "ETH": FundingStateConfig(enter_threshold=0.0005, exit_threshold=0.0002),
    },
)

NOW = datetime(2026, 7, 6, 12, 0, 0)


def test_fetch_latest_returns_calls_exchange_with_asset_usdt_symbol_and_daily_timeframe():
    exchange = FakeExchange({"BTC/USDT": make_candles(200, 0.01)})
    returns = fetch_latest_returns(exchange, "BTC", limit=200)
    assert exchange.calls == [("BTC/USDT", "1d", 200)]
    assert len(returns) == 200  # 201 candele -> 200 rendimenti dopo pct_change().dropna()


def test_fetch_latest_returns_raises_when_exchange_returns_far_fewer_candles_than_requested():
    """Finding review indipendente (5): se OKX restituisce silenziosamente
    molte meno candele del richiesto (endpoint parziale, nuovo listing,
    downtime), un vol calcolato su pochissimi punti verrebbe confrontato
    con soglie calibrate su ~200 punti senza che nessuno se ne accorga —
    stesso tipo di guardia gia' presente in compute_ewma_vol per il caso
    zero-candele, estesa al caso "poche candele"."""
    exchange = FakeExchange({"BTC/USDT": make_candles(5, 0.01)})
    with pytest.raises(ValueError, match="candele insufficienti"):
        fetch_latest_returns(exchange, "BTC", limit=200)


def test_run_once_updates_states_and_persists_snapshot(tmp_path):
    high_return = 0.06  # vol ~= 0.06*sqrt(365) = 1.146, sopra enter BTC (0.8711) ed ETH (0.9990)
    exchange = FakeExchange(
        {
            "BTC/USDT": make_candles(200, high_return),
            "ETH/USDT": make_candles(200, high_return),
        }
    )
    funding_source = FakeFundingSource(rate=0.0006)  # sopra enter ETH funding (0.0005)
    store = RegimeStateStore(tmp_path)
    states = RegimeDaemonStates.seeded_from(
        build_snapshot(False, False, False, now=NOW), REGIME_CONFIG
    )

    snapshot = run_once(exchange, funding_source, states, store, now=NOW)

    assert snapshot.btc_high_vol is True
    assert snapshot.eth_high_vol is True
    assert snapshot.eth_harvester_on is True
    persisted = store.read()
    assert persisted == snapshot


def test_run_once_propagates_fetch_failure_without_writing_snapshot(tmp_path):
    store = RegimeStateStore(tmp_path)
    states = RegimeDaemonStates.seeded_from(
        build_snapshot(False, False, False, now=NOW), REGIME_CONFIG
    )
    with pytest.raises(ConnectionError):
        run_once(FailingExchange(), FakeFundingSource(0.0), states, store, now=NOW)
    assert store.read() is None, "un ciclo fallito non deve scrivere nessuno snapshot"


def test_run_loop_seeds_states_from_persisted_snapshot_on_restart(tmp_path):
    """Contratto di riavvio (ADR-037 §10): il daemon deve chiamare
    resolve_initial_snapshot, non ripartire da False. Uso un rendimento che
    produce un vol nella banda morta di isteresi BTC (tra exit=0.5940 e
    enter=0.8711): se lo stato fosse seminato da True (persistito), resta
    True; se (per bug) ripartisse da False, resterebbe False. Questo
    distingue in modo inequivocabile le due implementazioni."""
    dead_band_return = 0.035  # vol = 0.035*sqrt(365) = 0.6687, tra 0.5940 e 0.8711
    assert 0.5940 < vol_for_daily_return(dead_band_return) < 0.8711

    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(True, False, False, now=NOW - timedelta(hours=1)))

    exchange = FakeExchange(
        {
            "BTC/USDT": make_candles(200, dead_band_return),
            "ETH/USDT": make_candles(200, 0.0),
        }
    )
    funding_source = FakeFundingSource(rate=0.0)
    alerts: list[str] = []
    pings: list[int] = []

    class RecordingAlertSink:
        def send(self, text: str) -> None:
            alerts.append(text)

    class RecordingHealthcheckSink:
        def ping(self) -> None:
            pings.append(1)

    run_loop(
        exchange,
        funding_source,
        store,
        REGIME_CONFIG,
        poll_interval=timedelta(minutes=15),
        alert_sink=RecordingAlertSink(),
        healthcheck_sink=RecordingHealthcheckSink(),
        max_iterations=1,
        sleep_fn=lambda seconds: None,
        now_fn=lambda: NOW,
    )

    persisted = store.read()
    assert persisted.btc_high_vol is True, (
        "il daemon non ha seminato lo stato dallo snapshot persistito: un valore in banda morta "
        "e' rimasto/tornato a False, come se resolve_initial_snapshot non fosse mai stato chiamato"
    )


def test_run_loop_alerts_and_continues_on_cycle_failure_without_pinging(tmp_path):
    store = RegimeStateStore(tmp_path)
    alerts: list[str] = []
    pings: list[int] = []

    class RecordingAlertSink:
        def send(self, text: str) -> None:
            alerts.append(text)

    class RecordingHealthcheckSink:
        def ping(self) -> None:
            pings.append(1)

    run_loop(
        FailingExchange(),
        FakeFundingSource(0.0),
        store,
        REGIME_CONFIG,
        poll_interval=timedelta(minutes=15),
        alert_sink=RecordingAlertSink(),
        healthcheck_sink=RecordingHealthcheckSink(),
        max_iterations=2,
        sleep_fn=lambda seconds: None,
        now_fn=lambda: NOW,
    )

    assert len(alerts) == 2, "ogni ciclo fallito deve generare un alert"
    assert "LAYER CIECO" in alerts[0]
    assert pings == [], "nessun ping healthcheck su un ciclo fallito (VIVO-MA-CIECO)"


def test_run_loop_pings_healthcheck_only_on_successful_cycles(tmp_path):
    store = RegimeStateStore(tmp_path)
    exchange = FakeExchange(
        {"BTC/USDT": make_candles(200, 0.0), "ETH/USDT": make_candles(200, 0.0)}
    )
    pings: list[int] = []

    class RecordingAlertSink:
        def send(self, text: str) -> None:
            pass

    class RecordingHealthcheckSink:
        def ping(self) -> None:
            pings.append(1)

    run_loop(
        exchange,
        FakeFundingSource(0.0),
        store,
        REGIME_CONFIG,
        poll_interval=timedelta(minutes=15),
        alert_sink=RecordingAlertSink(),
        healthcheck_sink=RecordingHealthcheckSink(),
        max_iterations=3,
        sleep_fn=lambda seconds: None,
        now_fn=lambda: NOW,
    )

    assert len(pings) == 3


def test_build_sinks_returns_dry_run_pair_when_dry_run_true():
    from alerting.sinks import DryRunAlertSink, DryRunHealthcheckSink

    alert_sink, healthcheck_sink = build_sinks(
        dry_run=True, bot_token=None, chat_id=None, healthchecks_url=None
    )
    assert isinstance(alert_sink, DryRunAlertSink)
    assert isinstance(healthcheck_sink, DryRunHealthcheckSink)


def test_build_sinks_returns_real_pair_when_dry_run_false_with_all_credentials():
    from alerting.sinks import HealthchecksPingSink, TelegramAlertSink

    alert_sink, healthcheck_sink = build_sinks(
        dry_run=False,
        bot_token="TOKEN",
        chat_id="CHAT",
        healthchecks_url="https://hc-ping.com/x",
    )
    assert isinstance(alert_sink, TelegramAlertSink)
    assert isinstance(healthcheck_sink, HealthchecksPingSink)


@pytest.mark.parametrize(
    "bot_token,chat_id,healthchecks_url",
    [
        (None, "CHAT", "https://hc-ping.com/x"),
        ("TOKEN", None, "https://hc-ping.com/x"),
        ("TOKEN", "CHAT", None),
    ],
)
def test_build_sinks_raises_when_real_mode_missing_any_credential(
    bot_token, chat_id, healthchecks_url
):
    with pytest.raises(ValueError):
        build_sinks(
            dry_run=False,
            bot_token=bot_token,
            chat_id=chat_id,
            healthchecks_url=healthchecks_url,
        )


def test_run_loop_survives_when_alert_sink_itself_fails_during_cycle_failure(tmp_path):
    """Finding review indipendente (1): se alert_sink.send() fallisce
    DENTRO l'except (es. rete VPS giu': OKX e Telegram irraggiungibili
    insieme), il loop non deve propagare quell'eccezione — altrimenti il
    pattern VIVO-MA-CIECO diventa MORTO-E-MUTO, esattamente il rischio
    dichiarato in ADR-037 8 ma non ancora chiuso nel codice."""
    store = RegimeStateStore(tmp_path)

    class FailingAlertSink:
        def send(self, text: str) -> None:
            raise TimeoutError("anche Telegram e' irraggiungibile")

    class RecordingHealthcheckSink:
        def ping(self) -> None:
            pass

    run_loop(
        FailingExchange(),
        FakeFundingSource(0.0),
        store,
        REGIME_CONFIG,
        poll_interval=timedelta(minutes=15),
        alert_sink=FailingAlertSink(),
        healthcheck_sink=RecordingHealthcheckSink(),
        max_iterations=2,
        sleep_fn=lambda seconds: None,
        now_fn=lambda: NOW,
    )
    # se arriviamo qui senza eccezione propagata, il loop e' sopravvissuto


def test_run_loop_sleeps_between_iterations_but_not_after_the_last():
    class NullAlertSink:
        def send(self, text: str) -> None:
            pass

    class NullHealthcheckSink:
        def ping(self) -> None:
            pass

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = RegimeStateStore(tmp)
        exchange = FakeExchange(
            {"BTC/USDT": make_candles(200, 0.0), "ETH/USDT": make_candles(200, 0.0)}
        )
        sleep_calls: list[float] = []
        run_loop(
            exchange,
            FakeFundingSource(0.0),
            store,
            REGIME_CONFIG,
            poll_interval=timedelta(minutes=15),
            alert_sink=NullAlertSink(),
            healthcheck_sink=NullHealthcheckSink(),
            max_iterations=3,
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            now_fn=lambda: NOW,
        )
        assert sleep_calls == [900.0, 900.0], "atteso sleep tra i cicli, non dopo l'ultimo"
