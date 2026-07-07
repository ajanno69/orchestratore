# Runbook di deploy M2 (VPS Contabo) — binario harvester

**Ambito:** deploy dei due processi runtime (ADR-037 §10) sul VPS Contabo esistente, per il
binario harvester (ETH): `regime-daemon` (misura) e `wiring-loop` (decisione/alert). Nessun
comando qui va eseguito prima che Andrea apra esplicitamente la sessione di deploy dedicata.

**Aggiornamento 2026-07-07:** entrambi gli entrypoint (`src/components/regime_daemon.py`,
`src/components/wiring_loop.py`) sono stati scritti con TDD, hanno superato una review
indipendente (2 round, 2 difetti reali chiusi — vedi
`docs/m2-checkpoint-entrypoints-review-integrativo.md`), e sono stati verificati con uno smoke
test locale end-to-end reale (fetch OKX vero, alert dry-run — vedi
`docs/m2-checkpoint-entrypoints-review-integrativo.md` per l'output integrale). Il prerequisito
"manca l'entrypoint" segnalato nella versione precedente di questo runbook è chiuso: questa
sessione diventa ora solo esecuzione, come previsto.

**GridBTC — CONDIZIONALE, non applicabile oggi:** GridBTC non esiste oggi come bot live (vedi
`docs/gridbtc-highvol-analysis-m2.md`; ground truth Andrea: solo shadow, mai capitale esposto).
`wiring-loop` legge comunque lo stato BTC (un solo `RegimeSnapshot` per entrambi gli asset), ma
qualunque passo che presuppone un consumatore GridBTC attivo resta sospeso fino al gate di
promozione (`docs/m2-reactivation-gates.md`).

Stesso pattern operativo di funding-harvester (systemd + canary + healthcheck).

---

## Checklist pre-deploy

### 1. Passi TUOI (manuali — chiavi, token, dove inserirli)

1. **Canale Telegram (condiviso dai due processi)**: decidere se riusare lo stesso bot/chat già
   attivo per funding-harvester (valori in `/etc/funding-harvester/env` sul VPS, mai nel repo) o
   crearne uno dedicato via @BotFather. I due processi condividono lo stesso `TG_ALERT_BOT_TOKEN`/
   `TG_ALERT_CHAT_ID` (entrambi alertano lo stesso operatore; i messaggi sono già distinguibili per
   prefisso: "regime-daemon:" vs "wiring-loop:" vs "LAYER LAVORA"/"LAYER CIECO").
2. **Healthchecks.io — DUE check separati, non uno**: `orchestrator-regime-daemon` (period 20 min,
   grace 10 min — la cadenza del daemon è 15 min, vedi ADR-037 §10) e `orchestrator-wiring-loop`
   (period 10 min, grace 5 min — cadenza 5 min). Due processi con cadenze e condizioni di guasto
   indipendenti devono avere canary indipendenti, altrimenti un guasto del daemon potrebbe restare
   mascherato dai ping ancora sani del wiring-loop (o viceversa).
3. **Scrittura dei valori**: `TG_ALERT_BOT_TOKEN`, `TG_ALERT_CHAT_ID`,
   `HEALTHCHECKS_PING_URL_REGIME_DAEMON`, `HEALTHCHECKS_PING_URL_WIRING_LOOP` vanno scritti SOLO in
   `/etc/orchestrator/env` sul VPS, con un editor durante la sessione (mai incollati in chat, mai
   in un commit, mai in un log) — io preparo il file vuoto con permessi corretti (Passo 2.5 sotto),
   tu lo compili.
4. **GridBTC**: nessuna azione — questo deploy è harvester-only.
5. **Conferma visiva in sessione**: al momento dello smoke test reale su VPS (§3), sei tu a
   confermare che i due alert di test sono arrivati sul telefono — il criterio di completamento
   non è soddisfatto da un log locale.

### 2. Passi MIEI via SSH (in ordine — comando di verifica + esito atteso, MAI "verificato" in prosa)

1. `ssh freqbot@207.180.247.38` → atteso: prompt di shell.
2. `ls /opt/orchestrator 2>&1 || git clone https://github.com/ajanno69/orchestratore.git /opt/orchestrator`
   → atteso: directory presente con `.git` (primo deploy di questo repo su questo VPS).
3. `cd /opt/orchestrator && git fetch origin && git rev-parse origin/master` → atteso: hash
   confermato a voce con te prima di procedere.
4. `git checkout master && git pull` → atteso: `git rev-parse HEAD` coincide col passo 3.
5. `python3 -m venv .venv && .venv/bin/pip install -e .` → atteso: nessun errore;
   `.venv/bin/python -c "import components.regime_daemon; import components.wiring_loop"` esce
   con codice 0.
6. `sudo mkdir -p /etc/orchestrator && sudo touch /etc/orchestrator/env && sudo chmod 600 /etc/orchestrator/env && sudo chown root:freqbot /etc/orchestrator/env`
   → atteso: `ls -l /etc/orchestrator/env` mostra `-rw------- root freqbot`. **Qui si ferma la mia
   parte finché tu non compili il file (Passo 1.3).**
7. Creare **due** unit systemd (non una):

   `/etc/systemd/system/orchestrator-regime-daemon.service`:
   ```ini
   [Unit]
   Description=Orchestrator regime-daemon (ADR-037 §10)
   After=network-online.target

   [Service]
   Type=simple
   User=freqbot
   WorkingDirectory=/opt/orchestrator
   EnvironmentFile=/etc/orchestrator/env
   ExecStart=/opt/orchestrator/.venv/bin/python -m components.regime_daemon \
     --state-dir /opt/orchestrator/var/regime \
     --config /opt/orchestrator/config/regime.yaml \
     --bot-token ${TG_ALERT_BOT_TOKEN} \
     --chat-id ${TG_ALERT_CHAT_ID} \
     --healthchecks-url ${HEALTHCHECKS_PING_URL_REGIME_DAEMON}
   Restart=on-failure
   RestartSec=30

   [Install]
   WantedBy=multi-user.target
   ```

   `/etc/systemd/system/orchestrator-wiring-loop.service`:
   ```ini
   [Unit]
   Description=Orchestrator wiring-loop (ADR-037 §10)
   After=network-online.target orchestrator-regime-daemon.service

   [Service]
   Type=simple
   User=freqbot
   WorkingDirectory=/opt/orchestrator
   EnvironmentFile=/etc/orchestrator/env
   ExecStart=/opt/orchestrator/.venv/bin/python -m components.wiring_loop \
     --state-dir /opt/orchestrator/var/regime \
     --staleness-minutes 60 \
     --bot-token ${TG_ALERT_BOT_TOKEN} \
     --chat-id ${TG_ALERT_CHAT_ID} \
     --healthchecks-url ${HEALTHCHECKS_PING_URL_WIRING_LOOP}
   Restart=on-failure
   RestartSec=30

   [Install]
   WantedBy=multi-user.target
   ```

   Nota: `Restart=on-failure` (mai `always` senza `RestartSec` — lezione `mft_paper.service`,
   `crypto-agent/docs/DECOMMISSION-2026-07.md`). `--state-dir` identica per i due processi: è
   proprio il file locale condiviso attraverso cui comunicano (ADR-037 §10, nessuna chiamata di
   rete tra i due). `After=...orchestrator-regime-daemon.service` sul wiring-loop è un
   suggerimento di ordine di avvio, non una dipendenza stretta: `wiring-loop` è già fail-safe se
   parte prima che esista un primo snapshot (`load_snapshot_safely` → `None` →
   `NO_ACTION_STALE_DATA` + alert, verificato in review).
   → atteso per entrambe: `systemd-analyze verify orchestrator-regime-daemon.service` e
   `systemd-analyze verify orchestrator-wiring-loop.service` senza errori.
8. `sudo systemctl daemon-reload && sudo systemctl enable --now orchestrator-regime-daemon.service orchestrator-wiring-loop.service`
   → atteso: `systemctl status` di entrambe mostra `active (running)`.
9. Attendere un ciclo completo di ciascuno (15 min daemon, 5 min loop), poi verificare i canary →
   atteso: ENTRAMBI i check su healthchecks.io risultano "up" (screenshot o risposta API per
   ciascuno, non uno solo).
10. Aggiornare l'inventario VPS (`report.inventory`, M1 Task 13) → atteso: i due nuovi processi
    compaiono nel prossimo snapshot (diff mostrato).

### 3. Criterio di completamento — smoke test end-to-end su VPS con i due alert reali

**Nota:** questo è lo smoke test SUL VPS REALE, con Telegram vero. Un smoke test locale
equivalente (dry-run, senza token reali) è già stato eseguito ed è nel report — vedi
`docs/m2-checkpoint-entrypoints-review-integrativo.md`. Questo passo ripete lo stesso schema con i
canali reali, non lo sostituisce: un dry-run locale prova che la logica funziona, non che il
canale Telegram/healthchecks reale sul VPS è configurato correttamente.

1. Attendere che `regime-daemon` abbia scritto almeno un `RegimeSnapshot` reale (verificabile con
   `cat /opt/orchestrator/var/regime/regime_state.json`).
2. Scrivere a mano, sullo stesso path, uno snapshot con `eth_high_vol=true, eth_harvester_on=true`
   → attendere un ciclo di `wiring-loop` (≤5 min) → **atteso: un messaggio Telegram reale con
   prefisso `LAYER LAVORA`**.
3. Scrivere uno snapshot con timestamp invecchiato oltre 60 minuti → attendere un ciclo → **atteso:
   un messaggio Telegram reale con prefisso `LAYER CIECO`**.
4. **Completamento = entrambi i messaggi confermati ricevuti da te di persona** (Passo 1.5) — non
   un'asserzione di test, non un log locale.
5. Ripristinare lo snapshot allo stato di riposo (o cancellarlo) subito dopo — non lasciare il
   sistema in uno stato di test. `regime-daemon` lo sovrascriverà comunque al ciclo successivo con
   una misura reale.

### 4. Piano di rollback (testabile, riporta il VPS allo stato attuale)

1. `sudo systemctl stop orchestrator-regime-daemon.service orchestrator-wiring-loop.service && sudo systemctl disable orchestrator-regime-daemon.service orchestrator-wiring-loop.service`
   → verifica: `systemctl status` di entrambe mostra `inactive (dead)`.
2. `sudo rm /etc/systemd/system/orchestrator-regime-daemon.service /etc/systemd/system/orchestrator-wiring-loop.service && sudo systemctl daemon-reload`
   → verifica: `systemctl status` di entrambe mostra "could not be found".
3. `/etc/orchestrator/env`: lasciarlo (credenziali innocue, non lette da nessun processo a servizio
   fermo) per un rollback rapido successivo, oppure `sudo rm` se si abbandona per sempre — scelta
   al momento.
4. `/opt/orchestrator/var/regime/regime_state.json`: dato locale, non un segreto — lasciarlo o
   cancellarlo non ha implicazioni di sicurezza, solo di pulizia.
5. Nessuna immagine Docker coinvolta (processi Python nativi) — nessun `docker container prune`
   necessario.
6. Verifica finale: `ps aux | grep -E "regime_daemon|wiring_loop"` → nessun processo; prossimo
   snapshot inventario VPS (M1 Task 13) → i due processi non compaiono più (diff mostrato).
7. **Stato del VPS dopo rollback: identico a prima del deploy** tranne per `/opt/orchestrator`
   (codice clonato, inerte) e, se non cancellati, `/etc/orchestrator/env` e
   `var/regime/regime_state.json` (nessun dato né chiave di altri progetti toccato).

---

## Verifica post-deploy (obbligatoria, con comando + output — non "verificato" in prosa)

Regola esplicita (Task 2, coda forense): ogni affermazione "verificato X" in questo runbook deve
riportare il comando eseguito e l'output osservato. Esempio del formato atteso, da compilare al
momento del deploy reale:

```
$ systemctl status orchestrator-regime-daemon.service
[output reale qui]
$ systemctl status orchestrator-wiring-loop.service
[output reale qui]
$ curl -s https://hc-ping.com/<uuid-regime-daemon>
[output reale qui]
$ curl -s https://hc-ping.com/<uuid-wiring-loop>
[output reale qui]
```
