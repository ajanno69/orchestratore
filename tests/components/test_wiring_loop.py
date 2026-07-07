from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from components.regime_wiring import GridBtcHighVolAction, StalenessPolicy
from components.wiring_loop import build_sinks, run_loop, run_once
from components.wiring_sequencer import RateLimitPolicy, WiringSequencer
from regime.store import RegimeStateStore, build_snapshot

STALENESS = StalenessPolicy(max_age=timedelta(hours=1))
RATE_LIMIT = RateLimitPolicy(window=timedelta(hours=1), max_transitions=3)
GRIDBTC_ACTION = GridBtcHighVolAction.STOP_NEW_ORDERS
NOW = datetime(2026, 7, 6, 12, 0, 0)


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


class FailingStore:
    def read(self):
        raise RuntimeError("disco non leggibile")


def test_run_once_sends_alert_events_from_sequencer_to_sink(tmp_path):
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(False, True, True, now=NOW))  # ETH high-vol -> DEFENSIVE
    sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
    alert_sink = RecordingAlertSink()

    decision = run_once(store, sequencer, STALENESS, GRIDBTC_ACTION, alert_sink, now=NOW)

    assert decision.harvester_command.value == "defensive"
    assert len(alert_sink.sent) == 1
    assert "LAYER LAVORA" in alert_sink.sent[0]


def test_run_once_sends_nothing_when_no_alert_worthy_transition(tmp_path):
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(False, False, True, now=NOW))
    sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
    alert_sink = RecordingAlertSink()

    run_once(store, sequencer, STALENESS, GRIDBTC_ACTION, alert_sink, now=NOW)
    alert_sink.sent.clear()
    run_once(
        store, sequencer, STALENESS, GRIDBTC_ACTION, alert_sink, now=NOW + timedelta(minutes=5)
    )

    assert alert_sink.sent == []


def test_run_loop_pings_healthcheck_on_successful_cycles(tmp_path):
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(False, False, True, now=NOW))
    sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
    alert_sink = RecordingAlertSink()
    healthcheck_sink = RecordingHealthcheckSink()

    run_loop(
        store,
        sequencer,
        STALENESS,
        GRIDBTC_ACTION,
        alert_sink,
        healthcheck_sink,
        poll_interval=timedelta(minutes=5),
        max_iterations=3,
        sleep_fn=lambda seconds: None,
        now_fn=lambda: NOW,
    )

    assert healthcheck_sink.ping_count == 3


def test_run_loop_alerts_and_continues_without_pinging_on_store_failure():
    alert_sink = RecordingAlertSink()
    healthcheck_sink = RecordingHealthcheckSink()
    sequencer = WiringSequencer(rate_limit=RATE_LIMIT)

    run_loop(
        FailingStore(),
        sequencer,
        STALENESS,
        GRIDBTC_ACTION,
        alert_sink,
        healthcheck_sink,
        poll_interval=timedelta(minutes=5),
        max_iterations=2,
        sleep_fn=lambda seconds: None,
        now_fn=lambda: NOW,
    )

    assert len(alert_sink.sent) == 2
    assert "LAYER CIECO" in alert_sink.sent[0]
    assert healthcheck_sink.ping_count == 0


def test_run_loop_uses_fresh_sequencer_reemits_current_state_on_restart(tmp_path):
    """Contratto di riavvio (ADR-037 §9/§10): un nuovo WiringSequencer per
    processo deve riemettere comando+alert dello stato corrente al primo
    ciclo, anche se quello stato persiste da prima del riavvio simulato."""
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(False, True, True, now=NOW))  # gia' in DEFENSIVE

    fresh_sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
    alert_sink = RecordingAlertSink()
    healthcheck_sink = RecordingHealthcheckSink()

    run_loop(
        store,
        fresh_sequencer,
        STALENESS,
        GRIDBTC_ACTION,
        alert_sink,
        healthcheck_sink,
        poll_interval=timedelta(minutes=5),
        max_iterations=1,
        sleep_fn=lambda seconds: None,
        now_fn=lambda: NOW,
    )

    assert len(alert_sink.sent) == 1
    assert "LAYER LAVORA" in alert_sink.sent[0]


def test_build_sinks_returns_dry_run_pair_when_dry_run_true():
    from alerting.sinks import DryRunAlertSink, DryRunHealthcheckSink

    alert_sink, healthcheck_sink = build_sinks(
        dry_run=True, bot_token=None, chat_id=None, healthchecks_url=None
    )
    assert isinstance(alert_sink, DryRunAlertSink)
    assert isinstance(healthcheck_sink, DryRunHealthcheckSink)


def test_build_sinks_raises_when_real_mode_missing_credentials():
    with pytest.raises(ValueError):
        build_sinks(dry_run=False, bot_token=None, chat_id="C", healthchecks_url="https://x")
