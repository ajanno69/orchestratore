# Orchestratore M1 (fondazione) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fondazione del repo `D:\Claude\orchestrator` per ADR-036 (accepted 2026-07-05): scaffolding + regime layer v0 a regole (vol EWMA + funding, isteresi obbligatoria) + schema/scorer del Binario B (forecasts append-only) + inventario VPS automatico + runbook di riattivazione harvester. Nessun ordine, nessun live, nessun ML in questa milestone.

**Architecture:** Repo Python a package top-level sotto `src/` (`regime`, `components`, `risk`, `forecasts`, `report`), stesso stile a "src layout" di `quantpedia-validation`. Il motore fiscale (`fiscal.classifier`/`fiscal.engine`, incl. la categoria `crypto_c_sexies`) è riusato COME LIBRERIA da `D:\Claude\quantpedia-validation\src` via `pythonpath` in `pyproject.toml` — stesso meccanismo già in uso nei test di quel repo (`tests/backtest/test_engine_invariants.py` usa un path assoluto identico). Nessun codice di quel repo o di `funding-harvester` viene copiato o modificato: solo config (aliquote fiscali, invariata) e pattern (isteresi, invarianti "self-invalidate on impossible state", watchdog VIVO-MA-CIECO) reimplementati localmente dove serve.

**Tech Stack:** Python >=3.11, pandas, pyyaml, pyarrow (parquet append-only), ccxt (lettura pubblica funding rate OKX, nessuna chiave), pytest, ruff.

## Global Constraints

- Budget cap assoluto: **€5.000** (ADR-036 §1) — implementato come guard esplicito, mai solo documentazione.
- Muro tra Binario A (capitale, `src/components`, `src/risk`) e Binario B (ricerca, `src/forecasts`): Binario B scrive SOLO nella tabella forecasts append-only, non chiama mai `risk` o `components`.
- Nessun ordine, nessuna chiave con permessi di trading in M1: solo lettura (funding rate pubblico OKX) e regole locali.
- Nessun ML in questa milestone: regime layer v0 è SOLO regole; Binario B in M1 è solo schema + scorer, nessun modello.
- Isteresi obbligatoria per gli stati di regime (evita flip-flop a cavallo di un'unica soglia) — test esplicito richiesto.
- Per l'orizzonte 72h lo scoring usa blocchi non sovrapposti (autocorrelazione, ADR-036 §4).
- `D:\Claude\quantpedia-validation` e `D:\Claude\funding-harvester`: SOLO riferimento/libreria, mai modificati da questo repo.
- TDD ovunque: test che fallisce → implementazione minima → verde → commit. Conventional commits (`feat:`, `test:`, `docs:`, `chore:`).
- Tutti i path Windows in questo piano usano forward slash (`D:/Claude/...`) per compatibilità pyproject/pytest — funzionano identicamente su Windows.

---

## File Structure

```
D:\Claude\orchestrator\
  CLAUDE.md
  pyproject.toml
  .gitignore
  config\
    binari.yaml         # budget cap, orizzonti Binario B
    regime.yaml          # soglie EWMA vol + funding, per asset
    fiscal.yaml           # copia aliquote fiscali (crypto_c_sexies 33%), richiesta dal loader condiviso
  src\
    regime\
      __init__.py
      hysteresis.py        # Task 5
      vol_state.py          # Task 6
      funding_state.py       # Task 7
      config.py               # Task 8
      store.py                 # Task 9
    components\
      __init__.py           # Task 1 (placeholder, M2 riattiva)
    risk\
      __init__.py
      constraints.py         # Task 4
    forecasts\
      __init__.py
      schema.py              # Task 11
      store.py                 # Task 11
      scorer.py                 # Task 12
    report\
      __init__.py
      regime_report.py       # Task 10
      monthly_forecast_report.py  # Task 13
      inventory.py                 # Task 14
      weekly_report.py               # Task 15
  tests\
    test_fiscal_reuse.py    # Task 3
    regime\
      test_hysteresis.py     # Task 5
      test_vol_state.py        # Task 6
      test_funding_state.py      # Task 7
      test_config.py               # Task 8
      test_store.py                  # Task 9
    risk\
      test_constraints.py    # Task 4
    forecasts\
      test_schema.py          # Task 11
      test_store.py             # Task 11
      test_scorer.py               # Task 12
    report\
      test_regime_report.py   # Task 10
      test_monthly_forecast_report.py  # Task 13
      test_inventory.py                  # Task 14
      test_weekly_report.py                # Task 15
  docs\
    ADR-036-orchestratore-due-binari.md  (già presente)
    runbook-riattivazione-harvester.md  # Task 16
```

---

### Task 1: Repo scaffolding (pyproject, CLAUDE.md, package skeleton, git init)

**Files:**
- Create: `pyproject.toml`
- Create: `CLAUDE.md`
- Create: `.gitignore`
- Create: `config/binari.yaml`
- Create: `src/regime/__init__.py`, `src/components/__init__.py`, `src/risk/__init__.py`, `src/forecasts/__init__.py`, `src/report/__init__.py`
- Test: `tests/test_packages_importable.py`

**Interfaces:**
- Produces: pythonpath `["src", "D:/Claude/quantpedia-validation/src"]` in `pyproject.toml` — ogni task successivo che fa `import regime.xxx`, `import fiscal.xxx` ecc. dipende da questa riga.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_packages_importable.py
"""Scaffolding: verifica che tutti i package top-level del repo siano
importabili (pythonpath src/ configurato correttamente in pyproject.toml)."""

from __future__ import annotations


def test_all_top_level_packages_import():
    import components  # noqa: F401
    import forecasts  # noqa: F401
    import regime  # noqa: F401
    import report  # noqa: F401
    import risk  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/test_packages_importable.py -v`
Expected: FAIL (ModuleNotFoundError / no pyproject configured yet, or collection error since `src/` doesn't exist)

- [ ] **Step 3: Create pyproject.toml**

```toml
[project]
name = "orchestrator"
version = "0.1.0"
description = "Orchestratore ADR-036: edge strutturali (Binario A) + predittore in shadow mode (Binario B)"
requires-python = ">=3.11"
dependencies = [
    "pandas>=2.2",
    "pyyaml>=6.0",
    "pyarrow>=16.0",
    "ccxt>=4.5",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.6",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "D:/Claude/quantpedia-validation/src"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 4: Create package skeleton**

```python
# src/regime/__init__.py
```

```python
# src/components/__init__.py
"""Placeholder Binario A — componenti a capitale (GridBTC, funding-harvester,
basis/carry). Nessun componente attivo in M1 (ADR-036: M2 richiede conferma
esplicita di Andrea prima di qualunque riattivazione live)."""
```

```python
# src/risk/__init__.py
```

```python
# src/forecasts/__init__.py
```

```python
# src/report/__init__.py
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/test_packages_importable.py -v`
Expected: PASS

- [ ] **Step 6: Create CLAUDE.md**

```markdown
# Orchestratore — principi vincolanti (ADR-036)

Questo repo implementa ADR-036 (docs/ADR-036-orchestratore-due-binari.md,
stato ACCEPTED 2026-07-05, congelato). Chi lavora qui rispetta questi
principi SENZA eccezioni silenziose.

## Il muro tra i due binari

- **Binario A (capitale)**: componenti a edge strutturale misurato/validato
  (GridBTC, funding-harvester, basis/carry). Vive sotto `src/components/`,
  `src/risk/`.
- **Binario B (ricerca)**: predittore direzionale in shadow mode. Vive sotto
  `src/forecasts/`. Scrive SOLO nella tabella forecasts append-only.
  **Non manda ordini, non parla col risk manager, non influenza pesi.**
  Qualunque violazione di questo muro è un incidente di governance, non un
  bug qualunque — fermarsi e chiedere conferma esplicita prima di collegare
  Binario B a qualunque decisione che tocchi capitale.

## Budget cap

- Cap assoluto: **€5.000** live, perdibile per intero senza che il progetto
  fallisca (è budget di laboratorio, non investimento). Vedi
  `src/risk/constraints.py::assert_within_budget_cap`. Aumenti di capitale
  SOLO via scaling ladder (ADR-036 §6), mai a caldo.

## Regole prima del ML

- Ogni componente parte da **regole semplici e trasparenti** (v0). Un
  layer ML (es. regime v1) sostituisce le regole SOLO se le batte su
  metrica pre-registrata in shadow comparison >= 3 mesi — altrimenti si
  tiene v0 per sempre. Non introdurre ML in questa milestone (M1): niente
  modelli, niente training, solo la misura (schema + scorer).

## Pre-registrazione

- Orizzonti forecast (24h/72h), soglie di gate e metriche di successo sono
  **congelati in ADR-036** prima di vedere risultati. Non modificarli
  silenziosamente: qualunque cambiamento (es. terzo orizzonte) è un
  emendamento pre-registrato esplicito, mai un refactor silenzioso.

## Vietato per costruzione

- Nessun componente short-vol in Binario A.
- Nessun componente direzionale predittivo con capitale in Binario A
  (vivono solo in Binario B, senza capitale).
- Nessun ordine, nessuna chiave exchange con permessi di trading in questa
  milestone (M1): regime layer e forecasts sono lettura/misura, non
  esecuzione.

## Riuso deliberato

- Motore fiscale (`fiscal.classifier`, `fiscal.engine`, `fiscal.ledger`) e
  invarianti di motore riusati da `D:\Claude\quantpedia-validation` COME
  LIBRERIA (via `pythonpath` in `pyproject.toml`, vedi
  `tests/test_fiscal_reuse.py`) — **non modificare quel repo da qui**.
- `funding-harvester` (`D:\Claude\funding-harvester`) è riferimento di
  pattern (es. watchdog VIVO-MA-CIECO in `newcrypto/ops/watchdog.py`) —
  **non si tocca**, si copiano solo i pattern quando serve (es. runbook
  riattivazione).

## TDD e commit

- TDD ovunque: test che fallisce -> implementazione minima -> test verde ->
  commit. Conventional commits (`feat:`, `test:`, `docs:`, `fix:`).
- M1 si ferma qui: niente ordini, niente live, niente ML. M2 richiede
  conferma esplicita di Andrea prima di riattivare qualunque componente
  live (vedi `docs/runbook-riattivazione-harvester.md`).
```

- [ ] **Step 7: Create .gitignore**

```
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.venv/
data/
*.egg-info/
build/
dist/
```

- [ ] **Step 8: Create config/binari.yaml**

```yaml
# Vincoli operativi Binario A / Binario B (ADR-036 §1, §2).
budget_cap_eur: 5000.0
binario_b:
  horizons: ["24h", "72h"]
  emission_hour_utc: 0
  assets: ["BTC", "ETH"]
```

- [ ] **Step 9: git init and initial commit**

```bash
cd D:/Claude/orchestrator
git init
git add pyproject.toml CLAUDE.md .gitignore config/binari.yaml src tests docs
git commit -m "chore: scaffold orchestrator repo per ADR-036 M1"
```

---

### Task 2: Fiscal engine reuse — proprio config + smoke test

**Files:**
- Create: `config/fiscal.yaml`
- Test: `tests/test_fiscal_reuse.py`

**Interfaces:**
- Consumes: `fiscal.classifier.load_fiscal_rules`, `fiscal.engine.RealizedEvent`, `fiscal.engine.compute_fiscal_years` da `D:/Claude/quantpedia-validation/src` (via pythonpath, Task 1).
- Produces: conferma che il riuso-come-libreria funziona end-to-end; nessun modulo successivo dipende da questo file (è uno smoke test isolato).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fiscal_reuse.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/test_fiscal_reuse.py -v`
Expected: FAIL with `FileNotFoundError` (config/fiscal.yaml non esiste ancora)

- [ ] **Step 3: Create config/fiscal.yaml**

```yaml
# Copiato da quantpedia-validation/config/fiscal.yaml (stesse aliquote,
# stesso schema — richiesto dal loader condiviso fiscal.classifier.load_fiscal_rules,
# che indicizza tutte e tre le categorie). Solo crypto_c_sexies e' rilevante
# per l'orchestratore (Binario A/harvester); etf_ucits/fx_leva restano per
# compatibilita' con lo schema del motore riusato.
fiscal_year_end_month: 12
cost_method: LIFO
cost_method_da_confermare_commercialista: true
categories:
  etf_ucits:
    gain:
      tax_category: redditi_di_capitale
      rate: 0.26
      compensabile: false
    loss:
      tax_category: redditi_diversi
      rate: 0.26
      compensabile: true
      carry_forward_years: 4
    da_confermare_commercialista: false
  fx_leva:
    differenziale:
      tax_category: redditi_diversi
      rate: 0.26
      compensabile: true
      carry_forward_years: 4
    da_confermare_commercialista: true
  crypto_c_sexies:
    differenziale:
      tax_category: redditi_diversi
      rate: 0.33
      compensabile: true
      carry_forward_years: 4
    da_confermare_commercialista: false
dividends:
  etf_distribuzione:
    tax_category: redditi_di_capitale
  preferire_accumulazione: true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/test_fiscal_reuse.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/fiscal.yaml tests/test_fiscal_reuse.py
git commit -m "test: smoke test riuso motore fiscale (crypto_c_sexies) da quantpedia-validation"
```

---

### Task 3: Budget cap guard

**Files:**
- Create: `src/risk/constraints.py`
- Test: `tests/risk/test_constraints.py`

**Interfaces:**
- Produces: `BUDGET_CAP_EUR: float`, `assert_within_budget_cap(deployed_eur: float, cap_eur: float = BUDGET_CAP_EUR) -> None` (raises `ValueError`). Nessun task successivo lo consuma direttamente in M1 (componenti Binario A sono placeholder) — è l'invariante pronto per M2.

- [ ] **Step 1: Write the failing test**

```python
# tests/risk/test_constraints.py
from __future__ import annotations

import pytest

from risk.constraints import BUDGET_CAP_EUR, assert_within_budget_cap


def test_within_cap_does_not_raise():
    assert_within_budget_cap(4_999.0)
    assert_within_budget_cap(BUDGET_CAP_EUR)


def test_over_cap_raises():
    with pytest.raises(ValueError, match="supera il budget cap"):
        assert_within_budget_cap(5_000.01)


def test_custom_cap_overrides_default():
    with pytest.raises(ValueError):
        assert_within_budget_cap(1_500.0, cap_eur=1_000.0)
    assert_within_budget_cap(900.0, cap_eur=1_000.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/risk/test_constraints.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'risk.constraints'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/risk/constraints.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/risk/test_constraints.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/risk/constraints.py tests/risk/test_constraints.py
git commit -m "feat: budget cap guard (ADR-036 §1)"
```

---

### Task 4: Hysteresis primitive (generico, Schmitt trigger)

**Files:**
- Create: `src/regime/hysteresis.py`
- Test: `tests/regime/test_hysteresis.py`

**Interfaces:**
- Produces: `HysteresisBand(enter: float, exit: float)` (raises `ValueError` se `enter <= exit`), `next_state(current_state: bool, value: float, band: HysteresisBand) -> bool`. Consumato da Task 5 (`vol_state.py`) e Task 6 (`funding_state.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/regime/test_hysteresis.py
from __future__ import annotations

import pytest

from regime.hysteresis import HysteresisBand, next_state


def test_state_turns_on_above_enter_and_off_only_below_exit():
    band = HysteresisBand(enter=1.0, exit=0.8)
    assert next_state(False, 1.1, band) is True
    assert next_state(True, 0.9, band) is True  # ancora sopra exit, resta ON
    assert next_state(True, 0.75, band) is False  # scende sotto exit, si spegne


def test_state_does_not_flip_flop_oscillating_in_dead_band():
    """ADR-036: isteresi obbligatoria — un valore che oscilla intorno a
    un'unica soglia (qui 0.85-0.95, sempre tra exit=0.8 ed enter=1.0) non
    deve mai far scattare lo stato."""
    band = HysteresisBand(enter=1.0, exit=0.8)
    state = False
    for value in [0.9, 0.85, 0.95, 0.82, 0.99, 0.81]:
        state = next_state(state, value, band)
    assert state is False  # mai salito sopra enter=1.0


def test_degenerate_band_raises():
    with pytest.raises(ValueError):
        HysteresisBand(enter=0.8, exit=1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/regime/test_hysteresis.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'regime.hysteresis'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/regime/hysteresis.py
"""Isteresi generica per stati binari (Schmitt trigger) — evita flip-flop
quando il valore oscilla intorno a un'unica soglia (ADR-036 §3: 'isteresi
obbligatoria' per lo stato di vol)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HysteresisBand:
    """Soglia di ingresso (enter) e di uscita (exit) per uno stato ON/OFF.

    Convenzione: `enter` > `exit` per uno stato che si attiva quando il
    valore SALE sopra soglia (es. vol alta, funding sopra soglia) e si
    disattiva solo quando il valore SCENDE sotto una soglia più bassa.
    """

    enter: float
    exit: float

    def __post_init__(self) -> None:
        if self.enter <= self.exit:
            raise ValueError(
                f"enter ({self.enter}) deve essere > exit ({self.exit}): "
                "altrimenti la banda di isteresi è degenere e non previene il flip-flop."
            )


def next_state(current_state: bool, value: float, band: HysteresisBand) -> bool:
    """Calcola il prossimo stato ON/OFF dato lo stato corrente e il nuovo
    valore osservato. Non cambia stato se il valore è nella banda morta
    (tra `exit` e `enter`): questa è la proprietà che elimina il flip-flop
    quando il valore oscilla a cavallo di un'unica soglia."""
    if current_state:
        return value >= band.exit
    return value >= band.enter
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/regime/test_hysteresis.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/regime/hysteresis.py tests/regime/test_hysteresis.py
git commit -m "feat: isteresi generica per stati di regime (Schmitt trigger)"
```

---

### Task 5: Vol regime state (EWMA BTC/ETH)

**Files:**
- Create: `src/regime/vol_state.py`
- Test: `tests/regime/test_vol_state.py`

**Interfaces:**
- Consumes: `regime.hysteresis.HysteresisBand`, `regime.hysteresis.next_state` (Task 4).
- Produces: `VolStateConfig(ewma_span: int, enter_threshold: float, exit_threshold: float)`, `compute_ewma_vol(returns: pd.Series, span: int) -> pd.Series`, `VolRegimeState(config: VolStateConfig, is_high_vol: bool = False)` con `.update(latest_vol: float) -> bool`. Consumato da Task 8 (`config.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/regime/test_vol_state.py
from __future__ import annotations

import pandas as pd

from regime.vol_state import VolRegimeState, VolStateConfig, compute_ewma_vol


def test_compute_ewma_vol_higher_for_more_volatile_series():
    calm = pd.Series([0.001, -0.001, 0.001, -0.001, 0.001] * 20)
    wild = pd.Series([0.05, -0.05, 0.05, -0.05, 0.05] * 20)
    calm_vol = compute_ewma_vol(calm, span=10).iloc[-1]
    wild_vol = compute_ewma_vol(wild, span=10).iloc[-1]
    assert wild_vol > calm_vol


def test_vol_state_turns_on_above_enter_threshold():
    config = VolStateConfig(ewma_span=10, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config)
    assert state.update(0.5) is False
    assert state.update(0.9) is True


def test_vol_state_does_not_flip_flop_across_single_threshold():
    """ADR-036 §3: isteresi obbligatoria — un valore che oscilla intorno a
    0.7 (tra exit=0.6 e enter=0.8) non deve far flappare lo stato."""
    config = VolStateConfig(ewma_span=10, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config)
    state.update(0.9)  # entra in high-vol
    assert state.is_high_vol is True
    for value in [0.7, 0.65, 0.75, 0.62, 0.79]:
        state.update(value)
    assert state.is_high_vol is True  # mai sceso sotto exit=0.6


def test_vol_state_turns_off_only_below_exit_threshold():
    config = VolStateConfig(ewma_span=10, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config)
    state.update(0.9)
    state.update(0.5)
    assert state.is_high_vol is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/regime/test_vol_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'regime.vol_state'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/regime/vol_state.py
"""Stato di volatilità (EWMA su BTC/ETH) — regime layer v0 (ADR-036 §3):
regole semplici e trasparenti, isteresi obbligatoria per evitare flip-flop
a cavallo della soglia."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from regime.hysteresis import HysteresisBand, next_state


@dataclass(frozen=True)
class VolStateConfig:
    ewma_span: int
    enter_threshold: float
    exit_threshold: float

    @property
    def band(self) -> HysteresisBand:
        return HysteresisBand(enter=self.enter_threshold, exit=self.exit_threshold)


def compute_ewma_vol(returns: pd.Series, span: int) -> pd.Series:
    """Volatilità EWMA annualizzata dei rendimenti giornalieri (radice della
    varianza EWMA * sqrt(365), crypto è 24/7)."""
    ewma_var = (returns**2).ewm(span=span, adjust=False).mean()
    return (ewma_var**0.5) * (365**0.5)


@dataclass
class VolRegimeState:
    """Stato di vol (alta/bassa) per un asset, con isteresi. `is_high_vol`
    parte False (bassa vol) finché il primo update non lo cambia."""

    config: VolStateConfig
    is_high_vol: bool = False

    def update(self, latest_vol: float) -> bool:
        self.is_high_vol = next_state(self.is_high_vol, latest_vol, self.config.band)
        return self.is_high_vol
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/regime/test_vol_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/regime/vol_state.py tests/regime/test_vol_state.py
git commit -m "feat: stato di vol EWMA con isteresi (regime layer v0)"
```

---

### Task 6: Funding regime state (OKX)

**Files:**
- Create: `src/regime/funding_state.py`
- Test: `tests/regime/test_funding_state.py`

**Interfaces:**
- Consumes: `regime.hysteresis.HysteresisBand`, `regime.hysteresis.next_state` (Task 4).
- Produces: `FundingStateConfig(enter_threshold, exit_threshold)`, `FundingRegimeState(config, is_harvester_on=False)` con `.update(latest_funding_rate: float) -> bool`, `FundingRateSource` Protocol, `CcxtOkxFundingRateSource(exchange).fetch(asset: str) -> float`. Consumato da Task 8 (`config.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/regime/test_funding_state.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/regime/test_funding_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'regime.funding_state'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/regime/funding_state.py
"""Stato di funding (OKX) — soglia on/off per l'harvester (ADR-036 §3).
Stessa isteresi generica di vol_state, per evitare accensioni/spegnimenti
ravvicinati dell'harvester (attrito fiscale non gratuito, vedi ADR-036 §3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from regime.hysteresis import HysteresisBand, next_state


class FundingRateSource(Protocol):
    def fetch(self, asset: str) -> float:
        """Ultimo funding rate osservato per `asset` (frazione, es. 0.0001 = 0.01%)."""
        ...


@dataclass(frozen=True)
class FundingStateConfig:
    enter_threshold: float
    exit_threshold: float

    @property
    def band(self) -> HysteresisBand:
        return HysteresisBand(enter=self.enter_threshold, exit=self.exit_threshold)


@dataclass
class FundingRegimeState:
    """Stato harvester-on/off per un asset, con isteresi."""

    config: FundingStateConfig
    is_harvester_on: bool = False

    def update(self, latest_funding_rate: float) -> bool:
        self.is_harvester_on = next_state(self.is_harvester_on, latest_funding_rate, self.config.band)
        return self.is_harvester_on


class CcxtOkxFundingRateSource:
    """Adapter su ccxt.okx per leggere il funding rate corrente via
    endpoint pubblico (nessuna chiave richiesta — sola lettura, ADR-036
    M1: niente ordini, niente chiavi di trading in questa milestone)."""

    def __init__(self, exchange) -> None:
        self._exchange = exchange

    def fetch(self, asset: str) -> float:
        symbol = f"{asset}/USDT:USDT"
        ticker = self._exchange.fetch_funding_rate(symbol)
        return float(ticker["fundingRate"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/regime/test_funding_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/regime/funding_state.py tests/regime/test_funding_state.py
git commit -m "feat: stato di funding OKX con isteresi (regime layer v0)"
```

---

### Task 7: Regime config loader

**Files:**
- Create: `config/regime.yaml`
- Create: `src/regime/config.py`
- Test: `tests/regime/test_config.py`

**Interfaces:**
- Consumes: `regime.vol_state.VolStateConfig` (Task 5), `regime.funding_state.FundingStateConfig` (Task 6).
- Produces: `RegimeConfig(vol_by_asset: dict[str, VolStateConfig], funding_by_asset: dict[str, FundingStateConfig])`, `load_regime_config(path) -> RegimeConfig`.

- [ ] **Step 1: Write the failing test**

```python
# tests/regime/test_config.py
from __future__ import annotations

from pathlib import Path

from regime.config import load_regime_config

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "regime.yaml"


def test_load_regime_config_reads_btc_and_eth_vol_thresholds():
    config = load_regime_config(CONFIG_PATH)
    assert config.vol_by_asset["BTC"].enter_threshold == 0.80
    assert config.vol_by_asset["BTC"].exit_threshold == 0.60
    assert config.vol_by_asset["ETH"].enter_threshold == 1.00


def test_load_regime_config_reads_funding_thresholds():
    config = load_regime_config(CONFIG_PATH)
    assert config.funding_by_asset["ETH"].enter_threshold == 0.0005
    assert config.funding_by_asset["ETH"].exit_threshold == 0.0002
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/regime/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'regime.config'`

- [ ] **Step 3: Create config/regime.yaml**

```yaml
# Soglie regime layer v0 (ADR-036 §3) — regole semplici, isteresi obbligatoria.
vol:
  ewma_span: 20
  btc:
    enter_threshold: 0.80   # vol annualizzata EWMA, soglia di ingresso high-vol
    exit_threshold: 0.60    # soglia di uscita (isteresi: exit < enter)
  eth:
    enter_threshold: 1.00
    exit_threshold: 0.75
funding:
  eth:
    enter_threshold: 0.0005   # funding rate, soglia harvester ON
    exit_threshold: 0.0002
```

- [ ] **Step 4: Write minimal implementation**

```python
# src/regime/config.py
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/regime/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config/regime.yaml src/regime/config.py tests/regime/test_config.py
git commit -m "feat: loader config regime (soglie vol/funding per asset)"
```

---

### Task 8: Regime state persistence (con reseeding esplicito al riavvio)

**Files:**
- Create: `src/regime/store.py`
- Test: `tests/regime/test_store.py`

**Interfaces:**
- Produces: `RegimeSnapshot(timestamp: str, btc_high_vol: bool, eth_high_vol: bool, eth_harvester_on: bool)`, `build_snapshot(btc_high_vol, eth_high_vol, eth_harvester_on, now=None) -> RegimeSnapshot`, `RegimeStateStore(base_path).write(snapshot)` / `.read() -> RegimeSnapshot | None` (raises `ValueError` on a corrupted/unreadable snapshot file — mai un fallback silenzioso), `resolve_initial_snapshot(store: RegimeStateStore) -> RegimeSnapshot` (primo avvio assoluto senza snapshot pregresso -> default esplicito e documentato, MAI il default implicito del linguaggio). Consumato da Task 9 (`report/regime_report.py`) e Task 15 (`weekly_report.py`). Il chiamante che ricostruisce `VolRegimeState`/`FundingRegimeState` dopo un riavvio deve passare `is_high_vol=resolved.btc_high_vol` (o l'equivalente) al costruttore invece di lasciare il default `False` della dataclass — questo è il meccanismo di reseeding "restart-no-flip": senza, un riavvio con vol nella banda morta reintrodurrebbe il difetto di flip già chiuso in Task 5.

- [ ] **Step 1: Write the failing test**

```python
# tests/regime/test_store.py
from __future__ import annotations

from datetime import datetime

import pytest

from regime.store import RegimeStateStore, build_snapshot, resolve_initial_snapshot
from regime.vol_state import VolRegimeState, VolStateConfig


def test_build_snapshot_formats_timestamp_iso_utc():
    snap = build_snapshot(True, False, True, now=datetime(2026, 7, 5, 12, 30, 0))
    assert snap.timestamp == "2026-07-05T12:30:00Z"
    assert snap.btc_high_vol is True
    assert snap.eth_high_vol is False
    assert snap.eth_harvester_on is True


def test_store_write_then_read_roundtrip(tmp_path):
    store = RegimeStateStore(tmp_path)
    snap = build_snapshot(True, True, False, now=datetime(2026, 7, 5, 0, 0, 0))
    store.write(snap)
    loaded = store.read()
    assert loaded == snap


def test_store_read_returns_none_when_no_snapshot_yet(tmp_path):
    store = RegimeStateStore(tmp_path)
    assert store.read() is None


def test_store_write_overwrites_previous_snapshot(tmp_path):
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(False, False, False, now=datetime(2026, 7, 5, 0, 0, 0)))
    store.write(build_snapshot(True, True, True, now=datetime(2026, 7, 6, 0, 0, 0)))
    loaded = store.read()
    assert loaded.btc_high_vol is True
    assert loaded.timestamp == "2026-07-06T00:00:00Z"


def test_read_raises_explicit_error_on_corrupted_snapshot_file(tmp_path):
    """Un file corrotto/illeggibile è un segnale di un problema a monte, non
    un default silenzioso su cui basare una decisione di regime (stesso
    principio del guard NaN/inf in vol_state.py)."""
    store = RegimeStateStore(tmp_path)
    (tmp_path / "regime_state.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrotto o illeggibile"):
        store.read()


def test_read_raises_explicit_error_on_snapshot_missing_required_field(tmp_path):
    store = RegimeStateStore(tmp_path)
    path = tmp_path / "regime_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"timestamp": "2026-07-05T00:00:00Z"}', encoding="utf-8")
    with pytest.raises(ValueError, match="corrotto o illeggibile"):
        store.read()


def test_resolve_initial_snapshot_defaults_explicitly_on_first_ever_startup(tmp_path):
    """Primo avvio assoluto (nessuno snapshot pregresso): lo stato iniziale
    è una scelta esplicita e documentata (bassa vol, harvester off), non il
    default implicito del linguaggio (coerente con VolRegimeState.is_high_vol
    che parte da False di suo, ma qui la scelta è dichiarata a livello di
    store, non lasciata al caso)."""
    store = RegimeStateStore(tmp_path)
    snapshot = resolve_initial_snapshot(store)
    assert snapshot.btc_high_vol is False
    assert snapshot.eth_high_vol is False
    assert snapshot.eth_harvester_on is False


def test_resolve_initial_snapshot_returns_persisted_snapshot_when_present(tmp_path):
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(True, False, True, now=datetime(2026, 7, 5, 0, 0, 0)))
    resolved = resolve_initial_snapshot(store)
    assert resolved.btc_high_vol is True
    assert resolved.eth_harvester_on is True


def test_restart_no_flip_reseeds_high_vol_state_from_persisted_snapshot(tmp_path):
    """Lo scenario che ha motivato questo task: stato vero pre-riavvio =
    high-vol (True), un riavvio del processo NON deve far tornare lo stato
    a bassa vol solo perché la nuova vol osservata cade nella banda morta
    [exit, enter). Senza reseeding esplicito, VolRegimeState() partirebbe
    dal default della dataclass (False) e un update(0.7) - dentro
    [0.6, 0.8) - lo lascerebbe erroneamente False. Con il reseeding dal
    RegimeSnapshot persistito, resta correttamente True."""
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(True, False, False, now=datetime(2026, 7, 5, 0, 0, 0)))

    resolved = resolve_initial_snapshot(store)
    config = VolStateConfig(ewma_span=20, enter_threshold=0.8, exit_threshold=0.6)
    state = VolRegimeState(config=config, is_high_vol=resolved.btc_high_vol)
    assert state.is_high_vol is True

    state.update(0.7)  # dentro la banda morta: nessun flip indotto dal riavvio
    assert state.is_high_vol is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/regime/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'regime.store'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/regime/store.py
"""Persistenza dello stato di regime corrente (ADR-036 §3: 'output: regime
corrente persistito + esposto al report'). Stato singolo (non append-only:
il regime è uno STATO, non un evento storico) — un JSON con l'ultimo
snapshot, sovrascritto a ogni update.

`resolve_initial_snapshot` è il punto di reseeding al riavvio: chi
ricostruisce `VolRegimeState`/`FundingRegimeState` dopo un riavvio del
processo DEVE passare il valore risolto qui come `is_high_vol`/
`is_harvester_on` iniziale, non lasciare il default `False` della
dataclass — altrimenti un riavvio con l'osservazione corrente dentro la
banda morta reintroduce esattamente il flip spurio che l'isteresi doveva
prevenire."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class RegimeSnapshot:
    timestamp: str  # ISO 8601 UTC
    btc_high_vol: bool
    eth_high_vol: bool
    eth_harvester_on: bool

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "RegimeSnapshot":
        return RegimeSnapshot(
            timestamp=data["timestamp"],
            btc_high_vol=data["btc_high_vol"],
            eth_high_vol=data["eth_high_vol"],
            eth_harvester_on=data["eth_harvester_on"],
        )


class RegimeStateStore:
    """Store del solo stato corrente (`regime_state.json`), non storico."""

    def __init__(self, base_path: Path | str) -> None:
        self._path = Path(base_path) / "regime_state.json"

    def write(self, snapshot: RegimeSnapshot) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")

    def read(self) -> RegimeSnapshot | None:
        if not self._path.exists():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return RegimeSnapshot.from_dict(raw)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(
                f"snapshot di regime corrotto o illeggibile in {self._path}: {exc}. "
                "Non si può decidere lo stato di regime da un file corrotto — "
                "ripristinare da backup o cancellare il file per ripartire dal "
                "default esplicito (resolve_initial_snapshot) prima di riavviare."
            ) from exc


def build_snapshot(
    btc_high_vol: bool, eth_high_vol: bool, eth_harvester_on: bool, now: datetime | None = None
) -> RegimeSnapshot:
    ts = (now or datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")
    return RegimeSnapshot(
        timestamp=ts,
        btc_high_vol=btc_high_vol,
        eth_high_vol=eth_high_vol,
        eth_harvester_on=eth_harvester_on,
    )


def resolve_initial_snapshot(store: RegimeStateStore) -> RegimeSnapshot:
    """Stato da usare per riseminare `VolRegimeState`/`FundingRegimeState`
    all'avvio del processo. Se esiste uno snapshot persistito, è quello
    (reseeding: nessun flip indotto dal solo riavvio). Se NON esiste ancora
    nessuno snapshot (primo avvio assoluto), il default è dichiarato qui
    esplicitamente — bassa vol su entrambi gli asset, harvester OFF — non
    lasciato al default implicito della dataclass `VolRegimeState`/
    `FundingRegimeState` (che per conto suo parte comunque da False, ma la
    scelta va presa e documentata a questo livello, non per coincidenza)."""
    snapshot = store.read()
    if snapshot is not None:
        return snapshot
    return RegimeSnapshot(
        timestamp="1970-01-01T00:00:00Z",  # nessuna osservazione reale ancora
        btc_high_vol=False,
        eth_high_vol=False,
        eth_harvester_on=False,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/regime/test_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/regime/store.py tests/regime/test_store.py
git commit -m "feat: persistenza dello stato di regime con reseeding esplicito al riavvio (restart-no-flip)"
```

---

### Task 9: Regime report exposure

**Files:**
- Create: `src/report/regime_report.py`
- Test: `tests/report/test_regime_report.py`

**Interfaces:**
- Consumes: `regime.store.RegimeSnapshot`, `regime.store.RegimeStateStore`, `regime.store.build_snapshot` (Task 8).
- Produces: `format_regime_section(snapshot: RegimeSnapshot | None) -> str`, `load_and_format_regime_section(store: RegimeStateStore) -> str`. Consumato da Task 15 (`weekly_report.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/report/test_regime_report.py
from __future__ import annotations

from datetime import datetime

from regime.store import RegimeStateStore, build_snapshot
from report.regime_report import format_regime_section, load_and_format_regime_section


def test_format_regime_section_no_snapshot():
    assert format_regime_section(None) == "Regime: nessuno snapshot disponibile ancora."


def test_format_regime_section_with_snapshot():
    snap = build_snapshot(True, False, True, now=datetime(2026, 7, 5, 12, 0, 0))
    text = format_regime_section(snap)
    assert "2026-07-05T12:00:00Z" in text
    assert "BTC high-vol: ON" in text
    assert "ETH high-vol: OFF" in text
    assert "ETH harvester: ON" in text


def test_load_and_format_regime_section_reads_from_store(tmp_path):
    store = RegimeStateStore(tmp_path)
    store.write(build_snapshot(False, True, False, now=datetime(2026, 7, 5, 0, 0, 0)))
    text = load_and_format_regime_section(store)
    assert "ETH high-vol: ON" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/report/test_regime_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'report.regime_report'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/report/regime_report.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/report/test_regime_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/regime_report.py tests/report/test_regime_report.py
git commit -m "feat: sezione regime nel report"
```

---

### Task 10: Forecasts schema + append-only store

**Files:**
- Create: `src/forecasts/schema.py`
- Create: `src/forecasts/store.py`
- Test: `tests/forecasts/test_schema.py`
- Test: `tests/forecasts/test_store.py`

**Interfaces:**
- Produces: `FORECAST_COLUMNS: list[str]`, `ForecastRecord(timestamp, asset, horizon, p_up, model_version_hash, feature_ref)` (raises `ValueError` su horizon non in `("24h","72h")` o `p_up` fuori `[0,1]`), `ForecastStore(base_path).append(record)` / `.read_all() -> pd.DataFrame`. Consumato da Task 11 (`scorer.py`) e Task 13 (`monthly_forecast_report.py`).

- [ ] **Step 1: Write the failing test (schema)**

```python
# tests/forecasts/test_schema.py
from __future__ import annotations

import pytest

from forecasts.schema import ForecastRecord


def _record(**overrides):
    defaults = dict(
        timestamp="2026-07-05T00:00:00Z",
        asset="BTC",
        horizon="24h",
        p_up=0.55,
        model_version_hash="abc123",
        feature_ref="features/2026-07-05.parquet",
    )
    defaults.update(overrides)
    return ForecastRecord(**defaults)


def test_valid_record_constructs():
    record = _record()
    assert record.asset == "BTC"
    assert record.horizon == "24h"


def test_invalid_horizon_raises():
    with pytest.raises(ValueError, match="horizon non valido"):
        _record(horizon="1h")


def test_p_up_out_of_range_raises():
    with pytest.raises(ValueError, match="p_up fuori range"):
        _record(p_up=1.5)


def test_to_row_returns_all_columns():
    row = _record().to_row()
    assert set(row.keys()) == {
        "timestamp", "asset", "horizon", "p_up", "model_version_hash", "feature_ref",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/forecasts/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'forecasts.schema'`

- [ ] **Step 3: Write minimal implementation (schema)**

```python
# src/forecasts/schema.py
"""Schema Binario B: tabella forecasts append-only (ADR-036 §4).
Un ForecastRecord per ogni previsione emessa a orario fisso (00:00 UTC)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

_VALID_HORIZONS = ("24h", "72h")

FORECAST_COLUMNS: list[str] = [
    "timestamp",
    "asset",
    "horizon",
    "p_up",
    "model_version_hash",
    "feature_ref",
]


@dataclass(frozen=True)
class ForecastRecord:
    """Previsione immutabile (ADR-036 §4): P(rendimento>0) calibrata,
    orizzonte 24h (primario) o 72h (secondario), versione modello e
    riferimento allo snapshot feature usati (per riproducibilità)."""

    timestamp: str  # ISO 8601 UTC, orario fisso 00:00
    asset: str
    horizon: str
    p_up: float
    model_version_hash: str
    feature_ref: str

    def __post_init__(self) -> None:
        if self.horizon not in _VALID_HORIZONS:
            raise ValueError(
                f"horizon non valido: {self.horizon!r} (atteso {_VALID_HORIZONS!r} — "
                "ADR-036 §4: terzo orizzonte richiede emendamento pre-registrato esplicito)"
            )
        if not 0.0 <= self.p_up <= 1.0:
            raise ValueError(f"p_up fuori range [0,1]: {self.p_up!r}")

    def to_row(self) -> dict:
        return asdict(self)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/forecasts/test_schema.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test (store)**

```python
# tests/forecasts/test_store.py
from __future__ import annotations

from forecasts.schema import ForecastRecord
from forecasts.store import ForecastStore


def _record(**overrides):
    defaults = dict(
        timestamp="2026-07-05T00:00:00Z",
        asset="BTC",
        horizon="24h",
        p_up=0.55,
        model_version_hash="abc123",
        feature_ref="features/2026-07-05.parquet",
    )
    defaults.update(overrides)
    return ForecastRecord(**defaults)


def test_read_all_empty_when_no_data(tmp_path):
    store = ForecastStore(tmp_path)
    df = store.read_all()
    assert len(df) == 0
    assert list(df.columns) == [
        "timestamp", "asset", "horizon", "p_up", "model_version_hash", "feature_ref",
    ]


def test_append_then_read_all_roundtrip(tmp_path):
    store = ForecastStore(tmp_path)
    store.append(_record(asset="BTC"))
    store.append(_record(asset="ETH", horizon="72h"))
    df = store.read_all()
    assert len(df) == 2
    assert set(df["asset"]) == {"BTC", "ETH"}


def test_append_is_additive_never_overwrites(tmp_path):
    store = ForecastStore(tmp_path)
    for i in range(5):
        store.append(_record(model_version_hash=f"v{i}"))
    df = store.read_all()
    assert len(df) == 5
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/forecasts/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'forecasts.store'`

- [ ] **Step 7: Write minimal implementation (store)**

```python
# src/forecasts/store.py
"""Store append-only per ForecastRecord (stesso pattern di
fiscal.ledger.FiscalLedger da quantpedia-validation: mai UPDATE/DELETE su
un record esistente — correzioni si registrano come nuovo record)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from forecasts.schema import FORECAST_COLUMNS, ForecastRecord


class ForecastStore:
    def __init__(self, base_path: Path | str) -> None:
        self._path = Path(base_path) / "forecasts.parquet"

    def append(self, record: ForecastRecord) -> None:
        row = pd.DataFrame([record.to_row()], columns=FORECAST_COLUMNS)
        if self._path.exists():
            existing = pd.read_parquet(self._path)
            combined = pd.concat([existing, row], ignore_index=True)
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            combined = row
        combined.to_parquet(self._path, index=False)

    def read_all(self) -> pd.DataFrame:
        if not self._path.exists():
            return pd.DataFrame(columns=FORECAST_COLUMNS)
        return pd.read_parquet(self._path)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/forecasts/test_store.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/forecasts/schema.py src/forecasts/store.py tests/forecasts/test_schema.py tests/forecasts/test_store.py
git commit -m "feat: schema e store append-only forecasts (Binario B)"
```

---

### Task 11: Forecasts scorer

**Files:**
- Create: `src/forecasts/scorer.py`
- Test: `tests/forecasts/test_scorer.py`

**Interfaces:**
- Produces: `ScoreResult(n_forecasts, hit_rate, brier_score, calibration_buckets)`, `score_forecasts(forecasts: pd.DataFrame, outcomes: pd.Series, horizon: str) -> ScoreResult`. Consumato da Task 13 (`monthly_forecast_report.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/forecasts/test_scorer.py
from __future__ import annotations

import pandas as pd
import pytest

from forecasts.scorer import score_forecasts


def _forecasts_df(p_ups, horizon="24h"):
    return pd.DataFrame(
        {
            "timestamp": [f"2026-07-{i+1:02d}T00:00:00Z" for i in range(len(p_ups))],
            "asset": ["BTC"] * len(p_ups),
            "horizon": [horizon] * len(p_ups),
            "p_up": p_ups,
        }
    )


def test_perfect_predictor_hit_rate_1_and_brier_0():
    forecasts = _forecasts_df([0.9, 0.1, 0.9, 0.1])
    outcomes = pd.Series([True, False, True, False])
    result = score_forecasts(forecasts, outcomes, horizon="24h")
    assert result.n_forecasts == 4
    assert result.hit_rate == 1.0
    assert result.brier_score < 0.02


def test_random_coin_flip_hit_rate_near_half():
    forecasts = _forecasts_df([0.5] * 10)
    outcomes = pd.Series([True, False] * 5)
    result = score_forecasts(forecasts, outcomes, horizon="24h")
    assert result.hit_rate == 0.5


def test_72h_uses_non_overlapping_blocks_every_third_forecast():
    # 6 previsioni giornaliere sovrapposte a orizzonte 72h -> solo indici 0,3 usati
    forecasts = _forecasts_df([0.9, 0.9, 0.9, 0.1, 0.1, 0.1], horizon="72h")
    outcomes = pd.Series([True, False, False, False, True, True])
    result = score_forecasts(forecasts, outcomes, horizon="72h")
    assert result.n_forecasts == 2  # solo indice 0 e 3


def test_empty_forecasts_returns_nan_scores():
    forecasts = _forecasts_df([])
    outcomes = pd.Series([], dtype=bool)
    result = score_forecasts(forecasts, outcomes, horizon="24h")
    assert result.n_forecasts == 0
    assert pd.isna(result.hit_rate)


def test_calibration_buckets_group_by_decile():
    forecasts = _forecasts_df([0.75, 0.72, 0.15])
    outcomes = pd.Series([True, False, False])
    result = score_forecasts(forecasts, outcomes, horizon="24h")
    assert "0.7-0.8" in result.calibration_buckets
    avg_p, actual_rate, n = result.calibration_buckets["0.7-0.8"]
    assert n == 2
    assert avg_p == pytest.approx((0.75 + 0.72) / 2)
    assert actual_rate == pytest.approx(0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/forecasts/test_scorer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'forecasts.scorer'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/forecasts/scorer.py
"""Scoring mensile del predittore (ADR-036 §4): hit rate, Brier score,
calibrazione. Per l'orizzonte 72h le previsioni sono sovrapposte (una ogni
giorno con orizzonte di 3 giorni) — lo scoring usa BLOCCHI NON SOVRAPPOSTI
(ogni 3° previsione) per evitare un CI90 sovra-confidente da
autocorrelazione (obbligatorio, ADR-036 §4)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

_HORIZON_DAYS = {"24h": 1, "72h": 3}


@dataclass(frozen=True)
class ScoreResult:
    n_forecasts: int
    hit_rate: float
    brier_score: float
    calibration_buckets: dict[str, tuple[float, float, int]]  # bucket -> (avg_p, actual_rate, n)


def _non_overlapping_block_mask(n: int, block_size: int) -> list[bool]:
    """True per gli indici 0, block_size, 2*block_size, ... (blocchi non
    sovrapposti, ADR-036 §4, obbligatorio per il 72h)."""
    return [i % block_size == 0 for i in range(n)]


def score_forecasts(forecasts: pd.DataFrame, outcomes: pd.Series, horizon: str) -> ScoreResult:
    """`forecasts`: colonne timestamp/asset/horizon/p_up (schema
    forecasts.schema), già filtrate per un singolo asset e horizon,
    ordinate per timestamp. `outcomes`: Series booleana (rendimento>0
    realizzato), stesso indice di `forecasts` (allineata dal chiamante —
    lo scorer non fa I/O di prezzi, ADR-036 §4: 'prima la misura, poi il
    misurato')."""
    block_size = _HORIZON_DAYS[horizon]
    mask = _non_overlapping_block_mask(len(forecasts), block_size)

    p_up = forecasts["p_up"].reset_index(drop=True)[mask]
    actual = outcomes.reset_index(drop=True)[mask]

    n = len(p_up)
    if n == 0:
        return ScoreResult(
            n_forecasts=0, hit_rate=float("nan"), brier_score=float("nan"), calibration_buckets={}
        )

    predicted_up = p_up >= 0.5
    hit_rate = (predicted_up == actual).mean()
    brier_score = ((p_up - actual.astype(float)) ** 2).mean()

    calibration_buckets = _calibration_buckets(p_up, actual)

    return ScoreResult(
        n_forecasts=n,
        hit_rate=float(hit_rate),
        brier_score=float(brier_score),
        calibration_buckets=calibration_buckets,
    )


def _calibration_buckets(p_up: pd.Series, actual: pd.Series) -> dict[str, tuple[float, float, int]]:
    """Bucket di calibrazione a decili [0-0.1), [0.1-0.2), ... [0.9-1.0].
    Per ogni bucket: probabilità media dichiarata vs frequenza realizzata
    di rendimento>0 (ADR-036 §4: 'quando dice 70%, ha ragione il 70%?')."""
    buckets: dict[str, tuple[float, float, int]] = {}
    edges = [i / 10 for i in range(11)]
    for lo, hi in zip(edges[:-1], edges[1:]):
        in_bucket = (p_up >= lo) & (p_up < hi if hi < 1.0 else p_up <= hi)
        n_in_bucket = int(in_bucket.sum())
        if n_in_bucket == 0:
            continue
        avg_p = float(p_up[in_bucket].mean())
        actual_rate = float(actual[in_bucket].mean())
        buckets[f"{lo:.1f}-{hi:.1f}"] = (avg_p, actual_rate, n_in_bucket)
    return buckets
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/forecasts/test_scorer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/forecasts/scorer.py tests/forecasts/test_scorer.py
git commit -m "feat: scorer forecasts (hit rate, Brier, calibrazione, blocchi non sovrapposti 72h)"
```

---

### Task 12: Monthly forecast report stub

**Files:**
- Create: `src/report/monthly_forecast_report.py`
- Test: `tests/report/test_monthly_forecast_report.py`

**Interfaces:**
- Consumes: `forecasts.store.ForecastStore` (Task 10), `forecasts.scorer.score_forecasts`, `forecasts.scorer.ScoreResult` (Task 11).
- Produces: `build_monthly_report(store: ForecastStore, outcomes_by_asset: dict[str, pd.Series]) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/report/test_monthly_forecast_report.py
from __future__ import annotations

import pandas as pd

from forecasts.schema import ForecastRecord
from forecasts.store import ForecastStore
from report.monthly_forecast_report import build_monthly_report


def test_report_with_no_forecasts_says_so_explicitly(tmp_path):
    store = ForecastStore(tmp_path)
    report = build_monthly_report(store, outcomes_by_asset={})
    assert report == "Report mensile Binario B: nessuna previsione registrata ancora."


def test_report_scores_existing_forecasts(tmp_path):
    store = ForecastStore(tmp_path)
    store.append(ForecastRecord(
        timestamp="2026-07-01T00:00:00Z", asset="BTC", horizon="24h",
        p_up=0.9, model_version_hash="v0", feature_ref="f1",
    ))
    store.append(ForecastRecord(
        timestamp="2026-07-02T00:00:00Z", asset="BTC", horizon="24h",
        p_up=0.1, model_version_hash="v0", feature_ref="f2",
    ))
    outcomes = {"BTC": pd.Series([True, False])}
    report = build_monthly_report(store, outcomes)
    assert "BTC 24h: n=2 hit_rate=1.000" in report
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/report/test_monthly_forecast_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'report.monthly_forecast_report'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/report/monthly_forecast_report.py
"""Report mensile Binario B (ADR-036 §4): scoring vs due baseline
(persistenza/caso, regime layer v0). M1: stub — nessun modello ancora,
il report gira su qualunque cosa sia nella tabella forecasts (anche
vuota) e lo dichiara esplicitamente invece di fallire."""

from __future__ import annotations

import pandas as pd

from forecasts.scorer import ScoreResult, score_forecasts
from forecasts.store import ForecastStore


def build_monthly_report(store: ForecastStore, outcomes_by_asset: dict[str, pd.Series]) -> str:
    """`outcomes_by_asset`: rendimento>0 realizzato per asset, indicizzato
    come le previsioni di quell'asset (M2+ collega il feed prezzi reale;
    qui il report accetta la Series già allineata dal chiamante)."""
    df = store.read_all()
    if df.empty:
        return "Report mensile Binario B: nessuna previsione registrata ancora."

    lines = ["Report mensile Binario B — scoring predittore vs realtà", ""]
    for asset, outcomes in outcomes_by_asset.items():
        for horizon in ("24h", "72h"):
            subset = df[(df["asset"] == asset) & (df["horizon"] == horizon)]
            if subset.empty:
                continue
            result = score_forecasts(subset, outcomes, horizon)
            lines.append(_format_score_line(asset, horizon, result))

    return "\n".join(lines)


def _format_score_line(asset: str, horizon: str, result: ScoreResult) -> str:
    return (
        f"{asset} {horizon}: n={result.n_forecasts} "
        f"hit_rate={result.hit_rate:.3f} brier={result.brier_score:.4f}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/report/test_monthly_forecast_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/monthly_forecast_report.py tests/report/test_monthly_forecast_report.py
git commit -m "feat: stub report mensile Binario B"
```

---

### Task 13: VPS inventory collector + diff

**Files:**
- Create: `src/report/inventory.py`
- Test: `tests/report/test_inventory.py`

**Interfaces:**
- Produces: `InventorySnapshot(timestamp, systemd_units, systemd_unit_files, cron_lines, docker_containers, processes)`, `InventoryCollector(ssh_host, ssh_user, run_command=...).collect(now=None) -> InventorySnapshot`, `diff_snapshots(previous, current) -> InventoryDiff`, `InventoryDiff(added, removed)` con `.is_empty`, `InventoryStore(base_path).save(snapshot) -> Path` / `.load_latest_before(exclude_path) -> InventorySnapshot | None`. Consumato da Task 15 (`weekly_report.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/report/test_inventory.py
from __future__ import annotations

from datetime import datetime

from report.inventory import (
    InventoryCollector,
    InventorySnapshot,
    InventoryStore,
    diff_snapshots,
)


def _fake_runner(responses: dict[str, str]):
    def runner(args: list[str]) -> str:
        remote_command = args[-1]
        for key, value in responses.items():
            if key in remote_command:
                return value
        raise AssertionError(f"comando non atteso: {remote_command!r}")
    return runner


def test_collect_parses_all_categories():
    responses = {
        "list-units": "unit-a.service loaded active running\nunit-b.timer loaded active waiting",
        "list-unit-files": "mft_paper.service disabled",
        "crontab": "*/15 * * * * oi_snapshot",
        "docker ps": "infra-postgres-1\tUp 4 weeks",
        "ps aux": "root 1 0.0 0.0 systemd",
    }
    collector = InventoryCollector("207.180.247.38", "freqbot", run_command=_fake_runner(responses))
    snapshot = collector.collect(now=datetime(2026, 7, 5, 12, 0, 0))
    assert snapshot.timestamp == "2026-07-05T12:00:00Z"
    assert "unit-a.service loaded active running" in snapshot.systemd_units
    assert "mft_paper.service disabled" in snapshot.systemd_unit_files
    assert any("oi_snapshot" in line for line in snapshot.cron_lines)
    assert any("infra-postgres-1" in line for line in snapshot.docker_containers)
    assert any("systemd" in line for line in snapshot.processes)


def test_diff_detects_added_and_removed_units():
    previous = InventorySnapshot(
        timestamp="2026-07-04T00:00:00Z",
        systemd_units=["a.service"],
        systemd_unit_files=[],
        cron_lines=[],
        docker_containers=["c1"],
        processes=[],
    )
    current = InventorySnapshot(
        timestamp="2026-07-05T00:00:00Z",
        systemd_units=["a.service", "b.service"],
        systemd_unit_files=[],
        cron_lines=[],
        docker_containers=[],
        processes=[],
    )
    diff = diff_snapshots(previous, current)
    assert diff.added["systemd_units"] == ["b.service"]
    assert diff.removed["docker_containers"] == ["c1"]
    assert diff.is_empty is False


def test_diff_against_none_previous_marks_everything_as_added():
    current = InventorySnapshot(
        timestamp="2026-07-05T00:00:00Z",
        systemd_units=["a.service"],
        systemd_unit_files=[],
        cron_lines=[],
        docker_containers=[],
        processes=[],
    )
    diff = diff_snapshots(None, current)
    assert diff.added["systemd_units"] == ["a.service"]
    assert diff.is_empty is False


def test_identical_snapshots_produce_empty_diff():
    snap = InventorySnapshot(
        timestamp="2026-07-05T00:00:00Z",
        systemd_units=["a.service"],
        systemd_unit_files=[],
        cron_lines=[],
        docker_containers=[],
        processes=[],
    )
    diff = diff_snapshots(snap, snap)
    assert diff.is_empty is True


def test_inventory_store_roundtrip(tmp_path):
    store = InventoryStore(tmp_path)
    snap1 = InventorySnapshot(timestamp="2026-07-04T00:00:00Z")
    snap2 = InventorySnapshot(timestamp="2026-07-05T00:00:00Z")
    path1 = store.save(snap1)
    path2 = store.save(snap2)
    latest_before_2 = store.load_latest_before(exclude_path=path2)
    assert latest_before_2.timestamp == "2026-07-04T00:00:00Z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/report/test_inventory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'report.inventory'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/report/inventory.py
"""Inventario VPS automatico (ADR-036 §5 punto 3-bis — lezione mft_engine:
'mai piu' processi non censiti'). Censisce unit systemd (attive E
disabilitate: mft_paper.service non compariva da sola in `list-units
--all`, serve anche `list-unit-files` — vedi
D:\\Claude\\crypto-agent\\docs\\DECOMMISSION-2026-07.md), timer, cron,
container docker, processi persistenti. Produce uno snapshot strutturato
e un diff vs lo snapshot precedente."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

CommandRunner = Callable[[list[str]], str]


def _default_command_runner(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    return result.stdout


@dataclass(frozen=True)
class InventorySnapshot:
    timestamp: str
    systemd_units: list[str] = field(default_factory=list)
    systemd_unit_files: list[str] = field(default_factory=list)
    cron_lines: list[str] = field(default_factory=list)
    docker_containers: list[str] = field(default_factory=list)
    processes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "InventorySnapshot":
        return InventorySnapshot(**data)


@dataclass(frozen=True)
class InventoryDiff:
    added: dict[str, list[str]]
    removed: dict[str, list[str]]

    @property
    def is_empty(self) -> bool:
        return not any(self.added.values()) and not any(self.removed.values())


_CATEGORIES = (
    "systemd_units",
    "systemd_unit_files",
    "cron_lines",
    "docker_containers",
    "processes",
)


class InventoryCollector:
    """SSH host/user parametrici (config/binari.yaml o argomento diretto).
    `run_command` iniettabile per test — nessuna chiamata SSH reale nei
    test unitari."""

    def __init__(
        self, ssh_host: str, ssh_user: str, run_command: CommandRunner = _default_command_runner
    ) -> None:
        self._ssh_host = ssh_host
        self._ssh_user = ssh_user
        self._run_command = run_command

    def _ssh(self, remote_command: str) -> str:
        return self._run_command(["ssh", f"{self._ssh_user}@{self._ssh_host}", remote_command])

    def collect(self, now: datetime | None = None) -> InventorySnapshot:
        ts = (now or datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")
        units_raw = self._ssh("systemctl list-units --all --type=service,timer --no-legend")
        unit_files_raw = self._ssh("systemctl list-unit-files --type=service,timer --no-legend")
        cron_raw = self._ssh(f"crontab -u {self._ssh_user} -l")
        docker_raw = self._ssh("docker ps -a --format '{{.Names}}\t{{.Status}}'")
        processes_raw = self._ssh("ps aux")

        return InventorySnapshot(
            timestamp=ts,
            systemd_units=_nonblank_lines(units_raw),
            systemd_unit_files=_nonblank_lines(unit_files_raw),
            cron_lines=_nonblank_lines(cron_raw),
            docker_containers=_nonblank_lines(docker_raw),
            processes=_nonblank_lines(processes_raw),
        )


def _nonblank_lines(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def diff_snapshots(previous: InventorySnapshot | None, current: InventorySnapshot) -> InventoryDiff:
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    prev_dict = previous.to_dict() if previous is not None else {}

    for category in _CATEGORIES:
        prev_set = set(prev_dict.get(category, []))
        curr_set = set(getattr(current, category))
        added[category] = sorted(curr_set - prev_set)
        removed[category] = sorted(prev_set - curr_set)

    return InventoryDiff(added=added, removed=removed)


class InventoryStore:
    """Snapshot storici su disco (uno per run, mai sovrascritti — a
    differenza di RegimeStateStore che tiene solo il corrente: qui serve
    lo storico per il diff settimanale)."""

    def __init__(self, base_path: Path | str) -> None:
        self._base_path = Path(base_path)

    def save(self, snapshot: InventorySnapshot) -> Path:
        self._base_path.mkdir(parents=True, exist_ok=True)
        date_part = snapshot.timestamp.split("T")[0]
        path = self._base_path / f"snapshot-{date_part}.json"
        path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
        return path

    def load_latest_before(self, exclude_path: Path) -> InventorySnapshot | None:
        candidates = sorted(p for p in self._base_path.glob("snapshot-*.json") if p != exclude_path)
        if not candidates:
            return None
        return InventorySnapshot.from_dict(json.loads(candidates[-1].read_text(encoding="utf-8")))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/report/test_inventory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/inventory.py tests/report/test_inventory.py
git commit -m "feat: inventario VPS automatico con diff vs snapshot precedente"
```

---

### Task 14: Weekly report stub

**Files:**
- Create: `src/report/weekly_report.py`
- Test: `tests/report/test_weekly_report.py`

**Interfaces:**
- Consumes: `report.regime_report.format_regime_section` (Task 9), `regime.store.RegimeSnapshot`/`build_snapshot` (Task 8), `report.inventory.InventoryDiff` (Task 13).
- Produces: `build_weekly_report(regime_snapshot: RegimeSnapshot | None, inventory_diff: InventoryDiff) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/report/test_weekly_report.py
from __future__ import annotations

from datetime import datetime

from regime.store import build_snapshot
from report.inventory import InventoryDiff
from report.weekly_report import build_weekly_report


def test_weekly_report_no_changes():
    snapshot = build_snapshot(False, False, False, now=datetime(2026, 7, 5, 0, 0, 0))
    diff = InventoryDiff(added={"systemd_units": []}, removed={"systemd_units": []})
    report = build_weekly_report(snapshot, diff)
    assert "Regime al 2026-07-05T00:00:00Z" in report
    assert "nessuna variazione rispetto alla settimana precedente" in report


def test_weekly_report_shows_added_and_removed_units():
    diff = InventoryDiff(
        added={"systemd_units": ["mft_paper.service"]},
        removed={"systemd_units": []},
    )
    report = build_weekly_report(None, diff)
    assert "+ [systemd_units] mft_paper.service" in report
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/report/test_weekly_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'report.weekly_report'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/report/weekly_report.py
"""Report settimanale (ADR-036 §5): regime corrente + inventario VPS con
diff vs settimana precedente (punto 3-bis, lezione mft_engine)."""

from __future__ import annotations

from regime.store import RegimeSnapshot
from report.inventory import InventoryDiff
from report.regime_report import format_regime_section


def build_weekly_report(regime_snapshot: RegimeSnapshot | None, inventory_diff: InventoryDiff) -> str:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd D:/Claude/orchestrator && python -m pytest tests/report/test_weekly_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/report/weekly_report.py tests/report/test_weekly_report.py
git commit -m "feat: stub report settimanale (regime + diff inventario)"
```

---

### Task 15: Runbook riattivazione harvester (documento)

**Files:**
- Create: `docs/runbook-riattivazione-harvester.md`

**Interfaces:**
- Nessuna (documento puro, nessun codice/test).

- [ ] **Step 1: Create the runbook**

```markdown
# Runbook — Riattivazione funding-harvester (M2, richiede conferma esplicita di Andrea)

Questo documento è SOLO checklist. Nessun comando qui va eseguito senza
conferma esplicita di Andrea (ADR-036: M2 parte con conferma esplicita,
M1 si ferma qui — niente ordini, niente live).

Stato di partenza (2026-07-05, da
[DECOMMISSION-2026-07.md](../../crypto-agent/docs/DECOMMISSION-2026-07.md)):
funding-harvester ETH/OKX è code-complete (520 test), parcheggiato.
`funding-harvester-daily-report.timer` fermato+disabled (era l'ultimo
canary attivo sul VPS). Container `funding-postgres` ancora up (dati
intatti). Nessuna chiave OKX attiva.

## Checklist di riattivazione

1. **Chiavi OKX NUOVE a permessi minimi**
   - [ ] Andrea crea chiavi OKX nuove (mai riusare quelle vecchie/scadute)
   - [ ] Permessi: SOLO trade + read, **MAI withdraw**
   - [ ] Chiavi caricate in `.env` del repo orchestratore (mai committate),
     non nel vecchio `.env` di funding-harvester

2. **Size iniziale**
   - [ ] Size ridotta rispetto al code-complete originale (ADR-036 §3:
     "riattivazione a size ridotta in M2 su conferma esplicita")
   - [ ] Budget cap verificato via `risk.constraints.assert_within_budget_cap`
     prima di ogni incremento di size

3. **Canary**
   - [ ] Riattivare `funding-harvester-daily-report.timer`:
     `systemctl enable --now funding-harvester-daily-report.timer`
     (reversibilità confermata in DECOMMISSION-2026-07.md — stesso
     ExecStart, nessuna modifica necessaria)
   - [ ] Verificare 1 messaggio Telegram/giorno ricevuto prima di procedere

4. **Healthcheck riusato (pattern VIVO-MA-CIECO)**
   - [ ] Riusare la logica di
     [`newcrypto/ops/watchdog.py`](../../funding-harvester/newcrypto/ops/watchdog.py)
     (funding-harvester, NON toccare quel repo — solo pattern di
     riferimento): ping a healthchecks.io condizionato su `work_ok=True`
     ("ho fatto il mio lavoro e l'ho fatto bene", non "sono vivo")
   - [ ] Verificare che un heartbeat non leggibile (file mancante,
     Postgres down) NON pinghi healthchecks.io — deve scattare l'alert
     esterno, non un falso "vivo"

5. **Riattivazione ordinata**
   - [ ] `docker start funding-postgres` (se non già up)
   - [ ] Avviare l'executor a size ridotta, SOLO dopo canary + healthcheck
     verificati per >= 24h
   - [ ] Aggiornare l'inventario VPS (`report.inventory`) subito dopo:
     il nuovo processo/unit deve comparire nel prossimo snapshot, MAI
     un punto cieco come `mft_paper.service` (vedi DECOMMISSION-2026-07.md,
     sezione "Sorpresa trovata")

6. **Conferma esplicita**
   - [ ] Nessuno step sopra eseguito senza messaggio esplicito di conferma
     di Andrea per QUESTA riattivazione specifica (non basta l'approvazione
     di ADR-036 in generale)

## Rollback

- Stop pulito: `systemctl stop <unit-executor>` + `systemctl disable`
  (mai `kill -9`: vedi la sorpresa di `mft_paper.service` in
  DECOMMISSION-2026-07.md — un `Restart=always` riavvia il processo in
  meno di un secondo se non si passa da systemd)
- Le chiavi OKX nuove vanno revocate dal pannello OKX (azione manuale,
  non eseguibile da qui) se la riattivazione viene abortita
```

- [ ] **Step 2: Commit**

```bash
git add docs/runbook-riattivazione-harvester.md
git commit -m "docs: runbook riattivazione funding-harvester (M2, non eseguibile senza conferma)"
```

---

## Self-Review Notes

**Spec coverage:**
1. Repo + CLAUDE.md + struttura + riuso fiscale + invarianti → Task 1, 2, 3.
2. Regime layer v0 (vol EWMA isteresi + funding + persistenza + esposizione report) → Task 4-9.
3. Schema Binario B + scorer + stub report mensile → Task 10-12.
4. Inventario VPS automatico + diff → Task 13, wired nel weekly report Task 14.
5. Runbook riattivazione → Task 15.
Tutti e 5 i punti della richiesta coperti.

**Placeholder scan:** nessun "TBD"/"implementare dopo" — ogni step ha codice completo e comandi eseguibili.

**Type consistency:** `RegimeSnapshot`, `VolStateConfig`/`FundingStateConfig`, `InventorySnapshot`/`InventoryDiff`, `ForecastRecord`/`ScoreResult` usano nomi e firme identici ovunque siano referenziati tra task (verificato manualmente task per task).
