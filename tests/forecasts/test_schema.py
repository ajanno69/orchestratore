from __future__ import annotations

import pytest

from forecasts.schema import ForecastRecord


def _record(**overrides):
    defaults = dict(
        timestamp="2026-07-05T00:00:00Z",
        asset="BTC",
        horizon="24h",
        p_up=0.55,
        model_version_hash="abc123",
        feature_ref="features/2026-07-05.parquet",
    )
    defaults.update(overrides)
    return ForecastRecord(**defaults)


def test_valid_record_constructs():
    record = _record()
    assert record.asset == "BTC"
    assert record.horizon == "24h"


def test_invalid_horizon_raises():
    with pytest.raises(ValueError, match="horizon non valido"):
        _record(horizon="1h")


def test_p_up_out_of_range_raises():
    with pytest.raises(ValueError, match="p_up fuori range"):
        _record(p_up=1.5)


def test_to_row_returns_all_columns():
    row = _record().to_row()
    assert set(row.keys()) == {
        "timestamp", "asset", "horizon", "p_up", "model_version_hash", "feature_ref",
    }
