"""Derivazione offline delle soglie assolute enter/exit per il regime layer
v0 (ADR-036 §3, milestone M1.5). Modulo PURO: nessun I/O, nessuna chiamata
di rete. Simula la macchina a stati esistente (`regime.hysteresis`, MAI
reimplementata qui) su una serie storica di vol per misurare frazione di
tempo in high-vol, transizioni/anno e dwell time — le metriche del
criterio pre-registrato (target 20-25% high-vol, mediana transizioni/anno
<= 8, dwell time minimo >= 3 giorni). Le soglie risultanti vengono scritte
come valori assoluti statici nel config (Task 3): nessun calcolo
percentile a runtime nel layer v0."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

import pandas as pd

from regime.hysteresis import HysteresisBand, next_state


def count_transitions(states: pd.Series) -> int:
    """Numero di cambi di stato lungo la serie (confronto con l'osservazione precedente)."""
    if len(states) < 2:
        return 0
    return int((states.values[1:] != states.values[:-1]).sum())


def dwell_times(states: pd.Series) -> list[int]:
    """Lunghezza (in osservazioni) di ogni run consecutivo dello stesso stato."""
    if len(states) == 0:
        return []
    runs: list[int] = []
    current_value = states.iloc[0]
    current_length = 1
    for value in states.iloc[1:]:
        if value == current_value:
            current_length += 1
        else:
            runs.append(current_length)
            current_value = value
            current_length = 1
    runs.append(current_length)
    return runs


def fraction_high_vol(states: pd.Series) -> float:
    """Frazione di osservazioni in stato True (high-vol)."""
    return float(states.mean())


def transitions_per_calendar_year(states: pd.Series) -> dict[int, int]:
    """Transizioni per anno solare, attribuite all'anno in cui la NUOVA
    osservazione (quella diversa dalla precedente) cade. Include tutti gli
    anni presenti nell'indice, anche con zero transizioni. Richiede
    `states.index` sia un DatetimeIndex."""
    years = states.index.year
    result = dict.fromkeys(sorted(set(years)), 0)
    changed = states.values[1:] != states.values[:-1]
    for is_change, year in zip(changed, years[1:], strict=True):
        if is_change:
            result[year] += 1
    return result


def simulate_hysteresis_path(
    vol_series: pd.Series, band: HysteresisBand, initial_state: bool = False
) -> pd.Series:
    """Applica `regime.hysteresis.next_state` in sequenza lungo `vol_series`,
    restituendo la serie di stati risultante (stesso indice di `vol_series`)."""
    state = initial_state
    output = []
    for value in vol_series:
        state = next_state(state, value, band)
        output.append(state)
    return pd.Series(output, index=vol_series.index)


@dataclass(frozen=True)
class ThresholdCandidateMetrics:
    enter: float
    exit: float
    fraction_high_vol: float
    transitions_per_year: dict[int, int]
    median_transitions_per_year: float
    dwell_times: list[int]
    min_dwell_time: int


def evaluate_threshold_candidate(
    vol_series: pd.Series, enter: float, exit: float
) -> ThresholdCandidateMetrics:
    """Valuta una coppia (enter, exit) candidata simulando la macchina a
    stati sulla storia reale e misurando tutte le metriche del criterio
    pre-registrato."""
    band = HysteresisBand(enter=enter, exit=exit)
    states = simulate_hysteresis_path(vol_series, band)
    tpy = transitions_per_calendar_year(states)
    dwell = dwell_times(states)
    return ThresholdCandidateMetrics(
        enter=enter,
        exit=exit,
        fraction_high_vol=fraction_high_vol(states),
        transitions_per_year=tpy,
        median_transitions_per_year=statistics.median(tpy.values()) if tpy else 0.0,
        dwell_times=dwell,
        min_dwell_time=min(dwell) if dwell else 0,
    )


@dataclass(frozen=True)
class ThresholdSearchCriterion:
    target_fraction_low: float
    target_fraction_high: float
    max_median_transitions_per_year: float
    min_dwell_time_days: int


def search_threshold_candidates(
    vol_series: pd.Series,
    enter_percentiles: list[float],
    exit_percentiles: list[float],
    criterion: ThresholdSearchCriterion,
) -> list[ThresholdCandidateMetrics]:
    """Genera candidati (enter, exit) dai percentili storici di
    `vol_series` (soglie DERIVATE offline da qui, mai calcolate a runtime
    nel layer v0), valuta ciascuno, e restituisce solo quelli che
    rispettano il criterio pre-registrato — ordinati per vicinanza al
    centro del range di frazione target (il primo elemento è il candidato
    migliore)."""
    target_center = (criterion.target_fraction_low + criterion.target_fraction_high) / 2
    candidates: list[ThresholdCandidateMetrics] = []

    for enter_pct in enter_percentiles:
        enter_value = float(vol_series.quantile(enter_pct))
        for exit_pct in exit_percentiles:
            exit_value = float(vol_series.quantile(exit_pct))
            if exit_value >= enter_value:
                continue

            metrics = evaluate_threshold_candidate(vol_series, enter_value, exit_value)

            if not (
                criterion.target_fraction_low
                <= metrics.fraction_high_vol
                <= criterion.target_fraction_high
            ):
                continue
            if metrics.median_transitions_per_year > criterion.max_median_transitions_per_year:
                continue
            if metrics.min_dwell_time < criterion.min_dwell_time_days:
                continue

            candidates.append(metrics)

    return sorted(candidates, key=lambda m: abs(m.fraction_high_vol - target_center))
