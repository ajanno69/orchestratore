# Gate di attivazione per componente (M2) — protocollo unico

**Emendamento 2026-07-06 (ground truth Andrea):** la prima versione di questo documento (mai
committata separatamente, esisteva solo come bozza nel piano) prevedeva due protocolli distinti —
2 settimane di shadow per l'harvester, 4 settimane per GridBTC, giustificate dal fatto che
"GridBTC ha già capitale reale esposto". Ground truth: **falso — GridBTC è stato SOLO shadow, mai
capitale esposto.** Non c'è nessuna base per un protocollo più permissivo o diverso per GridBTC:
i due componenti seguono **lo stesso protocollo**, senza eccezioni. Vedi
`docs/ADR-037-wiring-regime-layer-capitale.md` §5-6 (emendato) e
`docs/gridbtc-highvol-analysis-m2.md` (finding forense).

Ordine: harvester (gate G3) prima. GridBTC dopo, e comunque non prima che esista di nuovo un bot
GridBTC reale — oggi non esiste (vedi Task 2) — da mettere in shadow.

## Protocollo unico (harvester e GridBTC, nessuna differenza di trattamento)

- **Durata shadow/dry-run minima: 2 settimane** di wiring attivo in sola lettura. Il wiring produce
  decisioni e le logga/alerta, ma il componente sottostante esegue secondo la sua logica attuale,
  ignorando il comando del wiring (`DEFENSIVE`/`HIGH_VOL_*`) — verifica che il wiring produca i
  comandi giusti SENZA ancora agire su di essi.
- **Criteri di promozione** (il wiring inizia davvero a bloccare nuovi ingressi / a comandare
  un'azione high-vol):
  - zero eccezioni non gestite nel loop di wiring per l'intera durata dello shadow;
  - ogni transizione di stato di regime osservata durante lo shadow è stata alertata
    correttamente (verificabile a mano dai log/alert, confrontati con lo storico reale dello
    snapshot — con comando + output allegato alla verifica, non "verificato" in prosa: vedi la
    regola emersa dalla coda forense del Task 2);
  - nessun falso `NO_ACTION_STALE_DATA` durante lo shadow dovuto a un bug di staleness (soglia
    scelta in Task 1 verificata empiricamente non troppo stretta);
  - conferma esplicita di Andrea, non una promozione automatica al termine delle 2 settimane —
    la durata minima è una condizione necessaria, non sufficiente.
- Dopo la promozione: size invariata rispetto al gate G3 esistente — il wiring aggiunge prudenza,
  non cambia il sizing.

## Harvester ETH

- Segue il protocollo unico sopra, senza aggiunte. Precondizione aggiuntiva al gate G3 esistente
  (`past project/03_newcrypto-funding-harvester.md`), non lo sostituisce.

## GridBTC — CONDIZIONALE al suo shadow futuro

**Questa sezione non si applica oggi.** GridBTC non esiste come bot live né come processo in
shadow nel repo crypto-agent attuale (verificato: nessuna definizione `bot_grid_btc` in
`infra/docker-compose.yml`, nessun file di strategia con nome riconducibile, nessuna traccia in
`agent/v2/*` — vedi `docs/gridbtc-highvol-analysis-m2.md`). Si applica **solo quando/se** GridBTC
verrà ricostruito e rientrerà in shadow.

Quando quel momento arriverà:

- Segue **esattamente il protocollo unico sopra** — stessa durata minima (2 settimane), stessi
  criteri di promozione, stesso gate G3 in termini di size. Nessuna eredità di fiducia dallo stato
  shadow del 2026-05 (una versione precedente di GridBTC arrivò in shadow allora, ma quella storia
  non trasferisce credito alla versione futura: si riparte da zero).
- **Aggiuntivo, specifico di GridBTC — verifica dell'esistenza di un guard proprio, al momento,
  non per changelog:** prima di iniziare lo shadow del wiring, verificare con un comando reale
  (non con la memoria del changelog storico, che si è già dimostrato inaffidabile — vedi Task 2)
  se il GridBTC ricostruito ha un proprio meccanismo di guardia interno. Se sì: durante lo shadow,
  ogni volta che `btc_high_vol=True` e il guard esistente scatta indipendentemente, confrontare a
  mano il comportamento dei due segnali — se sono in disaccordo sistematico, la promozione NON
  procede finché quel disaccordo non è capito.
- Conferma esplicita di Andrea sul valore di `GridBtcHighVolAction` (informata dalla
  raccomandazione condizionale già in `docs/gridbtc-highvol-analysis-m2.md` §5, da riverificare
  contro il GridBTC reale che esisterà allora, non da applicare alla cieca).
- Dopo la promozione: size secondo il sizing che GridBTC avrà in quel momento (nessun assunto di
  "size invariata rispetto allo stato attuale" — non c'è uno stato attuale con capitale da cui
  partire, essendo GridBTC sempre stato shadow-only).
