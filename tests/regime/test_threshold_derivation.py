from __future__ import annotations

import pandas as pd
import pytest

from regime.hysteresis import HysteresisBand
from regime.threshold_derivation import (
    ThresholdCandidateMetrics,
    ThresholdSearchCriterion,
    count_transitions,
    dwell_times,
    evaluate_threshold_candidate,
    fraction_high_vol,
    search_threshold_candidates,
    simulate_hysteresis_path,
    transitions_per_calendar_year,
)


def test_count_transitions_counts_state_changes():
    states = pd.Series([False, False, True, True, False, True])
    assert count_transitions(states) == 3


def test_count_transitions_constant_series_has_zero_transitions():
    assert count_transitions(pd.Series([True, True, True])) == 0


def test_count_transitions_single_element_has_zero_transitions():
    assert count_transitions(pd.Series([True])) == 0


def test_dwell_times_returns_run_lengths():
    states = pd.Series([False, False, True, True, True, False, True])
    assert dwell_times(states) == [2, 3, 1, 1]


def test_dwell_times_single_run():
    assert dwell_times(pd.Series([True, True, True])) == [3]


def test_fraction_high_vol_computes_mean():
    states = pd.Series([True, True, False, False])
    assert fraction_high_vol(states) == pytest.approx(0.5)


def test_transitions_per_calendar_year_includes_years_with_zero_transitions():
    idx = pd.DatetimeIndex(
        ["2023-12-30", "2023-12-31", "2024-01-01", "2024-01-02", "2024-06-01"]
    )
    states = pd.Series([False, False, True, True, False], index=idx)
    result = transitions_per_calendar_year(states)
    assert result == {2023: 0, 2024: 2}


def test_simulate_hysteresis_path_reproduces_next_state_semantics():
    band = HysteresisBand(enter=0.8, exit=0.6)
    vol_series = pd.Series([0.9, 0.7, 0.5, 0.85])
    result = simulate_hysteresis_path(vol_series, band)
    expected = pd.Series([True, True, False, True])
    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_simulate_hysteresis_path_accepts_custom_initial_state():
    band = HysteresisBand(enter=0.8, exit=0.6)
    vol_series = pd.Series([0.7])
    result = simulate_hysteresis_path(vol_series, band, initial_state=True)
    assert bool(result.iloc[0]) is True


def test_evaluate_threshold_candidate_computes_all_metrics():
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    vol_series = pd.Series([0.9, 0.7, 0.5, 0.85], index=idx)
    metrics = evaluate_threshold_candidate(vol_series, enter=0.8, exit=0.6)
    assert isinstance(metrics, ThresholdCandidateMetrics)
    assert metrics.enter == 0.8
    assert metrics.exit == 0.6
    assert metrics.fraction_high_vol == pytest.approx(0.75)
    assert metrics.dwell_times == [2, 1, 1]
    assert metrics.min_dwell_time == 1


def test_search_threshold_candidates_filters_by_criterion():
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    # Serie monotona crescente da 0 a 99/99: quantile(p) su questa serie restituisce
    # esattamente p (proprieta' di un linspace uniforme), quindi le soglie derivate dai
    # percentili sono prevedibili senza ambiguita' di interpolazione o di blocchi costanti
    # (verificato con calcolo diretto: enter=0.60 -> fraction=0.400, enter=0.70 -> fraction=0.300,
    # entrambi con un'unica transizione, min_dwell_time=30-40 giorni).
    vol_series = pd.Series([i / 99 for i in range(100)], index=idx)
    criterion = ThresholdSearchCriterion(
        target_fraction_low=0.30,
        target_fraction_high=0.45,
        max_median_transitions_per_year=8.0,
        min_dwell_time_days=3,
    )
    candidates = search_threshold_candidates(
        vol_series,
        enter_percentiles=[0.60, 0.70],
        exit_percentiles=[0.20, 0.30],
        criterion=criterion,
    )
    assert len(candidates) > 0
    best = candidates[0]
    assert criterion.target_fraction_low <= best.fraction_high_vol <= criterion.target_fraction_high


def test_search_threshold_candidates_returns_empty_when_nothing_satisfies_criterion():
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    vol_series = pd.Series([0.5] * 10, index=idx)
    criterion = ThresholdSearchCriterion(
        target_fraction_low=0.90,
        target_fraction_high=1.0,
        max_median_transitions_per_year=8.0,
        min_dwell_time_days=3,
    )
    candidates = search_threshold_candidates(
        vol_series,
        enter_percentiles=[0.80],
        exit_percentiles=[0.20],
        criterion=criterion,
    )
    assert candidates == []
