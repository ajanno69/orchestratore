# src/forecasts/scorer.py
"""Scoring mensile del predittore (ADR-036 §4): hit rate, Brier score,
calibrazione. Per l'orizzonte 72h le previsioni sono sovrapposte (una ogni
giorno con orizzonte di 3 giorni) — lo scoring usa BLOCCHI NON SOVRAPPOSTI
(ogni 3° previsione) per evitare un CI90 sovra-confidente da
autocorrelazione (obbligatorio, ADR-036 §4)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

_HORIZON_DAYS = {"24h": 1, "72h": 3}


@dataclass(frozen=True)
class ScoreResult:
    n_forecasts: int
    hit_rate: float
    brier_score: float
    calibration_buckets: dict[str, tuple[float, float, int]]  # bucket -> (avg_p, actual_rate, n)


def _non_overlapping_block_mask(n: int, block_size: int) -> list[bool]:
    """True per gli indici 0, block_size, 2*block_size, ... (blocchi non
    sovrapposti, ADR-036 §4, obbligatorio per il 72h)."""
    return [i % block_size == 0 for i in range(n)]


def score_forecasts(forecasts: pd.DataFrame, outcomes: pd.Series, horizon: str) -> ScoreResult:
    """`forecasts`: colonne timestamp/asset/horizon/p_up (schema
    forecasts.schema), già filtrate per un singolo asset e horizon,
    ordinate per timestamp. `outcomes`: Series booleana (rendimento>0
    realizzato), stesso indice di `forecasts` (allineata dal chiamante —
    lo scorer non fa I/O di prezzi, ADR-036 §4: 'prima la misura, poi il
    misurato')."""
    if len(forecasts) != len(outcomes):
        raise ValueError(
            f"forecasts e outcomes hanno lunghezze diverse ({len(forecasts)} vs "
            f"{len(outcomes)}): non possono essere allineati posizionalmente — "
            "il chiamante deve allinearli esplicitamente prima di chiamare lo scorer."
        )

    block_size = _HORIZON_DAYS[horizon]
    mask = _non_overlapping_block_mask(len(forecasts), block_size)

    p_up = forecasts["p_up"].reset_index(drop=True)[mask]
    actual = outcomes.reset_index(drop=True)[mask]

    # Un outcome NaN (dato di prezzo mancante quel giorno) significa "non
    # sappiamo" — non è la stessa cosa di "previsione sbagliata". Va escluso
    # in modo esplicito e consistente da TUTTE le metriche (n, hit_rate,
    # brier_score, calibrazione), non lasciato che ciascuna lo tratti a modo
    # suo (confronto booleano lo conta come miss, la media lo skippa).
    known_mask = actual.notna()
    p_up = p_up[known_mask]
    actual = actual[known_mask]

    n = len(p_up)
    if n == 0:
        return ScoreResult(
            n_forecasts=0, hit_rate=float("nan"), brier_score=float("nan"), calibration_buckets={}
        )

    predicted_up = p_up >= 0.5
    hit_rate = (predicted_up == actual).mean()
    brier_score = ((p_up - actual.astype(float)) ** 2).mean()

    calibration_buckets = _calibration_buckets(p_up, actual)

    return ScoreResult(
        n_forecasts=n,
        hit_rate=float(hit_rate),
        brier_score=float(brier_score),
        calibration_buckets=calibration_buckets,
    )


def _calibration_buckets(p_up: pd.Series, actual: pd.Series) -> dict[str, tuple[float, float, int]]:
    """Bucket di calibrazione a decili [0-0.1), [0.1-0.2), ... [0.9-1.0].
    Per ogni bucket: probabilità media dichiarata vs frequenza realizzata
    di rendimento>0 (ADR-036 §4: 'quando dice 70%, ha ragione il 70%?')."""
    buckets: dict[str, tuple[float, float, int]] = {}
    edges = [i / 10 for i in range(11)]
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        in_bucket = (p_up >= lo) & (p_up < hi if hi < 1.0 else p_up <= hi)
        n_in_bucket = int(in_bucket.sum())
        if n_in_bucket == 0:
            continue
        avg_p = float(p_up[in_bucket].mean())
        actual_rate = float(actual[in_bucket].mean())
        buckets[f"{lo:.1f}-{hi:.1f}"] = (avg_p, actual_rate, n_in_bucket)
    return buckets
