# tests/report/test_inventory.py
from __future__ import annotations

from datetime import datetime

from report.inventory import (
    InventoryCollector,
    InventorySnapshot,
    InventoryStore,
    diff_snapshots,
)


def _fake_runner(responses: dict[str, str]):
    def runner(args: list[str]) -> str:
        remote_command = args[-1]
        for key, value in responses.items():
            if key in remote_command:
                return value
        raise AssertionError(f"comando non atteso: {remote_command!r}")
    return runner


def test_collect_parses_all_categories():
    responses = {
        "list-units": "unit-a.service loaded active running\nunit-b.timer loaded active waiting",
        "list-unit-files": "mft_paper.service disabled",
        "crontab": "*/15 * * * * oi_snapshot",
        "docker ps": "infra-postgres-1\tUp 4 weeks",
        "ps aux": "root 1 0.0 0.0 systemd",
    }
    collector = InventoryCollector("207.180.247.38", "freqbot", run_command=_fake_runner(responses))
    snapshot = collector.collect(now=datetime(2026, 7, 5, 12, 0, 0))
    assert snapshot.timestamp == "2026-07-05T12:00:00Z"
    assert "unit-a.service loaded active running" in snapshot.systemd_units
    assert "mft_paper.service disabled" in snapshot.systemd_unit_files
    assert any("oi_snapshot" in line for line in snapshot.cron_lines)
    assert any("infra-postgres-1" in line for line in snapshot.docker_containers)
    assert any("systemd" in line for line in snapshot.processes)


def test_diff_detects_added_and_removed_units():
    previous = InventorySnapshot(
        timestamp="2026-07-04T00:00:00Z",
        systemd_units=["a.service"],
        systemd_unit_files=[],
        cron_lines=[],
        docker_containers=["c1"],
        processes=[],
    )
    current = InventorySnapshot(
        timestamp="2026-07-05T00:00:00Z",
        systemd_units=["a.service", "b.service"],
        systemd_unit_files=[],
        cron_lines=[],
        docker_containers=[],
        processes=[],
    )
    diff = diff_snapshots(previous, current)
    assert diff.added["systemd_units"] == ["b.service"]
    assert diff.removed["docker_containers"] == ["c1"]
    assert diff.is_empty is False


def test_diff_against_none_previous_marks_everything_as_added():
    current = InventorySnapshot(
        timestamp="2026-07-05T00:00:00Z",
        systemd_units=["a.service"],
        systemd_unit_files=[],
        cron_lines=[],
        docker_containers=[],
        processes=[],
    )
    diff = diff_snapshots(None, current)
    assert diff.added["systemd_units"] == ["a.service"]
    assert diff.is_empty is False


def test_identical_snapshots_produce_empty_diff():
    snap = InventorySnapshot(
        timestamp="2026-07-05T00:00:00Z",
        systemd_units=["a.service"],
        systemd_unit_files=[],
        cron_lines=[],
        docker_containers=[],
        processes=[],
    )
    diff = diff_snapshots(snap, snap)
    assert diff.is_empty is True


def test_inventory_store_roundtrip(tmp_path):
    store = InventoryStore(tmp_path)
    snap1 = InventorySnapshot(timestamp="2026-07-04T00:00:00Z")
    snap2 = InventorySnapshot(timestamp="2026-07-05T00:00:00Z")
    _path1 = store.save(snap1)
    path2 = store.save(snap2)
    latest_before_2 = store.load_latest_before(exclude_path=path2)
    assert latest_before_2.timestamp == "2026-07-04T00:00:00Z"
