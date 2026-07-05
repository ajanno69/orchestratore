from __future__ import annotations

from datetime import datetime

from regime.store import RegimeStateStore, build_snapshot
from report.regime_report import format_regime_section, load_and_format_regime_section


def test_format_regime_section_no_snapshot():
    assert format_regime_section(None) == "Regime: nessuno snapshot disponibile ancora."


def test_format_regime_section_with_snapshot():
    snap = build_snapshot(True, False, True, now=datetime(2026, 7, 5, 12, 0, 0))
    text = format_regime_section(snap)
    assert "2026-07-05T12:00:00Z" in text
    assert "BTC high-vol: ON" in text
    assert "ETH high-vol: OFF" in text
    assert "ETH harvester: ON" in text


def test_load_and_format_regime_section_reads_from_store(tmp_path):
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(False, True, False, now=datetime(2026, 7, 5, 0, 0, 0)))
    text = load_and_format_regime_section(store)
    assert "ETH high-vol: ON" in text
