from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from components.history_collector import (
    ALIVE_BUT_BLIND_THRESHOLD,
    HistoryStore,
    build_sinks,
    compute_derived_fields,
    is_alive_but_blind,
    run_loop,
    run_once,
)
from components.regime_wiring import GridBtcCommand, HarvesterCommand
from components.wiring_sequencer import AlertCategory, RateLimitPolicy, WiringSequencer
from regime.store import RegimeSnapshot, RegimeStateStore, build_snapshot

NOW = datetime(2026, 7, 7, 12, 0, 0)


def _sequencer() -> WiringSequencer:
    return WiringSequencer(rate_limit=RateLimitPolicy(window=timedelta(hours=1), max_transitions=3))


# --- HistoryStore --------------------------------------------------------


def test_init_schema_creates_regime_history_and_meta_tables(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    tables = {
        row[0]
        for row in store._conn.execute(  # noqa: SLF001 - verifica strutturale in test
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "regime_history" in tables
    assert "_meta" in tables


def test_insert_snapshot_row_first_time_returns_true_and_is_queryable(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    snapshot = RegimeSnapshot(
        timestamp="2026-07-07T12:00:00Z",
        btc_high_vol=False,
        eth_high_vol=True,
        eth_harvester_on=True,
    )
    derived = compute_derived_fields(snapshot, _sequencer(), now=NOW)

    inserted = store.insert_snapshot_row(snapshot, collected_at=NOW, derived=derived)

    assert inserted is True
    row = store._conn.execute(  # noqa: SLF001
        "SELECT btc_high_vol, eth_high_vol, eth_harvester_on, derived_harvester_command "
        "FROM regime_history WHERE snapshot_timestamp = ?",
        (snapshot.timestamp,),
    ).fetchone()
    assert row == (0, 1, 1, "defensive")


def test_insert_snapshot_row_same_timestamp_twice_dedupes_and_returns_false(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    snapshot = build_snapshot(False, False, True, now=NOW)
    derived = compute_derived_fields(snapshot, _sequencer(), now=NOW)

    first = store.insert_snapshot_row(snapshot, collected_at=NOW, derived=derived)
    second = store.insert_snapshot_row(
        snapshot, collected_at=NOW + timedelta(minutes=5), derived=derived
    )

    assert first is True
    assert second is False
    count = store._conn.execute("SELECT COUNT(*) FROM regime_history").fetchone()[0]  # noqa: SLF001
    assert count == 1


def test_record_collection_start_is_idempotent_keeps_first_value(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    first_time = datetime(2026, 7, 7, 8, 0, 0)
    later_time = datetime(2026, 7, 7, 9, 0, 0)

    store.record_collection_start(first_time)
    store.record_collection_start(later_time)

    assert store.collection_started_at() == first_time


def test_last_new_row_at_is_none_before_any_insert(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    assert store.last_new_row_at() is None


def test_last_new_row_at_updates_only_on_genuine_new_insert(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    snap1 = build_snapshot(False, False, True, now=NOW)
    derived = compute_derived_fields(snap1, _sequencer(), now=NOW)
    store.insert_snapshot_row(snap1, collected_at=NOW, derived=derived)
    assert store.last_new_row_at() == NOW

    later = NOW + timedelta(minutes=5)
    store.insert_snapshot_row(snap1, collected_at=later, derived=derived)  # dedup, stesso timestamp
    assert store.last_new_row_at() == NOW  # non aggiornato dal dedup


# --- compute_derived_fields (osservazione stateless via componenti pure) --


def test_compute_derived_fields_labels_defensive_and_alert():
    snapshot = build_snapshot(False, True, True, now=NOW)
    derived = compute_derived_fields(snapshot, _sequencer(), now=NOW)
    assert derived.harvester_command == HarvesterCommand.DEFENSIVE.value
    assert derived.gridbtc_command == GridBtcCommand.NORMAL.value
    assert derived.alert is True
    assert derived.alert_category == AlertCategory.LAYER_LAVORA_DIFENSIVA.value
    assert "LAYER LAVORA" in derived.alert_text


def test_compute_derived_fields_no_alert_on_quiet_normal_state():
    snapshot = build_snapshot(False, False, True, now=NOW)
    derived = compute_derived_fields(snapshot, _sequencer(), now=NOW)
    assert derived.alert is False
    assert derived.alert_category is None
    assert derived.alert_text is None


# --- is_alive_but_blind (pura) --------------------------------------------


def test_is_alive_but_blind_false_within_threshold():
    reference = NOW
    now = NOW + timedelta(minutes=30)
    assert is_alive_but_blind(reference, now, timedelta(minutes=60)) is False


def test_is_alive_but_blind_true_beyond_threshold():
    reference = NOW
    now = NOW + timedelta(minutes=61)
    assert is_alive_but_blind(reference, now, timedelta(minutes=60)) is True


# --- run_once --------------------------------------------------------------


def test_run_once_returns_false_when_no_snapshot_ever_written(tmp_path):
    regime_store = RegimeStateStore(tmp_path / "regime")
    history = HistoryStore(tmp_path / "history.db")
    assert run_once(regime_store, history, _sequencer(), now=NOW) is False


def test_run_once_inserts_row_from_real_snapshot(tmp_path):
    regime_store = RegimeStateStore(tmp_path / "regime")
    regime_store.write(build_snapshot(True, False, False, now=NOW))
    history = HistoryStore(tmp_path / "history.db")

    inserted = run_once(regime_store, history, _sequencer(), now=NOW)

    assert inserted is True
    count = history._conn.execute("SELECT COUNT(*) FROM regime_history").fetchone()[0]  # noqa: SLF001
    assert count == 1


# --- run_loop ----------------------------------------------------------------


class RecordingAlertSink:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


class RecordingHealthcheckSink:
    def __init__(self) -> None:
        self.ping_count = 0

    def ping(self) -> None:
        self.ping_count += 1


class FailingRegimeStore:
    def read(self):
        raise RuntimeError("disco non leggibile")


def test_run_loop_pings_on_successful_cycles(tmp_path):
    regime_store = RegimeStateStore(tmp_path / "regime")
    regime_store.write(build_snapshot(False, False, True, now=NOW))
    history = HistoryStore(tmp_path / "history.db")
    healthcheck_sink = RecordingHealthcheckSink()

    run_loop(
        regime_store,
        history,
        _sequencer(),
        RecordingAlertSink(),
        healthcheck_sink,
        poll_interval=timedelta(minutes=5),
        max_iterations=3,
        sleep_fn=lambda s: None,
        now_fn=lambda: NOW,
    )

    assert healthcheck_sink.ping_count == 3


def test_run_loop_alerts_and_continues_without_pinging_on_cycle_failure(tmp_path):
    history = HistoryStore(tmp_path / "history.db")
    alert_sink = RecordingAlertSink()
    healthcheck_sink = RecordingHealthcheckSink()

    run_loop(
        FailingRegimeStore(),
        history,
        _sequencer(),
        alert_sink,
        healthcheck_sink,
        poll_interval=timedelta(minutes=5),
        max_iterations=2,
        sleep_fn=lambda s: None,
        now_fn=lambda: NOW,
    )

    assert len(alert_sink.sent) == 2
    assert "COLLECTOR GUASTO" in alert_sink.sent[0]
    assert healthcheck_sink.ping_count == 0


def test_run_loop_survives_when_alert_sink_fails_during_cycle_failure(tmp_path):
    history = HistoryStore(tmp_path / "history.db")

    class FailingAlertSink:
        def send(self, text: str) -> None:
            raise TimeoutError("Telegram irraggiungibile")

    run_loop(
        FailingRegimeStore(),
        history,
        _sequencer(),
        FailingAlertSink(),
        RecordingHealthcheckSink(),
        poll_interval=timedelta(minutes=5),
        max_iterations=2,
        sleep_fn=lambda s: None,
        now_fn=lambda: NOW,
    )
    # se arriviamo qui senza eccezione propagata, il loop e' sopravvissuto


def test_run_loop_fires_alive_but_blind_and_skips_ping_when_history_stalls(tmp_path):
    """Il processo 'gira bene' (nessuna eccezione, snapshot invariato quindi
    dedup legittimo) ma la storia non cresce da piu' della soglia -> deve
    allertare (non con lo stesso testo di un ciclo fallito) e NON pingare,
    anche se il ciclo stesso non e' fallito."""
    regime_store = RegimeStateStore(tmp_path / "regime")
    regime_store.write(build_snapshot(False, False, True, now=NOW))
    history = HistoryStore(tmp_path / "history.db")
    alert_sink = RecordingAlertSink()
    healthcheck_sink = RecordingHealthcheckSink()

    # Prima riga inserita a NOW; poi tick molto oltre la soglia di 60 min
    # senza che lo snapshot cambi mai -> nessuna nuova riga -> alive-but-blind.
    later = NOW + timedelta(minutes=61)

    run_loop(
        regime_store,
        history,
        _sequencer(),
        alert_sink,
        healthcheck_sink,
        poll_interval=timedelta(minutes=5),
        alive_but_blind_threshold=timedelta(minutes=60),
        max_iterations=1,
        sleep_fn=lambda s: None,
        now_fn=lambda: NOW,
    )
    # riga 1 inserita, no anomalia ancora
    assert healthcheck_sink.ping_count == 1
    assert alert_sink.sent == []

    run_loop(
        regime_store,
        history,
        _sequencer(),
        alert_sink,
        healthcheck_sink,
        poll_interval=timedelta(minutes=5),
        alive_but_blind_threshold=timedelta(minutes=60),
        max_iterations=1,
        sleep_fn=lambda s: None,
        now_fn=lambda: later,
    )

    assert healthcheck_sink.ping_count == 1  # non incrementato: anomalia -> no ping
    assert len(alert_sink.sent) == 1
    assert "STORIA FERMA" in alert_sink.sent[0]


# --- build_sinks (stesso contratto degli altri due entrypoint) -------------


def test_build_sinks_dry_run_ignores_env():
    from alerting.sinks import DryRunAlertSink, DryRunHealthcheckSink

    alert_sink, healthcheck_sink = build_sinks(dry_run=True, env={})
    assert isinstance(alert_sink, DryRunAlertSink)
    assert isinstance(healthcheck_sink, DryRunHealthcheckSink)


def test_build_sinks_reads_from_env_not_argv():
    from alerting.sinks import HealthchecksPingSink, TelegramAlertSink

    env = {
        "TG_ALERT_BOT_TOKEN": "TOKEN123",
        "TG_ALERT_CHAT_ID": "CHAT456",
        "HEALTHCHECKS_PING_URL_HISTORY_COLLECTOR": "https://hc-ping.com/z",
    }
    alert_sink, healthcheck_sink = build_sinks(dry_run=False, env=env)
    assert isinstance(alert_sink, TelegramAlertSink)
    assert isinstance(healthcheck_sink, HealthchecksPingSink)
    assert alert_sink._bot_token == "TOKEN123"  # noqa: SLF001
    assert healthcheck_sink._url == "https://hc-ping.com/z"  # noqa: SLF001


def test_build_sinks_raises_naming_missing_variable():
    with pytest.raises(ValueError, match="HEALTHCHECKS_PING_URL_HISTORY_COLLECTOR"):
        build_sinks(dry_run=False, env={"TG_ALERT_BOT_TOKEN": "T", "TG_ALERT_CHAT_ID": "C"})


def test_default_alive_but_blind_threshold_is_60_minutes():
    assert ALIVE_BUT_BLIND_THRESHOLD == timedelta(minutes=60)
