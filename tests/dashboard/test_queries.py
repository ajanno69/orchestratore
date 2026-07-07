from __future__ import annotations

from datetime import datetime, timedelta

from components.history_collector import HistoryStore, compute_derived_fields
from components.wiring_sequencer import RateLimitPolicy, WiringSequencer
from dashboard.queries import load_meta, load_rows, load_rows_by_insertion_order
from regime.store import build_snapshot

NOW = datetime(2026, 7, 7, 12, 0, 0)


def _sequencer() -> WiringSequencer:
    return WiringSequencer(rate_limit=RateLimitPolicy(window=timedelta(hours=1), max_transitions=3))


def _make_fixture_db(tmp_path):
    """Riusa HistoryStore vero (stessa fonte di verita' dello schema —
    niente fixture SQL duplicata a mano che potrebbe andare fuori sync)."""
    store = HistoryStore(tmp_path / "history.db")
    store.record_collection_start(NOW)
    sequencer = _sequencer()
    for i, (btc, eth, harvester) in enumerate(
        [(False, False, True), (False, True, True), (False, True, True)]
    ):
        snapshot = build_snapshot(btc, eth, harvester, now=NOW + timedelta(minutes=15 * i))
        derived = compute_derived_fields(snapshot, sequencer, now=NOW + timedelta(minutes=15 * i))
        store.insert_snapshot_row(
            snapshot, collected_at=NOW + timedelta(minutes=15 * i, seconds=3), derived=derived
        )
    return tmp_path / "history.db"


def test_load_rows_returns_all_rows_in_chronological_order(tmp_path):
    db_path = _make_fixture_db(tmp_path)
    rows = load_rows(db_path)
    assert len(rows) == 3
    assert [r.snapshot_time for r in rows] == sorted(r.snapshot_time for r in rows)


def test_load_rows_parses_booleans_and_derived_fields(tmp_path):
    db_path = _make_fixture_db(tmp_path)
    rows = load_rows(db_path)
    first, second = rows[0], rows[1]
    assert first.eth_high_vol is False
    assert first.derived_harvester_command == "normal"
    assert second.eth_high_vol is True
    assert second.derived_harvester_command == "defensive"
    assert second.derived_alert_category == "layer_lavora_difensiva"


def test_load_rows_staleness_is_positive_timedelta(tmp_path):
    db_path = _make_fixture_db(tmp_path)
    rows = load_rows(db_path)
    for row in rows:
        assert row.staleness == timedelta(seconds=3)


def test_load_rows_by_insertion_order_matches_chronological_for_well_behaved_fixture(tmp_path):
    db_path = _make_fixture_db(tmp_path)
    chronological = load_rows(db_path)
    by_insertion = load_rows_by_insertion_order(db_path)
    assert [r.snapshot_timestamp for r in chronological] == [
        r.snapshot_timestamp for r in by_insertion
    ]


def test_load_rows_on_empty_db_returns_empty_list(tmp_path):
    HistoryStore(tmp_path / "history.db")  # solo schema, nessuna riga
    rows = load_rows(tmp_path / "history.db")
    assert rows == []


def test_load_meta_returns_collection_started_at_and_last_new_row_at(tmp_path):
    db_path = _make_fixture_db(tmp_path)
    meta = load_meta(db_path)
    assert "collection_started_at" in meta
    assert "last_new_row_at" in meta
    assert isinstance(meta["collection_started_at"], datetime)
    assert meta["last_new_row_at"] == NOW + timedelta(minutes=30, seconds=3)


def test_load_meta_on_fresh_db_has_no_last_new_row_at(tmp_path):
    HistoryStore(tmp_path / "history.db")
    meta = load_meta(tmp_path / "history.db")
    assert "last_new_row_at" not in meta
