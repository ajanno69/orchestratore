"""Vincoli operativi non negoziabili (ADR-036 §1): budget cap assoluto.
Binario B non passa MAI di qui (scrive solo in forecasts, append-only) —
qualunque futura integrazione che porti binario B a chiamare questo modulo
è la violazione del muro descritta in ADR-036 §2, da fermare subito."""

from __future__ import annotations

BUDGET_CAP_EUR = 5_000.0


def assert_within_budget_cap(deployed_eur: float, cap_eur: float = BUDGET_CAP_EUR) -> None:
    """Solleva ValueError se il capitale deployato supera il cap assoluto.
    L'aumento di capitale è ammesso SOLO via scaling ladder (ADR-036 §6,
    ADR dedicato) — mai come conseguenza silenziosa di un bug di sizing."""
    if deployed_eur > cap_eur:
        raise ValueError(
            f"capitale deployato {deployed_eur:.2f} EUR supera il budget cap "
            f"assoluto di {cap_eur:.2f} EUR (ADR-036 §1). Aumenti di capitale "
            "solo via scaling ladder con ADR dedicato, mai a runtime."
        )
