"""Sequenziatore stateful sopra `resolve_wiring_decision` (ADR-036/037).

`resolve_wiring_decision` è puro: dato uno snapshot, ricalcola sempre la
decisione da zero, senza memoria del tick precedente. Va bene per la
misura, ma un consumatore esterno (log, canale alert, executor futuro)
non deve vedere lo stesso comando ripetuto ad ogni tick nello stesso stato,
né un alert per ogni tick in cui una condizione persiste — altrimenti un
regime stabile in high-vol per giorni produrrebbe migliaia di comandi/alert
identici (rumore che nasconde il segnale, non lo evidenzia). Questo modulo
aggiunge la memoria minima necessaria per emettere eventi solo sui cambi
di stato (edge-triggered), con un rate-limit esplicito per non amplificare
un layer di regime instabile (flip-flop a monte, es. un bug di isteresi).

Non esegue nessuna azione (ADR-037 §7): produce solo eventi (dati) per un
sink esterno."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from components.regime_wiring import GridBtcCommand, HarvesterCommand, WiringDecision


class AlertCategory(Enum):
    NONE = "none"
    LAYER_CIECO = "layer_cieco"
    LAYER_LAVORA_DIFENSIVA = "layer_lavora_difensiva"
    LAYER_LAVORA_RIENTRO = "layer_lavora_rientro"
    LAYER_INSTABILE = "layer_instabile"


@dataclass(frozen=True)
class CommandEvent:
    harvester_command: HarvesterCommand
    gridbtc_command: GridBtcCommand
    at: datetime


@dataclass(frozen=True)
class AlertEvent:
    category: AlertCategory
    text: str
    at: datetime


@dataclass(frozen=True)
class SequencerOutput:
    commands: list[CommandEvent]
    alerts: list[AlertEvent]


@dataclass(frozen=True)
class RateLimitPolicy:
    """Oltre `max_transitions` cambi di categoria di alert nella finestra
    `window`, i singoli alert di transizione vengono soppressi e sostituiti
    da un unico alert aggregato — il wiring non deve amplificare un layer
    di regime che flippa più velocemente di quanto l'isteresi a monte
    dovrebbe permettere."""

    window: timedelta
    max_transitions: int


class WiringSequencer:
    def __init__(self, rate_limit: RateLimitPolicy) -> None:
        self._rate_limit = rate_limit
        self._last_commands: tuple[HarvesterCommand, GridBtcCommand] | None = None
        self._last_category: AlertCategory = AlertCategory.NONE
        self._transition_times: list[datetime] = []
        self._aggregate_alert_active = False

    def process(self, decision: WiringDecision, now: datetime) -> SequencerOutput:
        commands: list[CommandEvent] = []
        alerts: list[AlertEvent] = []

        current_commands = (decision.harvester_command, decision.gridbtc_command)
        if current_commands != self._last_commands:
            commands.append(
                CommandEvent(decision.harvester_command, decision.gridbtc_command, now)
            )
            self._last_commands = current_commands

        category = self._categorize(decision)
        if category != self._last_category:
            self._transition_times = [
                t for t in self._transition_times if now - t <= self._rate_limit.window
            ]
            self._transition_times.append(now)

            if len(self._transition_times) > self._rate_limit.max_transitions:
                if not self._aggregate_alert_active:
                    alerts.append(
                        AlertEvent(
                            AlertCategory.LAYER_INSTABILE,
                            "LAYER INSTABILE — "
                            f"{len(self._transition_times)} transizioni di stato in "
                            f"{self._rate_limit.window}: possibile flip-flop a monte "
                            "(layer di regime instabile o dati rumorosi), alert "
                            "individuali soppressi finché la frequenza non si "
                            "stabilizza sotto soglia.",
                            now,
                        )
                    )
                    self._aggregate_alert_active = True
            else:
                self._aggregate_alert_active = False
                text = self._alert_text(category, decision)
                if text is not None:
                    alerts.append(AlertEvent(category, text, now))

            self._last_category = category

        return SequencerOutput(commands=commands, alerts=alerts)

    def _categorize(self, decision: WiringDecision) -> AlertCategory:
        if decision.harvester_command is HarvesterCommand.NO_ACTION_STALE_DATA:
            return AlertCategory.LAYER_CIECO
        if decision.harvester_command is HarvesterCommand.DEFENSIVE:
            return AlertCategory.LAYER_LAVORA_DIFENSIVA
        if self._last_category is AlertCategory.LAYER_LAVORA_DIFENSIVA:
            return AlertCategory.LAYER_LAVORA_RIENTRO
        return AlertCategory.NONE

    @staticmethod
    def _alert_text(category: AlertCategory, decision: WiringDecision) -> str | None:
        if category is AlertCategory.LAYER_CIECO:
            return f"LAYER CIECO — {decision.reason}"
        if category is AlertCategory.LAYER_LAVORA_DIFENSIVA:
            return f"LAYER LAVORA — {decision.reason}"
        if category is AlertCategory.LAYER_LAVORA_RIENTRO:
            return (
                "LAYER LAVORA — ETH rientrato in low-vol: NESSUNA ripresa "
                "automatica, conferma manuale richiesta prima di uscire dalla "
                "modalità difensiva (ADR-037: la ripresa è decisione umana)."
            )
        return None
