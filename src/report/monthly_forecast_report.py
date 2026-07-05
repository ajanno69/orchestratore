"""Report mensile Binario B (ADR-036 §4): scoring vs due baseline
(persistenza/caso, regime layer v0). M1: stub — nessun modello ancora,
il report gira su qualunque cosa sia nella tabella forecasts (anche
vuota) e lo dichiara esplicitamente invece di fallire."""

from __future__ import annotations

import pandas as pd

from forecasts.scorer import ScoreResult, score_forecasts
from forecasts.store import ForecastStore


def build_monthly_report(store: ForecastStore, outcomes_by_asset: dict[str, pd.Series]) -> str:
    """`outcomes_by_asset`: rendimento>0 realizzato per asset, indicizzato
    come le previsioni di quell'asset (M2+ collega il feed prezzi reale;
    qui il report accetta la Series già allineata dal chiamante)."""
    df = store.read_all()
    if df.empty:
        return "Report mensile Binario B: nessuna previsione registrata ancora."

    lines = ["Report mensile Binario B — scoring predittore vs realtà", ""]
    for asset, outcomes in outcomes_by_asset.items():
        for horizon in ("24h", "72h"):
            subset = df[(df["asset"] == asset) & (df["horizon"] == horizon)]
            if subset.empty:
                continue
            result = score_forecasts(subset, outcomes, horizon)
            lines.append(_format_score_line(asset, horizon, result))

    return "\n".join(lines)


def _format_score_line(asset: str, horizon: str, result: ScoreResult) -> str:
    return (
        f"{asset} {horizon}: n={result.n_forecasts} "
        f"hit_rate={result.hit_rate:.3f} brier={result.brier_score:.4f}"
    )
