"""Isteresi generica per stati binari (Schmitt trigger) — evita flip-flop
quando il valore oscilla intorno a un'unica soglia (ADR-036 §3: 'isteresi
obbligatoria' per lo stato di vol)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HysteresisBand:
    """Soglia di ingresso (enter) e di uscita (exit) per uno stato ON/OFF.

    Convenzione: `enter` > `exit` per uno stato che si attiva quando il
    valore SALE sopra soglia (es. vol alta, funding sopra soglia) e si
    disattiva solo quando il valore SCENDE sotto una soglia più bassa.
    """

    enter: float
    exit: float

    def __post_init__(self) -> None:
        if self.enter <= self.exit:
            raise ValueError(
                f"enter ({self.enter}) deve essere > exit ({self.exit}): "
                "altrimenti la banda di isteresi è degenere e non previene il flip-flop."
            )


def next_state(current_state: bool, value: float, band: HysteresisBand) -> bool:
    """Calcola il prossimo stato ON/OFF dato lo stato corrente e il nuovo
    valore osservato. Non cambia stato se il valore è nella banda morta
    (tra `exit` e `enter`): questa è la proprietà che elimina il flip-flop
    quando il valore oscilla a cavallo di un'unica soglia."""
    if current_state:
        return value >= band.exit
    return value >= band.enter
