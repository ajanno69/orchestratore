from __future__ import annotations

from datetime import datetime, timedelta

from components.regime_wiring import GridBtcCommand, HarvesterCommand, WiringDecision
from components.wiring_sequencer import (
    AlertCategory,
    RateLimitPolicy,
    WiringSequencer,
)

T0 = datetime(2026, 7, 6, 12, 0, 0)


def _decision(
    harvester=HarvesterCommand.NORMAL,
    gridbtc=GridBtcCommand.NORMAL,
    alert=False,
    reason="stato di regime corrente.",
) -> WiringDecision:
    return WiringDecision(
        harvester_command=harvester, gridbtc_command=gridbtc, alert=alert, reason=reason
    )


def _sequencer() -> WiringSequencer:
    return WiringSequencer(rate_limit=RateLimitPolicy(window=timedelta(hours=1), max_transitions=3))


def test_command_emitted_on_first_tick_even_if_normal():
    seq = _sequencer()
    out = seq.process(_decision(), now=T0)
    assert len(out.commands) == 1
    assert out.commands[0].harvester_command == HarvesterCommand.NORMAL


def test_command_not_repeated_across_stable_ticks():
    seq = _sequencer()
    seq.process(_decision(), now=T0)
    out2 = seq.process(_decision(), now=T0 + timedelta(minutes=5))
    out3 = seq.process(_decision(), now=T0 + timedelta(minutes=10))
    assert out2.commands == []
    assert out3.commands == []


def test_no_alert_during_quiet_normal_steady_state():
    seq = _sequencer()
    out1 = seq.process(_decision(), now=T0)
    out2 = seq.process(_decision(), now=T0 + timedelta(minutes=5))
    assert out1.alerts == []
    assert out2.alerts == []


def test_command_emitted_again_when_it_changes():
    seq = _sequencer()
    seq.process(_decision(harvester=HarvesterCommand.NORMAL), now=T0)
    out = seq.process(
        _decision(harvester=HarvesterCommand.DEFENSIVE, alert=True), now=T0 + timedelta(minutes=5)
    )
    assert len(out.commands) == 1
    assert out.commands[0].harvester_command == HarvesterCommand.DEFENSIVE


def test_alert_emitted_once_entering_defensive_layer_lavora():
    seq = _sequencer()
    seq.process(_decision(harvester=HarvesterCommand.NORMAL), now=T0)
    out_enter = seq.process(
        _decision(harvester=HarvesterCommand.DEFENSIVE, alert=True), now=T0 + timedelta(minutes=5)
    )
    out_steady = seq.process(
        _decision(harvester=HarvesterCommand.DEFENSIVE, alert=True), now=T0 + timedelta(minutes=10)
    )
    assert len(out_enter.alerts) == 1
    assert out_enter.alerts[0].category == AlertCategory.LAYER_LAVORA_DIFENSIVA
    assert "LAYER LAVORA" in out_enter.alerts[0].text
    assert out_steady.alerts == []  # non ripetuto ad ogni tick in high-vol


def test_alert_emitted_once_on_resuming_to_normal_manual_resume_text():
    seq = _sequencer()
    seq.process(_decision(harvester=HarvesterCommand.NORMAL), now=T0)
    seq.process(
        _decision(harvester=HarvesterCommand.DEFENSIVE, alert=True), now=T0 + timedelta(minutes=5)
    )
    out_resume = seq.process(
        _decision(harvester=HarvesterCommand.NORMAL, alert=False), now=T0 + timedelta(minutes=10)
    )
    out_after = seq.process(
        _decision(harvester=HarvesterCommand.NORMAL, alert=False), now=T0 + timedelta(minutes=15)
    )
    assert len(out_resume.alerts) == 1
    assert out_resume.alerts[0].category == AlertCategory.LAYER_LAVORA_RIENTRO
    assert "ripresa automatica" in out_resume.alerts[0].text
    assert "manuale" in out_resume.alerts[0].text
    assert out_after.alerts == []  # non ripetuto ai tick successivi


def test_blind_alert_layer_cieco_text_distinct_from_lavora():
    seq = _sequencer()
    seq.process(_decision(harvester=HarvesterCommand.NORMAL), now=T0)
    out_blind = seq.process(
        _decision(
            harvester=HarvesterCommand.NO_ACTION_STALE_DATA,
            gridbtc=GridBtcCommand.NO_ACTION_STALE_DATA,
            alert=True,
            reason="snapshot stantio",
        ),
        now=T0 + timedelta(minutes=5),
    )
    assert len(out_blind.alerts) == 1
    assert out_blind.alerts[0].category == AlertCategory.LAYER_CIECO
    text = out_blind.alerts[0].text
    assert "LAYER CIECO" in text
    assert "LAYER LAVORA" not in text


def test_layer_instabile_reminder_refires_during_prolonged_flip_flop():
    """Finding review indipendente checkpoint 2 (b): un flip-flop che
    continua OLTRE la prima finestra di rate-limit non deve produrre
    silenzio totale — l'operatore deve ricevere un promemoria periodico
    (stessa cadenza della finestra) finché l'instabilità persiste, non un
    solo alert seguito da nessun altro segnale per ore."""
    seq = _sequencer()  # window=1h, max_transitions=3
    seq.process(_decision(harvester=HarvesterCommand.NORMAL), now=T0)
    all_alerts = []
    t = T0
    for i in range(72):  # 6 ore di flip ogni 5 minuti: ben oltre la prima finestra
        t = t + timedelta(minutes=5)
        cmd = HarvesterCommand.DEFENSIVE if i % 2 == 0 else HarvesterCommand.NORMAL
        out = seq.process(
            _decision(harvester=cmd, alert=(cmd == HarvesterCommand.DEFENSIVE)), now=t
        )
        all_alerts.extend(out.alerts)

    aggregate_alerts = [a for a in all_alerts if a.category == AlertCategory.LAYER_INSTABILE]
    assert len(aggregate_alerts) >= 3, (
        f"atteso almeno un promemoria per ognuna delle ~5 finestre successive alla prima, "
        f"osservato {len(aggregate_alerts)} — il flip-flop prolungato produce silenzio"
    )


def test_layer_instabile_rearms_after_stabilization_then_new_storm():
    """Finding review indipendente checkpoint 2 (b): dopo che una tempesta
    di flip-flop si stabilizza, una NUOVA tempesta successiva deve
    riarmare l'alert aggregato — non deve restare disarmato per sempre
    dopo la prima."""
    seq = _sequencer()  # window=1h, max_transitions=3
    seq.process(_decision(harvester=HarvesterCommand.NORMAL), now=T0)

    t = T0
    first_storm_alerts = []
    for i in range(6):
        t = t + timedelta(minutes=1)
        cmd = HarvesterCommand.DEFENSIVE if i % 2 == 0 else HarvesterCommand.NORMAL
        out = seq.process(
            _decision(harvester=cmd, alert=(cmd == HarvesterCommand.DEFENSIVE)), now=t
        )
        first_storm_alerts.extend(out.alerts)
    assert any(a.category == AlertCategory.LAYER_INSTABILE for a in first_storm_alerts)

    # stabilizzazione: molti tick FERMI (nessun cambio di categoria) distanziati
    # su >1h, cosi' tutte le transizioni escono dalla finestra di rate-limit
    # senza che nessun tick generi esso stesso una nuova transizione (altrimenti
    # si rischia di far scattare per caso il ramo "else" del codice bacato,
    # mascherando il bug invece di verificarlo)
    for minutes in (10, 30, 50, 70, 90, 130):
        t = t + timedelta(minutes=minutes)
        seq.process(_decision(harvester=HarvesterCommand.NORMAL), now=t)

    second_storm_alerts = []
    for i in range(6):
        t = t + timedelta(minutes=1)
        cmd = HarvesterCommand.DEFENSIVE if i % 2 == 0 else HarvesterCommand.NORMAL
        out = seq.process(
            _decision(harvester=cmd, alert=(cmd == HarvesterCommand.DEFENSIVE)), now=t
        )
        second_storm_alerts.extend(out.alerts)

    assert any(a.category == AlertCategory.LAYER_INSTABILE for a in second_storm_alerts), (
        "la seconda tempesta non ha riarmato l'alert LAYER_INSTABILE dopo la stabilizzazione"
    )


def test_sequencer_reemits_current_state_on_fresh_instance_simulating_restart():
    """Contratto di riavvio (finding review indipendente checkpoint 2, a):
    lo stato di dedup è in-memory ed effimero. Una nuova istanza (come
    dopo un restart del processo) deve riemettere comando E alert dello
    stato corrente al primo tick, anche se quello stato "di fatto" non è
    appena cambiato — sicuro solo perché i comandi sono level-triggered
    (ridichiarano uno stato, non eseguono un'azione one-shot)."""
    seq = _sequencer()
    out = seq.process(_decision(harvester=HarvesterCommand.DEFENSIVE, alert=True), now=T0)
    assert len(out.commands) == 1
    assert out.commands[0].harvester_command == HarvesterCommand.DEFENSIVE
    assert len(out.alerts) == 1
    assert out.alerts[0].category == AlertCategory.LAYER_LAVORA_DIFENSIVA


def test_rate_limit_aggregates_rapid_flip_flop_alerts():
    seq = _sequencer()  # max_transitions=3 in finestra 1h
    seq.process(_decision(harvester=HarvesterCommand.NORMAL), now=T0)
    flips = []
    t = T0
    for i in range(6):
        t = t + timedelta(minutes=1)
        cmd = HarvesterCommand.DEFENSIVE if i % 2 == 0 else HarvesterCommand.NORMAL
        flips.append(
            seq.process(_decision(harvester=cmd, alert=(cmd == HarvesterCommand.DEFENSIVE)), now=t)
        )

    all_alerts = [a for out in flips for a in out.alerts]
    aggregate_alerts = [a for a in all_alerts if a.category == AlertCategory.LAYER_INSTABILE]
    individual_working_alerts = [
        a
        for a in all_alerts
        if a.category in (AlertCategory.LAYER_LAVORA_DIFENSIVA, AlertCategory.LAYER_LAVORA_RIENTRO)
    ]
    assert len(aggregate_alerts) >= 1
    assert "LAYER INSTABILE" in aggregate_alerts[0].text
    # dopo l'aggregazione, il flip-flop non deve continuare a generare un
    # alert individuale per ogni transizione successiva (non amplifica)
    assert len(individual_working_alerts) < 6
