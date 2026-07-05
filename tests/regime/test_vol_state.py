from __future__ import annotations

import pandas as pd

from regime.vol_state import VolRegimeState, VolStateConfig, compute_ewma_vol


def test_compute_ewma_vol_higher_for_more_volatile_series():
    calm = pd.Series([0.001, -0.001, 0.001, -0.001, 0.001] * 20)
    wild = pd.Series([0.05, -0.05, 0.05, -0.05, 0.05] * 20)
    calm_vol = compute_ewma_vol(calm, span=10).iloc[-1]
    wild_vol = compute_ewma_vol(wild, span=10).iloc[-1]
    assert wild_vol > calm_vol


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
    assert state.is_high_vol is True  # mai sceso sotto exit=0.6


def test_vol_state_turns_off_only_below_exit_threshold():
    config = VolStateConfig(ewma_span=10, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config)
    state.update(0.9)
    state.update(0.5)
    assert state.is_high_vol is False
