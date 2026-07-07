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


def test_run_loop_fires_alive_but_blind_when_snapshot_never_written(tmp_path):
    """Copertura mancante segnalata dal reviewer: il caso 'nessuno snapshot
    mai scritto' deve comunque far scattare STORIA FERMA oltre soglia, non
    solo il caso 'snapshot invariato'. Verificato empiricamente dal
    reviewer ma senza test dedicato — lo aggiungo qui."""
    regime_store = RegimeStateStore(tmp_path / "regime")  # mai scritto
    history = HistoryStore(tmp_path / "history.db")
    alert_sink = RecordingAlertSink()
    healthcheck_sink = RecordingHealthcheckSink()

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
    assert healthcheck_sink.ping_count == 1  # entro soglia, nessuna riga ancora attesa
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
        now_fn=lambda: NOW + timedelta(minutes=61),
    )
    assert healthcheck_sink.ping_count == 1
    assert len(alert_sink.sent) == 1
    assert "STORIA FERMA" in alert_sink.sent[0]


def test_restart_does_not_inject_spurious_transition_when_state_unchanged(tmp_path):
    """Finding review indipendente (5): un riavvio del collector (nuovo
    WiringSequencer fresco, stesso contratto di wiring_loop) non deve
    iniettare una transizione derived_alert_category SPURIA — e
    PERMANENTE, a differenza di un alert Telegram effimero — in una riga
    persistita, se lo stato di regime non e' davvero cambiato nel
    frattempo. Fix: run_loop 'scalda' il sequencer fresco rileggendo
    l'ultima riga gia' persistita (non tocca WiringSequencer)."""
    regime_store = RegimeStateStore(tmp_path / "regime")
    history = HistoryStore(tmp_path / "history.db")

    # Storia pregressa: gia' in DEFENSIVE, riga gia' scritta da un
    # "collector precedente" (sequencer che ha visto la transizione vera).
    first_snapshot = build_snapshot(False, True, True, now=NOW)
    previous_run_sequencer = _sequencer()
    derived_before = compute_derived_fields(first_snapshot, previous_run_sequencer, now=NOW)
    history.insert_snapshot_row(first_snapshot, collected_at=NOW, derived=derived_before)
    assert derived_before.alert_category == AlertCategory.LAYER_LAVORA_DIFENSIVA.value

    # "Riavvio": stesso stato di regime (ancora DEFENSIVE), sequencer fresco.
    later = NOW + timedelta(minutes=15)
    second_snapshot = build_snapshot(False, True, True, now=later)
    regime_store.write(second_snapshot)
    fresh_sequencer = _sequencer()

    run_loop(
        regime_store,
        history,
        fresh_sequencer,
        RecordingAlertSink(),
        RecordingHealthcheckSink(),
        poll_interval=timedelta(minutes=5),
        max_iterations=1,
        sleep_fn=lambda s: None,
        now_fn=lambda: later,
    )

    row = history._conn.execute(  # noqa: SLF001
        "SELECT derived_alert_category FROM regime_history WHERE snapshot_timestamp = ?",
        (second_snapshot.timestamp,),
    ).fetchone()
    assert row is not None
    assert row[0] is None, "il riavvio ha iniettato una transizione spuria nella storia persistita"


def test_restart_still_detects_genuine_transition_after_warmup(tmp_path):
    """Il warm-up non deve mascherare una transizione VERA avvenuta durante
    il downtime del collector — solo evitare quelle spurie dovute al solo
    riavvio del sequencer."""
    regime_store = RegimeStateStore(tmp_path / "regime")
    history = HistoryStore(tmp_path / "history.db")

    first_snapshot = build_snapshot(False, False, True, now=NOW)  # NORMAL
    derived_before = compute_derived_fields(first_snapshot, _sequencer(), now=NOW)
    history.insert_snapshot_row(first_snapshot, collected_at=NOW, derived=derived_before)
    assert derived_before.alert_category is None

    later = NOW + timedelta(minutes=15)
    second_snapshot = build_snapshot(False, True, True, now=later)  # ora DEFENSIVE per davvero
    regime_store.write(second_snapshot)

    run_loop(
        regime_store,
        history,
        _sequencer(),
        RecordingAlertSink(),
        RecordingHealthcheckSink(),
        poll_interval=timedelta(minutes=5),
        max_iterations=1,
        sleep_fn=lambda s: None,
        now_fn=lambda: later,
    )

    row = history._conn.execute(  # noqa: SLF001
        "SELECT derived_alert_category FROM regime_history WHERE snapshot_timestamp = ?",
        (second_snapshot.timestamp,),
    ).fetchone()
    assert row[0] == AlertCategory.LAYER_LAVORA_DIFENSIVA.value


class _BothAnchorsNoneHistory:
    """Test double: forza `collection_started_at`/`last_new_row_at` a
    restituire sempre `None`, per esercitare il ramo di `run_loop` che
    tratta l'invariante violato — con un `HistoryStore` reale non è
    riproducibile dentro `run_loop`, che lo ripara da solo chiamando
    `record_collection_start` (idempotente) prima di ogni ciclo. Il punto
    del test è verificare la gestione del caso, non la sua plausibilità."""

    def __init__(self, real: HistoryStore) -> None:
        self._real = real

    def record_collection_start(self, now: datetime) -> None:
        self._real.record_collection_start(now)

    def last_new_row_at(self):
        return None

    def collection_started_at(self):
        return None

    def latest_row(self):
        return self._real.latest_row()

    def insert_snapshot_row(self, snapshot, collected_at, derived) -> bool:
        return self._real.insert_snapshot_row(snapshot, collected_at, derived)


def test_alive_but_blind_reference_missing_both_anchors_alerts_instead_of_masking(tmp_path):
    """Finding review indipendente (3): se, dentro il ciclo, sia
    last_new_row_at sia collection_started_at risultano assenti (invariante
    violato), il fallback silenzioso a `now` mascondererebbe l'anomalia
    (età 0, mai allertata). Deve invece allertare esplicitamente, non
    pingare — verificato con un doppio dedicato, vedi
    `_BothAnchorsNoneHistory`."""
    regime_store = RegimeStateStore(tmp_path / "regime")
    regime_store.write(build_snapshot(False, False, True, now=NOW))
    history = _BothAnchorsNoneHistory(HistoryStore(tmp_path / "history.db"))

    alert_sink = RecordingAlertSink()
    healthcheck_sink = RecordingHealthcheckSink()

    run_loop(
        regime_store,
        history,
        _sequencer(),
        alert_sink,
        healthcheck_sink,
        poll_interval=timedelta(minutes=5),
        max_iterations=1,
        sleep_fn=lambda s: None,
        now_fn=lambda: NOW,
    )

    assert healthcheck_sink.ping_count == 0
    assert len(alert_sink.sent) == 1
    assert "COLLECTOR GUASTO" in alert_sink.sent[0]


# --- build_sinks (stesso contratto degli altri due entrypoint) -------------


def test_build_sinks_dry_run_ignores_env():
    from alerting.sinks import DryRunAlertSink, DryRunHealthcheckSink

    alert_sink, healthcheck_sink = build_sinks(dry_run=True, env={})
    assert isinstance(alert_sink, DryRunAlertSink)
    assert isinstance(healthcheck_sink, DryRunHealthcheckSink)


def test_build_sinks_reads_only_healthcheck_url_from_env_no_telegram_token():
    """Privilegio minimo (decisione esplicita al checkpoint di deploy): il
    collector non riceve MAI il token Telegram — una sola variabile reale,
    l'alert_sink reale e' locale (LocalLogAlertSink), non Telegram."""
    from alerting.sinks import HealthchecksPingSink, LocalLogAlertSink

    env = {"HEALTHCHECKS_PING_URL_HISTORY_COLLECTOR": "https://hc-ping.com/z"}
    alert_sink, healthcheck_sink = build_sinks(dry_run=False, env=env)
    assert isinstance(alert_sink, LocalLogAlertSink)
    assert isinstance(healthcheck_sink, HealthchecksPingSink)
    assert healthcheck_sink._url == "https://hc-ping.com/z"  # noqa: SLF001


def test_build_sinks_raises_naming_missing_variable():
    with pytest.raises(ValueError, match="HEALTHCHECKS_PING_URL_HISTORY_COLLECTOR"):
        build_sinks(dry_run=False, env={})


def test_default_alive_but_blind_threshold_is_60_minutes():
    assert ALIVE_BUT_BLIND_THRESHOLD == timedelta(minutes=60)
