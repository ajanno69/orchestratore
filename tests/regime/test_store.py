# tests/regime/test_store.py
from __future__ import annotations

from datetime import datetime

import pytest

from regime.store import RegimeSnapshot, RegimeStateStore, build_snapshot, resolve_initial_snapshot
from regime.vol_state import VolRegimeState, VolStateConfig


def test_build_snapshot_formats_timestamp_iso_utc():
    snap = build_snapshot(True, False, True, now=datetime(2026, 7, 5, 12, 30, 0))
    assert snap.timestamp == "2026-07-05T12:30:00Z"
    assert snap.btc_high_vol is True
    assert snap.eth_high_vol is False
    assert snap.eth_harvester_on is True
    assert snap.btc_ewma_vol is None
    assert snap.eth_ewma_vol is None


def test_build_snapshot_accepts_optional_ewma_vol_values():
    """Prep schema post-gate (Parte 2, 2026-07-07): il daemon calcola questi
    valori a ogni ciclo ma finora non li persisteva mai — vedi
    docs/m2-shadow-dashboard-rendering-report-2026-07-07.md §4. Campi
    opzionali, mai deployati prima del gate 21/07 (vedi ADR-037)."""
    snap = build_snapshot(
        True, False, True, now=datetime(2026, 7, 5, 12, 30, 0), btc_ewma_vol=0.91, eth_ewma_vol=0.42
    )
    assert snap.btc_ewma_vol == 0.91
    assert snap.eth_ewma_vol == 0.42


def test_snapshot_from_dict_backward_compatible_when_ewma_vol_fields_missing():
    """Uno snapshot scritto dal codice PRIMA di questa modifica (es. il file
    reale sul VPS, mai toccato prima del gate) non ha queste chiavi —
    from_dict deve leggerlo comunque, con i nuovi campi a None, non sollevare."""
    raw = {
        "timestamp": "2026-07-05T12:30:00Z",
        "btc_high_vol": True,
        "eth_high_vol": False,
        "eth_harvester_on": True,
    }
    snap = RegimeSnapshot.from_dict(raw)
    assert snap.btc_ewma_vol is None
    assert snap.eth_ewma_vol is None


def test_snapshot_roundtrip_preserves_ewma_vol_values(tmp_path):
    store = RegimeStateStore(tmp_path)
    snap = build_snapshot(
        True, True, False, now=datetime(2026, 7, 5, 0, 0, 0), btc_ewma_vol=0.75, eth_ewma_vol=1.02
    )
    store.write(snap)
    loaded = store.read()
    assert loaded.btc_ewma_vol == 0.75
    assert loaded.eth_ewma_vol == 1.02


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
    [exit, enter). Con il reseeding dal RegimeSnapshot persistito, lo stato
    resta correttamente True dopo update(0.7) (dentro [0.6, 0.8)).

    Controfattuale eseguibile (non solo prosa): senza reseeding esplicito,
    VolRegimeState(config=config) parte dal default della dataclass
    (is_high_vol=False) e lo stesso update(0.7) - dentro la banda morta -
    lo lascia erroneamente False, perdendo silenziosamente lo stato vero
    pregresso. Il test dimostra entrambi i rami fianco a fianco."""
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(True, False, False, now=datetime(2026, 7, 5, 0, 0, 0)))

    resolved = resolve_initial_snapshot(store)
    config = VolStateConfig(ewma_span=20, enter_threshold=0.8, exit_threshold=0.6)

    # Ramo reseeded: lo stato vero (True) sopravvive al riavvio.
    state = VolRegimeState(config=config, is_high_vol=resolved.btc_high_vol)
    assert state.is_high_vol is True

    state.update(0.7)  # dentro la banda morta: nessun flip indotto dal riavvio
    assert state.is_high_vol is True

    # Ramo cold-start (controfattuale): stessa config, stesso update(0.7),
    # ma senza reseeding dallo snapshot persistito -> flip silenzioso a False.
    cold = VolRegimeState(config=config)
    assert cold.is_high_vol is False  # default della dataclass, non lo stato reale

    cold.update(0.7)
    assert cold.is_high_vol is False  # dimostra la perdita di stato senza reseeding
