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

1. **Healthcheck dedicato**: creare un terzo check su healthchecks.io, `orchestrator-history-collector`
   (period 5 min, grace 5 min — stessa cadenza del collector), copiare il ping URL.
2. **Scrittura del valore**: `HEALTHCHECKS_PING_URL_HISTORY_COLLECTOR` va aggiunto a
   `/etc/orchestrator/env` (lo stesso file già in uso dagli altri due processi — `TG_ALERT_BOT_TOKEN`/
   `TG_ALERT_CHAT_ID` sono già lì e vengono riusati, stesso canale Telegram, messaggi distinguibili
   per prefisso: `COLLECTOR GUASTO` / `STORIA FERMA`, mai confondibili con `LAYER LAVORA`/`LAYER CIECO`
   del wiring-loop). Aggiungi la riga tu stesso via editor durante la sessione — mai incollata in chat.
3. **Conferma in sessione**: al momento della verifica finale, confermami che il check
   `orchestrator-history-collector` risulta "up" dopo il primo ping — verifica visiva tua, come da
   regola già stabilita per gli altri due (mai assunto l'esito).

## 2. Passi MIEI via SSH (in ordine — comando + esito atteso)

1. `cd /opt/orchestrator && git fetch origin && git rev-parse origin/master` → confermato a voce con
   te prima di procedere.
2. `git pull` → `git rev-parse HEAD` coincide col passo 1.
3. `.venv/bin/python -c "import components.history_collector"` → exit 0.
4. Creare `/etc/systemd/system/orchestrator-history-collector.service`:
   ```ini
   [Unit]
   Description=Orchestrator history-collector (sola osservazione)
   After=network-online.target orchestrator-regime-daemon.service

   [Service]
   Type=simple
   User=freqbot
   WorkingDirectory=/opt/orchestrator
   EnvironmentFile=/etc/orchestrator/env
   ExecStart=/opt/orchestrator/.venv/bin/python -m components.history_collector --regime-state-dir /opt/orchestrator/var/regime --db-path /opt/orchestrator/var/history/history.db
   Restart=on-failure
   RestartSec=30

   [Install]
   WantedBy=multi-user.target
   ```
   **Nessun `${VAR}` nell'`ExecStart`** — stessa regola permanente post-incident
   (`docs/m2-deploy-runbook.md`): le credenziali arrivano solo via `EnvironmentFile`, mai in argv.
   → atteso: `systemd-analyze verify orchestrator-history-collector.service` senza errori.
5. `sudo systemctl daemon-reload && sudo systemctl enable --now orchestrator-history-collector.service`
   → atteso: `active (running)`.
6. **Verifica obbligatoria `/proc/PID/cmdline`** (regola permanente, stessa di sempre):
   ```
   $ sudo cat /proc/<PID>/cmdline | tr '\0' ' '
   [deve mostrare solo interprete, modulo, --regime-state-dir, --db-path — MAI un token/URL]
   ```
7. Attendere un ciclo (5 min), verificare il canary → check `orchestrator-history-collector` su
   healthchecks.io "up".
8. Verificare la prima riga scritta:
   ```
   $ sqlite3 /opt/orchestrator/var/history/history.db "SELECT * FROM regime_history; SELECT * FROM _meta;"
   [output reale qui]
   ```
9. Aggiornare l'inventario VPS (M1 Task 13) — il nuovo processo compare nel prossimo snapshot.

## 3. Criterio di completamento

- [ ] `orchestrator-history-collector.service` `active`/`enabled`.
- [ ] `/proc/PID/cmdline` pulito (comando+output).
- [ ] Check healthchecks `orchestrator-history-collector` "up" (conferma di Andrea).
- [ ] Almeno una riga reale in `regime_history` (comando+output `sqlite3`).
- [ ] `_meta.collection_started_at` popolato con l'orario reale di primo avvio.
- [ ] Rollback provato a secco (§4) e verificato, poi ripristinato.
- [ ] I due processi esistenti (`regime_daemon`, `wiring_loop`) **invariati**: `systemctl status`
  di entrambi mostra lo stesso PID/uptime di prima di questo deploy — nessun riavvio indotto.

## 4. Piano di rollback (testabile, stesso schema degli altri due)

1. `sudo systemctl stop orchestrator-history-collector.service && sudo systemctl disable orchestrator-history-collector.service`
   → verifica: `inactive (dead)`.
2. `sudo rm /etc/systemd/system/orchestrator-history-collector.service && sudo systemctl daemon-reload`
   → verifica: `could not be found`.
3. `ps aux | grep history_collector` → nessun processo.
4. `/opt/orchestrator/var/history/history.db`: dato locale accumulato, non un segreto — si lascia
   (per riprendere senza perdita se il collector riparte) salvo decisione esplicita di cancellarlo.
5. **Verifica esplicita che i due processi esistenti non siano stati toccati**: `systemctl status
   orchestrator-regime-daemon.service orchestrator-wiring-loop.service` → stesso PID/uptime di prima
   dell'intera operazione (comando+output, non assunto).
6. Stato del VPS dopo rollback: identico a prima di questo deploy, shadow dei due processi esistenti
   ininterrotto.
