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
