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

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
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


class OhlcvSource(Protocol):
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list[list]: ...


def fetch_latest_returns(
    exchange: OhlcvSource, asset: str, limit: int = LOOKBACK_CANDLES
) -> pd.Series:
    """Rendimenti giornalieri delle ultime `limit` candele di `asset`/USDT
    (nessun `since`: ccxt restituisce le più recenti). Non l'intera storia
    dal 2019 come in M1.5 — approssimazione a precisione pratica
    dell'EWMA, vedi ADR-037 §10."""
    candles = exchange.fetch_ohlcv(f"{asset}/USDT", timeframe="1d", limit=limit)
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
) -> RegimeSnapshot:
    """Un ciclo di misura completo. Propaga qualunque eccezione (fetch,
    parsing, stato non finito) senza scrivere uno snapshot parziale o
    scorretto — il chiamante (`run_loop`) decide cosa fare di un ciclo
    fallito, questa funzione non deve mai "indovinare" un default."""
    btc_returns = fetch_latest_returns(exchange, "BTC")
    btc_vol = compute_ewma_vol(btc_returns, span=states.btc_vol.config.ewma_span).iloc[-1]
    btc_high_vol = states.btc_vol.update(float(btc_vol))

    eth_returns = fetch_latest_returns(exchange, "ETH")
    eth_vol = compute_ewma_vol(eth_returns, span=states.eth_vol.config.ewma_span).iloc[-1]
    eth_high_vol = states.eth_vol.update(float(eth_vol))

    funding_rate = funding_source.fetch("ETH")
    eth_harvester_on = states.eth_funding.update(float(funding_rate))

    snapshot = build_snapshot(btc_high_vol, eth_high_vol, eth_harvester_on, now=now)
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
    now_fn=datetime.utcnow,
) -> None:
    """Loop di produzione. `max_iterations=None` gira per sempre (uso
    reale, systemd); un intero finito è per `--once`/test/smoke test.

    Un ciclo fallito (`run_once` che solleva) NON interrompe il loop: si
    invia un alert e si passa al ciclo successivo, senza pingare
    l'healthcheck (pattern VIVO-MA-CIECO — il ping conferma solo che il
    lavoro è stato fatto, non solo che il processo è vivo). L'except largo
    qui è intenzionale ed è l'unico punto del codice dove è corretto: è il
    confine di resilienza del loop di produzione, non un tentativo di
    nascondere un bug — il messaggio include sempre l'eccezione reale."""
    initial_snapshot = resolve_initial_snapshot(store)
    states = RegimeDaemonStates.seeded_from(initial_snapshot, regime_config)

    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        try:
            run_once(exchange, funding_source, states, store, now=now_fn())
            healthcheck_sink.ping()
        except Exception as exc:  # noqa: BLE001 - confine di resilienza intenzionale, vedi docstring
            alert_sink.send(
                "LAYER CIECO — regime-daemon: ciclo di misura fallito "
                f"({exc!r}). Nessuno snapshot scritto in questo ciclo, "
                "il precedente resta valido fino alla soglia di staleness."
            )
        iteration += 1
        if max_iterations is None or iteration < max_iterations:
            sleep_fn(poll_interval.total_seconds())


def build_sinks(
    dry_run: bool,
    bot_token: str | None,
    chat_id: str | None,
    healthchecks_url: str | None,
) -> tuple[AlertSink, HealthcheckSink]:
    """Confine dry-run/reale (ADR-037 §10). In `--dry-run` nessuna
    credenziale è richiesta: i doppioni registrano soltanto. Fuori da
    dry-run, le tre credenziali sono TUTTE obbligatorie — mai un fallback
    silenzioso a dry-run se una manca, che nasconderebbe una
    misconfigurazione di produzione dietro un comportamento innocuo."""
    if dry_run:
        return DryRunAlertSink(), DryRunHealthcheckSink()
    if not (bot_token and chat_id and healthchecks_url):
        raise ValueError(
            "senza --dry-run servono TUTTE le credenziali reali: "
            "--bot-token, --chat-id, --healthchecks-url "
            "(mai un fallback silenzioso a dry-run per una credenziale mancante)."
        )
    return (
        TelegramAlertSink(bot_token=bot_token, chat_id=chat_id),
        HealthchecksPingSink(url=healthchecks_url),
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
    parser.add_argument("--bot-token", default=None)
    parser.add_argument("--chat-id", default=None)
    parser.add_argument("--healthchecks-url", default=None)
    args = parser.parse_args(argv)

    alert_sink, healthcheck_sink = build_sinks(
        dry_run=args.dry_run,
        bot_token=args.bot_token,
        chat_id=args.chat_id,
        healthchecks_url=args.healthchecks_url,
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
