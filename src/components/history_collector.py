"""Terza unit runtime: collector di storia per il regime layer (sessione
shadow 2026-07-07, progetto collaterale — VINCOLO SOVRANO: sola lettura
di `regime_state.json`, MAI una scrittura lì, MAI una modifica a
`regime_daemon`/`wiring_loop`/alle loro unit esistenti).

Perché esiste: Task 0 (censimento) ha verificato che oggi non esiste da
nessuna parte una storia consultabile del regime layer — `RegimeStateStore`
persiste solo l'ultimo snapshot (mai una storia), e journald delle due
unit esistenti contiene solo eventi di ciclo di vita systemd (Started/
Stopping), zero dati applicativi, perché i sink reali sono silenziosi sul
successo per design. Senza questo collector, l'istruttoria del gate G3
non avrebbe alcuna serie storica su cui basarsi.

Schema (vedi `HistoryStore.init_schema`): colonne FATTO sono i campi dello
snapshot così come letti (`btc_high_vol`, `eth_high_vol`,
`eth_harvester_on`); colonne `derived_*` sono un'INFERENZA STATELESS
ricalcolata da questo collector, con la propria istanza di
`WiringSequencer`, richiamando le stesse funzioni pure e già approvate del
wiring-loop (`resolve_wiring_decision`, `WiringSequencer.process`) in sola
osservazione. Queste due categorie POSSONO LEGITTIMAMENTE DIVERGERE dal
comportamento del wiring-loop reale in quello stesso istante — storia del
sequencer diversa (restart in momenti diversi), cadenza di poll diversa,
eventuali versioni di codice diverse. **La verità sugli alert REALMENTE
inviati resta il canale Telegram**: una divergenza rilevata leggendo
questa storia al gate è un finding da investigare, non un bug della
dashboard che la legge.

Pattern di storage riusato da `copy-selector` (repo isolato, archiviato,
"designato al riuso" — solo il PATTERN, non il codice, per policy di
isolamento tra progetti): SQLite append-only, WAL, PK naturale,
`INSERT OR IGNORE`, mai `UPDATE`/`DELETE`. Pattern di osservabilità
"alive-but-blind" (`compute_run_health` di copy-selector) riadattato qui:
non "righe scritte in questo run" (qui la maggioranza dei cicli sono
dedup legittimi, un daemon a 15' con un collector a 5'), ma "tempo dall'
ultima riga NUOVA inserita" — un processo che gira senza eccezioni ma non
fa crescere la storia da troppo tempo è comunque un guasto da segnalare."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alerting.sinks import (
    AlertSink,
    DryRunAlertSink,
    DryRunHealthcheckSink,
    HealthcheckSink,
    HealthchecksPingSink,
    TelegramAlertSink,
)
from components.regime_wiring import (
    GridBtcHighVolAction,
    StalenessPolicy,
    load_snapshot_safely,
    resolve_wiring_decision,
)
from components.wiring_sequencer import RateLimitPolicy, WiringSequencer
from regime.store import RegimeSnapshot, RegimeStateStore

DEFAULT_POLL_INTERVAL = timedelta(minutes=5)
ALIVE_BUT_BLIND_THRESHOLD = timedelta(
    minutes=60
)  # stessa soglia di staleness del wiring-loop (ADR-037 §9/§10), per coerenza

DEFAULT_STALENESS = StalenessPolicy(max_age=timedelta(hours=1))
DEFAULT_RATE_LIMIT = RateLimitPolicy(window=timedelta(hours=1), max_transitions=3)
DEFAULT_GRIDBTC_ACTION = (
    GridBtcHighVolAction.STOP_NEW_ORDERS
)  # inerte, stesso placeholder di wiring_loop

TG_BOT_TOKEN_ENV = "TG_ALERT_BOT_TOKEN"
TG_CHAT_ID_ENV = "TG_ALERT_CHAT_ID"
HEALTHCHECKS_ENV_VAR = "HEALTHCHECKS_PING_URL_HISTORY_COLLECTOR"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class DerivedFields:
    harvester_command: str
    gridbtc_command: str
    alert: bool
    alert_category: str | None
    alert_text: str | None


def compute_derived_fields(
    snapshot: RegimeSnapshot,
    sequencer: WiringSequencer,
    now: datetime,
    staleness: StalenessPolicy = DEFAULT_STALENESS,
    gridbtc_action: GridBtcHighVolAction = DEFAULT_GRIDBTC_ACTION,
) -> DerivedFields:
    """Osservazione stateless via le stesse componenti pure e già approvate
    del wiring-loop (non le reimplementa). `sequencer` è di proprietà del
    chiamante — la sua storia determina se compare un `alert_category`
    (edge-triggered, come nel wiring-loop reale)."""
    decision = resolve_wiring_decision(
        snapshot, now=now, staleness=staleness, gridbtc_high_vol_action=gridbtc_action
    )
    output = sequencer.process(decision, now=now)
    if output.alerts:
        alert_event = output.alerts[-1]
        alert_category: str | None = alert_event.category.value
        alert_text: str | None = alert_event.text
    else:
        alert_category = None
        alert_text = None
    return DerivedFields(
        harvester_command=decision.harvester_command.value,
        gridbtc_command=decision.gridbtc_command.value,
        alert=decision.alert,
        alert_category=alert_category,
        alert_text=alert_text,
    )


def is_alive_but_blind(reference_time: datetime, now: datetime, threshold: timedelta) -> bool:
    """Pura: True se non è arrivata una riga nuova da più di `threshold`
    rispetto a `reference_time` (ultima riga nuova, o inizio raccolta se
    non c'è mai stata nessuna riga)."""
    return (now - reference_time) > threshold


class HistoryStore:
    """Storage append-only SQLite (pattern copy-selector, non il codice —
    vedi docstring di modulo). PK naturale = `snapshot_timestamp`."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self.init_schema()

    def init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS regime_history (
                snapshot_timestamp        TEXT PRIMARY KEY,
                btc_high_vol               INTEGER NOT NULL,
                eth_high_vol               INTEGER NOT NULL,
                eth_harvester_on           INTEGER NOT NULL,
                collected_at               TEXT NOT NULL,
                derived_harvester_command  TEXT NOT NULL,
                derived_gridbtc_command    TEXT NOT NULL,
                derived_alert              INTEGER NOT NULL,
                derived_alert_category     TEXT,
                derived_alert_text         TEXT
            )
            """
        )

    def record_collection_start(self, now: datetime) -> None:
        """Idempotente: mai sovrascritto dopo la prima chiamata riuscita —
        Andrea, backfill zero dichiarato: il gate deve sapere da quando
        parte la serie, non da quando è stata riavviata l'ultima volta."""
        self._conn.execute(
            "INSERT OR IGNORE INTO _meta (key, value) VALUES ('collection_started_at', ?)",
            (_iso(now),),
        )

    def collection_started_at(self) -> datetime | None:
        row = self._conn.execute(
            "SELECT value FROM _meta WHERE key = 'collection_started_at'"
        ).fetchone()
        return _parse_iso(row[0]) if row else None

    def last_new_row_at(self) -> datetime | None:
        row = self._conn.execute("SELECT value FROM _meta WHERE key = 'last_new_row_at'").fetchone()
        return _parse_iso(row[0]) if row else None

    def _set_last_new_row_at(self, when: datetime) -> None:
        self._conn.execute(
            "INSERT INTO _meta (key, value) VALUES ('last_new_row_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_iso(when),),
        )

    def insert_snapshot_row(
        self, snapshot: RegimeSnapshot, collected_at: datetime, derived: DerivedFields
    ) -> bool:
        """`INSERT OR IGNORE` (dedup gratis su PK) + verifica ESPLICITA che
        la riga sia presente dopo la scrittura — mai assumere che
        l'istruzione SQL abbia fatto ciò che doveva senza controllarlo
        (principio esplicitamente richiesto: comando+output, non fiducia)."""
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO regime_history (
                snapshot_timestamp, btc_high_vol, eth_high_vol, eth_harvester_on,
                collected_at, derived_harvester_command, derived_gridbtc_command,
                derived_alert, derived_alert_category, derived_alert_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.timestamp,
                int(snapshot.btc_high_vol),
                int(snapshot.eth_high_vol),
                int(snapshot.eth_harvester_on),
                _iso(collected_at),
                derived.harvester_command,
                derived.gridbtc_command,
                int(derived.alert),
                derived.alert_category,
                derived.alert_text,
            ),
        )
        inserted = cursor.rowcount > 0

        verified = self._conn.execute(
            "SELECT snapshot_timestamp FROM regime_history WHERE snapshot_timestamp = ?",
            (snapshot.timestamp,),
        ).fetchone()
        if verified is None:
            raise RuntimeError(
                f"riga non trovata dopo INSERT OR IGNORE per snapshot_timestamp="
                f"{snapshot.timestamp!r} — scrittura non verificata, mai assumerla riuscita."
            )

        if inserted:
            self._set_last_new_row_at(collected_at)
        return inserted

    def close(self) -> None:
        self._conn.close()


def run_once(
    store: RegimeStateStore,
    history: HistoryStore,
    sequencer: WiringSequencer,
    now: datetime,
) -> bool:
    """Un ciclo: sola lettura di `store` (mai una scrittura). Ritorna True
    se una riga NUOVA è stata inserita (per distinguere un dedup legittimo
    da una crescita reale della storia). Propaga qualunque eccezione —
    stessa disciplina di `regime_daemon.run_once`/`wiring_loop.run_once`."""
    snapshot = load_snapshot_safely(store)
    if snapshot is None:
        return False
    derived = compute_derived_fields(snapshot, sequencer, now=now)
    return history.insert_snapshot_row(snapshot, collected_at=now, derived=derived)


def run_loop(
    store: RegimeStateStore,
    history: HistoryStore,
    sequencer: WiringSequencer,
    alert_sink: AlertSink,
    healthcheck_sink: HealthcheckSink,
    poll_interval: timedelta,
    alive_but_blind_threshold: timedelta = ALIVE_BUT_BLIND_THRESHOLD,
    max_iterations: int | None = None,
    sleep_fn=time.sleep,
    now_fn=lambda: datetime.now(UTC),
) -> None:
    """Loop di produzione, stessa struttura/resilienza di
    `regime_daemon.run_loop`/`wiring_loop.run_loop`: un ciclo fallito invia
    un alert (mai propagato oltre, anche se l'invio dell'alert stesso
    fallisce — stesso doppio try/except già hardenato altrove) e NON pinga
    l'healthcheck, il loop continua.

    In aggiunta (specifico di questo collector): anche un ciclo che NON
    fallisce può rivelare un'anomalia "alive-but-blind" — il processo gira,
    legge, ma la storia non cresce da più di `alive_but_blind_threshold`.
    In quel caso: alert dedicato (testo distinguibile da un ciclo fallito),
    niente ping — stesso principio "il ping conferma solo che il lavoro
    utile è stato fatto", non solo che il processo è vivo."""
    now0 = now_fn()
    history.record_collection_start(now0)

    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        now = now_fn()
        try:
            run_once(store, history, sequencer, now=now)
            reference = history.last_new_row_at() or history.collection_started_at() or now
            if is_alive_but_blind(reference, now, alive_but_blind_threshold):
                message = (
                    "STORIA FERMA — history-collector: nessuna riga nuova da "
                    f"{now - reference} (soglia {alive_but_blind_threshold}). Il processo gira "
                    "senza eccezioni ma la storia per il gate G3 non cresce."
                )
                try:
                    alert_sink.send(message)
                except Exception as alert_exc:  # noqa: BLE001 - mai propagare da qui
                    print(
                        f"[history-collector] impossibile inviare l'alert alive-but-blind: "
                        f"{alert_exc!r}",
                        file=sys.stderr,
                    )
            else:
                healthcheck_sink.ping()
        except Exception as exc:  # noqa: BLE001 - confine di resilienza intenzionale, vedi docstring
            message = f"COLLECTOR GUASTO — history-collector: ciclo fallito ({exc!r})."
            try:
                alert_sink.send(message)
            except Exception as alert_exc:  # noqa: BLE001 - vedi docstring, mai propagare da qui
                print(
                    f"[history-collector] impossibile inviare l'alert di ciclo fallito: "
                    f"{alert_exc!r} (causa originale del ciclo fallito: {exc!r})",
                    file=sys.stderr,
                )
        iteration += 1
        if max_iterations is None or iteration < max_iterations:
            sleep_fn(poll_interval.total_seconds())


def build_sinks(
    dry_run: bool,
    env: Mapping[str, str] | None = None,
) -> tuple[AlertSink, HealthcheckSink]:
    """Stesso contratto di `regime_daemon.build_sinks`/`wiring_loop.build_sinks`
    (duplicato deliberatamente, stesso motivo: processi indipendenti) —
    credenziali SOLO da un mapping iniettabile (di norma `os.environ`), mai
    da CLI/argv (incident 2026-07-07, vedi `docs/m2-deploy-runbook.md`)."""
    if dry_run:
        return DryRunAlertSink(), DryRunHealthcheckSink()

    env = env if env is not None else os.environ
    required = (TG_BOT_TOKEN_ENV, TG_CHAT_ID_ENV, HEALTHCHECKS_ENV_VAR)
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise ValueError(
            f"variabili d'ambiente mancanti per l'esecuzione reale: {', '.join(missing)}. "
            "Impostarle in EnvironmentFile (mai passarle da CLI: finirebbero in argv, "
            "visibili via /proc/PID/cmdline) — mai un avvio mezzo-configurato."
        )
    return (
        TelegramAlertSink(bot_token=env[TG_BOT_TOKEN_ENV], chat_id=env[TG_CHAT_ID_ENV]),
        HealthchecksPingSink(url=env[HEALTHCHECKS_ENV_VAR]),
    )


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="history-collector (sessione shadow 2026-07-07)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true", help="un solo ciclo, poi esce")
    parser.add_argument(
        "--regime-state-dir",
        default=".",
        help="directory di regime_state.json (SOLA LETTURA, mai scritta da questo processo)",
    )
    parser.add_argument("--db-path", default="var/history/history.db")
    args = parser.parse_args(argv)

    alert_sink, healthcheck_sink = build_sinks(dry_run=args.dry_run)

    store = RegimeStateStore(args.regime_state_dir)
    history = HistoryStore(args.db_path)
    sequencer = WiringSequencer(rate_limit=DEFAULT_RATE_LIMIT)

    run_loop(
        store,
        history,
        sequencer,
        alert_sink,
        healthcheck_sink,
        poll_interval=DEFAULT_POLL_INTERVAL,
        max_iterations=1 if args.once else None,
    )


if __name__ == "__main__":
    main()
