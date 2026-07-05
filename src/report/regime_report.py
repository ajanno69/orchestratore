"""Espone lo stato di regime corrente al report (ADR-036 §3)."""

from __future__ import annotations

from regime.store import RegimeSnapshot, RegimeStateStore


def format_regime_section(snapshot: RegimeSnapshot | None) -> str:
    """Sezione testuale del report settimanale/mensile con il regime
    corrente. Nessuno snapshot ancora scritto -> messaggio esplicito,
    mai un crash o un default silenzioso."""
    if snapshot is None:
        return "Regime: nessuno snapshot disponibile ancora."

    def _state(flag: bool) -> str:
        return "ON" if flag else "OFF"

    return (
        f"Regime al {snapshot.timestamp}:\n"
        f"  BTC high-vol: {_state(snapshot.btc_high_vol)}\n"
        f"  ETH high-vol: {_state(snapshot.eth_high_vol)}\n"
        f"  ETH harvester: {_state(snapshot.eth_harvester_on)}"
    )


def load_and_format_regime_section(store: RegimeStateStore) -> str:
    return format_regime_section(store.read())
