# Report di deploy M2 — 2026-07-07 (VPS Contabo, binario harvester)

**Esito: completato.** Due unit systemd attive e abilitate, entrambi gli alert reali
(LAYER LAVORA / LAYER CIECO) confermati da Andrea sul telefono, entrambi i check healthchecks
"up", rollback provato a secco e verificato in ogni fase. **Shadow avviato** — vedi §6.

Durante la sessione si è verificato un **incident di esposizione credenziali**, chiuso in sessione
con rotazione + fix strutturale + re-deploy. Documentato per intero in §2, prima del resto, perché
è il fatto più rilevante di questa sessione.

---

## 1. Contesto

Esecuzione di `docs/m2-deploy-runbook.md`, una seduta, passo per passo. Repo alla partenza:
`master` locale e `origin/master` coincidenti su `f62ecd0`. VPS: primo deploy assoluto di questo
repo (`/opt/orchestrator` non esisteva).

---

## 2. Incident: credenziali in argv (severità alta, chiuso in sessione)

### Cosa è successo

Le prime due unit systemd create passavano le credenziali (token Telegram, chat id, due URL
healthchecks) come **argomenti da riga di comando** nell'`ExecStart` (`--bot-token ${VAR}` ecc.).
systemd espande `${VAR}` **prima** di eseguire il processo — il valore finisce quindi nell'argv del
processo, leggibile in chiaro via `/proc/PID/cmdline` o `ps aux` da chiunque abbia shell sulla
macchina. Il comando `systemctl status` eseguito per la verifica di routine ha mostrato la riga di
comando completa, esponendo le 4 credenziali sia sul terminale (quindi in questa conversazione) sia
— per la durata in cui i due processi sono girati con quella configurazione — nel process table del
VPS.

### Finestra di esposizione

- Processi avviati: 2026-07-07 09:42:26 CEST (07:42:26 UTC).
- Esposizione notata e processi fermati: 2026-07-07 09:43:10 CEST (07:43:10 UTC).
- **Finestra: ~44 secondi** in cui `ps`/`systemctl status` sulla macchina avrebbero mostrato le
  credenziali in chiaro a chiunque con accesso shell. Esposizione aggiuntiva: la riga di comando
  completa è comparsa una volta nel terminale/conversazione di questa sessione.

### Rotazioni fatte

Andrea ha rigenerato **token bot Telegram** e **i due URL di ping healthchecks** (trattati come
compromessi indipendentemente dalla plausibilità reale di un abuso — stesso principio già
applicato in questo progetto in occasione di un'esposizione di token GitHub in una sessione
precedente) e aggiornato `/etc/orchestrator/env` con i nuovi valori, senza farli mai transitare
per questa chat.

### Fix (commit `2d5948f`)

Rimossi **completamente** gli argomenti CLI `--bot-token`/`--chat-id`/`--healthchecks-url` da
entrambi gli entrypoint (`src/components/regime_daemon.py`, `src/components/wiring_loop.py`) — non
deprecati, rimossi: un'opzione che permette il pattern insicuro è il pattern insicuro. `build_sinks()`
legge ora le credenziali **solo** da un mapping iniettabile (di norma `os.environ`, popolato da
`EnvironmentFile`, mai visibile in argv); se una variabile manca, `ValueError` esplicito che la
nomina — mai un avvio mezzo-configurato. TDD: test aggiornati e verificati falliti contro la vecchia
firma CLI prima del fix, poi verdi. Suite 134/134, ruff pulito.

Le due unit systemd sono state ricreate con `ExecStart` pulito (solo interprete, modulo, flag non
segreti) e ri-verificate:

```
$ sudo cat /proc/3009215/cmdline | tr '\0' ' '   # regime-daemon, PRIMA del fix
/opt/orchestrator/.venv/bin/python -m components.regime_daemon --state-dir ... --bot-token 8710547328:AA... --chat-id 7143169748 --healthchecks-url https://hc-ping.com/...
```
(valore reale visto e poi rigenerato — non è più valido, riportato qui solo come evidenza della
forma del problema, non come credenziale attiva)

```
$ sudo cat /proc/3011579/cmdline | tr '\0' ' '   # regime-daemon, DOPO il fix e il re-deploy finale
/opt/orchestrator/.venv/bin/python -m components.regime_daemon --state-dir /opt/orchestrator/var/regime --config /opt/orchestrator/config/regime.yaml
$ sudo cat /proc/3011580/cmdline | tr '\0' ' '   # wiring-loop, DOPO il fix
/opt/orchestrator/.venv/bin/python -m components.wiring_loop --state-dir /opt/orchestrator/var/regime --staleness-minutes 60
```

Nessun segreto in nessuno dei due, confermato anche via `ps aux` (stesso output, coerente).

### Regola che ne esce (permanente, in `docs/m2-deploy-runbook.md`)

**Mai segreti in argv.** Ogni runbook futuro con credenziali include la verifica
`/proc/PID/cmdline` (o `ps aux` equivalente) come passo standard subito dopo l'avvio del servizio —
non un'eccezione per questo deploy.

---

## 3. Log passo-per-passo (sintesi — comando reale + esito, dettaglio completo nella cronologia)

| Passo | Comando (sintesi) | Esito |
|---|---|---|
| SSH + verifica repo locale | `git rev-parse master origin/master` | `f62ecd0` su entrambi |
| Clone su VPS | `git clone ... /opt/orchestrator` | HEAD `f62ecd0` confermato |
| venv + install | `python3 -m venv .venv && pip install -e .` | import dei due moduli OK (exit 0) |
| File credenziali | `sudo touch/chmod 600/chown root:freqbot /etc/orchestrator/env` | `-rw------- root freqbot`, poi compilato da Andrea (4 chiavi confermate per nome, mai per valore) |
| Unit systemd (1° tentativo) | `ExecStart=... --bot-token ${VAR} ...` | **INCIDENT — vedi §2** |
| Fix + redeploy | pull `2d5948f`, unit ricreate senza `${VAR}` | `/proc/cmdline` pulito, confermato |
| Smoke test parte 1 | snapshot `eth_high_vol=true` scritto a mano | **LAYER LAVORA confermato da Andrea sul telefono** |
| Smoke test parte 2 | snapshot invecchiato 3h (daemon fermato per evitare race con la sua stessa cadenza) | **LAYER CIECO confermato da Andrea sul telefono** |
| Rollback a secco | stop+disable+rm unit+daemon-reload | `inactive (dead)` → `could not be found`, `ps` senza processi (grep exit 1) |
| Ripristino | unit ricreate identiche, `enable --now` | `active`/`enabled` per entrambe, `/proc/cmdline` ri-verificato pulito |
| Inventario VPS | `InventoryCollector` (M1 Task 13) via SSH | Snapshot salvato, entrambe le unit e i due processi presenti, nessun segreto nelle righe processo |

---

## 4. Osservazione collaterale (non incident, non bloccante)

Durante un test locale (non sul VPS) dello smoke test post-fix, `regime-daemon --dry-run --once`
ha incontrato un `TypeError: '<' not supported between instances of 'NoneType' and 'str'`
riproducibile dentro `ccxt.okx().load_markets()` — un problema lato dati OKX/ccxt (probabile market
listing con ID nullo), esterno al codice di questo repo. Isolato con una probe diretta a
`ccxt.okx().fetch_ohlcv(...)`, confermato non causato dal fix di sicurezza. **Il fail-safe ha
funzionato esattamente come progettato**: ciclo fallito, alert `LAYER CIECO`, nessuno snapshot
scritto, nessun crash. Sul VPS il primo ciclo reale del daemon è invece riuscito senza problemi
(snapshot con dati di mercato reali). Nessuna azione richiesta — annotato come esercizio reale,
inatteso, del fail-safe.

---

## 5. Criterio di completamento — verifica finale

- [x] Due unit `active`/`enabled`: `systemctl is-active` + `is-enabled` → `active active` / `enabled enabled`.
- [x] `LAYER LAVORA` reale ricevuto — confermato da Andrea.
- [x] `LAYER CIECO` reale ricevuto — confermato da Andrea.
- [x] Nessun segreto in `/proc/PID/cmdline`/`ps aux` — verificato 3 volte (dopo il fix, dopo il
  rollback rehearsal, via inventario M1).
- [x] Rollback provato a secco: stop/disable/rm/daemon-reload → verificato `could not be found` +
  zero processi, poi ripristinato.
- [x] Inventario VPS aggiornato con le due nuove unit/processi (M1 Task 13, snapshot salvato).

---

## 6. Avvio shadow — annotazione formale

**Inizio cronometro shadow (2 settimane, harvester — `docs/m2-reactivation-gates.md`):**

```
2026-07-07T08:33:48Z UTC
```

(timestamp ottenuto da `date -u` sul VPS, subito dopo la verifica finale post-rollback-rehearsal —
non un orario stimato).

**Fine prevista (2 settimane):** 2026-07-21T08:33:48Z UTC.

**Criteri di promozione al termine dello shadow:** `docs/m2-reactivation-gates.md`, protocollo
unico — zero eccezioni non gestite nel loop di wiring per l'intera durata, ogni transizione di
`eth_high_vol` osservata alertata correttamente, nessun falso `NO_ACTION_STALE_DATA` dovuto a un
bug di staleness. Nessuna promozione automatica: conferma esplicita di Andrea richiesta.

---

## 7. File toccati in questa sessione (repo)

- `src/components/regime_daemon.py`, `src/components/wiring_loop.py` — fix credenziali (commit `2d5948f`).
- `tests/components/test_regime_daemon.py`, `tests/components/test_wiring_loop.py` — test aggiornati.
- `docs/m2-deploy-runbook.md` — regola permanente "mai segreti in argv" + verifica `/proc/cmdline` come passo standard.
- `docs/m2-reactivation-gates.md` — checklist monitoring: verifica esplicita uscita-dalla-pausa healthchecks, mai auto-resume assunto.
- `var/inventory/snapshot-2026-07-07T08-32-10Z.json` — primo snapshot inventario mai salvato per questo repo.
- Questo documento.

**Fuori dal repo (VPS, non versionato):** `/opt/orchestrator` (clone), `/etc/orchestrator/env`
(credenziali, mai nel repo), due unit in `/etc/systemd/system/`.
