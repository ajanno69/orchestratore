from __future__ import annotations

import shlex
from datetime import datetime

import pytest

from dashboard.export import (
    ExportResult,
    export_history_db,
    remote_tmp_path,
)


def test_remote_tmp_path_is_deterministic_and_timestamped():
    now = datetime(2026, 7, 7, 12, 34, 56)
    path = remote_tmp_path(now)
    assert path == "/tmp/history_export_20260707T123456Z.db"


def test_remote_tmp_path_differs_for_different_timestamps():
    a = remote_tmp_path(datetime(2026, 7, 7, 12, 0, 0))
    b = remote_tmp_path(datetime(2026, 7, 7, 12, 5, 0))
    assert a != b


class RecordingRunner:
    def __init__(self, outputs: list[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._outputs = outputs or []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if self._outputs:
            return self._outputs.pop(0)
        return ""


def test_export_history_db_issues_backup_scp_cleanup_in_order(tmp_path):
    runner = RecordingRunner(outputs=["BACKUP_OK\n", "", ""])
    now = datetime(2026, 7, 7, 12, 0, 0)

    result = export_history_db(
        ssh_host="207.180.247.38",
        ssh_user="freqbot",
        remote_db_path="/opt/orchestrator/var/history/history.db",
        local_output_dir=tmp_path,
        now=now,
        run_command=runner,
    )

    assert len(runner.calls) == 3

    backup_call = runner.calls[0]
    assert backup_call[0] == "ssh"
    assert backup_call[1] == "freqbot@207.180.247.38"
    # il comando remoto e' UN SOLO argv, gia' shell-quotato per il lato
    # remoto - deve fare round-trip corretto con shlex.split (bash lo
    # eseguirebbe cosi')
    remote_cmd = backup_call[2]
    parsed = shlex.split(remote_cmd)
    assert parsed[0] == "python3"
    assert parsed[1] == "-c"
    snippet = parsed[2]
    assert "sqlite3" in snippet
    assert "/opt/orchestrator/var/history/history.db" in snippet
    assert "/tmp/history_export_20260707T120000Z.db" in snippet
    assert ".backup(" in snippet

    scp_call = runner.calls[1]
    assert scp_call[0] == "scp"
    assert scp_call[1] == "freqbot@207.180.247.38:/tmp/history_export_20260707T120000Z.db"
    assert scp_call[2].endswith("history_export_20260707T120000Z.db")

    cleanup_call = runner.calls[2]
    assert cleanup_call == [
        "ssh",
        "freqbot@207.180.247.38",
        "rm",
        "/tmp/history_export_20260707T120000Z.db",
    ]

    assert isinstance(result, ExportResult)
    assert result.local_path.name == "history_export_20260707T120000Z.db"
    assert result.remote_tmp_path == "/tmp/history_export_20260707T120000Z.db"


def test_export_history_db_creates_local_output_dir(tmp_path):
    output_dir = tmp_path / "nested" / "dir"
    runner = RecordingRunner()

    export_history_db(
        ssh_host="h",
        ssh_user="u",
        remote_db_path="/opt/orchestrator/var/history/history.db",
        local_output_dir=output_dir,
        now=datetime(2026, 7, 7, 12, 0, 0),
        run_command=runner,
    )

    assert output_dir.is_dir()


def test_export_history_db_propagates_backup_failure_without_scp_or_cleanup(tmp_path):
    def failing_backup(args: list[str]) -> str:
        raise ConnectionError("SSH non raggiungibile")

    with pytest.raises(ConnectionError):
        export_history_db(
            ssh_host="h",
            ssh_user="u",
            remote_db_path="/opt/orchestrator/var/history/history.db",
            local_output_dir=tmp_path,
            now=datetime(2026, 7, 7, 12, 0, 0),
            run_command=failing_backup,
        )


def test_export_history_db_attempts_cleanup_even_if_scp_fails_then_propagates(tmp_path):
    calls: list[list[str]] = []

    def runner(args: list[str]) -> str:
        calls.append(args)
        if args[0] == "scp":
            raise ConnectionError("trasferimento interrotto")
        return ""

    with pytest.raises(ConnectionError):
        export_history_db(
            ssh_host="h",
            ssh_user="u",
            remote_db_path="/opt/orchestrator/var/history/history.db",
            local_output_dir=tmp_path,
            now=datetime(2026, 7, 7, 12, 0, 0),
            run_command=runner,
        )

    # backup, poi scp (fallito), poi comunque il tentativo di cleanup
    assert [c[0] for c in calls] == ["ssh", "scp", "ssh"]
    assert calls[2][2] == "rm"
