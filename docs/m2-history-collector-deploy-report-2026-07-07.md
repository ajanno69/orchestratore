# Report di deploy — history-collector (terza unit, 2026-07-07)

**Esito: completato.** `orchestrator-history-collector.service` attivo e abilitato sul VPS
Contabo, accanto a `orchestrator-regime-daemon.service` e `orchestrator-wiring-loop.service` (in
shadow dal 2026-07-07T08:33:48Z). **I due processi esistenti sono rimasti invariati per tutta la
sessione** (stesso PID, stesso `ActiveEnterTimestamp`, verificato prima, durante il rollback a
secco, e dopo) — il vincolo sovrano del progetto collaterale è stato rispettato per tutta la durata
del deploy, non solo dichiarato.

---

## 1. Design: privilegio minimo (decisione presa prima di questa sessione)

Rispetto al checkpoint precedente, un cambio di design richiesto esplicitamente prima del deploy:
il collector **non riceve il token del bot Telegram né i ping URL degli altri due processi**.
`EnvironmentFile` separato e dedicato (`/etc/orchestrator-collector.env`, non
`/etc/orchestrator/env`), una sola variabile reale (`HEALTHCHECKS_PING_URL_HISTORY_COLLECTOR`).
L'alert reale del collector è locale (`LocalLogAlertSink`, stderr → journald) — l'unico segnale
esterno è l'healthcheck (o la sua assenza). Implementato con TDD (commit `daedc03`), verificato
159/159 test verdi prima di procedere al deploy.

## 2. Log passo-per-passo (comando reale + esito)

| Passo | Comando (sintesi) | Esito |
|---|---|---|
| Baseline | `systemctl show ... MainPID,ActiveEnterTimestamp` (daemon+wiring-loop) | PID `3011579`/`3011580`, avviati `2026-07-07 10:30:56 CEST` |
| Pull codice | `git fetch && git pull` | `HEAD` → `65d914a`, import OK |
| File credenziali | `sudo touch/chmod 600/chown /etc/orchestrator-collector.env` | `-rw------- root freqbot`, poi compilato da Andrea (1 chiave confermata per nome, mai per valore) |
| Unit systemd | `ExecStart` senza `${VAR}` | `systemd-analyze verify` senza errori |
| Attivazione | `systemctl enable --now` | `active`, PID `3020761` |
| **Verifica cmdline** | `sudo cat /proc/3020761/cmdline` | Solo interprete/modulo/flag non segreti |
| **Verifica invarianza (subito dopo attivazione)** | `systemctl show` su daemon+wiring-loop | **Identici** al baseline |
| Attesa ciclo (5') + verifica riga | `sqlite3 ... "SELECT * FROM regime_history;"` | 1 riga reale, vedi §3 |
| Healthcheck | controllo su healthchecks.io | **"up"**, confermato da Andrea |
| Rollback a secco | stop/disable/rm/daemon-reload | `inactive (dead)` → `could not be found`, `ps` senza processi (grep exit 1) |
| **Verifica invarianza (durante rollback)** | `systemctl show` su daemon+wiring-loop | **Identici** al baseline |
| Ripristino | unit ricreata identica, `enable --now` | PID `3021885`, `active` |
| **Verifica cmdline (post-ripristino)** | `sudo cat /proc/3021885/cmdline` | Pulito |
| **Verifica invarianza (finale)** | `systemctl show` su daemon+wiring-loop | **Identici** al baseline |

## 3. Prima riga — verificata con SELECT esplicito

```
$ sqlite3 /opt/orchestrator/var/history/history.db "SELECT * FROM regime_history;"
2026-07-07T10:01:14Z|0|0|0|2026-07-07T10:05:35.818579+00:00|off|normal|0||

$ sqlite3 /opt/orchestrator/var/history/history.db "SELECT * FROM _meta;"
collection_started_at|2026-07-07T10:05:35.816154+00:00
last_new_row_at|2026-07-07T10:05:35.818579+00:00
```

Lettura: snapshot reale (`btc_high_vol=0, eth_high_vol=0, eth_harvester_on=0`, mercato normale),
`derived_harvester_command=off` (harvester non attivo), `derived_gridbtc_command=normal`,
`derived_alert=0`, categoria/testo `NULL` (nessuna transizione — coerente con uno stato quieto).

## 4. Annotazione formale — inizio raccolta storica

```
collection_started_at = 2026-07-07T10:05:35.816154+00:00 UTC
```

Da questo momento in poi la storia del regime layer è consultabile in
`/opt/orchestrator/var/history/history.db`. **I giorni di shadow precedenti (dal
2026-07-07T08:33:48Z al 2026-07-07T10:05:35Z) restano documentati solo dal canale Telegram** —
nessun backfill, come pre-registrato.

## 5. Criterio di completamento

- [x] `orchestrator-history-collector.service` `active`/`enabled`.
- [x] `EnvironmentFile` separato, mode 600, una sola variabile.
- [x] `/proc/PID/cmdline` pulito (verificato 2 volte: post-deploy e post-ripristino).
- [x] Check healthchecks `orchestrator-history-collector` "up" (confermato da Andrea).
- [x] Prima riga verificata con `SELECT` esplicito.
- [x] `collection_started_at` annotato.
- [x] Rollback provato a secco e verificato, poi ripristinato.
- [x] `regime_daemon`/`wiring_loop` invariati — verificato **tre volte** (post-deploy, durante
  rollback, post-ripristino), sempre stesso PID/`ActiveEnterTimestamp`.

## 6. File aggiornati in questa sessione (repo)

- `src/alerting/sinks.py` — `LocalLogAlertSink` (commit `daedc03`).
- `src/components/history_collector.py` — `build_sinks` a privilegio minimo.
- `docs/m2-history-collector-runbook.md` — `EnvironmentFile` separato, verifiche PID esplicite.
- Questo documento.

**Fuori dal repo (VPS, non versionato):** `/etc/orchestrator-collector.env` (una variabile, mai nel
repo), `/etc/systemd/system/orchestrator-history-collector.service`,
`/opt/orchestrator/var/history/history.db`.
