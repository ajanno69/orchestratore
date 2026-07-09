"""Entrypoint runtime del regime-daemon (ADR-037 §10, Binario A): misura —
candele OKX via ccxt -> EWMA vol -> macchina a stati con isteresi ->
`RegimeSnapshot` persistito. Processo separato dal `wiring-loop`
(`components.wiring_loop`): il fail-safe di staleness (ADR-037 §3)
presuppone che i due ruoli non condividano un processo, altrimenti un
blocco nella misura fermerebbe anche la capacità di dichiararsi "cieco".

Nessuna chiave richiesta: solo endpoint pubblici OHLCV/funding OKX (stesso
principio di `scripts/derive_vol_thresholds.py`, M1.5). Nessun ordine,
nessuna operazione autenticata."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pandas as pd

from alerting.sinks import (
    AlertSink,
    DryRunAlertSink,
    DryRunHealthcheckSink,
    HealthcheckSink,
    HealthchecksPingSink,
    TelegramAlertSink,
)
from regime.config import RegimeConfig
from regime.funding_state import FundingRateSource, FundingRegimeState
from regime.store import RegimeSnapshot, RegimeStateStore, build_snapshot, resolve_initial_snapshot
from regime.vol_state import VolRegimeState, compute_ewma_vol

DEFAULT_POLL_INTERVAL = timedelta(minutes=15)  # ADR-037 §10

LOOKBACK_CANDLES = 200  # ADR-037 §10: ~6x ewma_span=32, decadimento esponenziale del filtro
MIN_CANDLES_FRACTION = 0.5  # sotto meta' delle candele richieste: fetch parziale, mai silenzioso

# Resilienza rete (finding 2026-07-09, diagnosi read-only su VPS Contabo:
# docs/m2-shadow-network-resilience-finding-2026-07-09.md — 12 cicli falliti
# per NetworkError verso OKX in 43h di shadow, ~1 ogni 3-4h, causa isolata,
# non un problema del nostro client). Due livelli di resilienza distinti,
# repo-only fino al gate 21/07:
FETCH_MAX_ATTEMPTS = 3  # 1 tentativo iniziale + 2 retry, assorbe blip sub-minuto
FETCH_RETRY_BACKOFF_SECONDS = 2.0  # backoff lineare: 2s prima del 2°, 4s prima del 3°
CONSECUTIVE_FAILURES_BEFORE_ALERT = 2  # Andrea 2026-07-09, margine sotto staleness (60min/4 cicli)


def _call_with_retry(fn, max_attempts: int, backoff_seconds: float, sleep_fn=time.sleep):
    """Retry con backoff LINEARE (`backoff_seconds * tentativo`) per
    assorbire blip di rete momentanei (sub-minuto) prima che l'intero
    ciclo di misura sia considerato fallito. `max_attempts` è il numero
    TOTALE di tentativi (incluso il primo, non solo i retry). Propaga
    l'ULTIMA eccezione se tutti i tentativi falliscono — `run_once`/
    `run_loop` restano gli unici punti che decidono cosa fare di un
    ciclo davvero fallito, questa funzione si limita ad assorbire i blip
    più brevi del budget di retry, mai a nascondere un guasto reale."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - si vuole ritentare QUALUNQUE eccezione di rete
            last_exc = exc
            if attempt < max_attempts:
                sleep_fn(backoff_seconds * attempt)
    raise last_exc  # max_attempts >= 1 garantisce che last_exc sia stato assegnato


class OhlcvSource(Protocol):
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]: ...


def fetch_latest_returns(
    exchange: OhlcvSource, asset: str, limit: int = LOOKBACK_CANDLES
) -> pd.Series:
    """Rendimenti giornalieri delle ultime `limit` candele di `asset`/USDT
    (nessun `since`: ccxt restituisce le più recenti). Non l'intera storia
    dal 2019 come in M1.5 — approssimazione a precisione pratica
    dell'EWMA, vedi ADR-037 §10.

    Rifiuta esplicitamente un fetch che restituisce molte meno candele del
    richiesto (finding review indipendente checkpoint pre-deploy): un
    endpoint parziale, un nuovo listing, o un downtime non devono produrre
    un vol calcolato silenziosamente su dati insufficienti — `VolRegimeState`
    confronterebbe quel vol con soglie calibrate su ~200 punti senza che
    nessuno se ne accorga (nessuna eccezione, nessun alert: `compute_ewma_vol`
    solleva solo sul caso ESTREMO di zero rendimenti, non su "pochi
    rendimenti"). Stessa filosofia di auto-invalidazione già in uso in
    `vol_state`/`hysteresis`, estesa qui al caso "dati insufficienti"."""
    candles = exchange.fetch_ohlcv(f"{asset}/USDT", timeframe="1d", limit=limit)
    min_candles = int(limit * MIN_CANDLES_FRACTION)
    if len(candles) < min_candles:
        raise ValueError(
            f"candele insufficienti per {asset}/USDT: ricevute {len(candles)}, "
            f"richieste {limit} (minimo accettabile {min_candles}). Fetch "
            "parziale o endpoint degradato — non si calcola un vol su dati "
            "insufficienti."
        )
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset="date").set_index("date").sort_index()
    return df["close"].pct_change().dropna()


@dataclass
class RegimeDaemonStates:
    btc_vol: VolRegimeState
    eth_vol: VolRegimeState
    eth_funding: FundingRegimeState

    @staticmethod
    def seeded_from(
        initial_snapshot: RegimeSnapshot, regime_config: RegimeConfig
    ) -> RegimeDaemonStates:
        """Semina gli stati dall'ultimo snapshot persistito (mai dal
        default `False` della dataclass) — contratto di riavvio M1
        (`regime.store.resolve_initial_snapshot`), verificato qui non solo
        dichiarato: vedi ADR-037 §10 e i test dedicati."""
        return RegimeDaemonStates(
            btc_vol=VolRegimeState(
                config=regime_config.vol_by_asset["BTC"],
                is_high_vol=initial_snapshot.btc_high_vol,
            ),
            eth_vol=VolRegimeState(
                config=regime_config.vol_by_asset["ETH"],
                is_high_vol=initial_snapshot.eth_high_vol,
            ),
            eth_funding=FundingRegimeState(
                config=regime_config.funding_by_asset["ETH"],
                is_harvester_on=initial_snapshot.eth_harvester_on,
            ),
        )


def run_once(
    exchange: OhlcvSource,
    funding_source: FundingRateSource,
    states: RegimeDaemonStates,
    store: RegimeStateStore,
    now: datetime,
    sleep_fn=time.sleep,
) -> RegimeSnapshot:
    """Un ciclo di misura completo. Propaga qualunque eccezione (fetch,
    parsing, stato non finito) senza scrivere uno snapshot parziale o
    scorretto — il chiamante (`run_loop`) decide cosa fare di un ciclo
    fallito, questa funzione non deve mai "indovinare" un default.

    Le tre chiamate di rete (candele BTC, candele ETH, funding rate) sono
    avvolte in `_call_with_retry`: un blip singolo viene assorbito qui,
    senza mai emergere come "ciclo fallito" a `run_loop` (finding
    2026-07-09, vedi costanti `FETCH_MAX_ATTEMPTS`/
    `FETCH_RETRY_BACKOFF_SECONDS` sopra)."""
    btc_returns = _call_with_retry(
        lambda: fetch_latest_returns(exchange, "BTC"),
        max_attempts=FETCH_MAX_ATTEMPTS,
        backoff_seconds=FETCH_RETRY_BACKOFF_SECONDS,
        sleep_fn=sleep_fn,
    )
    btc_vol = compute_ewma_vol(btc_returns, span=states.btc_vol.config.ewma_span).iloc[-1]
    btc_high_vol = states.btc_vol.update(float(btc_vol))

    eth_returns = _call_with_retry(
        lambda: fetch_latest_returns(exchange, "ETH"),
        max_attempts=FETCH_MAX_ATTEMPTS,
        backoff_seconds=FETCH_RETRY_BACKOFF_SECONDS,
        sleep_fn=sleep_fn,
    )
    eth_vol = compute_ewma_vol(eth_returns, span=states.eth_vol.config.ewma_span).iloc[-1]
    eth_high_vol = states.eth_vol.update(float(eth_vol))

    funding_rate = _call_with_retry(
        lambda: funding_source.fetch("ETH"),
        max_attempts=FETCH_MAX_ATTEMPTS,
        backoff_seconds=FETCH_RETRY_BACKOFF_SECONDS,
        sleep_fn=sleep_fn,
    )
    eth_harvester_on = states.eth_funding.update(float(funding_rate))

    snapshot = build_snapshot(
        btc_high_vol,
        eth_high_vol,
        eth_harvester_on,
        now=now,
        btc_ewma_vol=float(btc_vol),
        eth_ewma_vol=float(eth_vol),
    )
    store.write(snapshot)
    return snapshot


def run_loop(
    exchange: OhlcvSource,
    funding_source: FundingRateSource,
    store: RegimeStateStore,
    regime_config: RegimeConfig,
    poll_interval: timedelta,
    alert_sink: AlertSink,
    healthcheck_sink: HealthcheckSink,
    max_iterations: int | None = None,
    sleep_fn=time.sleep,
    now_fn=lambda: datetime.now(UTC),
    consecutive_failures_before_alert: int = CONSECUTIVE_FAILURES_BEFORE_ALERT,
) -> None:
    """Loop di produzione. `max_iterations=None` gira per sempre (uso
    reale, systemd); un intero finito è per `--once`/test/smoke test.

    Un ciclo fallito (`run_once` che solleva, dopo aver esaurito anche il
    retry intra-ciclo) NON interrompe il loop: si passa al ciclo
    successivo, senza pingare l'healthcheck (pattern VIVO-MA-CIECO — il
    ping conferma solo che il lavoro è stato fatto, non solo che il
    processo è vivo). L'except largo qui è intenzionale ed è l'unico
    punto del codice dove è corretto: è il confine di resilienza del loop
    di produzione, non un tentativo di nascondere un bug — il messaggio
    include sempre l'eccezione reale.

    L'ALERT (non il fail-safe: nessuno snapshot viene MAI scritto su un
    ciclo fallito, a prescindere) è inviato solo quando i fallimenti
    CONSECUTIVI raggiungono `consecutive_failures_before_alert` (finding
    2026-07-09: 12 alert in 43h di shadow per singoli blip di rete isolati
    — rumore, non segnale). Una volta raggiunta la soglia, l'alert viene
    inviato su OGNI ciclo ancora fallito, non solo la prima volta (stesso
    principio già imparato con `WiringSequencer`: un design che tace
    durante un problema prolungato è un bug). Il contatore si azzera su
    ogni ciclo riuscito — non è mai un budget "consumato una volta per
    sempre" per il processo.

    Anche l'invio dell'alert stesso è protetto (finding review
    indipendente, ADR-037 §10): se il canale di alert è irraggiungibile
    proprio mentre il ciclo di misura fallisce (scenario realistico,
    correlato — es. rete del VPS giù, OKX e Telegram irraggiungibili
    insieme), il fallimento dell'invio NON deve propagare e uccidere il
    loop — altrimenti il pattern VIVO-MA-CIECO diventerebbe MORTO-E-MUTO,
    esattamente il rischio già dichiarato in ADR-037 §8. Ultima risorsa:
    stderr (catturato da systemd nel journal), mai un'eccezione.

    Un `healthcheck_sink.ping()` fallito DOPO che `run_once` ha già
    scritto con successo lo snapshot (finding review 33a477c, chiuso
    2026-07-09) NON è un ciclo di misura fallito: la misura è riuscita,
    lo snapshot esiste. Non deve incrementare `consecutive_failures` né
    generare un alert LAYER CIECO — il mancato ping è già rilevato da
    healthchecks.io per costruzione (il check risulta in ritardo da
    solo), un secondo canale di notifica qui duplicherebbe rumore senza
    aggiungere segnale. `try/except/else` separa esplicitamente le due
    cause: l'`except` cattura SOLO un fallimento di `run_once`, l'`else`
    gestisce il ping (eseguito solo se `run_once` non ha sollevato)."""
    initial_snapshot = resolve_initial_snapshot(store)
    states = RegimeDaemonStates.seeded_from(initial_snapshot, regime_config)

    iteration = 0
    consecutive_failures = 0
    while max_iterations is None or iteration < max_iterations:
        try:
            run_once(exchange, funding_source, states, store, now=now_fn(), sleep_fn=sleep_fn)
        except Exception as exc:  # noqa: BLE001 - confine di resilienza intenzionale, vedi docstring
            consecutive_failures += 1
            if consecutive_failures >= consecutive_failures_before_alert:
                message = (
                    "LAYER CIECO — regime-daemon: ciclo di misura fallito "
                    f"({exc!r}). {consecutive_failures} fallimenti consecutivi. "
                    "Nessuno snapshot scritto in questo ciclo, il precedente "
                    "resta valido fino alla soglia di staleness."
                )
                try:
                    alert_sink.send(message)
                except Exception as alert_exc:  # noqa: BLE001 - vedi docstring, mai propagare da qui
                    print(
                        f"[regime-daemon] impossibile inviare l'alert di ciclo fallito: "
                        f"{alert_exc!r} (causa originale del ciclo fallito: {exc!r})",
                        file=sys.stderr,
                    )
        else:
            consecutive_failures = 0
            try:
                healthcheck_sink.ping()
            except Exception as ping_exc:  # noqa: BLE001 - vedi docstring, mai propagare da qui
                print(
                    f"[regime-daemon] ping healthcheck fallito dopo una misura riuscita: "
                    f"{ping_exc!r} — la misura NON e' fallita, nessun alert CIECO da qui "
                    "(il check risulta comunque in ritardo su healthchecks.io per costruzione).",
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
    """Confine dry-run/reale (ADR-037 §10). In `--dry-run` nessuna
    credenziale è richiesta: i doppioni registrano soltanto.

    Incident 2026-07-07 (vedi docs/m2-deploy-runbook.md, sezione
    incident): le credenziali reali NON sono più accettate come
    parametri/argomenti CLI — un'unit systemd che le passasse via
    `${VAR}` in `ExecStart` le metterebbe nell'argv del processo,
    visibile in chiaro via `/proc/PID/cmdline`/`ps aux` a chiunque abbia
    accesso alla macchina. Si leggono SOLO da un mapping (di norma
    `os.environ`, popolato da `EnvironmentFile` — mai visibile in argv)
    iniettato qui per testabilità. Se una manca, `ValueError` esplicito
    che la nomina — mai un avvio mezzo-configurato, mai un fallback
    silenzioso a dry-run."""
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

    import ccxt

    from regime.config import load_regime_config
    from regime.funding_state import CcxtOkxFundingRateSource

    parser = argparse.ArgumentParser(description="regime-daemon (ADR-037 §10)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true", help="un solo ciclo, poi esce")
    parser.add_argument("--config", default="config/regime.yaml")
    parser.add_argument("--state-dir", default=".")
    args = parser.parse_args(argv)

    alert_sink, healthcheck_sink = build_sinks(
        dry_run=args.dry_run,
        healthchecks_env_var="HEALTHCHECKS_PING_URL_REGIME_DAEMON",
    )

    regime_config = load_regime_config(args.config)
    store = RegimeStateStore(args.state_dir)
    exchange = ccxt.okx()
    funding_source = CcxtOkxFundingRateSource(exchange)

    run_loop(
        exchange,
        funding_source,
        store,
        regime_config,
        poll_interval=DEFAULT_POLL_INTERVAL,
        alert_sink=alert_sink,
        healthcheck_sink=healthcheck_sink,
        max_iterations=1 if args.once else None,
    )


if __name__ == "__main__":
    main()
