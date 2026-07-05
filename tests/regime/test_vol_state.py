from __future__ import annotations

import pandas as pd
import pytest

from regime.vol_state import VolRegimeState, VolStateConfig, compute_ewma_vol


def test_compute_ewma_vol_higher_for_more_volatile_series():
    calm = pd.Series([0.001, -0.001, 0.001, -0.001, 0.001] * 20)
    wild = pd.Series([0.05, -0.05, 0.05, -0.05, 0.05] * 20)
    calm_vol = compute_ewma_vol(calm, span=10).iloc[-1]
    wild_vol = compute_ewma_vol(wild, span=10).iloc[-1]
    assert wild_vol > calm_vol


def test_compute_ewma_vol_raises_on_empty_series():
    """Una returns Series vuota non può produrre una lettura di vol: deve
    fallire in modo esplicito qui, non silenziosamente più a valle con un
    IndexError poco chiaro su .iloc[-1] (vedi review Task 5)."""
    with pytest.raises(ValueError):
        compute_ewma_vol(pd.Series([], dtype=float), span=10)


def test_vol_state_turns_on_above_enter_threshold():
    config = VolStateConfig(ewma_span=10, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config)
    assert state.update(0.5) is False
    assert state.update(0.9) is True


def test_vol_state_does_not_flip_flop_across_single_threshold():
    """ADR-036 §3: isteresi obbligatoria — un valore che oscilla intorno a
    0.7 (tra exit=0.6 e enter=0.8) non deve far flappare lo stato."""
    config = VolStateConfig(ewma_span=10, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config)
    state.update(0.9)  # entra in high-vol
    assert state.is_high_vol is True
    for value in [0.7, 0.65, 0.75, 0.62, 0.79]:
        state.update(value)
        # Assert ad OGNI step, non solo alla fine: una soglia singola
        # ingenua (es. 0.7) farebbe flip-flop internamente pur finendo
        # per caso su True all'ultimo valore (0.79) — un assert solo
        # finale non lo scoprirebbe (vedi review Task 5).
        assert state.is_high_vol is True  # mai sceso sotto exit=0.6


def test_vol_state_turns_off_only_below_exit_threshold():
    config = VolStateConfig(ewma_span=10, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config)
    state.update(0.9)
    state.update(0.5)
    assert state.is_high_vol is False


def test_vol_state_update_raises_on_nan_instead_of_silently_downgrading():
    """Un NaN in ingresso è un problema di data-quality upstream, non un
    segnale di bassa vol: lo stato deve rifiutarsi esplicitamente invece di
    fare downgrade silenzioso (vedi review Task 5). NaN è un caso specifico
    (non-esaustivo) di input non-finito rifiutato da `update`."""
    config = VolStateConfig(ewma_span=10, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config)
    state.update(0.9)  # entra in high-vol
    assert state.is_high_vol is True

    with pytest.raises(ValueError):
        state.update(float("nan"))

    assert state.is_high_vol is True  # invariato: nessun downgrade silenzioso


def test_vol_state_update_raises_on_infinite_input():
    """+inf/-inf sono un altro caso di input non-finito: -inf letto senza
    guardia verrebbe interpretato come "sotto ogni soglia" (downgrade
    silenzioso), +inf come "sopra ogni soglia" (upgrade silenzioso) —
    entrambi inaffidabili quanto un NaN (vedi review Task 5)."""
    config = VolStateConfig(ewma_span=10, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config)
    state.update(0.9)  # entra in high-vol
    assert state.is_high_vol is True

    with pytest.raises(ValueError):
        state.update(float("inf"))
    assert state.is_high_vol is True  # invariato

    with pytest.raises(ValueError):
        state.update(float("-inf"))
    assert state.is_high_vol is True  # invariato
