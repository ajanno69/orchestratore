"""Script di derivazione delle soglie vol regime da dati storici reali
(M1.5). Esegue fetch OHLCV giornaliero BTC/USDT ed ETH/USDT da OKX (con
fallback Kraken se OKX non copre fino al 2019-01-01, con test di sanità
sul periodo di overlap), calcola vol EWMA (span=32, stesso stimatore di
`regime.vol_state.compute_ewma_vol`), e propone soglie enter/exit per
ciascun asset separatamente secondo il criterio pre-registrato (frazione
target 20-25% high-vol, mediana transizioni/anno <= 8, dwell time minimo
>= 3 giorni).

Uso: python scripts/derive_vol_thresholds.py

NON esegue ordini, non richiede chiavi (solo endpoint pubblici OHLCV).
NON scrive config/regime.yaml da solo: l'output va rivisto da Andrea
prima di qualunque modifica al config (Task 3, dopo review bloccante)."""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import ccxt
import pandas as pd

from regime.threshold_derivation import ThresholdSearchCriterion, search_threshold_candidates
from regime.vol_state import compute_ewma_vol

EWMA_SPAN = 32
SINCE_DATE = "2019-01-01"
CRITERION = ThresholdSearchCriterion(
    target_fraction_low=0.20,
    target_fraction_high=0.25,
    max_median_transitions_per_year=8.0,
    min_dwell_time_days=3,
)
ENTER_PERCENTILES = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
EXIT_PERCENTILES = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]


def fetch_daily_ohlcv(exchange, symbol: str, since_ms: int) -> pd.DataFrame:
    """Fetch paginato di candele giornaliere da `exchange` per `symbol`
    a partire da `since_ms` (epoch millisecondi) fino a oggi."""
    all_candles: list[list] = []
    limit = 300
    while True:
        candles = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since_ms, limit=limit)
        if not candles:
            break
        all_candles.extend(candles)
        last_ts = candles[-1][0]
        next_since = last_ts + 24 * 60 * 60 * 1000
        if next_since <= since_ms:
            break
        since_ms = next_since
        if len(candles) < limit:
            break

    df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.drop_duplicates(subset="date").set_index("date").sort_index()


def fetch_with_fallback(asset: str) -> tuple[pd.DataFrame, str]:
    """Fetch OKX come fonte primaria; fallback Kraken per il segmento
    mancante se OKX non copre fino a SINCE_DATE, con test di sanità
    (correlazione dei rendimenti nel periodo di overlap) stampato."""
    since_ms = int(pd.Timestamp(SINCE_DATE, tz="UTC").timestamp() * 1000)
    target_start = pd.Timestamp(SINCE_DATE, tz="UTC")

    okx = ccxt.okx()
    okx_df = fetch_daily_ohlcv(okx, f"{asset}/USDT", since_ms)
    earliest_okx = okx_df.index.min()

    if earliest_okx <= target_start + pd.Timedelta(days=7):
        return okx_df, f"OKX (copertura completa dal {SINCE_DATE})"

    kraken = ccxt.kraken()
    kraken_df = fetch_daily_ohlcv(kraken, f"{asset}/USD", since_ms)

    overlap_start = max(kraken_df.index.min(), earliest_okx)
    overlap_end = min(kraken_df.index.max(), okx_df.index.max())
    if overlap_start < overlap_end:
        okx_ret = okx_df.loc[overlap_start:overlap_end, "close"].pct_change().dropna()
        kraken_ret = kraken_df.loc[overlap_start:overlap_end, "close"].pct_change().dropna()
        aligned = pd.concat([okx_ret.rename("okx"), kraken_ret.rename("kraken")], axis=1).dropna()
        correlation = aligned["okx"].corr(aligned["kraken"])
        print(
            f"[sanity check {asset}] correlazione rendimenti OKX vs Kraken "
            f"nel periodo di overlap ({overlap_start.date()} - {overlap_end.date()}, "
            f"n={len(aligned)}): {correlation:.4f}"
        )

    combined = pd.concat([kraken_df.loc[: earliest_okx - pd.Timedelta(days=1)], okx_df])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    source = f"Kraken ({SINCE_DATE} - {earliest_okx.date()}) + OKX (da {earliest_okx.date()})"
    return combined, source


def main() -> None:
    for asset in ("BTC", "ETH"):
        df, source = fetch_with_fallback(asset)
        returns = df["close"].pct_change().dropna()
        vol = compute_ewma_vol(returns, span=EWMA_SPAN).dropna()

        candidates = search_threshold_candidates(
            vol, ENTER_PERCENTILES, EXIT_PERCENTILES, CRITERION
        )

        print(f"\n=== {asset} - fonte dati: {source} ===")
        print(
            f"Periodo vol: {vol.index.min().date()} - {vol.index.max().date()} "
            f"({len(vol)} osservazioni)"
        )

        if not candidates:
            print(
                "NESSUN CANDIDATO rispetta il criterio pre-registrato con questa griglia "
                "di percentili. Riportare ad Andrea prima di allargare la griglia o "
                "rivedere il criterio."
            )
            continue

        best = candidates[0]
        print(f"Soglia proposta: enter={best.enter:.4f}, exit={best.exit:.4f}")
        print(f"Frazione tempo high-vol: {best.fraction_high_vol:.2%} (target 20-25%)")
        print(f"Transizioni/anno per anno solare: {best.transitions_per_year}")
        print(f"Mediana transizioni/anno: {best.median_transitions_per_year}")
        print(f"Dwell time minimo osservato: {best.min_dwell_time} giorni (soglia minima 3)")
        print(
            f"Distribuzione dwell time: min={min(best.dwell_times)}, "
            f"mediana={statistics.median(best.dwell_times)}, max={max(best.dwell_times)}"
        )
        print(f"Candidati totali che rispettano il criterio: {len(candidates)}")


if __name__ == "__main__":
    main()
