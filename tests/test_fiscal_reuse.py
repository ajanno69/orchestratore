"""Smoke test del riuso del motore fiscale da quantpedia-validation come
libreria (CLAUDE.md 'riuso deliberato' — non duplicare il codice, solo la
config). Se questo test fallisce, il pythonpath verso
D:/Claude/quantpedia-validation/src (pyproject.toml) e' rotto."""

from __future__ import annotations

from pathlib import Path

import pytest
from fiscal.classifier import load_fiscal_rules
from fiscal.engine import RealizedEvent, compute_fiscal_years

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "fiscal.yaml"


def test_load_fiscal_rules_from_orchestrator_own_config():
    rules = load_fiscal_rules(CONFIG_PATH)
    assert rules.crypto_differenziale.rate == pytest.approx(0.33)
    assert rules.crypto_differenziale.carry_forward_years == 4


def test_crypto_gain_taxed_at_33_percent_via_reused_engine():
    rules = load_fiscal_rules(CONFIG_PATH)
    events = [
        RealizedEvent(year=2026, fiscal_class="crypto_c_sexies", symbol="ETH", amount_eur=1_000.0)
    ]
    results = compute_fiscal_years(events, rules)
    assert results[2026].imposta_redditi_diversi == pytest.approx(330.0)
