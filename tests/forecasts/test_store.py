from __future__ import annotations

from forecasts.schema import ForecastRecord
from forecasts.store import ForecastStore


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


def test_read_all_empty_when_no_data(tmp_path):
    store = ForecastStore(tmp_path)
    df = store.read_all()
    assert len(df) == 0
    assert list(df.columns) == [
        "timestamp", "asset", "horizon", "p_up", "model_version_hash", "feature_ref",
    ]


def test_append_then_read_all_roundtrip(tmp_path):
    store = ForecastStore(tmp_path)
    store.append(_record(asset="BTC"))
    store.append(_record(asset="ETH", horizon="72h"))
    df = store.read_all()
    assert len(df) == 2
    assert set(df["asset"]) == {"BTC", "ETH"}


def test_append_is_additive_never_overwrites(tmp_path):
    store = ForecastStore(tmp_path)
    for i in range(5):
        store.append(_record(model_version_hash=f"v{i}"))
    df = store.read_all()
    assert len(df) == 5
