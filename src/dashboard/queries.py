"""Query di sola lettura sull'export LOCALE del DB di storia — mai sul
database remoto originale (questo modulo apre solo un file locale già
prodotto da `dashboard.export`, che a sua volta non lo modifica mai)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalizza a naive-UTC (stessa convenzione di progetto già
    stabilita altrove — vedi `components.regime_wiring._to_naive_utc`,
    non importata da qui: duplicata deliberatamente per non accoppiare
    questo modulo di sola lettura locale a un componente condiviso coi
    processi in shadow). `collected_at` è sempre aware nella produzione
    reale (`datetime.now(UTC)`); `snapshot_timestamp` è sempre aware per
    il suffisso 'Z' — ma normalizzare comunque protegge da qualunque
    storico misto senza assumerlo per costruzione."""
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


@dataclass(frozen=True)
class HistoryRow:
    snapshot_timestamp: str  # fatto, così come persistito (ISO 8601 UTC)
    snapshot_time: datetime  # stesso valore, parsato — per calcoli/grafici
    btc_high_vol: bool
    eth_high_vol: bool
    eth_harvester_on: bool
    collected_at: datetime
    derived_harvester_command: str
    derived_gridbtc_command: str
    derived_alert: bool
    derived_alert_category: str | None
    derived_alert_text: str | None

    @property
    def staleness(self) -> timedelta:
        return self.collected_at - self.snapshot_time


_COLUMNS = (
    "snapshot_timestamp",
    "btc_high_vol",
    "eth_high_vol",
    "eth_harvester_on",
    "collected_at",
    "derived_harvester_command",
    "derived_gridbtc_command",
    "derived_alert",
    "derived_alert_category",
    "derived_alert_text",
)


def _row_from_cursor_tuple(raw: tuple) -> HistoryRow:
    (
        snapshot_timestamp,
        btc_high_vol,
        eth_high_vol,
        eth_harvester_on,
        collected_at,
        derived_harvester_command,
        derived_gridbtc_command,
        derived_alert,
        derived_alert_category,
        derived_alert_text,
    ) = raw
    return HistoryRow(
        snapshot_timestamp=snapshot_timestamp,
        snapshot_time=_to_naive_utc(datetime.fromisoformat(snapshot_timestamp)),
        btc_high_vol=bool(btc_high_vol),
        eth_high_vol=bool(eth_high_vol),
        eth_harvester_on=bool(eth_harvester_on),
        collected_at=_to_naive_utc(datetime.fromisoformat(collected_at)),
        derived_harvester_command=derived_harvester_command,
        derived_gridbtc_command=derived_gridbtc_command,
        derived_alert=bool(derived_alert),
        derived_alert_category=derived_alert_category,
        derived_alert_text=derived_alert_text,
    )


def _select(db_path: Path | str, order_by_sql: str) -> list[HistoryRow]:
    # `order_by_sql` è sempre una delle due costanti letterali qui sotto,
    # mai una stringa esterna/costruita — nessuna interpolazione di input.
    columns_sql = ", ".join(_COLUMNS)
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(f"SELECT {columns_sql} FROM regime_history ORDER BY {order_by_sql}")  # noqa: S608
        return [_row_from_cursor_tuple(raw) for raw in cursor.fetchall()]
    finally:
        conn.close()


def load_rows(db_path: Path | str) -> list[HistoryRow]:
    """Ordine cronologico (`snapshot_timestamp` crescente) — per
    grafici/timeline, dove l'asse del tempo è quello del regime, non
    quello di quando il collector l'ha osservato."""
    return _select(db_path, "snapshot_timestamp ASC")


def load_rows_by_insertion_order(db_path: Path | str) -> list[HistoryRow]:
    """Ordine di inserimento reale (`rowid` crescente) — per verificare la
    monotonicità rispetto all'arrivo effettivo delle righe, non rispetto
    a un ordinamento a posteriori che la garantirebbe per costruzione."""
    return _select(db_path, "rowid ASC")


def load_meta(db_path: Path | str) -> dict[str, datetime]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT key, value FROM _meta").fetchall()
    finally:
        conn.close()
    return {key: _to_naive_utc(datetime.fromisoformat(value)) for key, value in rows}
