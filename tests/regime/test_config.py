from __future__ import annotations

from pathlib import Path

from regime.config import load_regime_config

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "regime.yaml"


def test_load_regime_config_reads_btc_and_eth_vol_thresholds():
    config = load_regime_config(CONFIG_PATH)
    assert config.vol_by_asset["BTC"].enter_threshold == 0.8711
    assert config.vol_by_asset["BTC"].exit_threshold == 0.5940
    assert config.vol_by_asset["ETH"].enter_threshold == 0.9990
    assert config.vol_by_asset["ETH"].exit_threshold == 0.8301
    assert config.vol_by_asset["BTC"].ewma_span == 32
    assert config.vol_by_asset["ETH"].ewma_span == 32


def test_load_regime_config_reads_funding_thresholds():
    config = load_regime_config(CONFIG_PATH)
    assert config.funding_by_asset["ETH"].enter_threshold == 0.0005
    assert config.funding_by_asset["ETH"].exit_threshold == 0.0002
