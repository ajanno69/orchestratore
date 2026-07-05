from __future__ import annotations

import pytest

from regime.funding_state import CcxtOkxFundingRateSource, FundingRegimeState, FundingStateConfig


def test_funding_state_turns_on_above_enter_threshold():
    config = FundingStateConfig(enter_threshold=0.0005, exit_threshold=0.0002)
    state = FundingRegimeState(config=config)
    assert state.update(0.0001) is False
    assert state.update(0.0008) is True


def test_funding_state_does_not_flip_flop_across_single_threshold():
    config = FundingStateConfig(enter_threshold=0.0005, exit_threshold=0.0002)
    state = FundingRegimeState(config=config)
    state.update(0.0008)  # harvester ON
    for value in [0.00035, 0.0003, 0.0004, 0.00025]:
        state.update(value)
    assert state.is_harvester_on is True  # mai sceso sotto exit=0.0002


def test_funding_state_turns_off_only_below_exit_threshold():
    config = FundingStateConfig(enter_threshold=0.0005, exit_threshold=0.0002)
    state = FundingRegimeState(config=config)
    state.update(0.0008)
    state.update(0.0001)
    assert state.is_harvester_on is False


class _FakeExchange:
    def __init__(self, funding_rate: float) -> None:
        self._funding_rate = funding_rate
        self.last_symbol: str | None = None

    def fetch_funding_rate(self, symbol: str) -> dict:
        self.last_symbol = symbol
        return {"fundingRate": self._funding_rate}


def test_ccxt_okx_funding_rate_source_reads_from_exchange():
    exchange = _FakeExchange(funding_rate=0.00042)
    source = CcxtOkxFundingRateSource(exchange)
    assert source.fetch("ETH") == pytest.approx(0.00042)
    assert exchange.last_symbol == "ETH/USDT:USDT"
