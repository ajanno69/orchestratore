"""Stato di volatilità (EWMA su BTC/ETH) — regime layer v0 (ADR-036 §3):
regole semplici e trasparenti, isteresi obbligatoria per evitare flip-flop
a cavallo della soglia."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from regime.hysteresis import HysteresisBand, next_state


@dataclass(frozen=True)
class VolStateConfig:
    ewma_span: int
    enter_threshold: float
    exit_threshold: float

    @property
    def band(self) -> HysteresisBand:
        return HysteresisBand(enter=self.enter_threshold, exit=self.exit_threshold)


def compute_ewma_vol(returns: pd.Series, span: int) -> pd.Series:
    """Volatilità EWMA annualizzata dei rendimenti giornalieri (radice della
    varianza EWMA * sqrt(365), crypto è 24/7)."""
    ewma_var = (returns**2).ewm(span=span, adjust=False).mean()
    return (ewma_var**0.5) * (365**0.5)


@dataclass
class VolRegimeState:
    """Stato di vol (alta/bassa) per un asset, con isteresi. `is_high_vol`
    parte False (bassa vol) finché il primo update non lo cambia.

    `update` rifiuta esplicitamente un `latest_vol` NaN (auto-invalidazione):
    in Python `nan >= soglia` è sempre False, quindi senza guardia un NaN
    verrebbe interpretato da `next_state` come "sotto ogni soglia" e farebbe
    silenziosamente il downgrade di uno stato high-vol proprio quando i dati
    a monte sono inaffidabili — il momento peggiore per farlo."""

    config: VolStateConfig
    is_high_vol: bool = False

    def update(self, latest_vol: float) -> bool:
        if math.isnan(latest_vol):
            raise ValueError(
                "VolRegimeState.update ha ricevuto latest_vol=NaN: è un "
                "problema di data-quality a monte (tick di prezzo mancante/"
                "bad), non un segnale di bassa volatilità. Lo stato si "
                "rifiuta di fare downgrade silenzioso su un input "
                "inaffidabile. Il chiamante deve gestire il NaN esso "
                "stesso — es. non invocare update() finché non arrivano "
                "dati validi, oppure applicare una policy di fallback "
                "esplicita decisa a parte — non interpretarlo qui in "
                "automatico."
            )
        self.is_high_vol = next_state(self.is_high_vol, latest_vol, self.config.band)
        return self.is_high_vol
