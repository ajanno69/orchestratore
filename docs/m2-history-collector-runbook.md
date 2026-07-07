# Mini-runbook — history-collector (terza unit, sola osservazione)

**Ambito:** deploy di `orchestrator-history-collector.service` sul VPS Contabo, accanto a
`orchestrator-regime-daemon.service` e `orchestrator-wiring-loop.service` (già in shadow dal
2026-07-07T08:33:48Z, NON toccati da questo runbook). **Nessun comando qui va eseguito prima del
checkpoint esplicito di Andrea** (schema tabella + esito review indipendente + questo runbook).

**Vincolo sovrano (invariato dal progetto collaterale):** il collector fa SOLA LETTURA di
`regime_state.json`. Nessuna scrittura lì, nessuna modifica a `regime_daemon`/`wiring_loop`/alle
loro unit esistenti. Un guasto in questo componente non deve poter toccare lo shadow in corso.

---

## 1. Passi TUOI (manuali — credenziali, dove inserirle)

**Privilegio minimo (decisione del checkpoint di deploy):** il collector NON riceve il token del
bot Telegram né i ping URL degli altri due processi. `EnvironmentFile` **separato e dedicato**,
una sola variabile reale. Il suo alert reale è locale (stderr → journald, `LocalLogAlertSink`), mai
Telegram — l'unico segnale esterno è l'healthcheck (o la sua assenza, che scatena la notifica
nativa configurata su healthchecks.io per quel check specifico).

1. **Healthcheck dedicato**: creare un terzo check su healthchecks.io, `orchestrator-history-collector`
   (period 5 min, grace 5 min — stessa cadenza del collector), copiare il ping URL.
2. **File dedicato**: `HEALTHCHECKS_PING_URL_HISTORY_COLLECTOR` va scritto in un file NUOVO,
   `/etc/orchestrator-collector.env` — **non** in `/etc/orchestrator/env` (quello resta riservato a
   `regime_daemon`/`wiring_loop`, che condividono il token Telegram; il collector non deve poterlo
   leggere). Io preparo il file vuoto con permessi corretti (mode 600 — Passo 2.4 sotto), tu lo
   compili con l'unica riga durante la sessione — mai incollata in chat.
3. **Conferma in sessione**: al momento della verifica finale, confermami che il check
   `orchestrator-history-collector` risulta "up" dopo il primo ping — verifica visiva tua, come da
   regola già stabilita per gli altri due (mai assunto l'esito).

## 2. Passi MIEI via SSH (in ordine — comando + esito atteso)

1. `cd /opt/orchestrator && git fetch origin && git rev-parse origin/master` → confermato a voce con
   te prima di procedere. Atteso: `daedc03` (o successivo, da confermare).
2. `git pull` → `git rev-parse HEAD` coincide col passo 1.
3. `.venv/bin/python -c "import components.history_collector"` → exit 0.
4. `sudo touch /etc/orchestrator-collector.env && sudo chmod 600 /etc/orchestrator-collector.env && sudo chown root:freqbot /etc/orchestrator-collector.env && ls -l /etc/orchestrator-collector.env`
   → atteso: `-rw------- root freqbot`. **Qui mi fermo finché non compili il file (Passo 1.2).**
5. Creare `/etc/systemd/system/orchestrator-history-collector.service`:
   ```ini
   [Unit]
   Description=Orchestrator history-collector (sola osservazione, privilegio minimo)
   After=network-online.target orchestrator-regime-daemon.service

   [Service]
   Type=simple
   User=freqbot
   WorkingDirectory=/opt/orchestrator
   EnvironmentFile=/etc/orchestrator-collector.env
   ExecStart=/opt/orchestrator/.venv/bin/python -m components.history_collector --regime-state-dir /opt/orchestrator/var/regime --db-path /opt/orchestrator/var/history/history.db
   Restart=on-failure
   RestartSec=30

   [Install]
   WantedBy=multi-user.target
   ```
   **`EnvironmentFile` separato da quello degli altri due processi** (privilegio minimo) e **nessun
   `${VAR}` nell'`ExecStart`** (regola permanente post-incident, `docs/m2-deploy-runbook.md`): le
   credenziali arrivano solo via `EnvironmentFile`, mai in argv.
   → atteso: `systemd-analyze verify orchestrator-history-collector.service` senza errori.
6. `sudo systemctl daemon-reload && sudo systemctl enable --now orchestrator-history-collector.service`
   → atteso: `active (running)`.
7. **Verifica obbligatoria `/proc/PID/cmdline`** (regola permanente, stessa di sempre):
   ```
   $ sudo cat /proc/<PID>/cmdline | tr '\0' ' '
   [deve mostrare solo interprete, modulo, --regime-state-dir, --db-path — MAI un token/URL]
   ```
8. **Verifica esplicita che i due processi esistenti NON siano stati toccati (PRIMA di proseguire)**:
   ```
   $ systemctl show orchestrator-regime-daemon.service orchestrator-wiring-loop.service -p MainPID,ActiveEnterTimestamp
   [output reale qui — stesso PID/timestamp di prima di questo deploy, nessun restart indotto]
   ```
9. Attendere un ciclo (5 min), verificare il canary → check `orchestrator-history-collector` su
   healthchecks.io "up".
10. Verificare la prima riga scritta CON UN SELECT esplicito (non assunto):
    ```
    $ sqlite3 /opt/orchestrator/var/history/history.db "SELECT * FROM regime_history;"
    [output reale qui]
    $ sqlite3 /opt/orchestrator/var/history/history.db "SELECT * FROM _meta;"
    [output reale qui — collection_started_at deve comparire]
    ```
11. Aggiornare l'inventario VPS (M1 Task 13) — il nuovo processo compare nel prossimo snapshot.

## 3. Criterio di completamento

- [ ] `orchestrator-history-collector.service` `active`/`enabled`.
- [ ] `/etc/orchestrator-collector.env` separato, mode 600, UNA sola variabile — mai condiviso con
  `/etc/orchestrator/env`.
- [ ] `/proc/PID/cmdline` pulito (comando+output).
- [ ] Check healthchecks `orchestrator-history-collector` "up" (conferma di Andrea).
- [ ] Prima riga reale in `regime_history` verificata con un `SELECT` esplicito (comando+output).
- [ ] `_meta.collection_started_at` popolato con l'orario reale di primo avvio — annotato nel report.
- [ ] I due processi esistenti (`regime_daemon`, `wiring_loop`) **invariati**: stesso PID/
  `ActiveEnterTimestamp` di prima di questo deploy, verificato PRIMA e DOPO (comando+output, non
  assunto) — nessun riavvio indotto.
- [ ] Rollback provato a secco (§4) e verificato, poi ripristinato.

## 4. Piano di rollback (testabile, stesso schema degli altri due)

1. `sudo systemctl stop orchestrator-history-collector.service && sudo systemctl disable orchestrator-history-collector.service`
   → verifica: `inactive (dead)`.
2. `sudo rm /etc/systemd/system/orchestrator-history-collector.service && sudo systemctl daemon-reload`
   → verifica: `could not be found`.
3. `ps aux | grep history_collector` → nessun processo.
4. `/opt/orchestrator/var/history/history.db` e `/etc/orchestrator-collector.env`: dati locali, non
   segreti critici (il file env contiene solo un ping URL) — si lasciano (per riprendere senza
   perdita se il collector riparte) salvo decisione esplicita di cancellarli.
5. **Verifica esplicita che i due processi esistenti non siano stati toccati**:
   ```
   $ systemctl show orchestrator-regime-daemon.service orchestrator-wiring-loop.service -p MainPID,ActiveEnterTimestamp
   [output reale qui — stesso PID/timestamp del passo 2.8, non assunto]
   ```
6. Stato del VPS dopo rollback: identico a prima di questo deploy, shadow dei due processi esistenti
   ininterrotto.
