"""Harness di dimostrazione per il checkpoint 2 ("wiring implementato
pre-deploy", piano M2, binario harvester). Monta il wiring COMPLETO
(lettura snapshot -> decisione -> comando -> alert) con due doppioni
controllabili:

- sorgente snapshot sintetica: un `RegimeStateStore` reale su una
  directory temporanea, alimentato scrivendo `RegimeSnapshot` validi
  (via `build_snapshot`) o, per lo scenario di corruzione, testo JSON
  scritto direttamente sul file per simulare dati reali malformati.
- sink comandi/alert: nessun canale reale (niente Telegram, niente
  harvester vero) — gli eventi emessi da `WiringSequencer` vengono solo
  raccolti in una lista e stampati in tabelle markdown.

Nessuna chiave, nessun deploy, nessuna modifica a config di produzione.
Ogni scenario include asserzioni esplicite sull'esito atteso: uno
scenario che si limitasse a stampare senza verificare non sarebbe una
dimostrazione, sarebbe una speranza. Se un'asserzione fallisce, lo
script esce con errore — il checkpoint riceve solo un sistema verificato
per davvero (comando eseguito + output osservato), non una descrizione
in prosa."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from components.regime_wiring import (  # noqa: E402
    GridBtcHighVolAction,
    HarvesterCommand,
    StalenessPolicy,
    load_snapshot_safely,
    resolve_wiring_decision,
)
from components.wiring_sequencer import (  # noqa: E402
    AlertCategory,
    RateLimitPolicy,
    WiringSequencer,
)
from regime.store import RegimeStateStore, build_snapshot  # noqa: E402

STALENESS = StalenessPolicy(max_age=timedelta(hours=1))
RATE_LIMIT = RateLimitPolicy(window=timedelta(hours=1), max_transitions=3)
GRIDBTC_ACTION_PLACEHOLDER = GridBtcHighVolAction.STOP_NEW_ORDERS
T0 = datetime(2026, 7, 6, 12, 0, 0)


def print_table(title: str, rows: list[dict]) -> None:
    print(f"\n### {title}\n")
    if not rows:
        print("(nessun tick)")
        return
    cols = list(rows[0].keys())
    print("| " + " | ".join(cols) + " |")
    print("|" + "|".join("---" for _ in cols) + "|")
    for row in rows:
        print("| " + " | ".join(str(row[c]) for c in cols) + " |")


def run_tick(store, sequencer, now, label, rows) -> tuple:
    snapshot = load_snapshot_safely(store)
    decision = resolve_wiring_decision(
        snapshot,
        now=now,
        staleness=STALENESS,
        gridbtc_high_vol_action=GRIDBTC_ACTION_PLACEHOLDER,
    )
    output = sequencer.process(decision, now=now)
    rows.append(
        {
            "tick": label,
            "now (UTC)": now.isoformat(sep=" "),
            "harvester_cmd": decision.harvester_command.value,
            "gridbtc_cmd": decision.gridbtc_command.value,
            "decision.alert": decision.alert,
            "comandi emessi": "; ".join(
                f"{c.harvester_command.value}/{c.gridbtc_command.value}" for c in output.commands
            )
            or "-",
            "alert emessi": "; ".join(f"[{a.category.value}] {a.text}" for a in output.alerts)
            or "-",
        }
    )
    return decision, output


def scenario_1_vita_normale() -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        store = RegimeStateStore(tmp)
        sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
        rows: list[dict] = []
        for i, minutes in enumerate((0, 15, 30)):
            now = T0 + timedelta(minutes=minutes)
            store.write(build_snapshot(False, False, True, now=now))
            decision, output = run_tick(store, sequencer, now, f"t+{minutes}m", rows)
            assert decision.harvester_command == HarvesterCommand.NORMAL
            assert decision.alert is False
            if i > 0:
                assert output.commands == [], "comando ripetuto in stato stabile (dedup fallito)"
                assert output.alerts == [], "alert spurio in stato stabile e senza transizioni"
        return rows


def scenario_2_3_entrata_e_rientro_defensive() -> tuple[list[dict], list[dict]]:
    with tempfile.TemporaryDirectory() as tmp:
        store = RegimeStateStore(tmp)
        sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
        rows_enter: list[dict] = []
        rows_exit: list[dict] = []

        store.write(build_snapshot(False, False, True, now=T0))
        run_tick(store, sequencer, T0, "t+0m (low-vol)", rows_enter)

        store.write(build_snapshot(False, True, True, now=T0 + timedelta(minutes=10)))
        decision, output = run_tick(
            store, sequencer, T0 + timedelta(minutes=10), "t+10m (entra high-vol)", rows_enter
        )
        assert decision.harvester_command == HarvesterCommand.DEFENSIVE
        assert len(output.commands) == 1
        assert len(output.alerts) == 1
        assert output.alerts[0].category == AlertCategory.LAYER_LAVORA_DIFENSIVA
        assert "LAYER LAVORA" in output.alerts[0].text

        store.write(build_snapshot(False, True, True, now=T0 + timedelta(minutes=20)))
        decision, output = run_tick(
            store, sequencer, T0 + timedelta(minutes=20), "t+20m (ancora high-vol)", rows_enter
        )
        assert output.commands == [], "comando DEFENSIVE ripetuto ad ogni tick (dedup fallito)"
        assert output.alerts == [], "alert LAYER LAVORA ripetuto ad ogni tick in high-vol"

        store.write(build_snapshot(False, False, True, now=T0 + timedelta(minutes=30)))
        decision, output = run_tick(
            store, sequencer, T0 + timedelta(minutes=30), "t+30m (rientra low-vol)", rows_exit
        )
        assert decision.harvester_command == HarvesterCommand.NORMAL
        assert len(output.commands) == 1
        assert len(output.alerts) == 1
        assert output.alerts[0].category == AlertCategory.LAYER_LAVORA_RIENTRO
        assert "manuale" in output.alerts[0].text
        assert "ripresa automatica" in output.alerts[0].text

        store.write(build_snapshot(False, False, True, now=T0 + timedelta(minutes=40)))
        decision, output = run_tick(
            store, sequencer, T0 + timedelta(minutes=40), "t+40m (low-vol stabile)", rows_exit
        )
        assert output.commands == []
        assert output.alerts == [], "alert di rientro ripetuto oltre la singola transizione"

        return rows_enter, rows_exit


def scenario_4_snapshot_stantio() -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        store = RegimeStateStore(tmp)
        sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
        rows: list[dict] = []

        store.write(build_snapshot(False, False, True, now=T0))
        run_tick(store, sequencer, T0, "t+0m (fresco)", rows)

        stale_now = T0 + timedelta(hours=2)  # oltre la soglia di 1h, file non riscritto
        decision, output = run_tick(
            store, sequencer, stale_now, "t+2h (stantio, processo morto)", rows
        )
        assert decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
        assert decision.alert is True
        assert len(output.alerts) == 1
        assert output.alerts[0].category == AlertCategory.LAYER_CIECO
        assert "LAYER CIECO" in output.alerts[0].text
        assert "LAYER LAVORA" not in output.alerts[0].text

        decision, output = run_tick(
            store, sequencer, T0 + timedelta(hours=2, minutes=10), "t+2h10m (ancora stantio)", rows
        )
        assert output.alerts == [], "alert LAYER CIECO ripetuto ad ogni tick stantio"
        return rows


def scenario_5_snapshot_corrotto() -> list[dict]:
    rows: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp:
        store = RegimeStateStore(tmp)
        sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
        path = Path(tmp) / "regime_state.json"
        path.write_text(
            '{"timestamp": "2026-07-06T12:00:00Z", "btc_high_vol": false, "eth_high_vol": false}',
            encoding="utf-8",
        )
        decision, output = run_tick(store, sequencer, T0, "campo mancante (eth_harvester_on)", rows)
        assert decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
        assert decision.alert is True
        assert output.alerts[0].category == AlertCategory.LAYER_CIECO

    with tempfile.TemporaryDirectory() as tmp:
        store = RegimeStateStore(tmp)
        sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
        path = Path(tmp) / "regime_state.json"
        path.write_text(
            '{"timestamp": "non-una-data", "btc_high_vol": false, "eth_high_vol": false, '
            '"eth_harvester_on": true}',
            encoding="utf-8",
        )
        decision, output = run_tick(store, sequencer, T0, "timestamp malformato", rows)
        assert decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
        assert decision.alert is True
        assert output.alerts[0].category == AlertCategory.LAYER_CIECO

    with tempfile.TemporaryDirectory() as tmp:
        store = RegimeStateStore(tmp)
        sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
        path = Path(tmp) / "regime_state.json"
        path.write_text(
            '{"timestamp": "2026-07-06T12:00:00Z", "btc_high_vol": "yes", "eth_high_vol": false, '
            '"eth_harvester_on": true}',
            encoding="utf-8",
        )
        decision, output = run_tick(
            store, sequencer, T0, "bool invalido (btc_high_vol='yes')", rows
        )
        assert decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
        assert decision.alert is True
        assert output.alerts[0].category == AlertCategory.LAYER_CIECO

    return rows


def scenario_6_staleness_al_bordo() -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        store = RegimeStateStore(tmp)
        store.write(build_snapshot(False, False, True, now=T0))
        rows: list[dict] = []
        cases = [
            ("t+59m59s (sotto soglia)", T0 + timedelta(minutes=59, seconds=59), False),
            ("t+60m esatti (== soglia)", T0 + timedelta(minutes=60), False),
            ("t+60m1s (appena sopra soglia)", T0 + timedelta(minutes=60, seconds=1), True),
        ]
        for label, now, expect_stale in cases:
            snapshot = load_snapshot_safely(store)
            decision = resolve_wiring_decision(
                snapshot,
                now=now,
                staleness=STALENESS,
                gridbtc_high_vol_action=GRIDBTC_ACTION_PLACEHOLDER,
            )
            is_stale = decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
            rows.append(
                {
                    "tick": label,
                    "età vs soglia (1h)": str(now - T0),
                    "esito atteso": "STANTIO" if expect_stale else "FRESCO",
                    "esito osservato": "STANTIO" if is_stale else "FRESCO",
                }
            )
            assert is_stale == expect_stale, f"boundary ambiguo/errato per {label}"
        return rows


def scenario_7_flip_flop() -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        store = RegimeStateStore(tmp)
        sequencer = WiringSequencer(rate_limit=RATE_LIMIT)
        rows: list[dict] = []

        store.write(build_snapshot(False, False, True, now=T0))
        run_tick(store, sequencer, T0, "t+0m (baseline low-vol)", rows)

        all_alert_categories: list[AlertCategory] = []
        for i in range(6):
            now = T0 + timedelta(minutes=i + 1)
            eth_high = i % 2 == 0
            store.write(build_snapshot(False, eth_high, True, now=now))
            label = f"t+{i + 1}m ({'high' if eth_high else 'low'}-vol, flip #{i + 1})"
            _, output = run_tick(store, sequencer, now, label, rows)
            all_alert_categories.extend(a.category for a in output.alerts)

        assert AlertCategory.LAYER_INSTABILE in all_alert_categories, (
            "il rate-limit non ha aggregato il flip-flop in un alert LAYER INSTABILE"
        )
        individual_working = [
            c
            for c in all_alert_categories
            if c in (AlertCategory.LAYER_LAVORA_DIFENSIVA, AlertCategory.LAYER_LAVORA_RIENTRO)
        ]
        assert len(individual_working) < 6, (
            "il wiring ha amplificato il flip-flop (nessuna soppressione)"
        )
        return rows


def main() -> None:
    print("# Harness dimostrazione wiring — checkpoint 2 (M2, binario harvester)")
    print(
        f"\nStaleness policy: max_age={STALENESS.max_age}. "
        f"Rate-limit alert: max {RATE_LIMIT.max_transitions} transizioni / {RATE_LIMIT.window}. "
        f"GridBtcHighVolAction usato solo come placeholder di firma "
        f"({GRIDBTC_ACTION_PLACEHOLDER.value}) — GridBTC resta condizionale, "
        "nessuna decisione presa qui."
    )

    print_table("Scenario 1 — vita normale (ETH low-vol stabile)", scenario_1_vita_normale())

    rows_enter, rows_exit = scenario_2_3_entrata_e_rientro_defensive()
    print_table("Scenario 2 — transizione ETH low->high", rows_enter)
    print_table("Scenario 3 — rientro high->low (nessuna ripresa automatica)", rows_exit)

    print_table("Scenario 4 — snapshot stantio (processo morto)", scenario_4_snapshot_stantio())
    print_table("Scenario 5 — snapshot corrotto (3 varianti)", scenario_5_snapshot_corrotto())
    print_table("Scenario 6 — staleness al bordo", scenario_6_staleness_al_bordo())
    print_table("Scenario 7 — flip-flop (rate-limit)", scenario_7_flip_flop())

    print("\nTutte le asserzioni degli scenari sono passate (nessuna eccezione sollevata).")


if __name__ == "__main__":
    main()
