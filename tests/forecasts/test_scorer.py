# tests/forecasts/test_scorer.py
from __future__ import annotations

import pandas as pd
import pytest

from forecasts.scorer import score_forecasts


def _forecasts_df(p_ups, horizon="24h"):
    return pd.DataFrame(
        {
            "timestamp": [f"2026-07-{i+1:02d}T00:00:00Z" for i in range(len(p_ups))],
            "asset": ["BTC"] * len(p_ups),
            "horizon": [horizon] * len(p_ups),
            "p_up": p_ups,
        }
    )


def test_perfect_predictor_hit_rate_1_and_brier_0():
    forecasts = _forecasts_df([0.9, 0.1, 0.9, 0.1])
    outcomes = pd.Series([True, False, True, False])
    result = score_forecasts(forecasts, outcomes, horizon="24h")
    assert result.n_forecasts == 4
    assert result.hit_rate == 1.0
    assert result.brier_score < 0.02


def test_random_coin_flip_hit_rate_near_half():
    forecasts = _forecasts_df([0.5] * 10)
    outcomes = pd.Series([True, False] * 5)
    result = score_forecasts(forecasts, outcomes, horizon="24h")
    assert result.hit_rate == 0.5


def test_72h_uses_non_overlapping_blocks_every_third_forecast():
    # 6 previsioni giornaliere sovrapposte a orizzonte 72h -> solo indici 0,3 usati
    forecasts = _forecasts_df([0.9, 0.9, 0.9, 0.1, 0.1, 0.1], horizon="72h")
    outcomes = pd.Series([True, False, False, False, True, True])
    result = score_forecasts(forecasts, outcomes, horizon="72h")
    assert result.n_forecasts == 2  # solo indice 0 e 3


def test_empty_forecasts_returns_nan_scores():
    forecasts = _forecasts_df([])
    outcomes = pd.Series([], dtype=bool)
    result = score_forecasts(forecasts, outcomes, horizon="24h")
    assert result.n_forecasts == 0
    assert pd.isna(result.hit_rate)


def test_calibration_buckets_group_by_decile():
    forecasts = _forecasts_df([0.75, 0.72, 0.15])
    outcomes = pd.Series([True, False, False])
    result = score_forecasts(forecasts, outcomes, horizon="24h")
    assert "0.7-0.8" in result.calibration_buckets
    avg_p, actual_rate, n = result.calibration_buckets["0.7-0.8"]
    assert n == 2
    assert avg_p == pytest.approx((0.75 + 0.72) / 2)
    assert actual_rate == pytest.approx(0.5)
