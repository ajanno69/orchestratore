# Report — rendering locale dashboard shadow (2026-07-07)

**Esito: pipeline completa, eseguita per davvero contro il VPS reale (sola lettura).** Export
consistente via Online Backup API → query locali → data-sanity → HTML statico autosufficiente.
**0 anomalie rilevate** sulle 2 righe accumulate finora. **Un finding architetturale emerso durante
la costruzione, non un bug**: il grafico "vol EWMA nel tempo con soglie" originariamente richiesto
non è costruibile con i dati oggi disponibili — vedi §4.

---

## 1. Cosa è stato costruito (TDD, sola lettura sul VPS)

- **`src/dashboard/export.py`**: estrazione consistente del DB SQLite in WAL mode tramite Online
  Backup API di `sqlite3` (stdlib) eseguita SUL VPS via SSH — mai una copia a freddo del file
  (rischio di snapshot incoerente su un processo vivo). Backup → `scp` → cleanup del temporaneo
  remoto (tentato anche se lo `scp` fallisce). Quoting shell a due livelli (Python `!r` per lo
  snippet, `shlex.quote` per l'involucro bash) verificato via round-trip nei test E nell'esecuzione
  reale sotto.
- **`src/dashboard/queries.py`**: lettura di sola lettura dell'export locale, normalizzazione
  naive-UTC duplicata deliberatamente (stesso principio già applicato più volte in questo progetto:
  non accoppiare un modulo locale a un componente condiviso coi processi in shadow).
- **`src/dashboard/sanity.py`**: 5 controlli — righe vs cadenza attesa, timestamp duplicati (PK),
  buchi di cadenza, consistenza level (via `resolve_wiring_decision` riusata, pura, già approvata —
  non reimplementata), monotonicità cronologica e di inserimento.
- **`src/dashboard/render.py`**: HTML statico, grafici matplotlib incorporati come PNG base64
  (nessun asset esterno, nessun web server).
- **`scripts/render_shadow_dashboard.py`**: CLI che lega tutto.
- **`pyproject.toml`**: `matplotlib` come optional-dependency `dashboard` — **mai installato sul
  VPS**, i tre processi runtime non lo richiedono.

TDD: 193/193 test verdi (locali, nessuna rete nella suite), ruff pulito.

## 2. Esecuzione reale — comando e output integrale

```
$ python scripts/render_shadow_dashboard.py --ssh-host 207.180.247.38 --ssh-user freqbot

Export consistente (Online Backup API) da freqbot@207.180.247.38 ...
  backup remoto: BACKUP_OK
  scaricato in: D:\Claude\orchestrator\var\dashboard-output\history_export_20260707T102916Z.db
  temporaneo remoto rimosso: /tmp/history_export_20260707T102916Z.db
Righe caricate: 2
Anomalie data-sanity: 0
Report scritto in: D:\Claude\orchestrator\var\dashboard-output\dashboard.html
```

**Verifica indipendente del cleanup** (non fidata dalla sola dichiarazione dello script):
```
$ ssh freqbot@207.180.247.38 "ls -la /tmp/ | grep history_export"
(nessun output — grep exit 1, nessun file temporaneo residuo)
```

**Verifica del contenuto HTML generato** (grep sul file reale, non un'affermazione):
```
$ grep -o "Righe totali:</strong> [0-9]*" dashboard.html
Righe totali:</strong> 2
$ grep -c "data:image/png;base64" dashboard.html
2
$ grep -o "Nessuna anomalia rilevata\." dashboard.html
Nessuna anomalia rilevata.
$ grep -o "collection_started_at:</strong> [^<]*" dashboard.html
collection_started_at:</strong> 2026-07-07 10:05:35.816154
$ grep -oi "valore numerico" dashboard.html | head -1
VALORE NUMERICO
$ grep -oi "level-triggered" dashboard.html
LEVEL-triggered
```

Tutte le sezioni previste sono presenti e popolate con dati reali: riepilogo, data-sanity, nota sul
limite della vol numerica, 2 grafici (timeline stato + staleness), tabella derived con nota
level/edge.

## 3. Data-sanity — 0 anomalie su 2 righe

Con solo 2 righe accumulate (il collector gira da ~25 minuti al momento del render), i controlli di
cadenza/gap non hanno ancora abbastanza storia per essere statisticamente significativi — ma
**zero** duplicati PK, **zero** inconsistenze level, **zero** problemi di monotonicità: il collector
sta scrivendo dati coerenti con i fatti grezzi fin dalle prime righe. Il report andrà rieseguito
periodicamente man mano che la storia cresce (nessuna azione richiesta ora, il comando è pronto).

## 4. Finding architetturale: la vol numerica non è mai stata persistita

**Scoperto durante la costruzione del grafico "principale" richiesto in origine** (vol EWMA nel
tempo con soglie enter/exit sovrapposte): lo schema di `regime_history` (e, più a monte,
`regime_state.json` stesso) persiste SOLO lo stato booleano derivato (`btc_high_vol`,
`eth_high_vol` — alto/basso), **mai il valore numerico continuo** dell'EWMA vol che
`regime_daemon.run_once` calcola a ogni ciclo (`compute_ewma_vol(...).iloc[-1]`, una variabile
locale mai scritta da nessuna parte, nemmeno nello snapshot).

**Conseguenza:** il grafico "vol nel tempo con soglie" non è costruibile con i dati oggi
disponibili — in nessun punto della pipeline (daemon, snapshot, storico) quel numero sopravvive al
ciclo in cui viene calcolato. Ho renderizzato al suo posto la **timeline di stato** (alto/basso),
che è tutto ciò che lo storico contiene — dichiarato in modo prominente **nell'HTML stesso** (non
solo qui), con un riquadro evidenziato che spiega il perché e nomina esplicitamente la possibile
azione: estendere lo schema del collector per catturare anche il valore numerico è una **decisione
di schema separata**, non presa in questa sessione.

**Non ho toccato `regime_daemon.py` per esporre quel valore** — resta vietato dal vincolo sovrano
(nessuna modifica ai processi in shadow). Se in futuro si vuole il grafico originale, la strada
sarebbe estendere `history_collector.py` (non `regime_daemon`) a leggere/ricalcolare il vol in modo
indipendente, oppure — più semplice — estendere `RegimeSnapshot`/`regime_state.json` per includere
anche il valore numerico, ma quest'ultima tocca `regime_daemon`/`wiring_loop` e richiederebbe un suo
proprio checkpoint.

## 5. File toccati in questa sessione (repo)

- `pyproject.toml` — extra `dashboard` (matplotlib).
- `src/dashboard/{export,queries,sanity,render}.py` + test corrispondenti.
- `scripts/render_shadow_dashboard.py`.
- Questo documento.

**Non committato** (rigenerabile, già escluso da `.gitignore` via la regola `var/` esistente):
`var/dashboard-output/dashboard.html`, `var/dashboard-output/history_export_*.db`.

**Fuori dal repo:** nessuna modifica al VPS — solo lettura (backup temporaneo creato e rimosso
nello stesso comando, verificato).
