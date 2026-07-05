from __future__ import annotations

import pandas as pd

from forecasts.schema import ForecastRecord
from forecasts.store import ForecastStore
from report.monthly_forecast_report import build_monthly_report


def test_report_with_no_forecasts_says_so_explicitly(tmp_path):
    store = ForecastStore(tmp_path)
    report = build_monthly_report(store, outcomes_by_asset={})
    assert report == "Report mensile Binario B: nessuna previsione registrata ancora."


def test_report_scores_existing_forecasts(tmp_path):
    store = ForecastStore(tmp_path)
    store.append(ForecastRecord(
        timestamp="2026-07-01T00:00:00Z", asset="BTC", horizon="24h",
        p_up=0.9, model_version_hash="v0", feature_ref="f1",
    ))
    store.append(ForecastRecord(
        timestamp="2026-07-02T00:00:00Z", asset="BTC", horizon="24h",
        p_up=0.1, model_version_hash="v0", feature_ref="f2",
    ))
    outcomes = {"BTC": pd.Series([True, False])}
    report = build_monthly_report(store, outcomes)
    assert "BTC 24h: n=2 hit_rate=1.000" in report
