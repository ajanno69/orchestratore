from __future__ import annotations

import pytest

from regime.hysteresis import HysteresisBand, next_state


def test_state_turns_on_above_enter_and_off_only_below_exit():
    band = HysteresisBand(enter=1.0, exit=0.8)
    assert next_state(False, 1.1, band) is True
    assert next_state(True, 0.9, band) is True  # ancora sopra exit, resta ON
    assert next_state(True, 0.75, band) is False  # scende sotto exit, si spegne


def test_state_does_not_flip_flop_oscillating_in_dead_band():
    """ADR-036: isteresi obbligatoria — un valore che oscilla intorno a
    un'unica soglia (qui 0.85-0.95, sempre tra exit=0.8 ed enter=1.0) non
    deve mai far scattare lo stato."""
    band = HysteresisBand(enter=1.0, exit=0.8)
    state = False
    for value in [0.9, 0.85, 0.95, 0.82, 0.99, 0.81]:
        state = next_state(state, value, band)
    assert state is False  # mai salito sopra enter=1.0


def test_degenerate_band_raises():
    with pytest.raises(ValueError):
        HysteresisBand(enter=0.8, exit=1.0)
