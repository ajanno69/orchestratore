# Checkpoint pre-deploy — entrypoint runtime (regime-daemon + wiring-loop)

**Data:** 2026-07-07
**Ambito:** costruzione TDD dei due entrypoint runtime pre-registrati in ADR-037 §10
(`src/components/regime_daemon.py`, `src/components/wiring_loop.py`), canali esterni iniettabili
(`src/alerting/sinks.py`), smoke test locale end-to-end dry-run, review indipendente (2 round),
aggiornamento del runbook di deploy per due processi separati. Nessun deploy, nessuna chiave
reale — sessione repo-only.

---

## Cosa è stato costruito

- **`src/alerting/sinks.py`**: `AlertSink`/`HealthcheckSink` (Protocol), `DryRunAlertSink`/
  `DryRunHealthcheckSink` (registrano soltanto), `TelegramAlertSink`/`HealthchecksPingSink`
  (reali, solo stdlib `urllib`, nessuna nuova dipendenza, funzione di trasporto iniettabile).
- **`src/components/regime_daemon.py`**: fetch candele OKX via ccxt (pubblico, nessuna chiave) →
  EWMA vol → `VolRegimeState`/`FundingRegimeState` → `RegimeSnapshot` persistito. Cadenza 15 min,
  lookback 200 candele. Semina gli stati da `resolve_initial_snapshot` al riavvio (M1), verificato
  con un test che distingue i due comportamenti tramite un valore in banda morta di isteresi.
- **`src/components/wiring_loop.py`**: `RegimeSnapshot` → `resolve_wiring_decision` →
  `WiringSequencer` → alert. Cadenza 5 min. Nessun comando eseguito (ADR-037 §7).
- **`scripts/smoke_test_entrypoints.py`**: smoke test locale eseguito per davvero (fetch OKX
  reale, alert dry-run) — vedi output integrale sotto.

## Review indipendente — 2 round

**Round 1 — 2 difetti reali trovati:**

1. **(severità medio-alta) Alert-fallisce-durante-except → MORTO-E-MUTO.** Se `alert_sink.send()`
   falliva dentro l'`except` che gestisce un ciclo fallito (scenario realistico e correlato: rete
   del VPS giù, OKX e Telegram irraggiungibili insieme), l'eccezione propagava e uccideva il loop
   — il pattern VIVO-MA-CIECO diventava MORTO-E-MUTO, esattamente il rischio già dichiarato in
   ADR-037 §8 ma non chiuso nel codice.
2. **(minore ma insidioso) Candele insufficienti digerite in silenzio.** `fetch_latest_returns`
   accettava silenziosamente molte meno candele del richiesto (endpoint OKX parziale, nuovo
   listing, downtime) e calcolava un vol su dati insufficienti senza nessun alert.

**Fix (commit `25983c1`):** invio dell'alert dentro l'except ora protetto da un secondo
try/except (ultima risorsa stderr, mai un'eccezione propagata) in entrambi gli entrypoint; guardia
esplicita in `fetch_latest_returns` (soglia: metà delle candele richieste) che trasforma un fetch
parziale in un ciclo fallito con alert, mai un vol falso digerito in silenzio. Corretto anche
`datetime.utcnow()` (deprecato, rischio latente segnalato dal reviewer) → `datetime.now(UTC)`, e
un'imprecisione di prosa in ADR-037 §10 sul margine di cadenza.

**Round 2 — re-review:** entrambi i fix confermati corretti e verificati empiricamente (non solo
letti) — il fix (1) testato contro l'intera famiglia `Exception` (non solo il caso di test),
verificato che `BaseException`/`KeyboardInterrupt` continuino a propagare correttamente; il fix
(2) verificato al confine esatto (99 candele falliscono, 100 passano). Nessun nuovo difetto
introdotto. **Via libera esplicito del reviewer** per procedere oltre questo checkpoint. Punti
minori lasciati come sono (write non atomica dello snapshot — innocua per il fail-safe a valle;
duplicazione deliberata di `build_sinks` tra i due moduli; timeout ccxt vs poll_interval — nota
per il runbook) confermati non bloccanti dal reviewer stesso.

## Smoke test locale end-to-end — output reale

**Comando eseguito:**
```
cd D:/Claude/orchestrator && PYTHONIOENCODING=utf-8 python scripts/smoke_test_entrypoints.py
```

**Output (integrale, post-fix):**
```
=== Fase 1: regime-daemon --dry-run --once (fetch reale da OKX, nessuna chiave) ===
[DRY-RUN PING] #1
Snapshot scritto DAVVERO dal daemon (dati di mercato reali di oggi): RegimeSnapshot(timestamp='2026-07-07T06:27:00Z', btc_high_vol=False, eth_high_vol=False, eth_harvester_on=False)

=== Fase 2: wiring-loop --dry-run --once sullo snapshot reale appena scritto ===
[DRY-RUN PING] #1

=== Fase 3: wiring-loop --dry-run --once su uno snapshot high-vol scritto a mano (atteso: alert LAYER LAVORA) ===
[DRY-RUN ALERT] LAYER LAVORA — snapshot valido, comandi derivati dallo stato di regime corrente.
[DRY-RUN PING] #1

=== Fase 4: wiring-loop --dry-run --once su uno snapshot stantio (atteso: alert LAYER CIECO) ===
[DRY-RUN ALERT] LAYER CIECO — snapshot stantio (età 3:00:00.187855, soglia 1:00:00): nessuna azione automatica, posizione mantenuta.
[DRY-RUN PING] #1

Smoke test completato senza eccezioni.
```

**Lettura:** Fase 1 dimostra il fetch reale da OKX funzionante (dati di mercato di oggi, tutti
normali — nessun high-vol, harvester off, coerente con le condizioni reali del 2026-07-07). Fase 2
dimostra che `wiring-loop` legge correttamente lo snapshot reale scritto dal daemon (nessun alert,
stato quieto — corretto). Fasi 3 e 4 dimostrano, attraverso il path CLI vero (non solo la logica
pura già testata al checkpoint 2), i due alert reali richiesti: LAYER LAVORA su transizione a
high-vol, LAYER CIECO su snapshot stantio.

## Verifica finale

```
python -m pytest -q                       → 132 passed
python -m ruff check src tests scripts    → All checks passed!
```

## Aggiornamento runbook di deploy

`docs/m2-deploy-runbook.md` riscritto: due unit systemd separate
(`orchestrator-regime-daemon.service`, `orchestrator-wiring-loop.service`), credenziali Telegram
condivise ma **due healthchecks.io separati** (cadenze e condizioni di guasto indipendenti),
`EnvironmentFile` unico (`/etc/orchestrator/env`) con sostituzione `${VAR}` nei comandi
`ExecStart`. Il prerequisito "manca l'entrypoint" della versione precedente del runbook è chiuso:
la sessione di deploy dedicata diventa ora solo esecuzione del runbook aggiornato.

## Per il checkpoint con Andrea

Rito completo (TDD, review indipendente su entrambi gli entrypoint, fix, re-review, smoke test
locale con output reale) chiuso. Non procedo alla sessione di deploy reale senza tua istruzione
esplicita.
