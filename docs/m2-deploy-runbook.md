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
