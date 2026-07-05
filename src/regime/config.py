"""Loader del config regime.yaml (ADR-036 §3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from regime.funding_state import FundingStateConfig
from regime.vol_state import VolStateConfig


@dataclass(frozen=True)
class RegimeConfig:
    vol_by_asset: dict[str, VolStateConfig]
    funding_by_asset: dict[str, FundingStateConfig]


def load_regime_config(path: Path | str) -> RegimeConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    ewma_span = raw["vol"]["ewma_span"]
    vol_by_asset = {
        asset.upper(): VolStateConfig(
            ewma_span=ewma_span,
            enter_threshold=cfg["enter_threshold"],
            exit_threshold=cfg["exit_threshold"],
        )
        for asset, cfg in raw["vol"].items()
        if asset != "ewma_span"
    }

    funding_by_asset = {
        asset.upper(): FundingStateConfig(
            enter_threshold=cfg["enter_threshold"],
            exit_threshold=cfg["exit_threshold"],
        )
        for asset, cfg in raw.get("funding", {}).items()
    }

    return RegimeConfig(vol_by_asset=vol_by_asset, funding_by_asset=funding_by_asset)
