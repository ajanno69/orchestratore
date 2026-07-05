# tests/regime/test_store.py
from __future__ import annotations

from datetime import datetime

import pytest

from regime.store import RegimeStateStore, build_snapshot, resolve_initial_snapshot
from regime.vol_state import VolRegimeState, VolStateConfig


def test_build_snapshot_formats_timestamp_iso_utc():
    snap = build_snapshot(True, False, True, now=datetime(2026, 7, 5, 12, 30, 0))
    assert snap.timestamp == "2026-07-05T12:30:00Z"
    assert snap.btc_high_vol is True
    assert snap.eth_high_vol is False
    assert snap.eth_harvester_on is True


def test_store_write_then_read_roundtrip(tmp_path):
    store = RegimeStateStore(tmp_path)
    snap = build_snapshot(True, True, False, now=datetime(2026, 7, 5, 0, 0, 0))
    store.write(snap)
    loaded = store.read()
    assert loaded == snap


def test_store_read_returns_none_when_no_snapshot_yet(tmp_path):
    store = RegimeStateStore(tmp_path)
    assert store.read() is None


def test_store_write_overwrites_previous_snapshot(tmp_path):
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(False, False, False, now=datetime(2026, 7, 5, 0, 0, 0)))
    store.write(build_snapshot(True, True, True, now=datetime(2026, 7, 6, 0, 0, 0)))
    loaded = store.read()
    assert loaded.btc_high_vol is True
    assert loaded.timestamp == "2026-07-06T00:00:00Z"


def test_read_raises_explicit_error_on_corrupted_snapshot_file(tmp_path):
    """Un file corrotto/illeggibile è un segnale di un problema a monte, non
    un default silenzioso su cui basare una decisione di regime (stesso
    principio del guard NaN/inf in vol_state.py)."""
    store = RegimeStateStore(tmp_path)
    (tmp_path / "regime_state.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrotto o illeggibile"):
        store.read()


def test_read_raises_explicit_error_on_snapshot_missing_required_field(tmp_path):
    store = RegimeStateStore(tmp_path)
    path = tmp_path / "regime_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"timestamp": "2026-07-05T00:00:00Z"}', encoding="utf-8")
    with pytest.raises(ValueError, match="corrotto o illeggibile"):
        store.read()


def test_resolve_initial_snapshot_defaults_explicitly_on_first_ever_startup(tmp_path):
    """Primo avvio assoluto (nessuno snapshot pregresso): lo stato iniziale
    è una scelta esplicita e documentata (bassa vol, harvester off), non il
    default implicito del linguaggio (coerente con VolRegimeState.is_high_vol
    che parte da False di suo, ma qui la scelta è dichiarata a livello di
    store, non lasciata al caso)."""
    store = RegimeStateStore(tmp_path)
    snapshot = resolve_initial_snapshot(store)
    assert snapshot.btc_high_vol is False
    assert snapshot.eth_high_vol is False
    assert snapshot.eth_harvester_on is False


def test_resolve_initial_snapshot_returns_persisted_snapshot_when_present(tmp_path):
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(True, False, True, now=datetime(2026, 7, 5, 0, 0, 0)))
    resolved = resolve_initial_snapshot(store)
    assert resolved.btc_high_vol is True
    assert resolved.eth_harvester_on is True


def test_restart_no_flip_reseeds_high_vol_state_from_persisted_snapshot(tmp_path):
    """Lo scenario che ha motivato questo task: stato vero pre-riavvio =
    high-vol (True), un riavvio del processo NON deve far tornare lo stato
    a bassa vol solo perché la nuova vol osservata cade nella banda morta
    [exit, enter). Senza reseeding esplicito, VolRegimeState() partirebbe
    dal default della dataclass (False) e un update(0.7) - dentro
    [0.6, 0.8) - lo lascerebbe erroneamente False. Con il reseeding dal
    RegimeSnapshot persistito, resta correttamente True."""
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(True, False, False, now=datetime(2026, 7, 5, 0, 0, 0)))

    resolved = resolve_initial_snapshot(store)
    config = VolStateConfig(ewma_span=20, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config, is_high_vol=resolved.btc_high_vol)
    assert state.is_high_vol is True

    state.update(0.7)  # dentro la banda morta: nessun flip indotto dal riavvio
    assert state.is_high_vol is True
