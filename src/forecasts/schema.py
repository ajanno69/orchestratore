"""Schema Binario B: tabella forecasts append-only (ADR-036 §4).
Un ForecastRecord per ogni previsione emessa a orario fisso (00:00 UTC)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

_VALID_HORIZONS = ("24h", "72h")

FORECAST_COLUMNS: list[str] = [
    "timestamp",
    "asset",
    "horizon",
    "p_up",
    "model_version_hash",
    "feature_ref",
]


@dataclass(frozen=True)
class ForecastRecord:
    """Previsione immutabile (ADR-036 §4): P(rendimento>0) calibrata,
    orizzonte 24h (primario) o 72h (secondario), versione modello e
    riferimento allo snapshot feature usati (per riproducibilità)."""

    timestamp: str  # ISO 8601 UTC, orario fisso 00:00
    asset: str
    horizon: str
    p_up: float
    model_version_hash: str
    feature_ref: str

    def __post_init__(self) -> None:
        if self.horizon not in _VALID_HORIZONS:
            raise ValueError(
                f"horizon non valido: {self.horizon!r} (atteso {_VALID_HORIZONS!r} — "
                "ADR-036 §4: terzo orizzonte richiede emendamento pre-registrato esplicito)"
            )
        if not 0.0 <= self.p_up <= 1.0:
            raise ValueError(f"p_up fuori range [0,1]: {self.p_up!r}")

    def to_row(self) -> dict:
        return asdict(self)
