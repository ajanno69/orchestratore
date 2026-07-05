"""Stato di funding (OKX) — soglia on/off per l'harvester (ADR-036 §3).
Stessa isteresi generica di vol_state, per evitare accensioni/spegnimenti
ravvicinati dell'harvester (attrito fiscale non gratuito, vedi ADR-036 §3)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from regime.hysteresis import HysteresisBand, next_state


class FundingRateSource(Protocol):
    def fetch(self, asset: str) -> float:
        """Ultimo funding rate osservato per `asset` (frazione, es. 0.0001 = 0.01%)."""
        ...


@dataclass(frozen=True)
class FundingStateConfig:
    enter_threshold: float
    exit_threshold: float

    @property
    def band(self) -> HysteresisBand:
        return HysteresisBand(enter=self.enter_threshold, exit=self.exit_threshold)


@dataclass
class FundingRegimeState:
    """Stato harvester-on/off per un asset, con isteresi.

    `update` rifiuta esplicitamente un `latest_funding_rate` non finito
    (NaN o infinito, auto-invalidazione): in Python sia `nan >= soglia` sia
    `-inf >= soglia` sono sempre False, quindi senza guardia un NaN o un
    -inf verrebbero interpretati da `next_state` come "sotto ogni soglia" e
    farebbero silenziosamente il downgrade di uno stato harvester-on
    proprio quando i dati a monte sono inaffidabili — il momento peggiore
    per farlo. Allo stesso modo un +inf verrebbe letto come "sopra ogni
    soglia", altrettanto inaffidabile."""

    config: FundingStateConfig
    is_harvester_on: bool = False

    def update(self, latest_funding_rate: float) -> bool:
        if not math.isfinite(latest_funding_rate):
            raise ValueError(
                "FundingRegimeState.update ha ricevuto latest_funding_rate "
                "non-finito (NaN o infinito): è un problema di "
                "data-quality a monte (lettura OKX mancante/bad, o un "
                "calcolo a monte esploso), non un segnale di funding "
                "sotto (o sopra) soglia. Lo stato si rifiuta di fare "
                "downgrade/upgrade silenzioso dell'harvester su un input "
                "inaffidabile. Il chiamante deve gestire il valore "
                "non-finito esso stesso — es. non invocare update() "
                "finché non arrivano dati validi, oppure applicare una "
                "policy di fallback esplicita decisa a parte — non "
                "interpretarlo qui in automatico."
            )
        self.is_harvester_on = next_state(
            self.is_harvester_on, latest_funding_rate, self.config.band
        )
        return self.is_harvester_on


class CcxtOkxFundingRateSource:
    """Adapter su ccxt.okx per leggere il funding rate corrente via
    endpoint pubblico (nessuna chiave richiesta — sola lettura, ADR-036
    M1: niente ordini, niente chiavi di trading in questa milestone)."""

    def __init__(self, exchange) -> None:
        self._exchange = exchange

    def fetch(self, asset: str) -> float:
        symbol = f"{asset}/USDT:USDT"
        ticker = self._exchange.fetch_funding_rate(symbol)
        return float(ticker["fundingRate"])
