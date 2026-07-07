from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from dashboard.queries import HistoryRow
from dashboard.render import (
    build_header_summary,
    render_html,
    render_staleness_png,
    render_state_timeline_png,
    render_vol_reconstruction_png,
)
from dashboard.sanity import SanityFinding
from dashboard.vol_reconstruction import VolSeries

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


def test_render_html_declares_missing_numeric_vol_series_when_no_reconstruction_given():
    """Finding di sessione: senza una ricostruzione ex-post fornita, resta
    dichiarato che il daemon non persiste il valore osservato."""
    html = render_html([_row(0)], [_row(0)], {"collection_started_at": BASE}, [])
    assert "valore numerico" in html.lower() or "vol numerica" in html.lower()


# --- ricostruzione ex-post della vol (richiesta successiva) -----------------


def _vol_series(asset: str, values: list[float]) -> VolSeries:
    index = pd.date_range("2026-06-01", periods=len(values), freq="D")
    return VolSeries(
        asset=asset,
        vol=pd.Series(values, index=index),
        enter_threshold=0.87 if asset == "BTC" else 0.99,
        exit_threshold=0.59 if asset == "BTC" else 0.83,
    )


def test_render_vol_reconstruction_png_returns_nonempty_png_bytes():
    series = {
        "BTC": _vol_series("BTC", [0.3, 0.5, 0.9, 0.6]),
        "ETH": _vol_series("ETH", [0.4, 0.6, 1.1, 0.7]),
    }
    png = render_vol_reconstruction_png(series)
    assert isinstance(png, bytes)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_vol_reconstruction_png_handles_empty_dict_without_raising():
    png = render_vol_reconstruction_png({})
    assert isinstance(png, bytes)


def test_render_html_with_vol_reconstruction_shows_ex_post_label_and_thresholds():
    rows = [_row(0), _row(15)]
    vol_series_by_asset = {
        "BTC": _vol_series("BTC", [0.3, 0.5, 0.9]),
        "ETH": _vol_series("ETH", [0.4, 0.6, 1.1]),
    }

    html = render_html(
        rows, rows, {"collection_started_at": BASE}, [], vol_series_by_asset=vol_series_by_asset
    )

    assert "ricostruzione ex-post" in html.lower()
    assert "non è il valore osservato dal daemon" in html.lower() or (
        "non e' il valore osservato dal daemon" in html.lower()
    )
    assert "0.87" in html  # soglia enter BTC
    assert "0.59" in html  # soglia exit BTC
