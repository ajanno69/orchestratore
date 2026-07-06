"""Wiring del regime layer (Binario A) a comandi per harvester ETH e
GridBTC (ADR-037). Modulo PURO: produce COMANDI (dati), non esegue mai
un'operazione autenticata contro Kraken/OKX — quello resta compito di un
executor separato (fuori scope di questo piano, post-checkpoint).

Fail-safe (ADR-037 §3): su snapshot assente O stantio, mai un'azione
automatica — solo `NO_ACTION_STALE_DATA` + alert. Uno snapshot corrotto
(`RegimeStateStore.read()` solleva ValueError) è trattato da
`load_snapshot_safely` esattamente come uno snapshot assente: qui, a
differenza del layer di misura (`regime.vol_state`, che solleva
esplicitamente su input inaffidabile), un input inaffidabile a livello
di wiring capitale deve tradursi in "nessuna azione", non in
un'eccezione che fermerebbe il loop di wiring senza generare alert."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from regime.store import RegimeSnapshot, RegimeStateStore


class HarvesterCommand(Enum):
    NO_ACTION_STALE_DATA = "no_action_stale_data"
    NORMAL = "normal"
    DEFENSIVE = "defensive"
    OFF = "off"


class GridBtcHighVolAction(Enum):
    """Azione da eseguire su GridBTC quando btc_high_vol=True. Nessun
    default: il chiamante deve specificarla esplicitamente. Scelta
    riservata al checkpoint 'wiring implementato pre-deploy' (piano M2),
    informata dall'analisi in docs/gridbtc-highvol-analysis-m2.md."""

    STOP_NEW_ORDERS = "stop_new_orders"
    CLOSE_GRID_ORDERLY = "close_grid_orderly"


class GridBtcCommand(Enum):
    NO_ACTION_STALE_DATA = "no_action_stale_data"
    NORMAL = "normal"
    HIGH_VOL_STOP_NEW_ORDERS = "high_vol_stop_new_orders"
    HIGH_VOL_CLOSE_GRID_ORDERLY = "high_vol_close_grid_orderly"


@dataclass(frozen=True)
class StalenessPolicy:
    max_age: timedelta


@dataclass(frozen=True)
class WiringDecision:
    harvester_command: HarvesterCommand
    gridbtc_command: GridBtcCommand
    alert: bool
    reason: str


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalizza un datetime a naive-UTC per il confronto di staleness.
    Se `dt` è aware, converte prima a UTC (`astimezone`) e SOLO DOPO
    scarta l'offset — mai uno strip secco (`replace(tzinfo=None)` senza
    conversione), che ignorerebbe silenziosamente l'offset e produrrebbe
    un'età sbagliata esattamente dell'ampiezza dell'offset scartato
    (bug reale trovato e chiuso durante la review del checkpoint 1: una
    versione precedente di questo modulo faceva lo strip secco, innocuo
    SOLO perché ogni timestamp prodotto da `regime.store` finisce sempre
    in 'Z'/+00:00, ma silenziosamente sbagliato per qualunque altro
    offset o per un `now` aware non-UTC — verificato per davvero: con lo
    strip secco, un `now` in CEST (+02:00) alla stessa ora reale di uno
    snapshot appena scritto risultava stantio di 2 ore invece di ~0).
    Se `dt` è naive, è già trattato come UTC per convenzione esplicita di
    questo modulo (stessa convenzione di `regime.store`) — **mai un
    datetime locale naive** (es. `datetime.now()` senza `timezone.utc`)
    deve arrivare qui: il chiamante è responsabile di passare
    `datetime.now(timezone.utc)` o un naive-UTC dichiarato esplicitamente."""
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _parse_timestamp_or_none(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _malformed_snapshot_reason(snapshot: RegimeSnapshot) -> str | None:
    """Ritorna una descrizione del difetto se lo snapshot ha campi
    semanticamente invalidi pur essendo stato costruito con successo — un
    `dataclass` non valida i tipi a runtime, quindi un JSON con
    `"btc_high_vol": "true"` (stringa) o un timestamp non-ISO costruisce
    comunque un `RegimeSnapshot`, senza sollevare nulla. Senza questo
    controllo esplicito, un campo booleano invalido verrebbe interpretato
    per truthiness (un default silenzioso vietato dalla convenzione di
    questo modulo) e un timestamp non parsabile farebbe esplodere il
    confronto di staleness con un'eccezione non gestita — l'opposto del
    fail-safe che questo livello deve garantire."""
    if _parse_timestamp_or_none(snapshot.timestamp) is None:
        return f"timestamp non valido: {snapshot.timestamp!r}"
    for field_name, value in (
        ("btc_high_vol", snapshot.btc_high_vol),
        ("eth_high_vol", snapshot.eth_high_vol),
        ("eth_harvester_on", snapshot.eth_harvester_on),
    ):
        if not isinstance(value, bool):
            return f"campo booleano invalido: {field_name}={value!r}"
    return None


def resolve_wiring_decision(
    snapshot: RegimeSnapshot | None,
    now: datetime,
    staleness: StalenessPolicy,
    gridbtc_high_vol_action: GridBtcHighVolAction,
) -> WiringDecision:
    if snapshot is None:
        return WiringDecision(
            harvester_command=HarvesterCommand.NO_ACTION_STALE_DATA,
            gridbtc_command=GridBtcCommand.NO_ACTION_STALE_DATA,
            alert=True,
            reason=(
                "nessuno snapshot di regime mai scritto: nessuna azione "
                "automatica, posizione mantenuta."
            ),
        )

    malformed_reason = _malformed_snapshot_reason(snapshot)
    if malformed_reason is not None:
        return WiringDecision(
            harvester_command=HarvesterCommand.NO_ACTION_STALE_DATA,
            gridbtc_command=GridBtcCommand.NO_ACTION_STALE_DATA,
            alert=True,
            reason=(
                f"snapshot con dati invalidi ({malformed_reason}): nessuna "
                "azione automatica, posizione mantenuta."
            ),
        )

    now_utc = _to_naive_utc(now)
    snapshot_time_utc = _to_naive_utc(_parse_timestamp_or_none(snapshot.timestamp))
    age = now_utc - snapshot_time_utc
    if age > staleness.max_age:
        return WiringDecision(
            harvester_command=HarvesterCommand.NO_ACTION_STALE_DATA,
            gridbtc_command=GridBtcCommand.NO_ACTION_STALE_DATA,
            alert=True,
            reason=(
                f"snapshot stantio (età {age}, soglia {staleness.max_age}): "
                "nessuna azione automatica, posizione mantenuta."
            ),
        )

    if snapshot.eth_harvester_on:
        harvester_command = (
            HarvesterCommand.DEFENSIVE if snapshot.eth_high_vol else HarvesterCommand.NORMAL
        )
    else:
        harvester_command = HarvesterCommand.OFF

    if snapshot.btc_high_vol:
        gridbtc_command = (
            GridBtcCommand.HIGH_VOL_STOP_NEW_ORDERS
            if gridbtc_high_vol_action is GridBtcHighVolAction.STOP_NEW_ORDERS
            else GridBtcCommand.HIGH_VOL_CLOSE_GRID_ORDERLY
        )
    else:
        gridbtc_command = GridBtcCommand.NORMAL

    alert = harvester_command is HarvesterCommand.DEFENSIVE or snapshot.btc_high_vol

    return WiringDecision(
        harvester_command=harvester_command,
        gridbtc_command=gridbtc_command,
        alert=alert,
        reason="snapshot valido, comandi derivati dallo stato di regime corrente.",
    )


def load_snapshot_safely(store: RegimeStateStore) -> RegimeSnapshot | None:
    """Wrapper fail-safe su RegimeStateStore.read(): uno snapshot corrotto
    è trattato esattamente come uno snapshot assente (nessuna azione
    automatica) — mai un'eccezione non gestita che fermerebbe il loop di
    wiring senza generare un alert esplicito a monte."""
    try:
        return store.read()
    except ValueError:
        return None
