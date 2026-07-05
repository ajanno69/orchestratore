"""Inventario VPS automatico (ADR-036 §5 punto 3-bis — lezione mft_engine:
'mai piu' processi non censiti'). Censisce unit systemd (attive E
disabilitate: mft_paper.service non compariva da sola in `list-units
--all`, serve anche `list-unit-files` — vedi
D:\\Claude\\crypto-agent\\docs\\DECOMMISSION-2026-07.md), timer, cron,
container docker, processi persistenti. Produce uno snapshot strutturato
e un diff vs lo snapshot precedente."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

CommandRunner = Callable[[list[str]], str]


def _default_command_runner(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    return result.stdout


@dataclass(frozen=True)
class InventorySnapshot:
    timestamp: str
    systemd_units: list[str] = field(default_factory=list)
    systemd_unit_files: list[str] = field(default_factory=list)
    cron_lines: list[str] = field(default_factory=list)
    docker_containers: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> InventorySnapshot:
        return InventorySnapshot(**data)


@dataclass(frozen=True)
class InventoryDiff:
    added: dict[str, list[str]]
    removed: dict[str, list[str]]

    @property
    def is_empty(self) -> bool:
        return not any(self.added.values()) and not any(self.removed.values())


_CATEGORIES = (
    "systemd_units",
    "systemd_unit_files",
    "cron_lines",
    "docker_containers",
    "processes",
)


class InventoryCollector:
    """SSH host/user parametrici (config/binari.yaml o argomento diretto).
    `run_command` iniettabile per test — nessuna chiamata SSH reale nei
    test unitari."""

    def __init__(
        self, ssh_host: str, ssh_user: str, run_command: CommandRunner = _default_command_runner
    ) -> None:
        self._ssh_host = ssh_host
        self._ssh_user = ssh_user
        self._run_command = run_command

    def _ssh(self, remote_command: str) -> str:
        return self._run_command(["ssh", f"{self._ssh_user}@{self._ssh_host}", remote_command])

    def collect(self, now: datetime | None = None) -> InventorySnapshot:
        ts = (now or datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")
        units_raw = self._ssh("systemctl list-units --all --type=service,timer --no-legend")
        unit_files_raw = self._ssh("systemctl list-unit-files --type=service,timer --no-legend")
        cron_raw = self._ssh(f"crontab -u {self._ssh_user} -l")
        docker_raw = self._ssh("docker ps -a --format '{{.Names}}\t{{.Status}}'")
        processes_raw = self._ssh("ps aux")

        return InventorySnapshot(
            timestamp=ts,
            systemd_units=_nonblank_lines(units_raw),
            systemd_unit_files=_nonblank_lines(unit_files_raw),
            cron_lines=_nonblank_lines(cron_raw),
            docker_containers=_nonblank_lines(docker_raw),
            processes=_nonblank_lines(processes_raw),
        )


def _nonblank_lines(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def diff_snapshots(previous: InventorySnapshot | None, current: InventorySnapshot) -> InventoryDiff:
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    prev_dict = previous.to_dict() if previous is not None else {}

    for category in _CATEGORIES:
        prev_set = set(prev_dict.get(category, []))
        curr_set = set(getattr(current, category))
        added[category] = sorted(curr_set - prev_set)
        removed[category] = sorted(prev_set - curr_set)

    return InventoryDiff(added=added, removed=removed)


class InventoryStore:
    """Snapshot storici su disco (uno per run, mai sovrascritti — a
    differenza di RegimeStateStore che tiene solo il corrente: qui serve
    lo storico per il diff settimanale). Il filename usa il timestamp
    COMPLETO (non solo la data) con `:` sostituiti da `-` per restare
    validi su Windows, es. `snapshot-2026-07-05T12-00-00Z.json` — così
    due run nello stesso giorno UTC non si sovrascrivono a vicenda."""

    def __init__(self, base_path: Path | str) -> None:
        self._base_path = Path(base_path)

    def save(self, snapshot: InventorySnapshot) -> Path:
        self._base_path.mkdir(parents=True, exist_ok=True)
        safe_timestamp = snapshot.timestamp.replace(":", "-")
        path = self._base_path / f"snapshot-{safe_timestamp}.json"
        path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
        return path

    def load_latest_before(self, exclude_path: Path) -> InventorySnapshot | None:
        candidates = sorted(p for p in self._base_path.glob("snapshot-*.json") if p != exclude_path)
        if not candidates:
            return None
        return InventorySnapshot.from_dict(json.loads(candidates[-1].read_text(encoding="utf-8")))
