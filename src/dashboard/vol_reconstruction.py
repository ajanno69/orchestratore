"""Ricostruzione EX-POST della vol EWMA per il grafico "principale"
richiesto in origine per la dashboard (finding di sessione: il daemon
calcola il valore numerico a ogni ciclo ma non lo persiste mai da nessuna
parte — vedi `docs/m2-shadow-dashboard-rendering-report-2026-07-07.md`).

**NON è il valore osservato dal daemon.** È un fetch INDIPENDENTE (stesso
percorso dati pubblico OKX di `regime_daemon`/M1.5, nessuna chiave) più un
ricalcolo con lo STESSO stimatore già approvato — `regime.vol_state.
compute_ewma_vol`, mai reimplementato — ma eseguito ORA, non le stesse
identiche candele che il daemon ha visto in tempo reale a ogni suo ciclo
storico. Piccole divergenze dal valore che il daemon avrebbe realmente
osservato sono attese (revisioni tardive delle candele OKX, timing del
fetch): la label sul grafico (vedi `dashboard.render`) lo dichiara.

Riuso deliberato di `components.regime_daemon.fetch_latest_returns` (sola
lettura, funzione già approvata) invece di una nuova implementazione di
fetch — stesso percorso dati, stessa guardia su candele insufficienti,
nessuna duplicazione della logica di fetch."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from components.regime_daemon import LOOKBACK_CANDLES, OhlcvSource, fetch_latest_returns
from regime.config import RegimeConfig
from regime.vol_state import compute_ewma_vol


@dataclass(frozen=True)
class VolSeries:
    asset: str
    vol: pd.Series  # indice: data (UTC), valore: vol EWMA annualizzata
    enter_threshold: float
    exit_threshold: float


def reconstruct_vol_series(
    exchange: OhlcvSource,
    asset: str,
    regime_config: RegimeConfig,
    limit: int = LOOKBACK_CANDLES,
) -> VolSeries:
    """Fetch + ricalcolo per un singolo asset. Soglie e span presi da
    `regime_config` (di norma `config/regime.yaml` via `load_regime_config`
    — mai hardcoded qui, per non poter divergere silenziosamente dal
    config realmente in uso)."""
    returns = fetch_latest_returns(exchange, asset, limit=limit)
    vol_config = regime_config.vol_by_asset[asset]
    vol = compute_ewma_vol(returns, span=vol_config.ewma_span)
    return VolSeries(
        asset=asset,
        vol=vol,
        enter_threshold=vol_config.enter_threshold,
        exit_threshold=vol_config.exit_threshold,
    )
