"""Report settimanale (ADR-036 §5): regime corrente + inventario VPS con
diff vs settimana precedente (punto 3-bis, lezione mft_engine)."""

from __future__ import annotations

from regime.store import RegimeSnapshot
from report.inventory import InventoryDiff
from report.regime_report import format_regime_section


def build_weekly_report(
    regime_snapshot: RegimeSnapshot | None, inventory_diff: InventoryDiff
) -> str:
    sections = [format_regime_section(regime_snapshot), "", _format_inventory_diff(inventory_diff)]
    return "\n".join(sections)


def _format_inventory_diff(diff: InventoryDiff) -> str:
    if diff.is_empty:
        return "Inventario VPS: nessuna variazione rispetto alla settimana precedente."

    lines = ["Inventario VPS — variazioni rispetto alla settimana precedente:"]
    for category, items in diff.added.items():
        for item in items:
            lines.append(f"  + [{category}] {item}")
    for category, items in diff.removed.items():
        for item in items:
            lines.append(f"  - [{category}] {item}")
    return "\n".join(lines)
