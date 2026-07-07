from __future__ import annotations

from datetime import datetime, timedelta

from dashboard.queries import HistoryRow
from dashboard.sanity import (
    check_cadence_gaps,
    check_duplicate_timestamps,
    check_level_consistency,
    check_monotonic_timestamps,
    check_row_count,
    run_all_checks,
)

BASE = datetime(2026, 7, 7, 12, 0, 0)


def _row(
    minutes: int,
    btc_high_vol: bool = False,
    eth_high_vol: bool = False,
    eth_harvester_on: bool = True,
    derived_harvester_command: str = "normal",
    derived_gridbtc_command: str = "normal",
    derived_alert: bool = False,
    derived_alert_category: str | None = None,
    derived_alert_text: str | None = None,
    collected_at_offset_seconds: int = 3,
) -> HistoryRow:
    ts = BASE + timedelta(minutes=minutes)
    return HistoryRow(
        snapshot_timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        snapshot_time=ts,
        btc_high_vol=btc_high_vol,
        eth_high_vol=eth_high_vol,
        eth_harvester_on=eth_harvester_on,
        collected_at=ts + timedelta(seconds=collected_at_offset_seconds),
        derived_harvester_command=derived_harvester_command,
        derived_gridbtc_command=derived_gridbtc_command,
        derived_alert=derived_alert,
        derived_alert_category=derived_alert_category,
        derived_alert_text=derived_alert_text,
    )


# --- check_row_count -------------------------------------------------------


def test_check_row_count_none_when_within_expected_range():
    rows = [_row(0), _row(15), _row(30)]  # esattamente al ritmo di 15'
    assert check_row_count(rows) is None


def test_check_row_count_flags_when_far_fewer_rows_than_expected():
    rows = [_row(0), _row(180)]  # 3 ore di copertura, solo 2 righe (atteso ~13)
    finding = check_row_count(rows)
    assert finding is not None
    assert finding.check == "row_count"


def test_check_row_count_none_with_fewer_than_2_rows():
    assert check_row_count([_row(0)]) is None
    assert check_row_count([]) is None


# --- check_duplicate_timestamps ---------------------------------------------


def test_check_duplicate_timestamps_none_when_all_unique():
    rows = [_row(0), _row(15), _row(30)]
    assert check_duplicate_timestamps(rows) is None


def test_check_duplicate_timestamps_flags_duplicates():
    rows = [_row(0), _row(0), _row(15)]
    finding = check_duplicate_timestamps(rows)
    assert finding is not None
    assert finding.check == "duplicate_timestamps"


# --- check_cadence_gaps ------------------------------------------------------


def test_check_cadence_gaps_empty_when_regular():
    rows = [_row(0), _row(15), _row(30), _row(45)]
    assert check_cadence_gaps(rows, max_gap=timedelta(minutes=45)) == []


def test_check_cadence_gaps_flags_large_hole():
    rows = [_row(0), _row(15), _row(200)]  # buco di 185' tra la 2a e la 3a
    findings = check_cadence_gaps(rows, max_gap=timedelta(minutes=45))
    assert len(findings) == 1
    assert findings[0].check == "cadence_gap"


# --- check_level_consistency (riusa resolve_wiring_decision, pura, approvata) -


def test_check_level_consistency_none_when_derived_matches_raw_fields():
    rows = [
        _row(0, eth_high_vol=False, eth_harvester_on=True, derived_harvester_command="normal"),
        _row(
            15,
            eth_high_vol=True,
            eth_harvester_on=True,
            btc_high_vol=True,
            derived_harvester_command="defensive",
            derived_gridbtc_command="high_vol_stop_new_orders",
            derived_alert=True,
        ),
    ]
    assert check_level_consistency(rows) == []


def test_check_level_consistency_flags_mismatch():
    # eth_high_vol=True + eth_harvester_on=True dovrebbe dare "defensive",
    # non "normal" - riga corrotta/inconsistente rispetto ai fatti grezzi.
    rows = [_row(0, eth_high_vol=True, eth_harvester_on=True, derived_harvester_command="normal")]
    findings = check_level_consistency(rows)
    assert len(findings) == 1
    assert findings[0].check == "level_consistency"
    assert "harvester_command" in findings[0].message


# --- check_monotonic_timestamps ---------------------------------------------


def test_check_monotonic_timestamps_empty_when_well_ordered():
    rows = [_row(0), _row(15), _row(30)]
    assert check_monotonic_timestamps(rows) == []


def test_check_monotonic_timestamps_flags_out_of_order_snapshot_time():
    rows = [_row(15), _row(0)]  # arrivata "prima" una riga cronologicamente successiva
    findings = check_monotonic_timestamps(rows)
    assert len(findings) >= 1
    assert any(f.check == "monotonic_timestamps" for f in findings)


# --- run_all_checks (orchestratore) -----------------------------------------


def test_run_all_checks_empty_for_well_behaved_history():
    rows = [_row(0), _row(15), _row(30)]
    meta = {"collection_started_at": BASE}
    assert run_all_checks(rows, rows, meta) == []


def test_run_all_checks_aggregates_multiple_categories():
    rows = [
        _row(0, eth_high_vol=True, eth_harvester_on=True, derived_harvester_command="normal"),
        _row(0),  # duplicato
    ]
    findings = run_all_checks(rows, rows, {"collection_started_at": BASE})
    checks_found = {f.check for f in findings}
    assert "duplicate_timestamps" in checks_found
    assert "level_consistency" in checks_found
