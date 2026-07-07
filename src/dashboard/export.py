"""Estrazione consistente del DB di storia (sessione rendering locale
2026-07-07). VINCOLO SOVRANO: sola lettura sul database remoto — mai una
scrittura, mai una modifica al VPS/alle unit/al database originale.

Il DB è SQLite in WAL mode aggiornato da un processo VIVO
(history-collector, ADR-037 §10). Copiare il file `.db` a freddo (es. un
`scp` diretto) rischia uno snapshot incoerente — pagine WAL non ancora
integrate nel file principale, o una scrittura del collector a metà.
Uso l'Online Backup API di `sqlite3` (stdlib, identica in locale e sul
VPS) per produrre un file temporaneo CONSISTENTE sul VPS stesso — quello
è ciò che viene poi scaricato con `scp` e, subito dopo, cancellato dal
VPS. Nessun file temporaneo lasciato in giro, in nessun caso (anche se lo
`scp` fallisce, il cleanup viene comunque tentato)."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CommandRunner = Callable[[list[str]], str]


def _default_command_runner(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return result.stdout


def remote_tmp_path(now: datetime) -> str:
    return f"/tmp/history_export_{now.strftime('%Y%m%dT%H%M%SZ')}.db"


def _build_remote_backup_command(remote_db_path: str, remote_tmp_path_value: str) -> str:
    """Comando remoto come UNA sola stringa già shell-quotata (round-trip
    corretto con `shlex.split`, come la eseguirebbe bash sul VPS) — evita
    l'ambiguità del ri-concatenamento che ssh farebbe su più argv
    separati. `!r` (repr Python) per i literal dentro lo snippet Python,
    `shlex.quote` per l'involucro shell esterno — due livelli di quoting
    distinti e corretti ciascuno per il proprio strato."""
    snippet = (
        "import sqlite3; "
        f"src = sqlite3.connect({remote_db_path!r}); "
        f"dst = sqlite3.connect({remote_tmp_path_value!r}); "
        "src.backup(dst); "
        "dst.close(); "
        "src.close(); "
        "print('BACKUP_OK')"
    )
    return f"python3 -c {shlex.quote(snippet)}"


@dataclass(frozen=True)
class ExportResult:
    local_path: Path
    remote_tmp_path: str
    backup_output: str
    scp_output: str
    cleanup_output: str


def export_history_db(
    ssh_host: str,
    ssh_user: str,
    remote_db_path: str,
    local_output_dir: Path | str,
    now: datetime,
    run_command: CommandRunner = _default_command_runner,
) -> ExportResult:
    """Sola lettura sul DB remoto: backup consistente → pull via scp →
    cleanup del temporaneo remoto. Se il backup fallisce, propaga subito
    (nessun file da scaricare/pulire). Se lo `scp` fallisce, il cleanup
    del temporaneo viene comunque tentato prima che l'errore propaghi —
    mai un file temporaneo abbandonato sul VPS per un errore a metà."""
    tmp_path = remote_tmp_path(now)
    backup_command = _build_remote_backup_command(remote_db_path, tmp_path)
    backup_output = run_command(["ssh", f"{ssh_user}@{ssh_host}", backup_command])

    local_output_dir = Path(local_output_dir)
    local_output_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_output_dir / Path(tmp_path).name

    try:
        scp_output = run_command(["scp", f"{ssh_user}@{ssh_host}:{tmp_path}", str(local_path)])
    finally:
        cleanup_output = run_command(["ssh", f"{ssh_user}@{ssh_host}", "rm", tmp_path])

    return ExportResult(
        local_path=local_path,
        remote_tmp_path=tmp_path,
        backup_output=backup_output,
        scp_output=scp_output,
        cleanup_output=cleanup_output,
    )
