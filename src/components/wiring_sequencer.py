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
un layer di regime instabile (flip-flop a monte, es. un bug di isteresi),
e un promemoria periodico finché l'instabilità persiste (mai un singolo
alert seguito da silenzio indefinito — vedi `WiringSequencer` sotto).

Non esegue nessuna azione (ADR-037 §7): produce solo eventi (dati) per un
sink esterno.

CONTRATTO DI RIAVVIO (dichiarato esplicitamente, non lasciato emergente —
finding review indipendente checkpoint 2, 2026-07-06): lo stato di dedup
è interamente in-memory ed effimero. Dopo un riavvio del processo che
ospita questo sequencer, una nuova istanza riparte da zero: il primo tick
riemette SEMPRE il comando e l'eventuale alert dello stato corrente, anche
se quello stato non è "appena cambiato" per davvero. Questo è sicuro SOLO
perché, ad oggi, ogni `HarvesterCommand`/`GridBtcCommand` è level-triggered
e idempotente — ridichiara uno stato persistente (es. "sei in modalità
difensiva finché dura l'high-vol"), non un'azione one-shot da eseguire una
volta sola. Un futuro executor che interpretasse un `CommandEvent` come
azione one-shot (es. `GridBtcCommand.HIGH_VOL_CLOSE_GRID_ORDERLY` letto
come "esegui la chiusura ORA", non come "lo stato desiderato è: chiuso")
romperebbe questa assunzione: un riavvio in stato high-vol ririemettarebbe
quel comando e potrebbe ri-triggerare l'azione. Collegare un simile
executor senza prima rendere lui stesso idempotente (o senza dargli
memoria persistita dello stato già eseguito) è un incidente di governance
ADR-037, non un bug qualunque — fermarsi e chiedere conferma esplicita.
Persistere lo stato di dedup su disco NON è la soluzione qui: aggiungerebbe
un secondo punto di guasto (stato stantio/corrotto) proprio nel componente
il cui scopo è il fail-safe su stato inaffidabile.

CONTRATTO DI CONCORRENZA (dichiarato esplicitamente, stesso finding):
`WiringSequencer.process()` NON è thread-safe — muta più attributi di
istanza senza lock. Il modello di deploy previsto (ADR-037 §8, piano M2
Task 3) è un solo processo con un loop di lettura seriale: `process()` va
chiamato da un solo thread, mai concorrentemente né in modo rientrante.
Se in futuro il modello di deploy cambiasse, quello è il momento per un
lock esplicito (emendamento pre-registrato), non un'aggiunta preventiva
oggi — un lock qui darebbe un falso senso di sicurezza in un componente
che per contratto gira già in un loop seriale."""

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
    da un alert aggregato — il wiring non deve amplificare un layer di
    regime che flippa più velocemente di quanto l'isteresi a monte
    dovrebbe permettere. Finché l'instabilità persiste, l'alert aggregato
    viene ripetuto come promemoria con cadenza pari a `window` (nessun
    nuovo parametro: la cadenza del promemoria riusa lo stesso valore già
    approvato come pre-registrato — vedi ADR-037 §9) — mai un singolo
    alert seguito da silenzio indefinito mentre il guasto è in corso."""

    window: timedelta
    max_transitions: int


class WiringSequencer:
    def __init__(self, rate_limit: RateLimitPolicy) -> None:
        self._rate_limit = rate_limit
        self._last_commands: tuple[HarvesterCommand, GridBtcCommand] | None = None
        self._last_category: AlertCategory = AlertCategory.NONE
        self._transition_times: list[datetime] = []
        self._aggregate_alert_active = False
        self._last_instability_alert_at: datetime | None = None

    def process(self, decision: WiringDecision, now: datetime) -> SequencerOutput:
        commands: list[CommandEvent] = []
        alerts: list[AlertEvent] = []

        current_commands = (decision.harvester_command, decision.gridbtc_command)
        if current_commands != self._last_commands:
            commands.append(CommandEvent(decision.harvester_command, decision.gridbtc_command, now))
            self._last_commands = current_commands

        category = self._categorize(decision)
        category_changed = category != self._last_category
        if category_changed:
            self._transition_times.append(now)
            self._last_category = category

        # Potatura e rivalutazione dell'instabilità ad OGNI tick, non solo
        # sulle transizioni: un flip-flop che continua a produrre transizioni
        # più veloci della finestra non deve mai "auto-stabilizzarsi" solo
        # perché nessun tick successivo azzera lo stato (bug reale trovato
        # dalla review indipendente del checkpoint 2 — la versione precedente
        # faceva questa rivalutazione SOLO dentro il blocco `if category
        # changed`, quindi un flip-flop prolungato restava perennemente
        # "instabile" senza mai un secondo alert, e una tempesta successiva
        # non riarmava più l'alert una volta disattivato).
        self._transition_times = [
            t for t in self._transition_times if now - t <= self._rate_limit.window
        ]
        is_unstable = len(self._transition_times) > self._rate_limit.max_transitions

        if is_unstable:
            due_for_reminder = (
                self._last_instability_alert_at is None
                or (now - self._last_instability_alert_at) >= self._rate_limit.window
            )
            if not self._aggregate_alert_active or due_for_reminder:
                alerts.append(
                    AlertEvent(
                        AlertCategory.LAYER_INSTABILE,
                        "LAYER INSTABILE — "
                        f"{len(self._transition_times)} transizioni di stato in "
                        f"{self._rate_limit.window}: possibile flip-flop a monte "
                        "(layer di regime instabile o dati rumorosi). Alert "
                        "individuali soppressi mentre l'instabilità persiste; "
                        "questo è un promemoria periodico (ogni "
                        f"{self._rate_limit.window}), non un singolo evento — "
                        "resta attivo finché le transizioni non rientrano sotto "
                        "soglia.",
                        now,
                    )
                )
                self._last_instability_alert_at = now
            self._aggregate_alert_active = True
        else:
            self._aggregate_alert_active = False
            self._last_instability_alert_at = None
            if category_changed:
                text = self._alert_text(category, decision)
                if text is not None:
                    alerts.append(AlertEvent(category, text, now))

        return SequencerOutput(commands=commands, alerts=alerts)

    def _categorize(self, decision: WiringDecision) -> AlertCategory:
        # Nota (finding review indipendente checkpoint 2): questo metodo
        # legge `self._last_category`, quindi NON è puro — chiamarlo due
        # volte di fila per lo stesso `decision` può dare risultati diversi
        # (la seconda vedrebbe come "last" il risultato della prima). Sicuro
        # oggi perché `process()` lo invoca una volta sola per tick; non
        # richiamarlo altrove senza rivedere questa dipendenza.
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
