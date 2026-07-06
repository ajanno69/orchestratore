# M2 — Wiring regime layer a capitale (harvester + GridBTC) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task — MA SOLO DOPO che il checkpoint bloccante "piano completo" (sotto) è stato superato. Nessun task di questo piano va eseguito prima di quel via libera esplicito.

**Goal:** Cablare lo stato del regime layer (già misurato e calibrato in M1/M1.5) a comandi concreti
per l'harvester ETH e per GridBTC, con fail-safe espliciti, senza eseguire nulla di questo piano
finché ogni checkpoint bloccante non è stato superato esplicitamente da Andrea.

**Architecture:** Un componente di wiring puro (`src/components/regime_wiring.py`, Binario A) legge
un `RegimeSnapshot` (già esistente, M1 Task 8-9) e produce COMANDI (dati, non azioni eseguite) per
harvester e GridBTC — mai una chiamata autenticata diretta a Kraken/OKX da questo modulo. La scelta
dell'azione GridBTC in high-vol (stop-nuovi-ordini vs chiusura ordinata) è un parametro esplicito
del componente, mai un default cablato: la scelta del VALORE di quel parametro è riservata al
checkpoint "wiring implementato pre-deploy", informata dall'analisi del Task 2.

**Tech Stack:** Python >=3.11 (stesso repo orchestrator), nessuna nuova dipendenza. Deploy: VPS
Contabo esistente, systemd, pattern canary/healthcheck già in uso da funding-harvester.

## Global Constraints

- **SOLO PIANIFICAZIONE in questa consegna**: nessuna esecuzione, nessuna chiave, nessun deploy,
  nessuna modifica a config di produzione. Il Task 1 (unico task con codice) NON va eseguito finché
  il checkpoint "piano completo" non è superato.
- **Wiring per-asset, nessun segnale combinato** (pre-registrato, non riaprire): harvester legge
  solo lo stato ETH, GridBTC legge solo lo stato BTC.
- **Fail-safe (pre-registrato, non riaprire)**: su snapshot assente O stantio (soglia di staleness
  definita e testata nel Task 1), NESSUNA azione automatica — posizione mantenuta, alert, decisione
  umana. Uno snapshot corrotto è trattato esattamente come uno snapshot assente (mai
  un'eccezione non gestita che interrompe il wiring senza generare alert).
- **Harvester su high-vol ETH (pre-registrato, non riaprire)**: modalità difensiva (blocco nuovi
  ingressi/scale-up, check margin buffer con soglia di rabbocco, alert). NESSUNA chiusura
  automatica delle gambe — la chiusura resta al kill-switch esistente dell'harvester (trigger
  propri, invariati, vivono in `D:\Claude\funding-harvester`, NON toccato da questo piano).
- **GridBTC su high-vol BTC**: la scelta stop-nuovi-ordini vs chiusura ordinata è oggetto di analisi
  (Task 2) con raccomandazione motivata — **la decisione finale è del checkpoint, mai del codice**.
  Il codice (Task 1) espone questa scelta come parametro obbligatorio senza default.
- **Ordine di riattivazione (pre-registrato, non riaprire)**: harvester (gate G3) prima, GridBTC
  dopo.
- **Chiavi**: creazione manuale di Andrea, permessi minimi (mai withdraw), gestite via `sops`/`age`,
  MAI nel repo né nei log. Nessun task di questo piano introduce lettura/gestione di chiavi — il
  wiring produce comandi (dati), non esegue operazioni autenticate.
- **`D:\Claude\crypto-agent` è un repo isolato, di sola lettura per questo piano** (policy globale:
  "non mischiare mai dati/config/blacklist fra progetti"). Il Task 2 lo legge, non lo modifica mai.
- **Convenzione temporale ESPLICITA (chiusura del checkpoint 1, non riaprire)**: tutti i confronti
  di staleness nel Task 1 sono in UTC. Un timestamp aware va convertito con
  `astimezone(timezone.utc)` PRIMA di un eventuale strip dell'offset — mai un `replace(tzinfo=None)`
  secco, che ignorerebbe silenziosamente l'offset e sbaglierebbe l'età esattamente dell'ampiezza
  dell'offset scartato. Un `now` naive è trattato come UTC per convenzione esplicita (stessa
  convenzione di `regime.store`); un `now` aware va normalizzato con la stessa conversione. **MAI
  `datetime.now()` locale (senza `timezone.utc`) nel path di staleness** — un caller deve usare
  `datetime.now(timezone.utc)` o un naive-UTC dichiarato esplicitamente, non un'ambiguità silenziosa.
- TDD dove il codice è puro e testabile (Task 1); i Task 2-5 sono documenti di analisi/runbook, non
  codice — ciascuno con contenuto completo, non placeholder.
- Ogni task con codice chiude con suite completa verde (`python -m pytest -v`) + `python -m ruff
  check src tests` pulito, stesso rito di M1/M1.5.

---

## Checkpoint bloccanti di questo piano (tre, non uno)

1. **CHECKPOINT "piano completo"** — questo documento + `docs/ADR-037-wiring-regime-layer-capitale.md`.
   Nessun task inizia prima che Andrea lo superi esplicitamente. **Siamo qui ora.**
2. **CHECKPOINT "wiring implementato pre-deploy"** — dopo il Task 1 (codice) e il Task 2 (analisi
   GridBTC), prima di qualunque Task 3 (deploy). Andrea rivede il codice del wiring E sceglie il
   valore del parametro `GridBtcHighVolAction` informato dalla raccomandazione del Task 2.
3. **CHECKPOINT "fine shadow pre-capitale"** — dopo il periodo di shadow/dry-run di ciascun
   componente (Task 4), prima che quel componente tocchi capitale reale. Un checkpoint PER
   COMPONENTE (harvester e GridBTC hanno date/criteri di shadow indipendenti, harvester per primo).

---

## File Structure

```
D:\Claude\orchestrator\
  docs\
    ADR-037-wiring-regime-layer-capitale.md      # già scritto, questa consegna
    gridbtc-highvol-analysis-m2.md               # Task 2
    m2-deploy-runbook.md                          # Task 3
    m2-reactivation-gates.md                       # Task 4
    m2-runbook-operativo-andrea.md                  # Task 5
  src\components\
    regime_wiring.py                              # Task 1
  tests\components\
    test_regime_wiring.py                          # Task 1
```

---

### Task 1: Componente di wiring (RegimeSnapshot → comandi)

**Files:**
- Create: `src/components/regime_wiring.py`
- Test: `tests/components/test_regime_wiring.py`

**Interfaces:**
- Consumes: `regime.store.RegimeSnapshot`, `regime.store.RegimeStateStore`, `regime.store.build_snapshot` (M1 Task 8, già approvato — non reimplementare, non modificare).
- Produces: `HarvesterCommand` (Enum: `NO_ACTION_STALE_DATA`, `NORMAL`, `DEFENSIVE`, `OFF`), `GridBtcCommand` (Enum: `NO_ACTION_STALE_DATA`, `NORMAL`, `HIGH_VOL_STOP_NEW_ORDERS`, `HIGH_VOL_CLOSE_GRID_ORDERLY`), `GridBtcHighVolAction` (Enum: `STOP_NEW_ORDERS`, `CLOSE_GRID_ORDERLY` — nessun default, il chiamante DEVE specificarlo), `StalenessPolicy` (dataclass frozen: `max_age: timedelta`), `WiringDecision` (dataclass frozen: `harvester_command, gridbtc_command, alert: bool, reason: str`), `resolve_wiring_decision(snapshot: RegimeSnapshot | None, now: datetime, staleness: StalenessPolicy, gridbtc_high_vol_action: GridBtcHighVolAction) -> WiringDecision`, `load_snapshot_safely(store: RegimeStateStore) -> RegimeSnapshot | None`. Nessun task successivo in questo piano consuma queste interfacce (il deploy reale è M2 post-checkpoint, fuori da questa consegna) — sono il contratto che il checkpoint 2 rivede.

- [ ] **Step 1: Write the failing tests**

```python
# tests/components/test_regime_wiring.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from components.regime_wiring import (
    GridBtcCommand,
    GridBtcHighVolAction,
    HarvesterCommand,
    StalenessPolicy,
    load_snapshot_safely,
    resolve_wiring_decision,
)
from regime.store import RegimeSnapshot, RegimeStateStore, build_snapshot

STALENESS = StalenessPolicy(max_age=timedelta(hours=1))
NOW = datetime(2026, 7, 6, 12, 0, 0)


def test_no_snapshot_produces_no_action_and_alert():
    decision = resolve_wiring_decision(
        None, now=NOW, staleness=STALENESS, gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS
    )
    assert decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
    assert decision.gridbtc_command == GridBtcCommand.NO_ACTION_STALE_DATA
    assert decision.alert is True


def test_stale_snapshot_produces_no_action_and_alert():
    snapshot = build_snapshot(True, True, True, now=datetime(2026, 7, 6, 10, 0, 0))  # 2h prima di NOW
    decision = resolve_wiring_decision(
        snapshot, now=NOW, staleness=STALENESS, gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS
    )
    assert decision.harvester_command == HarvesterCommand.NO_ACTION_STALE_DATA
    assert decision.gridbtc_command == GridBtcCommand.NO_ACTION_STALE_DATA
    assert decision.alert is True


def test_snapshot_exactly_at_staleness_boundary_is_still_fresh():
    snapshot = build_snapshot(False, False, False, now=datetime(2026, 7, 6, 11, 0, 0))  # esattamente 1h prima
    decision = resolve_wiring_decision(
        snapshot, now=NOW, staleness=STALENESS, gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS
    )
    assert decision.harvester_command != HarvesterCommand.NO_ACTION_STALE_DATA


def test_fresh_snapshot_within_staleness_is_used():
    snapshot = build_snapshot(False, False, False, now=datetime(2026, 7, 6, 11, 30, 0))
    decision = resolve_wiring_decision(
        snapshot, now=NOW, staleness=STALENESS, gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS
    )
    assert decision.harvester_command == HarvesterCommand.OFF
    assert decision.gridbtc_command == GridBtcCommand.NORMAL
    assert decision.alert is False


def test_harvester_defensive_when_on_and_high_vol():
    snapshot = build_snapshot(False, True, True, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot, now=NOW, staleness=STALENESS, gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS
    )
    assert decision.harvester_command == HarvesterCommand.DEFENSIVE
    assert decision.alert is True


def test_harvester_normal_when_on_and_not_high_vol():
    snapshot = build_snapshot(False, False, True, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot, now=NOW, staleness=STALENESS, gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS
    )
    assert decision.harvester_command == HarvesterCommand.NORMAL


def test_harvester_off_when_funding_signal_off_regardless_of_vol():
    snapshot = build_snapshot(False, True, False, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot, now=NOW, staleness=STALENESS, gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS
    )
    assert decision.harvester_command == HarvesterCommand.OFF


def test_gridbtc_stop_new_orders_when_configured_and_high_vol():
    snapshot = build_snapshot(True, False, False, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot, now=NOW, staleness=STALENESS, gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS
    )
    assert decision.gridbtc_command == GridBtcCommand.HIGH_VOL_STOP_NEW_ORDERS
    assert decision.alert is True


def test_gridbtc_close_orderly_when_configured_and_high_vol():
    snapshot = build_snapshot(True, False, False, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot, now=NOW, staleness=STALENESS, gridbtc_high_vol_action=GridBtcHighVolAction.CLOSE_GRID_ORDERLY
    )
    assert decision.gridbtc_command == GridBtcCommand.HIGH_VOL_CLOSE_GRID_ORDERLY


def test_gridbtc_normal_when_not_high_vol():
    snapshot = build_snapshot(False, False, False, now=datetime(2026, 7, 6, 12, 0, 0))
    decision = resolve_wiring_decision(
        snapshot, now=NOW, staleness=STALENESS, gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS
    )
    assert decision.gridbtc_command == GridBtcCommand.NORMAL


def test_load_snapshot_safely_returns_none_on_corrupted_file(tmp_path):
    store = RegimeStateStore(tmp_path)
    (tmp_path / "regime_state.json").write_text("{not valid json", encoding="utf-8")
    assert load_snapshot_safely(store) is None


def test_load_snapshot_safely_returns_snapshot_when_valid(tmp_path):
    store = RegimeStateStore(tmp_path)
    snap = build_snapshot(True, False, False, now=datetime(2026, 7, 6, 12, 0, 0))
    store.write(snap)
    assert load_snapshot_safely(store) == snap


def test_load_snapshot_safely_returns_none_when_no_file(tmp_path):
    store = RegimeStateStore(tmp_path)
    assert load_snapshot_safely(store) is None


def test_resolve_wiring_decision_normalizes_aware_non_utc_now_before_staleness_check():
    """Test dedicato che fallisce con il bug (verificato per davvero: con
    uno strip secco `replace(tzinfo=None)` senza `astimezone` prima, questo
    test fallisce con età 2:00:00 invece di ~0). Un `now` aware in un fuso
    non-UTC (qui CEST, +02:00) che rappresenta LO STESSO istante reale
    dello snapshot deve dare staleness ~0, non ~2h. Soglia di staleness
    volutamente stretta (5 minuti) per distinguere inequivocabilmente i
    due esiti: un errore di 2h farebbe scattare NO_ACTION_STALE_DATA, la
    normalizzazione corretta no."""
    tight_staleness = StalenessPolicy(max_age=timedelta(minutes=5))
    snapshot = build_snapshot(False, False, False, now=datetime(2026, 7, 6, 10, 0, 0))  # 10:00 UTC
    now_cest_same_instant = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    decision = resolve_wiring_decision(
        snapshot,
        now=now_cest_same_instant,
        staleness=tight_staleness,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command != HarvesterCommand.NO_ACTION_STALE_DATA


def test_resolve_wiring_decision_converts_explicit_non_z_offset_in_snapshot_timestamp():
    """Snapshot con timestamp che ha un offset esplicito +02:00 (non il
    solito 'Z' emesso da build_snapshot) — prova che astimezone(utc)
    applica la conversione giusta invece di leggere l'offset come se
    fosse già UTC (che sbaglierebbe l'età di esattamente 2h)."""
    tight_staleness = StalenessPolicy(max_age=timedelta(minutes=5))
    snapshot = RegimeSnapshot(
        timestamp="2026-07-06T14:00:00+02:00",  # = 12:00 UTC
        btc_high_vol=False,
        eth_high_vol=False,
        eth_harvester_on=False,
    )
    now_utc_same_instant = datetime(2026, 7, 6, 12, 0, 0)
    decision = resolve_wiring_decision(
        snapshot,
        now=now_utc_same_instant,
        staleness=tight_staleness,
        gridbtc_high_vol_action=GridBtcHighVolAction.STOP_NEW_ORDERS,
    )
    assert decision.harvester_command != HarvesterCommand.NO_ACTION_STALE_DATA
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/components/test_regime_wiring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'components.regime_wiring'` (o, se il
modulo esiste già ma con lo strip secco anziché `astimezone`, i due test sulla convenzione UTC
falliscono da soli con un'età sbagliata di ~2h — verificato per davvero prima di questa consegna).

- [ ] **Step 3: Write minimal implementation**

```python
# src/components/regime_wiring.py
"""Wiring del regime layer (Binario A) a comandi per harvester ETH e
GridBTC (ADR-037). Modulo PURO: produce COMANDI (dati), non esegue mai
un'operazione autenticata contro Kraken/OKX — quello resta compito di un
executor separato (fuori scope di questo piano, post-checkpoint).

Fail-safe (ADR-037 §3): su snapshot assente O stantio, mai un'azione
automatica — solo `NO_ACTION_STALE_DATA` + alert. Uno snapshot corrotto
(`RegimeStateStore.read()` solleva ValueError) è trattato da
`load_snapshot_safely` esattamente come uno snapshot assente: qui, a
differenza del layer di misura (`regime.vol_state`, che solleva
esplicitamente su input inaffidabile), un input inaffidabile a livello
di wiring capitale deve tradursi in "nessuna azione", non in
un'eccezione che fermerebbe il loop di wiring senza generare alert."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from regime.store import RegimeSnapshot, RegimeStateStore


class HarvesterCommand(Enum):
    NO_ACTION_STALE_DATA = "no_action_stale_data"
    NORMAL = "normal"
    DEFENSIVE = "defensive"
    OFF = "off"


class GridBtcHighVolAction(Enum):
    """Azione da eseguire su GridBTC quando btc_high_vol=True. Nessun
    default: il chiamante deve specificarla esplicitamente. Scelta
    riservata al checkpoint 'wiring implementato pre-deploy' (piano M2),
    informata dall'analisi in docs/gridbtc-highvol-analysis-m2.md."""

    STOP_NEW_ORDERS = "stop_new_orders"
    CLOSE_GRID_ORDERLY = "close_grid_orderly"


class GridBtcCommand(Enum):
    NO_ACTION_STALE_DATA = "no_action_stale_data"
    NORMAL = "normal"
    HIGH_VOL_STOP_NEW_ORDERS = "high_vol_stop_new_orders"
    HIGH_VOL_CLOSE_GRID_ORDERLY = "high_vol_close_grid_orderly"


@dataclass(frozen=True)
class StalenessPolicy:
    max_age: timedelta


@dataclass(frozen=True)
class WiringDecision:
    harvester_command: HarvesterCommand
    gridbtc_command: GridBtcCommand
    alert: bool
    reason: str


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalizza un datetime a naive-UTC per il confronto di staleness.
    Se `dt` è aware, converte prima a UTC (`astimezone`) e SOLO DOPO
    scarta l'offset — mai uno strip secco (`replace(tzinfo=None)` senza
    conversione), che ignorerebbe silenziosamente l'offset e produrrebbe
    un'età sbagliata esattamente dell'ampiezza dell'offset scartato
    (bug reale trovato e chiuso durante la review del checkpoint 1: una
    versione precedente di questo modulo faceva lo strip secco, innocuo
    SOLO perché ogni timestamp prodotto da `regime.store` finisce sempre
    in 'Z'/+00:00, ma silenziosamente sbagliato per qualunque altro
    offset o per un `now` aware non-UTC — verificato per davvero: con lo
    strip secco, un `now` in CEST (+02:00) alla stessa ora reale di uno
    snapshot appena scritto risultava stantio di 2 ore invece di ~0).
    Se `dt` è naive, è già trattato come UTC per convenzione esplicita di
    questo modulo (stessa convenzione di `regime.store`) — **mai un
    datetime locale naive** (es. `datetime.now()` senza `timezone.utc`)
    deve arrivare qui: il chiamante è responsabile di passare
    `datetime.now(timezone.utc)` o un naive-UTC dichiarato esplicitamente."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def resolve_wiring_decision(
    snapshot: RegimeSnapshot | None,
    now: datetime,
    staleness: StalenessPolicy,
    gridbtc_high_vol_action: GridBtcHighVolAction,
) -> WiringDecision:
    if snapshot is None:
        return WiringDecision(
            harvester_command=HarvesterCommand.NO_ACTION_STALE_DATA,
            gridbtc_command=GridBtcCommand.NO_ACTION_STALE_DATA,
            alert=True,
            reason="nessuno snapshot di regime mai scritto: nessuna azione automatica, posizione mantenuta.",
        )

    now_utc = _to_naive_utc(now)
    snapshot_time_utc = _to_naive_utc(datetime.fromisoformat(snapshot.timestamp))
    age = now_utc - snapshot_time_utc
    if age > staleness.max_age:
        return WiringDecision(
            harvester_command=HarvesterCommand.NO_ACTION_STALE_DATA,
            gridbtc_command=GridBtcCommand.NO_ACTION_STALE_DATA,
            alert=True,
            reason=(
                f"snapshot stantio (età {age}, soglia {staleness.max_age}): "
                "nessuna azione automatica, posizione mantenuta."
            ),
        )

    if snapshot.eth_harvester_on:
        harvester_command = (
            HarvesterCommand.DEFENSIVE if snapshot.eth_high_vol else HarvesterCommand.NORMAL
        )
    else:
        harvester_command = HarvesterCommand.OFF

    if snapshot.btc_high_vol:
        gridbtc_command = (
            GridBtcCommand.HIGH_VOL_STOP_NEW_ORDERS
            if gridbtc_high_vol_action is GridBtcHighVolAction.STOP_NEW_ORDERS
            else GridBtcCommand.HIGH_VOL_CLOSE_GRID_ORDERLY
        )
    else:
        gridbtc_command = GridBtcCommand.NORMAL

    alert = harvester_command is HarvesterCommand.DEFENSIVE or snapshot.btc_high_vol

    return WiringDecision(
        harvester_command=harvester_command,
        gridbtc_command=gridbtc_command,
        alert=alert,
        reason="snapshot valido, comandi derivati dallo stato di regime corrente.",
    )


def load_snapshot_safely(store: RegimeStateStore) -> RegimeSnapshot | None:
    """Wrapper fail-safe su RegimeStateStore.read(): uno snapshot corrotto
    è trattato esattamente come uno snapshot assente (nessuna azione
    automatica) — mai un'eccezione non gestita che fermerebbe il loop di
    wiring senza generare un alert esplicito a monte."""
    try:
        return store.read()
    except ValueError:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/components/test_regime_wiring.py -v`
Expected: PASS (15 test)

- [ ] **Step 5: Full suite + ruff**

Run: `cd D:/Claude/orchestrator && python -m pytest -v` — expected: 76 precedenti + 15 nuovi = 91 passing.
Run: `cd D:/Claude/orchestrator && python -m ruff check src tests scripts` — expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/components/regime_wiring.py tests/components/test_regime_wiring.py
git commit -m "feat: componente di wiring regime->comandi harvester/GridBTC (M2)"
```

**NON eseguire questo Step 6 finché il checkpoint "piano completo" non è stato superato.**

---

### Task 2: Analisi GridBTC in high-vol (documento, non codice)

**Files:**
- Create: `docs/gridbtc-highvol-analysis-m2.md`

**GATE FORMALE, BLOCCANTE (ADR-037 §5 + chiusura checkpoint 1) — non scrivere la sezione
"Raccomandazione" del documento prima di aver superato questo gate:**

Prima di scrivere qualunque raccomandazione definitiva, leggere il codice reale del guard
esistente di GridBTC in `D:\Claude\crypto-agent\agent\v2\risk\engine.py` e file correlati
(`agent/v2/orchestrator_hooks.py`, `agent/v2/shadow.py`) — SOLA LETTURA, nessuna modifica a quel
repo. Questo piano NON ha verificato quel codice riga per riga; lo ha solo censito a livello di
changelog (`past project/02_crypto-agent.md`: guard basato su HAR-RV + VPVR + Anchored VWAP,
promosso shadow→HARD il 2026-05-16). Il documento di analisi deve iniziare dichiarando cosa quel
guard fa OGGI (soglie, azione, meccanismo) — con citazione di file:riga del codice reale letto, non
del changelog — prima di proporre come il nuovo segnale di regime debba interagirci. Se questa
lettura non è stata fatta, il documento resta allo stato di "raccomandazione preliminare" (già
presente in questo piano) e NON può essere promosso a raccomandazione definitiva al checkpoint 2.

- [ ] **Step 1: Scrivere il documento con questa struttura minima**

```markdown
# Analisi GridBTC in high-vol BTC — stop-nuovi-ordini vs chiusura ordinata (M2)

## Cosa fa già il guard esistente di GridBTC
[Riassunto del meccanismo HAR-RV/VPVR/Anchored VWAP letto da agent/v2/risk/engine.py — cosa
rileva, quale azione prende oggi, quali soglie usa. Se il guard esistente già copre lo stesso
scenario (BTC high-vol), dichiararlo esplicitamente: il nuovo segnale di regime rischia di
duplicare, non di aggiungere.]

## Opzione A — stop nuovi ordini
[Vantaggi: la griglia esistente resta intatta, nessuna cristallizzazione di perdita non
realizzata, nessuna esposizione a slippage di chiusura in un momento di scarsa liquidità.
Svantaggi: la griglia esistente resta esposta al movimento di prezzo durante l'high-vol.]

## Opzione B — chiusura ordinata della griglia
[Vantaggi: elimina l'esposizione residua durante l'high-vol.
Svantaggi: cristallizza qualunque perdita non realizzata nel momento peggiore (alta vol spesso
coincide con bassa liquidità — chiudere ordinatamente può comunque costare in slippage);
richiede poi una riattivazione esplicita della griglia quando il regime torna normale, un secondo
punto di decisione/rischio operativo che l'Opzione A non ha.]

## Raccomandazione preliminare (di questo piano, da confermare/rivedere dopo la lettura del
## codice reale, punto precedente)

Stop nuovi ordini come default operativo: una griglia Kraken Futures è tipicamente composta da
ordini limite a diversi livelli di prezzo — chiuderla "ordinatamente" in un momento di alta
volatilità significa eseguire più ordini di mercato/cancellazioni proprio quando lo spread è più
largo, il costo peggiore possibile per un'azione che il regime layer avrebbe dovuto rendere PIÙ
prudente, non più costosa. Fermare i nuovi ingressi è l'equivalente Grid della modalità difensiva
già decisa per l'harvester (ADR-037 §4): riduce l'esposizione INCREMENTALE senza forzare
un'uscita nel momento peggiore per farlo.

**Condizione per preferire l'Opzione B invece:** se il guard esistente di GridBTC (punto 1)
dimostra che, storicamente, gli episodi di alta volatilità BTC che il nuovo segnale avrebbe
rilevato sono correlati con drawdown della griglia oltre una soglia di rischio già definita
altrove (es. il gate di go-live GATE_v2_recalibration.md, "rovina < 1%"), allora la chiusura
ordinata anticipata potrebbe ridurre il rischio di coda più della sola prudenza incrementale.
Questo è verificabile SOLO leggendo i dati storici di drawdown reali di GridBTC, non a tavolino.

## Decisione

**NON PRESA QUI.** Riservata al checkpoint "wiring implementato pre-deploy" del piano M2, dopo che
Andrea ha letto questa analisi (e verificato/corretto il punto 1 con il codice reale).
```

- [ ] **Step 2: Nessun test automatizzato — verifica manuale**

Questo è un documento di analisi, non codice. La sua "verifica" è che il punto 1 (cosa fa il guard
esistente) sia stato scritto DOPO aver letto il codice reale, non dedotto dal solo changelog.

- [ ] **Step 3: Commit**

```bash
git add docs/gridbtc-highvol-analysis-m2.md
git commit -m "docs: analisi GridBTC high-vol, stop-ordini vs chiusura ordinata (M2)"
```

---

### Task 3: Runbook di deploy

**Files:**
- Create: `docs/m2-deploy-runbook.md`

- [ ] **Step 1: Scrivere il runbook con questa struttura minima**

```markdown
# Runbook di deploy M2 (VPS Contabo)

Stesso pattern operativo di funding-harvester (systemd + canary + healthcheck), applicato al
processo di wiring. Nessun comando qui va eseguito prima del checkpoint "wiring implementato
pre-deploy".

## Deploy

1. `ssh freqbot@207.180.247.38`
2. `cd /path/to/orchestrator && git pull origin master` (repo orchestrator clonato sul VPS,
   percorso esatto da confermare al momento — non esiste ancora un clone lì, questo è il primo
   deploy di questo repo su quel VPS)
3. Chiavi: NON in questo repo. Create manualmente da Andrea, cifrate con `sops`/`age`, decifrate
   solo a runtime nella working directory del processo (mai su disco in chiaro, mai in un commit).
4. Unit systemd dedicata (nome da definire, es. `orchestrator-wiring.service`), `Restart=on-failure`
   (non `always` senza `RestartSec` — vedi lezione `mft_paper.service` in
   `crypto-agent/docs/DECOMMISSION-2026-07.md`: un `Restart=always` senza verifica di stato pulito
   può rimettere in piedi un processo che dovrebbe restare fermo).
5. Canary: stesso pattern di `funding-harvester-daily-report.timer` — un ping periodico a
   healthchecks.io condizionato su "il ciclo di wiring ha letto lo snapshot e prodotto una
   decisione senza eccezioni", non solo "il processo è vivo" (pattern VIVO-MA-CIECO, vedi
   `funding-harvester/newcrypto/ops/watchdog.py`, non toccato, solo di riferimento).
6. Dopo il deploy: aggiornare l'inventario VPS (`report.inventory`, M1 Task 13) al primo giro utile
   — il nuovo processo deve comparire nel prossimo snapshot, mai un punto cieco come
   `mft_paper.service`.

## Rollback

`systemctl stop <unit> && systemctl disable <unit>` — mai `kill -9` (stesso principio del runbook
harvester M1, `docs/runbook-riattivazione-harvester.md`).
```

- [ ] **Step 2: Commit**

```bash
git add docs/m2-deploy-runbook.md
git commit -m "docs: runbook di deploy M2 (VPS, systemd, canary)"
```

---

### Task 4: Gate di riattivazione per componente

**Files:**
- Create: `docs/m2-reactivation-gates.md`

- [ ] **Step 1: Scrivere il documento con questa struttura minima**

```markdown
# Gate di riattivazione per componente (M2)

Ordine: harvester (gate G3) prima, GridBTC dopo — pre-registrato, non riaperto qui.

## Harvester ETH

- **Durata shadow/dry-run minima:** 2 settimane di wiring attivo in sola lettura (il wiring produce
  decisioni e le logga/alerta, ma l'harvester esegue secondo la sua logica attuale, ignorando il
  comando `DEFENSIVE` — verifica che il wiring produca i comandi giusti SENZA ancora agire su di
  essi).
- **Criteri di promozione (il wiring inizia davvero a bloccare nuovi ingressi in DEFENSIVE):**
  - zero eccezioni non gestite nel loop di wiring per l'intera durata dello shadow;
  - ogni transizione di `eth_high_vol` osservata durante lo shadow è stata alertata correttamente
    (verificabile a mano dai log/alert, confrontati con lo storico reale di `eth_high_vol` nello
    snapshot);
  - nessun falso "NO_ACTION_STALE_DATA" durante lo shadow dovuto a un bug di staleness (soglia
    scelta in Task 1 verificata empiricamente non troppo stretta).
- Dopo la promozione: size invariata rispetto al gate G3 esistente — il wiring aggiunge prudenza,
  non cambia il sizing.

## GridBTC

- **Durata shadow/dry-run minima:** 4 settimane (più lunga dell'harvester: GridBTC ha già capitale
  reale esposto, un errore costa di più — coerente con ADR-037 §6).
- **Criteri di promozione:**
  - stesso criterio "zero eccezioni, alert corretti" dell'harvester;
  - **verifica esplicita di non-conflitto con il guard esistente di GridBTC** (Task 2): durante lo
    shadow, ogni volta che `btc_high_vol=True` E il guard esistente HAR-RV/VPVR scatta
    indipendentemente, il comportamento dei due segnali va confrontato a mano — se sono in
    disaccordo sistematico, la promozione NON procede finché quel disaccordo non è capito;
  - conferma esplicita di Andrea sul valore di `GridBtcHighVolAction` (Task 2), non un default.
- Dopo la promozione: size invariata rispetto allo stato attuale (GridBTC già "promosso HARD") — il
  wiring aggiunge prudenza in high-vol, non cambia il sizing base.
```

- [ ] **Step 2: Commit**

```bash
git add docs/m2-reactivation-gates.md
git commit -m "docs: gate di riattivazione per componente, harvester e GridBTC (M2)"
```

---

### Task 5: Runbook operativo di Andrea

**Files:**
- Create: `docs/m2-runbook-operativo-andrea.md`

- [ ] **Step 1: Scrivere il documento con questa struttura minima**

```markdown
# Runbook operativo — cosa fare quando scatta high-vol (M2)

## Cosa vedo

- Alert (canale da definire in Task 3 — Telegram, stesso canale già in uso per funding-harvester)
  con il campo `reason` di `WiringDecision` (M2 Task 1): dice esattamente perché è scattato
  (snapshot assente/stantio, oppure quale asset è in high-vol).
- Report settimanale (M1 Task 14, `report.weekly_report`) include già la sezione di regime — la
  uso per un controllo di secondo livello, non solo per la reazione in tempo reale all'alert.

## Come verifico lo stato del layer (non solo l'alert)

1. Il canale di alert stesso è vivo? (Questo NON è verificato dall'alert — se il processo di
   wiring muore, non arriva nessun alert. Verificare separatamente che il canary/healthcheck del
   Task 3 stia pingando regolarmente.)
2. `regime.store.RegimeStateStore(base_path).read()` sul VPS: lo snapshot corrente è quello che mi
   aspetto, o è più vecchio della soglia di staleness (Task 1)?
3. Il comando prodotto (`HarvesterCommand`/`GridBtcCommand`) corrisponde a quello che l'harvester/
   GridBTC sta effettivamente eseguendo? (Il wiring produce comandi — un bug nell'executor che li
   consuma potrebbe non applicarli davvero.)

## Cosa faccio

- **`NO_ACTION_STALE_DATA`:** nessuna azione automatica è già avvenuta. Verifico perché lo snapshot
  è assente/stantio (processo del regime layer morto? rete? dati exchange mancanti?) prima di
  qualunque altra cosa.
- **`DEFENSIVE` (harvester):** confermo che nessun nuovo ingresso/scale-up sia stato aperto. Se il
  margin buffer è sotto soglia di rabbocco, decido io se rabboccare — mai automatico.
- **`HIGH_VOL_STOP_NEW_ORDERS` / `HIGH_VOL_CLOSE_GRID_ORDERLY` (GridBTC):** confermo che l'azione
  scelta al checkpoint (Task 2) sia stata applicata. Se è chiusura ordinata, verifico l'esecuzione
  effettiva (prezzi di chiusura, slippage) prima di considerare l'episodio chiuso.

## Escalation

Se il wiring stesso si comporta in modo inatteso (comando diverso da quello che mi aspetterei dato
lo snapshot che vedo), fermo il processo di wiring (systemd stop, Task 3) — mai lascio un
componente che tocca capitale reale guidato da un wiring di cui non mi fido in quel momento.
```

- [ ] **Step 2: Commit**

```bash
git add docs/m2-runbook-operativo-andrea.md
git commit -m "docs: runbook operativo Andrea per high-vol (M2)"
```

---

## Self-Review

**Spec coverage:** i 6 punti richiesti sono coperti: (1) componente di wiring → Task 1; (2) GridBTC
analisi con raccomandazione motivata, decisione riservata al checkpoint → Task 2; (3) deploy VPS →
Task 3; (4) gate per componente con criteri di promozione → Task 4; (5) runbook operativo Andrea →
Task 5; (6) tre checkpoint bloccanti dichiarati esplicitamente in una sezione dedicata, non solo
menzionati di sfuggita.

**Placeholder scan:** i placeholder rimasti sono dichiarati e intenzionali: (a) il percorso esatto
del clone orchestrator sul VPS (Task 3, non esiste ancora un deploy pregresso di QUESTO repo su
quel VPS — non è noto finché non si fa il primo deploy); (b) il valore di `GridBtcHighVolAction`
(Task 1/2, riservato al checkpoint per costruzione, non per pigrizia); (c) il contenuto del punto 1
di Task 2 (richiede lettura di codice non ancora fatta in questa sessione di pianificazione,
dichiarato come prerequisito esplicito del task, non lasciato vago).

**Type consistency:** `HarvesterCommand`, `GridBtcCommand`, `GridBtcHighVolAction`,
`StalenessPolicy`, `WiringDecision` hanno la stessa forma ovunque citati (Task 1 unico task con
codice, nessuna cross-reference di tipi tra task diversi in questo piano).

**Verifica eseguita per davvero (non solo letta a occhio):** il codice del Task 1 è stato copiato
in una sandbox isolata fuori dal repo (non un'esecuzione del piano, solo una verifica che il codice
scritto qui funzioni prima di consegnarlo) e i 13 test sono stati eseguiti realmente — 13/13 PASS,
ruff pulito. Questo ha scoperto un bug reale prima della consegna: `datetime.fromisoformat` su un
timestamp con suffisso `Z` produce un datetime timezone-aware, che non si può sottrarre da un `now`
naive (convenzione usata ovunque nel resto del codebase, incl. tutti i test di `regime.store`) —
`TypeError: can't subtract offset-naive and offset-aware datetimes`. Corretto con
`.replace(tzinfo=None)` dopo il parsing, normalizzando a naive-UTC come il resto del codebase.
Sandbox rimossa dopo la verifica, nessun residuo.
