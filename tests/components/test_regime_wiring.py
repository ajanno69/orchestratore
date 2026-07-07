from __future__ import annotations

from datetime import datetime, timedelta, timezone

from components.regime_wiring import (
    GridBtcCommand,
    GridBtcHighVolAction,
    HarvesterCommand,
    StalenessPolicy,
    load_snapshot_safely,
    resolve_wiring_decision,
)
from regime.store import RegimeSnapshot, RegimeStateStore, build_snapshot

STALENESS = StalenessPolicy(max_age=timedelta(hours=1))
NOW = datetime(2026, 7, 6, 12, 0, 0)


def test_no_snapshot_produces_no_action_and_alert():
    decision = resolve_wiring_decision(
        None,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
    assert decision.gridbtc_command == GridBtcCommand.NO_ACTION_STALE_DATA
    assert decision.alert is True


def test_stale_snapshot_produces_no_action_and_alert():
    snapshot = build_snapshot(
        True, True, True, now=datetime(2026, 7, 6, 10, 0, 0)
    )  # 2h prima di NOW
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
    assert decision.gridbtc_command == GridBtcCommand.NO_ACTION_STALE_DATA
    assert decision.alert is True


def test_snapshot_exactly_at_staleness_boundary_is_still_fresh():
    snapshot = build_snapshot(
        False, False, False, now=datetime(2026, 7, 6, 11, 0, 0)
    )  # esattamente 1h prima
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command != HarvesterCommand.NO_ACTION_STALE_DATA


def test_fresh_snapshot_within_staleness_is_used():
    snapshot = build_snapshot(False, False, False, now=datetime(2026, 7, 6, 11, 30, 0))
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command == HarvesterCommand.OFF
    assert decision.gridbtc_command == GridBtcCommand.NORMAL
    assert decision.alert is False


def test_harvester_defensive_when_on_and_high_vol():
    snapshot = build_snapshot(False, True, True, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command == HarvesterCommand.DEFENSIVE
    assert decision.alert is True


def test_harvester_normal_when_on_and_not_high_vol():
    snapshot = build_snapshot(False, False, True, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command == HarvesterCommand.NORMAL


def test_harvester_off_when_funding_signal_off_regardless_of_vol():
    snapshot = build_snapshot(False, True, False, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command == HarvesterCommand.OFF


def test_gridbtc_stop_new_orders_when_configured_and_high_vol():
    snapshot = build_snapshot(True, False, False, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.gridbtc_command == GridBtcCommand.HIGH_VOL_STOP_NEW_ORDERS
    assert decision.alert is True


def test_gridbtc_close_orderly_when_configured_and_high_vol():
    snapshot = build_snapshot(True, False, False, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.CLOSE_GRID_ORDERLY,
    )
    assert decision.gridbtc_command == GridBtcCommand.HIGH_VOL_CLOSE_GRID_ORDERLY


def test_gridbtc_normal_when_not_high_vol():
    snapshot = build_snapshot(False, False, False, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.gridbtc_command == GridBtcCommand.NORMAL


def test_resolve_wiring_decision_ignores_numeric_ewma_vol_fields():
    """Chiude nota minore 2 del reviewer indipendente (Parte 2, review
    041f4fe): btc_ewma_vol/eth_ewma_vol (schema prep repo-only, mai
    deployati prima del gate 21/07) devono restare puramente osservativi
    — il muro Binario A/B richiede che NESSUNA decisione di wiring/capitale
    dipenda da loro. Due snapshot identici tranne che nei campi numerici
    devono produrre ESATTAMENTE la stessa decisione: se in futuro qualcuno
    li introduce per errore in resolve_wiring_decision, questo test rompe
    prima che il cambiamento arrivi a un reviewer umano."""
    base = build_snapshot(False, True, True, now=datetime(2026, 7, 6, 12, 0, 0))
    with_vol = RegimeSnapshot(
        timestamp=base.timestamp,
        btc_high_vol=base.btc_high_vol,
        eth_high_vol=base.eth_high_vol,
        eth_harvester_on=base.eth_harvester_on,
        btc_ewma_vol=99.0,  # valore assurdo apposta: se venisse letto, il test lo rileverebbe
        eth_ewma_vol=-1.0,
    )

    decision_without = resolve_wiring_decision(
        base,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    decision_with = resolve_wiring_decision(
        with_vol,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )

    assert decision_with == decision_without


def test_load_snapshot_safely_returns_none_on_corrupted_file(tmp_path):
    store = RegimeStateStore(tmp_path)
    (tmp_path / "regime_state.json").write_text("{not valid json", encoding="utf-8")
    assert load_snapshot_safely(store) is None


def test_load_snapshot_safely_returns_snapshot_when_valid(tmp_path):
    store = RegimeStateStore(tmp_path)
    snap = build_snapshot(True, False, False, now=datetime(2026, 7, 6, 12, 0, 0))
    store.write(snap)
    assert load_snapshot_safely(store) == snap


def test_load_snapshot_safely_returns_none_when_no_file(tmp_path):
    store = RegimeStateStore(tmp_path)
    assert load_snapshot_safely(store) is None


def test_resolve_wiring_decision_normalizes_aware_non_utc_now_before_staleness_check():
    """Test dedicato che fallisce con il bug (verificato per davvero: con
    uno strip secco `replace(tzinfo=None)` senza `astimezone` prima, questo
    test fallisce con età 2:00:00 invece di ~0). Un `now` aware in un fuso
    non-UTC (qui CEST, +02:00) che rappresenta LO STESSO istante reale
    dello snapshot deve dare staleness ~0, non ~2h. Soglia di staleness
    volutamente stretta (5 minuti) per distinguere inequivocabilmente i
    due esiti: un errore di 2h farebbe scattare NO_ACTION_STALE_DATA, la
    normalizzazione corretta no."""
    tight_staleness = StalenessPolicy(max_age=timedelta(minutes=5))
    snapshot = build_snapshot(False, False, False, now=datetime(2026, 7, 6, 10, 0, 0))  # 10:00 UTC
    now_cest_same_instant = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    decision = resolve_wiring_decision(
        snapshot,
        now=now_cest_same_instant,
        staleness=tight_staleness,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command != HarvesterCommand.NO_ACTION_STALE_DATA


def test_resolve_wiring_decision_fails_safe_on_malformed_timestamp():
    """Uno snapshot con JSON valido ma timestamp non ISO (i dataclass non
    validano i tipi/contenuto a runtime, quindi `RegimeSnapshot.from_dict`
    lo costruisce comunque) non deve far esplodere `resolve_wiring_decision`
    con un'eccezione non gestita — deve fermarsi allo stesso fail-safe
    NO_ACTION_STALE_DATA + alert usato per snapshot assente/stantio."""
    snapshot = RegimeSnapshot(
        timestamp="non-una-data-iso",
        btc_high_vol=False,
        eth_high_vol=False,
        eth_harvester_on=False,
    )
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
    assert decision.gridbtc_command == GridBtcCommand.NO_ACTION_STALE_DATA
    assert decision.alert is True


def test_resolve_wiring_decision_fails_safe_on_non_bool_field():
    """Un campo booleano con un tipo invalido (qui una stringa) non deve
    essere interpretato per truthiness (mai un default silenzioso) — deve
    produrre lo stesso fail-safe di uno snapshot assente."""
    snapshot = RegimeSnapshot(
        timestamp="2026-07-06T12:00:00Z",
        btc_high_vol="true",  # invalido: stringa, non bool
        eth_high_vol=False,
        eth_harvester_on=False,
    )
    decision = resolve_wiring_decision(
        snapshot,
        now=NOW,
        staleness=STALENESS,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
    assert decision.gridbtc_command == GridBtcCommand.NO_ACTION_STALE_DATA
    assert decision.alert is True


def test_resolve_wiring_decision_converts_explicit_non_z_offset_in_snapshot_timestamp():
    """Snapshot con timestamp che ha un offset esplicito +02:00 (non il
    solito 'Z' emesso da build_snapshot) — prova che astimezone(utc)
    applica la conversione giusta invece di leggere l'offset come se
    fosse già UTC (che sbaglierebbe l'età di esattamente 2h)."""
    tight_staleness = StalenessPolicy(max_age=timedelta(minutes=5))
    snapshot = RegimeSnapshot(
        timestamp="2026-07-06T14:00:00+02:00",  # = 12:00 UTC
        btc_high_vol=False,
        eth_high_vol=False,
        eth_harvester_on=False,
    )
    now_utc_same_instant = datetime(2026, 7, 6, 12, 0, 0)
    decision = resolve_wiring_decision(
        snapshot,
        now=now_utc_same_instant,
        staleness=tight_staleness,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command != HarvesterCommand.NO_ACTION_STALE_DATA
