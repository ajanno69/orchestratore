# Report — schema prep vol numerica, repo-only (2026-07-07, Parte 2)

**Esito: preparato, testato, review indipendente GO. IN CODA — deploy sul VPS SOLO dopo il gate
21/07 (fine shadow, ADR-037). Nessuna modifica ai tre processi in produzione (`regime-daemon`,
`wiring-loop`, `history-collector`) o alle loro unit systemd in questa sessione.**

Risponde alla richiesta: "Prepara (repo-only, NO deploy) il cambio di schema post-gate: snapshot
con ewma_vol per asset + colonna nel collector + migrazione additiva del DB + test. Review
indipendente, poi il task resta IN CODA, marcato 'deploy solo post-gate 21/07' nel piano."

## 1. Cosa è stato preparato (TDD, repo-only)

- **`src/regime/store.py`**: `RegimeSnapshot` guadagna `btc_ewma_vol: float | None = None` e
  `eth_ewma_vol: float | None = None` — opzionali, default `None`, `from_dict` via `.get()` per
  restare compatibile con uno `regime_state.json` scritto dal codice attualmente in produzione
  (senza queste chiavi).
- **`src/components/regime_daemon.py`**: `run_once` passa a `build_snapshot` lo stesso
  `float(btc_vol)`/`float(eth_vol)` già usato per aggiornare lo stato (`states.btc_vol.update(...)`)
  — non un ricalcolo separato, verificato dal reviewer leggendo le righe attorno.
- **`src/components/history_collector.py`**: `HistoryStore._migrate_add_ewma_vol_columns()` —
  `ALTER TABLE regime_history ADD COLUMN` per `btc_ewma_vol`/`eth_ewma_vol` (REAL), guardato da
  `PRAGMA table_info` per idempotenza (mai un ALTER ripetuto su colonna già presente). Migrazione
  ADDITIVA: righe pre-esistenti restano intatte, i nuovi campi NULL su di esse. `insert_snapshot_row`
  scrive i due valori (NULL se lo snapshot non li ha, backward-compat).

TDD: 207/207 test locali verdi, ruff pulito. Nuovi test dedicati: DB legacy senza colonne riaperto
senza perdita di righe, snapshot legacy senza chiavi, roundtrip valori, NULL persistito quando
assenti.

## 2. Review indipendente (Opus, contesto fresco)

Dispatchata su un checkout pulito del commit `041f4fe`, con istruzioni esplicite di verificare (a)
il vincolo "nessun deploy prima del gate", (b) l'integrità del muro Binario A/B (i nuovi campi
numerici non devono influenzare nessuna decisione di wiring/capitale), (c) correttezza del valore
catturato, (d) reale backward-compat.

**Verdetto: GO** per la coda "deploy solo post-gate 21/07". Nessun bloccante.

Confermato esplicitamente dal reviewer:
- Il commit non tocca nessuna unit systemd, script di deploy, config o CI — nessun cambiamento di
  comportamento runtime osservabile prima di un deploy esplicito.
- `regime_wiring.py`/`wiring_loop.py` usano esclusivamente i booleani per le decisioni — i nuovi
  campi numerici non sono referenziati in nessun punto di wiring/capitale (grep verificato dal
  reviewer). Muro intatto.
- Il valore persistito è lo stesso numero identico usato dalla decisione di stato, non un
  ricalcolo separato.
- Backward-compat verificata sia lato `regime_state.json` (dict senza chiavi) sia lato SQLite (DB
  con schema vecchio, riga pre-esistente non persa dopo la migrazione).

**3 note minori, non bloccanti, non affrontate in questa sessione** (dichiarate qui, non nascoste):
1. `NaN`/`inf` da `compute_ewma_vol` in casi degeneri finirebbero in `regime_state.json` come token
   JSON non-standard (`json.dumps(allow_nan=True)` di default) — il roundtrip Python regge, un
   parser strict esterno no. Nessun test copre questo caso.
2. I nuovi campi float non sono validati in `regime_wiring.py` (a differenza dei booleani) —
   accettabile perché restano osservativi, non decisionali.
3. La guardia `PRAGMA table_info` nella migrazione non è a prova di race tra processi concorrenti
   che aprano lo stesso DB — teorico, il collector è single-writer per design.

Nessuna di queste tre note richiede un fix prima della coda: possono essere riprese al momento del
deploy post-gate, se rilevanti allora.

## 3. Stato: IN CODA

**Non deployato. Non deployabile prima del 2026-07-21** (fine shadow pre-registrata, ADR-037).
Il codice esiste solo in questo repo — i tre processi sul VPS continuano a girare con il codice
precedente (senza questi campi) finché non ci sarà un deploy esplicito, autorizzato da Andrea,
dopo il gate.

**Prossimo passo (non ora)**: quando il gate 21/07 sarà superato e Andrea autorizzerà il deploy,
la sessione di deploy dovrà seguire lo stesso rito già rodato (`docs/m2-deploy-runbook.md`,
`docs/m2-history-collector-runbook.md`): pull del codice sul VPS, restart dei tre servizi,
verifica post-restart che `regime_state.json`/`regime_history` comincino a popolare i nuovi campi,
nessuna credenziale in argv (regola permanente post-incidente).

## 4. File toccati in questa sessione (repo)

- `src/regime/store.py`, `src/components/regime_daemon.py`, `src/components/history_collector.py`
  + test corrispondenti.
- Questo documento.

**Fuori dal repo:** nessuna modifica al VPS.

## 5. Commit

- `041f4fe` — feat: schema prep vol numerica (repo-only, TDD).

Pushato su `master`.
