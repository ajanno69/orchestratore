# Runbook operativo — cosa fare quando scatta high-vol (M2)

**Ambito attivo oggi: solo binario harvester.** Le sezioni GridBTC sono marcate CONDIZIONALI:
GridBTC non esiste oggi come bot live (vedi `docs/gridbtc-highvol-analysis-m2.md`, ground truth
2026-07-06 — solo shadow, mai capitale esposto), quindi non c'è oggi nessun `GridBtcCommand` da
eseguire nella realtà. Le sezioni restano qui per essere pronte quando/se GridBTC verrà
ricostruito e supererà il gate di promozione (`docs/m2-reactivation-gates.md`).

## Cosa vedo

- Alert (canale da definire in Task 3 — Telegram, stesso canale già in uso per funding-harvester)
  con il campo `reason` di `WiringDecision` (M2 Task 1): dice esattamente perché è scattato
  (snapshot assente/stantio, oppure quale asset è in high-vol).
- Report settimanale (M1 Task 14, `report.weekly_report`) include già la sezione di regime — la
  uso per un controllo di secondo livello, non solo per la reazione in tempo reale all'alert.

## Come verifico lo stato del layer (non solo l'alert)

1. Il canale di alert stesso è vivo? (Questo NON è verificato dall'alert — se il processo di
   wiring muore, non arriva nessun alert. Verificare separatamente che il canary/healthcheck del
   Task 3 stia pingando regolarmente — con comando + output, non "verificato" in prosa: vedi la
   regola emersa dalla coda forense del Task 2.)
2. `regime.store.RegimeStateStore(base_path).read()` sul VPS: lo snapshot corrente è quello che mi
   aspetto, o è più vecchio della soglia di staleness (Task 1)?
3. Il comando prodotto (`HarvesterCommand` — e, quando applicabile, `GridBtcCommand`) corrisponde
   a quello che il componente sottostante sta effettivamente eseguendo? (Il wiring produce
   comandi — un bug nell'executor che li consuma potrebbe non applicarli davvero.)

## Cosa faccio

- **`NO_ACTION_STALE_DATA`:** nessuna azione automatica è già avvenuta. Verifico perché lo snapshot
  è assente/stantio (processo del regime layer morto? rete? dati exchange mancanti?) prima di
  qualunque altra cosa.
- **`DEFENSIVE` (harvester):** confermo che nessun nuovo ingresso/scale-up sia stato aperto. Se il
  margin buffer è sotto soglia di rabbocco, decido io se rabboccare — mai automatico.
- **`HIGH_VOL_STOP_NEW_ORDERS` / `HIGH_VOL_CLOSE_GRID_ORDERLY` (GridBTC) — CONDIZIONALE, non
  applicabile finché GridBTC non esiste come bot live:** quando applicabile, confermo che l'azione
  scelta al gate di promozione (Task 4, `docs/m2-reactivation-gates.md`) sia stata applicata. Se è
  chiusura ordinata, verifico l'esecuzione effettiva (prezzi di chiusura, slippage) prima di
  considerare l'episodio chiuso.

## Escalation

Se il wiring stesso si comporta in modo inatteso (comando diverso da quello che mi aspetterei dato
lo snapshot che vedo), fermo il processo di wiring (systemd stop, Task 3) — mai lascio un
componente che tocca capitale reale guidato da un wiring di cui non mi fido in quel momento.
