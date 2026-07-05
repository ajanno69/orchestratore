from __future__ import annotations

from datetime import datetime

from regime.store import build_snapshot
from report.inventory import InventoryDiff
from report.weekly_report import build_weekly_report


def test_weekly_report_no_changes():
    snapshot = build_snapshot(False, False, False, now=datetime(2026, 7, 5, 0, 0, 0))
    diff = InventoryDiff(added={"systemd_units": []}, removed={"systemd_units": []})
    report = build_weekly_report(snapshot, diff)
    assert "Regime al 2026-07-05T00:00:00Z" in report
    assert "nessuna variazione rispetto alla settimana precedente" in report


def test_weekly_report_shows_added_and_removed_units():
    diff = InventoryDiff(
        added={"systemd_units": ["mft_paper.service"]},
        removed={"systemd_units": []},
    )
    report = build_weekly_report(None, diff)
    assert "+ [systemd_units] mft_paper.service" in report
