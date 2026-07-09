# Finding shadow — resilienza di rete regime-daemon (2026-07-09)

**Materiale d'istruttoria per il gate, non un rumore da nascondere.** Un'analisi read-only dello
storico raccolto dall'`history-collector` ha trovato 12 cicli di misura falliti in 43 ore di
shadow, tutti per `NetworkError` verso l'API pubblica OKX. **Lettura corretta al gate: il
fail-safe è scattato correttamente su un guasto di rete reale — è la prova che il design
funziona, non un difetto del sistema.** Il finding stesso è un argomento PRO shadow: ha scoperto
esattamente il tipo di comportamento reale che un periodo di osservazione deve scoprire, prima
che ci sia capitale in gioco.

## 1. Il finding — 12 gap in 43 ore

Richiesta originale: "arrivano spesso notifiche da healthcheck" (Andrea, osservazione diretta).
Verifica reale (sola lettura, nessuna modifica al VPS):

```
$ systemctl is-active orchestrator-regime-daemon orchestrator-wiring-loop orchestrator-history-collector
active / active / active   (NRestarts=0 su tutti e tre)
```

Analisi dello storico (`history.db`, 161 righe, 2026-07-07T10:01 → 2026-07-09T05:05):

```
righe totali: 161
gap >20min trovati: 12   (ciascuno = esattamente un ciclo di misura saltato)
  07-07 11:16→11:46, 16:47→17:17, 17:47→18:17, 20:17→20:47
  07-08 03:34→04:04, 10:33→11:03, 11:18→11:48, 20:19→20:49, 21:35→22:05, 23:05→23:35
  07-09 00:35→01:05, 03:35→04:05
```

~1 ciclo fallito ogni 3-4 ore, nessun pattern orario riconoscibile (non un cron job in
collisione, non un rate-limit periodico). Ogni gap = un alert Telegram "LAYER CIECO" inviato
correttamente, nessuno snapshot corrotto scritto, ripresa automatica al ciclo successivo — il
fail-safe (ADR-037 §3, §10) ha funzionato esattamente come progettato, 12 volte su 12.

**Elementi trovati e scartati come non correlati:**
- `copy-selector-weekly-pnl.service` fallita ma da oltre un mese (5 giugno), disabilitata, nessun
  timer attivo — rumore vecchio in `systemctl --failed`, non nuove notifiche.
- Nessun container/unit del funding-harvester in esecuzione (solo i suoi database Postgres) — le
  notifiche frequenti potrebbero includere anche il check `funding-harvester-watchdog` su
  healthchecks.io, verificato in una sessione precedente come "paused" da settimane; non
  riverificato qui (fuori scope, progetto separato, richiede verifica visiva che l'estensione
  Chrome non ha permesso di fare in questa sessione).
- Il riavvio simultaneo dei tre processi orchestrator (2026-07-08 06:46 CEST) è un aggiornamento
  di sicurezza automatico di `python3.12` via `unattended-upgrades` — benigno, non un guasto.

## 2. Diagnosi read-only — causa esatta, non più un'ipotesi

Script standalone (`okx_network_probe.py`, MAI una unit systemd, lanciato a mano via `nohup` in
`/home/freqbot/diag-okx-network-2026-07-09/`, fuori da `/opt/orchestrator`) che riproduce
ESATTAMENTE le tre chiamate di rete di `regime_daemon.run_once` (`fetch_ohlcv("BTC/USDT", "1d",
200)`, `fetch_ohlcv("ETH/USDT", "1d", 200)`, `fetch_funding_rate("ETH/USDT:USDT")`), stesso
oggetto `ccxt.okx()` riusato per tutta la durata (come in produzione), a cadenza di 20s invece di
15 min per accumulare un campione statistico in un'ora invece che in giorni. Log JSONL locale.

Eseguito: 2026-07-09 05:31–06:31 UTC (07:31–07:29 CEST), `ccxt` 4.5.64, timeout di default non
sovrascritto da `regime_daemon.py` (10000ms, default della libreria).

**Risultato — comando e output integrale:**

```
$ cat probe.out
[probe] ccxt version=4.5.64 default timeout=10000ms
[probe] fine: 172 iterazioni, 516 chiamate, 4 fallite (0.8%)
```

**Le 4 chiamate fallite, testo esatto:**

```
2026-07-09T05:33:27Z  call=fetch_ohlcv_btc  type=RequestTimeout (ccxt.base.errors)  latency=10013.8ms
2026-07-09T05:42:34Z  call=fetch_ohlcv_btc  type=RequestTimeout (ccxt.base.errors)  latency=10012.7ms
2026-07-09T06:04:19Z  call=fetch_ohlcv_btc  type=RequestTimeout (ccxt.base.errors)  latency=10014.9ms
2026-07-09T06:26:13Z  call=fetch_ohlcv_btc  type=RequestTimeout (ccxt.base.errors)  latency=10024.7ms
```

Testo dell'eccezione, identico in tutte e 4: `okx GET https://www.okx.com/api/v5/market/candles?
instId=BTC-USDT&bar=1Dutc&limit=200` — stesso identico endpoint/parametri dell'alert reale
osservato in produzione il 2026-07-07.

**Latenza delle 512 chiamate riuscite** (baseline sano): min=198ms, mediana=216ms, p95=273ms,
max=20303ms (un singolo outlier riuscito appena sotto il timeout doppio, non un fallimento).

**Diagnosi definitiva: `RequestTimeout` (sottoclasse di `NetworkError` in ccxt — il testo "LAYER
CIECO...NetworkError(...)" osservato in chat il 2026-07-07 riportava probabilmente solo la
classe base), NON un errore di connessione/DNS/reset.** Tutte e 4 le occorrenze sono cadute
ESATTAMENTE al bordo dei 10000ms (10013–10025ms) — il timeout lato client di ccxt (default della
libreria, mai configurato esplicitamente in `regime_daemon.py`) è scattato prima che OKX
rispondesse, non un fallimento di rete "duro". La baseline è sanissima (mediana 216ms — 46x
sotto il timeout): è la CODA della distribuzione di latenza di un endpoint pubblico su Internet
(non colocato con il VPS Contabo) a superare occasionalmente 10s, non una rete "intrinsecamente
rumorosa" nel senso di pacchetti persi/connessioni cadute.

**Nota onesta sul confronto con la produzione**: il tasso per-chiamata qui (0.8%, 4/516) non
coincide esattamente con quello per-ciclo osservato in produzione (12/172 ≈ 7% dei cicli, senza
retry — un solo fallimento su 3 chiamate uccide il ciclo, quindi atteso ≈2.4% con un tasso di
0.8% per chiamata). Il fattore ~3x di scarto è più verosimilmente rumore statistico su numeri
piccoli (4 vs 12 occorrenze) che una differenza sistematica — non abbastanza dati per escludere
con certezza un effetto della cadenza diversa (20s vs 15min), ma il MECCANISMO (timeout lato
client su una coda di latenza rara di un endpoint pubblico) è identico e già sufficiente a
spiegare il fenomeno e a validare il fix.

**Interessante, non necessariamente significativo**: tutte e 4 le occorrenze sono cadute sulla
chiamata BTC, mai su ETH o sul funding rate — verosimilmente perché nello script (come in
produzione) è sempre la PRIMA chiamata della sequenza, non per una particolarità della coppia
BTC-USDT in sé. Campione troppo piccolo (4) per affermarlo con sicurezza.

**Opzione aggiuntiva non implementata, per completezza**: oltre al retry già in coda (§3), si
potrebbe anche alzare il timeout esplicito di `ccxt.okx()` (oggi il default della libreria,
10s) — ridurrebbe ulteriormente la frequenza di `RequestTimeout`, in modo complementare al
retry, non alternativo. Non implementata in questa sessione (non richiesta), segnalata come
possibile follow-up.

## 3. Fix progettato (repo-only, TDD, commit `33a477c`)

Due meccanismi di resilienza distinti, nessuno dei due tocca la garanzia di sicurezza esistente
(nessuno snapshot scritto su ciclo fallito, sempre e comunque — verificato dal reviewer
indipendente, vedi §4):

- **Retry con backoff lineare intra-ciclo** (`_call_with_retry`, `FETCH_MAX_ATTEMPTS=3`,
  `FETCH_RETRY_BACKOFF_SECONDS=2.0`): le tre chiamate di rete in `run_once` assorbono un blip
  singolo (2s poi 4s di backoff) senza mai emergere come "ciclo fallito" verso `run_loop`.
- **Soglia di fallimenti consecutivi prima dell'alert** (`CONSECUTIVE_FAILURES_BEFORE_ALERT=2`):
  l'alert Telegram scatta solo dopo 2 cicli consecutivi falliti (30 minuti), non al primo — ma
  una volta raggiunta la soglia, alerta su OGNI ciclo ancora fallito, mai un secondo silenzio
  prolungato (stesso principio già imparato con `WiringSequencer` in questa sessione: un design
  che tace durante un problema prolungato è un bug, non un pregio). Il contatore si azzera ad
  ogni ciclo riuscito.

Margine rispetto alla soglia di staleness del wiring-loop (60 minuti = 4 cicli, verificata dal
reviewer come del tutto indipendente da quando/se un alert viene inviato): N=2 consuma 30 minuti
di silenzio, lasciando 30 minuti di margine prima che la staleness reale scatti — la soglia di
staleness resta il fail-safe di ultima istanza, invariata.

TDD: 217/217 test locali verdi, ruff pulito.

## 4. Review indipendente (Opus, contesto fresco)

Dispatchata sul commit `33a477c`. **Verdetto: GO** per la coda "deploy solo post-gate 21/07".
Nessun bloccante, nessuna violazione del muro Binario A/B (il fix non tocca nessuna unit systemd
né comportamento runtime deployato — `main()` chiama `run_loop` senza i nuovi parametri, quindi
il deploy attuale resta invariato). Confermato esplicitamente: `store.write(snapshot)` è l'ultima
istruzione di `run_once`, dopo tutti i fetch e tutti gli `update()` di stato — nessuno snapshot
parziale in alcun percorso, con o senza retry.

**1 nota minore, preesistente (non introdotta da questo commit) — CHIUSA il 2026-07-09, stesso
giorno, commit `05d1e02` + `1ecd371`**: se `healthcheck_sink.ping()` falliva DOPO che `run_once`
aveva già scritto con successo lo snapshot, il ciclo veniva comunque classificato come "misura
fallita" nell'except esterno di `run_loop`, e — a soglia raggiunta — l'alert avrebbe detto "ciclo
di misura fallito... nessuno snapshot scritto", entrambe le affermazioni false in quel caso
specifico. Fix: `try/except/else` separa esplicitamente le due cause — l'`except` cattura SOLO un
fallimento di `run_once`, l'`else` (eseguito solo se la misura è riuscita) gestisce il ping col
proprio try/except locale, senza mai contaminare `consecutive_failures`. TDD con due nuovi test;
un secondo giro di review indipendente ha inizialmente trovato che il primo tentativo del test di
non-contaminazione non dimostrava nulla (il fake exchange falliva solo un tentativo, assorbito
dal retry intra-ciclo — corretto per fallire tutti e `FETCH_MAX_ATTEMPTS` i tentativi, con
un'assertion esplicita sul conteggio chiamate a prova che il fallimento simulato fosse reale).
**Verdetto finale re-review: GO, nota chiusa a livello di codice.**

## 5. Stato: IN CODA

**Non deployato. Non deployabile prima del 2026-07-21.** Il fix esiste solo in questo repo — il
processo sul VPS continua a girare col codice precedente (senza retry, senza soglia) finché non
ci sarà un deploy esplicito, autorizzato da Andrea, dopo il gate. In coda insieme allo
schema-prep vol numerica (`docs/m2-shadow-dashboard-vol-schema-prep-report-2026-07-07.md`) — un
unico deploy post-gate porterà entrambi.

## 6. File toccati in questa sessione (repo)

- `src/components/regime_daemon.py`, `tests/components/test_regime_daemon.py`.
- Script diagnostico `okx_network_probe.py` — **non nel repo**, vive solo sul VPS in
  `/home/freqbot/diag-okx-network-2026-07-09/`, mai importato da/toccante i processi di
  produzione, cancellabile a fine diagnosi.
- Questo documento.

## 7. Commit

- `33a477c` — feat: retry backoff + soglia alert su fallimenti consecutivi (TDD).
- `05d1e02` — fix: ping healthcheck fallito non è un ciclo di misura fallito (TDD).
- `1ecd371` — test: correzione fake exchange, fallimento reale non assorbito dal retry.

Tutti pushati su `master`.
