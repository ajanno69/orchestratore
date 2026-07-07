from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd
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


def test_run_once_persists_numeric_ewma_vol_values(tmp_path):
    """Prep schema post-gate (Parte 2, 2026-07-07): finding di sessione, il
    valore numerico EWMA vol veniva calcolato ogni ciclo e mai persistito
    (vedi docs/m2-shadow-dashboard-rendering-report-2026-07-07.md §4). Da
    ora lo snapshot lo porta con sé — campo repo-only, deploy solo dopo il
    gate 21/07."""
    daily_return = 0.02
    exchange = FakeExchange(
        {
            "BTC/USDT": make_candles(200, daily_return),
            "ETH/USDT": make_candles(200, daily_return),
        }
    )
    funding_source = FakeFundingSource(rate=0.0001)
    store = RegimeStateStore(tmp_path)
    states = RegimeDaemonStates.seeded_from(
        build_snapshot(False, False, False, now=NOW), REGIME_CONFIG
    )

    snapshot = run_once(exchange, funding_source, states, store, now=NOW)

    expected_vol = vol_for_daily_return(daily_return)
    assert snapshot.btc_ewma_vol is not None
    assert snapshot.eth_ewma_vol is not None
    assert abs(snapshot.btc_ewma_vol - expected_vol) < 1e-9
    assert abs(snapshot.eth_ewma_vol - expected_vol) < 1e-9
    persisted = store.read()
    assert persisted.btc_ewma_vol == snapshot.btc_ewma_vol
    assert persisted.eth_ewma_vol == snapshot.eth_ewma_vol


def test_run_once_never_persists_non_finite_ewma_vol(tmp_path, monkeypatch):
    """Chiude nota minore 1 del reviewer indipendente (Parte 2, review
    041f4fe): un vol NaN/inf calcolato a monte non deve mai finire in
    regime_state.json come token JSON non standard
    (json.dumps(allow_nan=True) di default produrrebbe 'NaN' letterale,
    illeggibile da un parser JSON strict).

    Chiuso per costruzione, non con nuovo codice: VolRegimeState.update()
    già solleva ValueError su un latest_vol non finito (vedi
    regime/vol_state.py), ed è chiamato PRIMA di build_snapshot in
    run_once — un vol non-finito interrompe il ciclo prima che qualunque
    snapshot (coi nuovi campi o senza) venga scritto. Questo test rende
    quell'invariante esplicito e verificato, non solo dedotto leggendo il
    codice."""
    import components.regime_daemon as regime_daemon_module

    def fake_compute_ewma_vol(returns, span):
        return pd.Series([float("nan")], index=returns.index[-1:])

    monkeypatch.setattr(regime_daemon_module, "compute_ewma_vol", fake_compute_ewma_vol)

    exchange = FakeExchange(
        {
            "BTC/USDT": make_candles(200, 0.01),
            "ETH/USDT": make_candles(200, 0.01),
        }
    )
    store = RegimeStateStore(tmp_path)
    states = RegimeDaemonStates.seeded_from(
        build_snapshot(False, False, False, now=NOW), REGIME_CONFIG
    )

    with pytest.raises(ValueError, match="non-finito"):
        run_once(exchange, FakeFundingSource(0.0), states, store, now=NOW)

    assert store.read() is None, "un vol non-finito non deve mai produrre uno snapshot persistito"


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


def test_build_sinks_returns_dry_run_pair_when_dry_run_true_ignoring_env():
    from alerting.sinks import DryRunAlertSink, DryRunHealthcheckSink

    alert_sink, healthcheck_sink = build_sinks(
        dry_run=True, healthchecks_env_var="HEALTHCHECKS_PING_URL_REGIME_DAEMON", env={}
    )
    assert isinstance(alert_sink, DryRunAlertSink)
    assert isinstance(healthcheck_sink, DryRunHealthcheckSink)


def test_build_sinks_reads_credentials_from_env_not_argv():
    """Finding incident deploy (2026-07-07): le credenziali non devono
    MAI passare da un argomento CLI (finiscono in argv, visibili via
    /proc/PID/cmdline) — build_sinks le legge SOLO da un dict env
    iniettato (di norma os.environ), mai da parametri espliciti."""
    from alerting.sinks import HealthchecksPingSink, TelegramAlertSink

    env = {
        "TG_ALERT_BOT_TOKEN": "TOKEN123",
        "TG_ALERT_CHAT_ID": "CHAT456",
        "HEALTHCHECKS_PING_URL_REGIME_DAEMON": "https://hc-ping.com/x",
    }
    alert_sink, healthcheck_sink = build_sinks(
        dry_run=False, healthchecks_env_var="HEALTHCHECKS_PING_URL_REGIME_DAEMON", env=env
    )
    assert isinstance(alert_sink, TelegramAlertSink)
    assert isinstance(healthcheck_sink, HealthchecksPingSink)
    assert alert_sink._bot_token == "TOKEN123"
    assert alert_sink._chat_id == "CHAT456"
    assert healthcheck_sink._url == "https://hc-ping.com/x"


@pytest.mark.parametrize(
    "missing_var",
    ["TG_ALERT_BOT_TOKEN", "TG_ALERT_CHAT_ID", "HEALTHCHECKS_PING_URL_REGIME_DAEMON"],
)
def test_build_sinks_raises_naming_the_missing_variable(missing_var):
    """Mai un avvio mezzo-configurato: se una variabile manca, l'errore
    deve nominarla esplicitamente — non un generico 'credenziali
    mancanti' che costringerebbe a indovinare quale."""
    env = {
        "TG_ALERT_BOT_TOKEN": "TOKEN123",
        "TG_ALERT_CHAT_ID": "CHAT456",
        "HEALTHCHECKS_PING_URL_REGIME_DAEMON": "https://hc-ping.com/x",
    }
    del env[missing_var]
    with pytest.raises(ValueError, match=missing_var):
        build_sinks(
            dry_run=False, healthchecks_env_var="HEALTHCHECKS_PING_URL_REGIME_DAEMON", env=env
        )


def test_build_sinks_raises_listing_all_missing_variables_when_multiple_missing():
    with pytest.raises(ValueError) as exc_info:
        build_sinks(
            dry_run=False, healthchecks_env_var="HEALTHCHECKS_PING_URL_REGIME_DAEMON", env={}
        )
    message = str(exc_info.value)
    assert "TG_ALERT_BOT_TOKEN" in message
    assert "TG_ALERT_CHAT_ID" in message
    assert "HEALTHCHECKS_PING_URL_REGIME_DAEMON" in message


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
