"""Entrypoint runtime del wiring-loop (ADR-037 §10, Binario A): decisione —
`RegimeSnapshot` -> `resolve_wiring_decision` -> `WiringSequencer` -> alert
sul canale esterno. Processo separato dal `regime-daemon`
(`components.regime_daemon`): legge solo un file locale, nessuna chiamata
di rete salvo l'invio degli alert e il ping dell'healthcheck.

Non esegue nessuna azione (ADR-037 §7): produce solo alert (dati verso
l'esterno). Nessun comando viene mai eseguito qui — un executor separato,
non ancora costruito, resta fuori scope."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

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
    WiringDecision,
    load_snapshot_safely,
    resolve_wiring_decision,
)
from components.wiring_sequencer import RateLimitPolicy, WiringSequencer
from regime.store import RegimeStateStore

DEFAULT_POLL_INTERVAL = timedelta(minutes=5)  # ADR-037 §10


def run_once(
    store: RegimeStateStore,
    sequencer: WiringSequencer,
    staleness: StalenessPolicy,
    gridbtc_high_vol_action: GridBtcHighVolAction,
    alert_sink: AlertSink,
    now: datetime,
) -> WiringDecision:
    """Un ciclo di decisione completo. Propaga qualunque eccezione (lettura
    store, ecc.) — il chiamante (`run_loop`) decide cosa fare di un ciclo
    fallito, stessa disciplina di `regime_daemon.run_once`."""
    snapshot = load_snapshot_safely(store)
    decision = resolve_wiring_decision(
        snapshot, now=now, staleness=staleness, gridbtc_high_vol_action=gridbtc_high_vol_action
    )
    output = sequencer.process(decision, now=now)
    for event in output.alerts:
        alert_sink.send(event.text)
    return decision


def run_loop(
    store: RegimeStateStore,
    sequencer: WiringSequencer,
    staleness: StalenessPolicy,
    gridbtc_high_vol_action: GridBtcHighVolAction,
    alert_sink: AlertSink,
    healthcheck_sink: HealthcheckSink,
    poll_interval: timedelta,
    max_iterations: int | None = None,
    sleep_fn=time.sleep,
    now_fn=lambda: datetime.now(UTC),
) -> None:
    """Loop di produzione, stessa struttura di `regime_daemon.run_loop`:
    un ciclo fallito invia un alert e NON pinga l'healthcheck (VIVO-MA-CIECO),
    il loop continua. `sequencer` va costruito fresco a ogni avvio di
    processo dal chiamante (`main`) — il contratto di riavvio vive in
    `WiringSequencer` stesso (ADR-037 §9), qui si riusa senza reinventarlo.

    Anche l'invio dell'alert è protetto (finding review indipendente,
    ADR-037 §10, stessa motivazione di `regime_daemon.run_loop`): un
    fallimento del canale di alert durante la gestione di un ciclo fallito
    non deve propagare — ultima risorsa stderr, mai un'eccezione che
    ucciderebbe il loop."""
    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        try:
            run_once(
                store, sequencer, staleness, gridbtc_high_vol_action, alert_sink, now=now_fn()
            )
            healthcheck_sink.ping()
        except Exception as exc:  # noqa: BLE001 - confine di resilienza intenzionale, vedi regime_daemon
            message = f"LAYER CIECO — wiring-loop: ciclo di decisione fallito ({exc!r})."
            try:
                alert_sink.send(message)
            except Exception as alert_exc:  # noqa: BLE001 - vedi docstring, mai propagare da qui
                print(
                    f"[wiring-loop] impossibile inviare l'alert di ciclo fallito: "
                    f"{alert_exc!r} (causa originale del ciclo fallito: {exc!r})",
                    file=sys.stderr,
                )
        iteration += 1
        if max_iterations is None or iteration < max_iterations:
            sleep_fn(poll_interval.total_seconds())


TG_BOT_TOKEN_ENV = "TG_ALERT_BOT_TOKEN"
TG_CHAT_ID_ENV = "TG_ALERT_CHAT_ID"


def build_sinks(
    dry_run: bool,
    healthchecks_env_var: str,
    env: Mapping[str, str] | None = None,
) -> tuple[AlertSink, HealthcheckSink]:
    """Stessa logica di `regime_daemon.build_sinks` — duplicata
    deliberatamente (non estratta in un modulo condiviso) perché i due
    entrypoint sono processi indipendenti (ADR-037 §10) con il proprio
    ciclo di vita di configurazione; un'estrazione prematura creerebbe un
    accoppiamento tra due processi pensati per essere disaccoppiati.

    Incident 2026-07-07 (vedi docs/m2-deploy-runbook.md, sezione
    incident): le credenziali reali NON sono più accettate come
    parametri/argomenti CLI — finirebbero nell'argv del processo,
    visibile via `/proc/PID/cmdline`. Si leggono SOLO da un mapping (di
    norma `os.environ`) iniettato per testabilità."""
    if dry_run:
        return DryRunAlertSink(), DryRunHealthcheckSink()

    env = env if env is not None else os.environ
    required = (TG_BOT_TOKEN_ENV, TG_CHAT_ID_ENV, healthchecks_env_var)
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise ValueError(
            f"variabili d'ambiente mancanti per l'esecuzione reale: {', '.join(missing)}. "
            "Impostarle in EnvironmentFile (mai passarle da CLI: finirebbero in argv, "
            "visibili via /proc/PID/cmdline) — mai un avvio mezzo-configurato."
        )
    return (
        TelegramAlertSink(bot_token=env[TG_BOT_TOKEN_ENV], chat_id=env[TG_CHAT_ID_ENV]),
        HealthchecksPingSink(url=env[healthchecks_env_var]),
    )


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="wiring-loop (ADR-037 §10)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true", help="un solo ciclo, poi esce")
    parser.add_argument("--state-dir", default=".")
    parser.add_argument("--staleness-minutes", type=int, default=60)
    parser.add_argument(
        "--gridbtc-action",
        default="stop_new_orders",
        choices=[a.value for a in GridBtcHighVolAction],
        help=(
            "inerte oggi (GridBTC condizionale, nessun bot live) - "
            "vedi docs/gridbtc-highvol-analysis-m2.md"
        ),
    )
    args = parser.parse_args(argv)

    alert_sink, healthcheck_sink = build_sinks(
        dry_run=args.dry_run,
        healthchecks_env_var="HEALTHCHECKS_PING_URL_WIRING_LOOP",
    )

    store = RegimeStateStore(args.state_dir)
    sequencer = WiringSequencer(
        rate_limit=RateLimitPolicy(window=timedelta(hours=1), max_transitions=3)
    )
    staleness = StalenessPolicy(max_age=timedelta(minutes=args.staleness_minutes))
    gridbtc_action = GridBtcHighVolAction(args.gridbtc_action)

    run_loop(
        store,
        sequencer,
        staleness,
        gridbtc_action,
        alert_sink,
        healthcheck_sink,
        poll_interval=DEFAULT_POLL_INTERVAL,
        max_iterations=1 if args.once else None,
    )


if __name__ == "__main__":
    main()
