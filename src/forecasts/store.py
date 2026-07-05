"""Store append-only per ForecastRecord (stesso pattern di
fiscal.ledger.FiscalLedger da quantpedia-validation: mai UPDATE/DELETE su
un record esistente — correzioni si registrano come nuovo record)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from forecasts.schema import FORECAST_COLUMNS, ForecastRecord


class ForecastStore:
    def __init__(self, base_path: Path | str) -> None:
        self._path = Path(base_path) / "forecasts.parquet"

    def append(self, record: ForecastRecord) -> None:
        row = pd.DataFrame([record.to_row()], columns=FORECAST_COLUMNS)
        if self._path.exists():
            existing = pd.read_parquet(self._path)
            combined = pd.concat([existing, row], ignore_index=True)
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            combined = row
        combined.to_parquet(self._path, index=False)

    def read_all(self) -> pd.DataFrame:
        if not self._path.exists():
            return pd.DataFrame(columns=FORECAST_COLUMNS)
        return pd.read_parquet(self._path)
