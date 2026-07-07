"""Controlli di data-sanity sullo storico esportato — il vero scopo del
primo render (smoke test del collector): ogni anomalia in evidenza nel
report, non nascosta in fondo alla pagina.

Riusa `resolve_wiring_decision` (pura, già approvata) per verificare la
consistenza LEVEL-triggered tra i campi grezzi e le colonne `derived_*`
di ciascuna riga — non per rivalutare l'edge-triggered `alert_category`
(quello dipende dalla storia del sequencer al momento della scrittura,
non riproducibile a posteriori senza l'intera sequenza — vedi docstring
di `components.history_collector`)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from components.history_collector import DEFAULT_GRIDBTC_ACTION, DEFAULT_STALENESS
from components.regime_wiring import resolve_wiring_decision
from dashboard.queries import HistoryRow
from regime.store import RegimeSnapshot

DEFAULT_DAEMON_INTERVAL = timedelta(minutes=15)  # ADR-037 §10, cadenza regime-daemon
DEFAULT_ROW_COUNT_TOLERANCE = 0.4
DEFAULT_MAX_CADENCE_GAP = timedelta(minutes=45)  # 3x la cadenza daemon


@dataclass(frozen=True)
class SanityFinding:
    severity: str  # "warning" (nessun caso "error" oggi: mai bloccante di per se')
    check: str
    message: str


def check_row_count(
    rows: list[HistoryRow],
    daemon_interval: timedelta = DEFAULT_DAEMON_INTERVAL,
    tolerance: float = DEFAULT_ROW_COUNT_TOLERANCE,
) -> SanityFinding | None:
    if len(rows) < 2:
        return None
    span = rows[-1].snapshot_time - rows[0].snapshot_time
    expected = span / daemon_interval + 1
    low, high = expected * (1 - tolerance), expected * (1 + tolerance)
    actual = len(rows)
    if low <= actual <= high:
        return None
    return SanityFinding(
        severity="warning",
        check="row_count",
        message=(
            f"righe osservate {actual}, attese ~{expected:.1f} (tollerato "
            f"{low:.1f}-{high:.1f}) per una copertura di {span} a cadenza daemon "
            f"{daemon_interval}"
        ),
    )


def check_duplicate_timestamps(rows: list[HistoryRow]) -> SanityFinding | None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in rows:
        if row.snapshot_timestamp in seen:
            duplicates.add(row.snapshot_timestamp)
        seen.add(row.snapshot_timestamp)
    if not duplicates:
        return None
    return SanityFinding(
        severity="warning",
        check="duplicate_timestamps",
        message=(
            f"{len(duplicates)} snapshot_timestamp duplicati nello storico esportato "
            f"(atteso: 0, la PK dovrebbe impedirlo): {sorted(duplicates)[:5]}"
        ),
    )


def check_cadence_gaps(
    rows: list[HistoryRow], max_gap: timedelta = DEFAULT_MAX_CADENCE_GAP
) -> list[SanityFinding]:
    findings = []
    for prev, curr in zip(rows, rows[1:], strict=False):
        gap = curr.snapshot_time - prev.snapshot_time
        if gap > max_gap:
            findings.append(
                SanityFinding(
                    severity="warning",
                    check="cadence_gap",
                    message=(
                        f"buco di {gap} tra {prev.snapshot_timestamp} e "
                        f"{curr.snapshot_timestamp} (soglia {max_gap})"
                    ),
                )
            )
    return findings


def check_level_consistency(rows: list[HistoryRow]) -> list[SanityFinding]:
    findings = []
    for row in rows:
        reconstructed = RegimeSnapshot(
            timestamp=row.snapshot_timestamp,
            btc_high_vol=row.btc_high_vol,
            eth_high_vol=row.eth_high_vol,
            eth_harvester_on=row.eth_harvester_on,
        )
        expected = resolve_wiring_decision(
            reconstructed,
            now=row.snapshot_time,
            staleness=DEFAULT_STALENESS,
            gridbtc_high_vol_action=DEFAULT_GRIDBTC_ACTION,
        )
        mismatches = []
        if expected.harvester_command.value != row.derived_harvester_command:
            mismatches.append(
                f"harvester_command: riga={row.derived_harvester_command!r} "
                f"ricalcolato={expected.harvester_command.value!r}"
            )
        if expected.gridbtc_command.value != row.derived_gridbtc_command:
            mismatches.append(
                f"gridbtc_command: riga={row.derived_gridbtc_command!r} "
                f"ricalcolato={expected.gridbtc_command.value!r}"
            )
        if expected.alert != row.derived_alert:
            mismatches.append(f"alert: riga={row.derived_alert!r} ricalcolato={expected.alert!r}")
        if mismatches:
            findings.append(
                SanityFinding(
                    severity="warning",
                    check="level_consistency",
                    message=f"{row.snapshot_timestamp}: " + "; ".join(mismatches),
                )
            )
    return findings


def check_monotonic_timestamps(rows_by_insertion_order: list[HistoryRow]) -> list[SanityFinding]:
    findings = []
    for prev, curr in zip(rows_by_insertion_order, rows_by_insertion_order[1:], strict=False):
        if curr.snapshot_time < prev.snapshot_time:
            findings.append(
                SanityFinding(
                    severity="warning",
                    check="monotonic_timestamps",
                    message=(
                        f"ordine di inserimento non monotono: {curr.snapshot_timestamp} "
                        f"arrivato dopo {prev.snapshot_timestamp} ma cronologicamente precedente"
                    ),
                )
            )
        if curr.collected_at < prev.collected_at:
            findings.append(
                SanityFinding(
                    severity="warning",
                    check="monotonic_collected_at",
                    message=(
                        f"collected_at non monotono nell'ordine di inserimento: "
                        f"{curr.collected_at} dopo {prev.collected_at}"
                    ),
                )
            )
    return findings


def run_all_checks(
    rows: list[HistoryRow],
    rows_by_insertion_order: list[HistoryRow],
    meta: dict,
) -> list[SanityFinding]:
    del meta  # riservato per controlli futuri (es. collection_started_at vs primo timestamp)
    findings: list[SanityFinding] = []
    row_count_finding = check_row_count(rows)
    if row_count_finding is not None:
        findings.append(row_count_finding)
    dup_finding = check_duplicate_timestamps(rows)
    if dup_finding is not None:
        findings.append(dup_finding)
    findings.extend(check_cadence_gaps(rows))
    findings.extend(check_level_consistency(rows))
    findings.extend(check_monotonic_timestamps(rows_by_insertion_order))
    return findings
