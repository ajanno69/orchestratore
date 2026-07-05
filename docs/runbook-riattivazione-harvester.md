# Runbook — Riattivazione funding-harvester (M2, richiede conferma esplicita di Andrea)

Questo documento è SOLO checklist. Nessun comando qui va eseguito senza
conferma esplicita di Andrea (ADR-036: M2 parte con conferma esplicita,
M1 si ferma qui — niente ordini, niente live).

Stato di partenza (2026-07-05, da
[DECOMMISSION-2026-07.md](../../crypto-agent/docs/DECOMMISSION-2026-07.md)):
funding-harvester ETH/OKX è code-complete (520 test), parcheggiato.
`funding-harvester-daily-report.timer` fermato+disabled (era l'ultimo
canary attivo sul VPS). Container `funding-postgres` ancora up (dati
intatti). Nessuna chiave OKX attiva.

## Checklist di riattivazione

1. **Chiavi OKX NUOVE a permessi minimi**
   - [ ] Andrea crea chiavi OKX nuove (mai riusare quelle vecchie/scadute)
   - [ ] Permessi: SOLO trade + read, **MAI withdraw**
   - [ ] Chiavi caricate in `.env` del repo orchestratore (mai committate),
     non nel vecchio `.env` di funding-harvester

2. **Size iniziale**
   - [ ] Size ridotta rispetto al code-complete originale (ADR-036 §3:
     "riattivazione a size ridotta in M2 su conferma esplicita")
   - [ ] Budget cap verificato via `risk.constraints.assert_within_budget_cap`
     prima di ogni incremento di size

3. **Canary**
   - [ ] Riattivare `funding-harvester-daily-report.timer`:
     `systemctl enable --now funding-harvester-daily-report.timer`
     (reversibilità confermata in DECOMMISSION-2026-07.md — stesso
     ExecStart, nessuna modifica necessaria)
   - [ ] Verificare 1 messaggio Telegram/giorno ricevuto prima di procedere

4. **Healthcheck riusato (pattern VIVO-MA-CIECO)**
   - [ ] Riusare la logica di
     [`newcrypto/ops/watchdog.py`](../../funding-harvester/newcrypto/ops/watchdog.py)
     (funding-harvester, NON toccare quel repo — solo pattern di
     riferimento): ping a healthchecks.io condizionato su `work_ok=True`
     ("ho fatto il mio lavoro e l'ho fatto bene", non "sono vivo")
   - [ ] Verificare che un heartbeat non leggibile (file mancante,
     Postgres down) NON pinghi healthchecks.io — deve scattare l'alert
     esterno, non un falso "vivo"

5. **Riattivazione ordinata**
   - [ ] `docker start funding-postgres` (se non già up)
   - [ ] Avviare l'executor a size ridotta, SOLO dopo canary + healthcheck
     verificati per >= 24h
   - [ ] Aggiornare l'inventario VPS (`report.inventory`) subito dopo:
     il nuovo processo/unit deve comparire nel prossimo snapshot, MAI
     un punto cieco come `mft_paper.service` (vedi DECOMMISSION-2026-07.md,
     sezione "Sorpresa trovata")

6. **Conferma esplicita**
   - [ ] Nessuno step sopra eseguito senza messaggio esplicito di conferma
     di Andrea per QUESTA riattivazione specifica (non basta l'approvazione
     di ADR-036 in generale)

## Rollback

- Stop pulito: `systemctl stop <unit-executor>` + `systemctl disable`
  (mai `kill -9`: vedi la sorpresa di `mft_paper.service` in
  DECOMMISSION-2026-07.md — un `Restart=always` riavvia il processo in
  meno di un secondo se non si passa da systemd)
- Le chiavi OKX nuove vanno revocate dal pannello OKX (azione manuale,
  non eseguibile da qui) se la riattivazione viene abortita
