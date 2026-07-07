from __future__ import annotations

from datetime import datetime, timedelta

from dashboard.queries import HistoryRow
from dashboard.render import (
    build_header_summary,
    render_html,
    render_staleness_png,
    render_state_timeline_png,
)
from dashboard.sanity import SanityFinding

BASE = datetime(2026, 7, 7, 12, 0, 0)


def _row(minutes: int, btc_high_vol=False, eth_high_vol=False) -> HistoryRow:
    ts = BASE + timedelta(minutes=minutes)
    return HistoryRow(
        snapshot_timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        snapshot_time=ts,
        btc_high_vol=btc_high_vol,
        eth_high_vol=eth_high_vol,
        eth_harvester_on=True,
        collected_at=ts + timedelta(seconds=3),
        derived_harvester_command="defensive" if eth_high_vol else "normal",
        derived_gridbtc_command="high_vol_stop_new_orders" if btc_high_vol else "normal",
        derived_alert=eth_high_vol or btc_high_vol,
        derived_alert_category="layer_lavora_difensiva" if eth_high_vol else None,
        derived_alert_text="LAYER LAVORA — test" if eth_high_vol else None,
    )


# --- build_header_summary (pura) --------------------------------------------


def test_build_header_summary_with_rows():
    rows = [_row(0), _row(15), _row(30)]
    meta = {"collection_started_at": BASE}
    summary = build_header_summary(rows, meta)
    assert summary.row_count == 3
    assert summary.first_snapshot == rows[0].snapshot_timestamp
    assert summary.last_snapshot == rows[-1].snapshot_timestamp
    assert summary.collection_started_at == BASE
    assert "08:33" in summary.declared_gap_note
    assert "10:05" in summary.declared_gap_note


def test_build_header_summary_with_no_rows():
    summary = build_header_summary([], {})
    assert summary.row_count == 0
    assert summary.first_snapshot is None
    assert summary.last_snapshot is None
    assert summary.collection_started_at is None


# --- chart rendering (smoke — matplotlib e' collante, non logica pura) -----


def test_render_state_timeline_png_returns_nonempty_bytes():
    rows = [_row(0), _row(15, eth_high_vol=True), _row(30)]
    png = render_state_timeline_png(rows)
    assert isinstance(png, bytes)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # magic number PNG


def test_render_state_timeline_png_handles_empty_rows_without_raising():
    png = render_state_timeline_png([])
    assert isinstance(png, bytes)


def test_render_staleness_png_returns_nonempty_bytes():
    rows = [_row(0), _row(15), _row(30)]
    png = render_staleness_png(rows)
    assert isinstance(png, bytes)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


# --- render_html (assemblaggio — verificato per contenuto strutturale) -----


def test_render_html_contains_key_sections_and_data():
    rows = [_row(0), _row(15, eth_high_vol=True)]
    meta = {"collection_started_at": BASE}
    findings = [SanityFinding(severity="warning", check="row_count", message="test finding xyz")]

    html = render_html(rows, rows, meta, findings)

    assert "<html" not in html.lower()  # niente scheletro, solo contenuto (regola Artifact-style)
    assert "test finding xyz" in html
    assert "row_count" in html
    assert "inferenza level/edge" in html.lower() or "level-triggered" in html.lower()
    assert rows[0].snapshot_timestamp in html
    assert "data:image/png;base64," in html


def test_render_html_shows_no_anomalies_message_when_findings_empty():
    rows = [_row(0), _row(15)]
    html = render_html(rows, rows, {"collection_started_at": BASE}, [])
    assert "nessuna anomalia" in html.lower()


def test_render_html_declares_missing_numeric_vol_series():
    """Finding di sessione: lo schema attuale non persiste il valore
    numerico dell'EWMA vol, solo lo stato booleano - il grafico "vol nel
    tempo con soglie" richiesto non e' costruibile con i dati disponibili.
    Deve essere dichiarato in modo prominente nell'HTML, non taciuto."""
    html = render_html([_row(0)], [_row(0)], {"collection_started_at": BASE}, [])
    assert "valore numerico" in html.lower() or "vol numerica" in html.lower()
