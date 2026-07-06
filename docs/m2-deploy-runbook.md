# Runbook di deploy M2 (VPS Contabo) — binario harvester

**Ambito:** deploy del processo di wiring (`src/components/regime_wiring.py`, M2 Task 1) sul VPS
Contabo esistente, per il binario harvester (ETH). Nessun comando qui va eseguito prima del
checkpoint "wiring implementato pre-deploy" (piano M2) per il binario harvester.

**GridBTC — CONDIZIONALE, non applicabile oggi:** GridBTC non esiste oggi come bot live (nessuna
definizione `bot_grid_btc` in `infra/docker-compose.yml` di crypto-agent, vedi
`docs/gridbtc-highvol-analysis-m2.md`; ground truth Andrea 2026-07-06: solo shadow, mai capitale
esposto). Questo runbook copre il deploy del processo di wiring in generale — è lo stesso processo
per entrambi gli asset (legge un unico `RegimeSnapshot`, produce comandi per entrambi) — ma
qualunque passo che presuppone un consumatore GridBTC attivo (es. puntare l'executor a un servizio
Freqtrade GridBTC) resta sospeso fino al gate di promozione di GridBTC
(`docs/m2-reactivation-gates.md`), quando quel bot esisterà davvero.

Stesso pattern operativo di funding-harvester (systemd + canary + healthcheck), applicato al
processo di wiring.

---

## Checklist pre-deploy (da chiudere PRIMA di aprire la sessione dedicata)

Obiettivo: la sessione di deploy dedicata deve essere corta — nessuna scoperta a sorpresa durante
la seduta, nessun passo improvvisato. Tutto ciò che segue è preparazione di solo repo (nessuna
esecuzione, nessuna chiave, nessuna modifica al VPS) fatta in anticipo.

### 0. Prerequisito mancante trovato in fase di preparazione (blocca la sessione finché non chiuso)

Non esiste ancora, nel repo, un **entrypoint eseguibile** del loop di wiring. Oggi ci sono solo:
`src/components/regime_wiring.py` (funzione pura `resolve_wiring_decision`), `wiring_sequencer.py`
(dedup/alert stateful, testato) e `scripts/demo_wiring_checkpoint2.py` (dimostrazione con dati
sintetici, sink in-memory, nessun Telegram/healthchecks reale — vedi
`docs/m2-checkpoint2-wiring-demo-report.md`). **Manca lo script di produzione** (proposto:
`scripts/run_wiring_loop.py`) che: legge `RegimeStateStore` reale, chiama
`resolve_wiring_decision`, passa il risultato a `WiringSequencer`, e per ogni `AlertEvent` invia
un messaggio Telegram reale (stesso pattern di funding-harvester: POST a
`https://api.telegram.org/bot{TG_ALERT_BOT_TOKEN}/sendMessage` con `chat_id=TG_ALERT_CHAT_ID`,
vedi `funding-harvester/newcrypto/ops/telegram_alert.py:207-212`, sola lettura/riferimento), e
pinga `HEALTHCHECKS_PING_URL` **solo se il ciclo completa senza eccezioni** (pattern
VIVO-MA-CIECO di `funding-harvester/newcrypto/ops/watchdog.py`, non toccato). Questo script (+ i
suoi test) **non è stato scritto in questa sessione** — la richiesta di oggi era solo la
checklist — e va scritto TDD prima di aprire la sessione di deploy dedicata, altrimenti il Passo 2
sotto non ha nulla da eseguire.

**Secondo prerequisito, più strutturale:** anche con quell'entrypoint pronto, oggi non esiste da
nessuna parte un processo che scrive DAVVERO un `RegimeSnapshot` dal vivo (nessun M1 task ha
deployato un daemon di misura EWMA/funding continuo — M1/M1.5 sono rimasti codice+script one-off,
mai un servizio live). Per questo lo **smoke test (§3 sotto) userà uno snapshot scritto a mano**
durante la sessione, sul path reale del VPS — non un daemon di misura live, che resta un pezzo di
lavoro futuro separato, esplicitamente fuori scope anche per la sessione dedicata di deploy.

### 1. Passi TUOI (manuali — chiavi, token, dove inserirli)

1. **Canale Telegram**: decidere se riusare lo stesso bot/chat già attivo per funding-harvester
   (valori già esistenti in `/etc/funding-harvester/env` sul VPS, mai nel repo) o crearne uno
   dedicato all'orchestratore via @BotFather. Nessuna delle due scelte è già presa — è tua.
2. **Healthchecks.io**: creare un nuovo check gratuito dedicato a `orchestrator-wiring` (period/grace
   5+5 minuti, stesso pattern del watchdog funding-harvester) e copiare l'URL di ping.
3. **Scrittura dei valori**: `TG_ALERT_BOT_TOKEN`, `TG_ALERT_CHAT_ID`, `HEALTHCHECKS_PING_URL` vanno
   scritti SOLO in `/etc/orchestrator-wiring/env` sul VPS, con un editor durante la sessione (mai
   incollati in chat, mai in un commit, mai in un log) — io preparo il file vuoto con i permessi
   corretti (mode 600, `root:freqbot` — Passo 2.5 sotto), tu lo compili.
4. **GridBTC**: nessuna azione — questo deploy è harvester-only, `GridBtcHighVolAction` non entra
   in gioco (vedi `docs/gridbtc-highvol-analysis-m2.md`, condizionale al gate di promozione).
5. **Conferma visiva in sessione**: al momento dello smoke test (§3), sei tu a confermare a voce/in
   chat che i due alert di test sono arrivati sul telefono — il criterio di completamento non è
   soddisfatto da un log locale, serve la tua conferma diretta.

### 2. Passi MIEI via SSH (in ordine — comando di verifica + esito atteso, MAI "verificato" in prosa)

1. `ssh freqbot@207.180.247.38` → atteso: prompt di shell.
2. `ls /opt/orchestrator 2>&1 || git clone https://github.com/ajanno69/orchestratore.git /opt/orchestrator`
   → atteso: directory presente con `.git` (primo deploy di questo repo su questo VPS).
3. `cd /opt/orchestrator && git fetch origin && git rev-parse origin/master` → atteso: hash
   confermato a voce con te prima di procedere (non assunto identico a quello letto qui).
4. `git checkout master && git pull` → atteso: `git rev-parse HEAD` coincide col valore del passo 3.
5. `python3 -m venv .venv && .venv/bin/pip install -e .` → atteso: nessun errore;
   `.venv/bin/python -c "import components.wiring_sequencer"` esce con codice 0.
6. `sudo mkdir -p /etc/orchestrator-wiring && sudo touch /etc/orchestrator-wiring/env && sudo chmod 600 /etc/orchestrator-wiring/env && sudo chown root:freqbot /etc/orchestrator-wiring/env`
   → atteso: `ls -l /etc/orchestrator-wiring/env` mostra `-rw------- root freqbot`. **Qui si ferma
   la mia parte finché tu non compili il file (Passo 1.3).**
7. Creare `/etc/systemd/system/orchestrator-wiring.service` (`ExecStart` verso l'entrypoint del
   Prerequisito 0, `EnvironmentFile=/etc/orchestrator-wiring/env`, `Restart=on-failure`, mai
   `always` senza `RestartSec` — lezione `mft_paper.service`,
   `crypto-agent/docs/DECOMMISSION-2026-07.md`) → atteso: `systemd-analyze verify
   orchestrator-wiring.service` senza errori.
8. `sudo systemctl daemon-reload && sudo systemctl enable --now orchestrator-wiring.service` →
   atteso: `systemctl status orchestrator-wiring.service` mostra `active (running)`.
9. Attendere un ciclo completo del loop, poi verificare il canary → atteso: il check
   `orchestrator-wiring` su healthchecks.io risulta "up" (screenshot o risposta API allegata).
10. Aggiornare l'inventario VPS (`report.inventory`, M1 Task 13) → atteso: il nuovo processo
    compare nel prossimo snapshot (diff mostrato, non solo affermato).

### 3. Criterio di completamento — smoke test end-to-end con i due alert reali

1. Scrivere a mano, sul path reale di `RegimeStateStore` del VPS, uno snapshot con
   `eth_high_vol=True, eth_harvester_on=True` → attendere un ciclo → **atteso: un messaggio
   Telegram reale con prefisso `LAYER LAVORA`** (testo di `WiringSequencer` per l'entrata in
   `DEFENSIVE`, vedi `docs/m2-checkpoint2-wiring-demo-report.md` per il testo esatto).
2. Scrivere uno snapshot corrotto (o lasciarlo invecchiare oltre la soglia di staleness) →
   attendere un ciclo → **atteso: un messaggio Telegram reale con prefisso `LAYER CIECO`**.
3. **Completamento = entrambi i messaggi confermati ricevuti da te di persona** (Passo 1.5) — non
   un'asserzione di test, non un log locale.
4. Ripristinare lo snapshot allo stato di riposo (o cancellarlo) subito dopo — non lasciare il
   sistema in uno stato di test.

### 4. Piano di rollback (testabile, riporta il VPS allo stato attuale)

1. `sudo systemctl stop orchestrator-wiring.service && sudo systemctl disable orchestrator-wiring.service`
   → verifica: `systemctl status orchestrator-wiring.service` mostra `inactive (dead)`.
2. `sudo rm /etc/systemd/system/orchestrator-wiring.service && sudo systemctl daemon-reload` →
   verifica: `systemctl status orchestrator-wiring.service` mostra "could not be found".
3. `/etc/orchestrator-wiring/env`: lasciarlo (credenziali innocue, non lette da nessun processo a
   servizio fermo) per un rollback rapido successivo, oppure `sudo rm` se si abbandona per sempre
   — scelta al momento, non pre-decisa qui.
4. Nessuna immagine Docker coinvolta (processo Python nativo, non containerizzato come i bot
   Freqtrade) — nessun `docker container prune` necessario, nessun rischio di toccare container
   di altri progetti.
5. Verifica finale: `ps aux | grep wiring` → nessun processo; prossimo snapshot inventario VPS
   (M1 Task 13) → il processo non compare più (diff mostrato).
6. **Stato del VPS dopo rollback: identico a oggi (2026-07-06)** tranne per `/opt/orchestrator`
   (codice clonato, inerte) e, se non cancellato, `/etc/orchestrator-wiring/env` (credenziali
   innocue senza consumatore) — nessun dato né chiave di altri progetti toccato.

---

## Deploy

1. `ssh freqbot@207.180.247.38`
2. `cd /path/to/orchestrator && git pull origin master` (repo orchestrator clonato sul VPS,
   percorso esatto da confermare al momento del deploy — non esiste ancora un clone lì, questo è
   il primo deploy di questo repo su quel VPS).
3. Chiavi: NON in questo repo. Create manualmente da Andrea, permessi minimi (mai withdraw),
   cifrate con `sops`/`age`, decifrate solo a runtime nella working directory del processo (mai su
   disco in chiaro, mai in un commit, mai in un log). Per il binario harvester: stessa chiave OKX
   già prevista dal gate G3 esistente (`docs/runbook-riattivazione-harvester.md`), nessuna chiave
   nuova introdotta da questo deploy. Per GridBTC: nessuna chiave da creare finché il gate di
   promozione GridBTC non è stato raggiunto — creare una chiave Kraken in anticipo per un bot che
   non esiste sarebbe una credenziale senza consumatore, esattamente il tipo di punto cieco
   documentato in `crypto-agent/docs/DECOMMISSION-2026-07.md` (chiavi orfane rimaste attive senza
   processo consumatore).
4. Unit systemd dedicata (nome proposto: `orchestrator-wiring.service`), `Restart=on-failure` (non
   `always` senza `RestartSec` — vedi lezione `mft_paper.service` in
   `crypto-agent/docs/DECOMMISSION-2026-07.md`: un `Restart=always` senza verifica di stato pulito
   può rimettere in piedi un processo che dovrebbe restare fermo).
5. Canary: stesso pattern di `funding-harvester-daily-report.timer` — un ping periodico a
   healthchecks.io condizionato su "il ciclo di wiring ha letto lo snapshot e prodotto una
   decisione senza eccezioni", non solo "il processo è vivo" (pattern VIVO-MA-CIECO, vedi
   `funding-harvester/newcrypto/ops/watchdog.py`, non toccato, solo di riferimento).
6. Dopo il deploy: aggiornare l'inventario VPS (`report.inventory`, M1 Task 13) al primo giro utile
   — il nuovo processo deve comparire nel prossimo snapshot, mai un punto cieco come
   `mft_paper.service` (scoperto solo per caso durante il decommission del 2026-07-05, vedi
   `crypto-agent/docs/DECOMMISSION-2026-07.md`).

## Verifica post-deploy (obbligatoria, con comando + output — non "verificato" in prosa)

Regola esplicita (Task 2, coda forense): ogni affermazione "verificato X" in questo runbook, e in
qualunque suo aggiornamento futuro, deve riportare il comando eseguito e l'output osservato.
Esempio del formato atteso, da compilare al momento del deploy reale:

```
$ systemctl status orchestrator-wiring.service
[output reale qui]
$ curl -s http://localhost:<porta_healthcheck>/status
[output reale qui]
```

## Rollback

`systemctl stop <unit> && systemctl disable <unit>` — mai `kill -9` (stesso principio del runbook
harvester M1, `docs/runbook-riattivazione-harvester.md`).
