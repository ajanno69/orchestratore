# src/regime/store.py
"""Persistenza dello stato di regime corrente (ADR-036 §3: 'output: regime
corrente persistito + esposto al report'). Stato singolo (non append-only:
il regime è uno STATO, non un evento storico) — un JSON con l'ultimo
snapshot, sovrascritto a ogni update.

`resolve_initial_snapshot` è il punto di reseeding al riavvio: chi
ricostruisce `VolRegimeState`/`FundingRegimeState` dopo un riavvio del
processo DEVE passare il valore risolto qui come `is_high_vol`/
`is_harvester_on` iniziale, non lasciare il default `False` della
dataclass — altrimenti un riavvio con l'osservazione corrente dentro la
banda morta reintroduce esattamente il flip spurio che l'isteresi doveva
prevenire."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class RegimeSnapshot:
    timestamp: str  # ISO 8601 UTC
    btc_high_vol: bool
    eth_high_vol: bool
    eth_harvester_on: bool

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> RegimeSnapshot:
        return RegimeSnapshot(
            timestamp=data["timestamp"],
            btc_high_vol=data["btc_high_vol"],
            eth_high_vol=data["eth_high_vol"],
            eth_harvester_on=data["eth_harvester_on"],
        )


class RegimeStateStore:
    """Store del solo stato corrente (`regime_state.json`), non storico."""

    def __init__(self, base_path: Path | str) -> None:
        self._path = Path(base_path) / "regime_state.json"

    def write(self, snapshot: RegimeSnapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")

    def read(self) -> RegimeSnapshot | None:
        if not self._path.exists():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return RegimeSnapshot.from_dict(raw)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(
                f"snapshot di regime corrotto o illeggibile in {self._path}: {exc}. "
                "Non si può decidere lo stato di regime da un file corrotto — "
                "ripristinare da backup o cancellare il file per ripartire dal "
                "default esplicito (resolve_initial_snapshot) prima di riavviare."
            ) from exc


def build_snapshot(
    btc_high_vol: bool, eth_high_vol: bool, eth_harvester_on: bool, now: datetime | None = None
) -> RegimeSnapshot:
    ts = (now or datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")
    return RegimeSnapshot(
        timestamp=ts,
        btc_high_vol=btc_high_vol,
        eth_high_vol=eth_high_vol,
        eth_harvester_on=eth_harvester_on,
    )


def resolve_initial_snapshot(store: RegimeStateStore) -> RegimeSnapshot:
    """Stato da usare per riseminare `VolRegimeState`/`FundingRegimeState`
    all'avvio del processo. Se esiste uno snapshot persistito, è quello
    (reseeding: nessun flip indotto dal solo riavvio). Se NON esiste ancora
    nessuno snapshot (primo avvio assoluto), il default è dichiarato qui
    esplicitamente — bassa vol su entrambi gli asset, harvester OFF — non
    lasciato al default implicito della dataclass `VolRegimeState`/
    `FundingRegimeState` (che per conto suo parte comunque da False, ma la
    scelta va presa e documentata a questo livello, non per coincidenza)."""
    snapshot = store.read()
    if snapshot is not None:
        return snapshot
    return RegimeSnapshot(
        timestamp="1970-01-01T00:00:00Z",  # nessuna osservazione reale ancora
        btc_high_vol=False,
        eth_high_vol=False,
        eth_harvester_on=False,
    )
