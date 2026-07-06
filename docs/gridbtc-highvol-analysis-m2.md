# Analisi GridBTC in high-vol BTC — Task 2 piano M2

**Data:** 2026-07-06
**Ambito:** Task 2 di `docs/superpowers/plans/2026-07-06-m2-capital-reactivation-wiring.md`, gate
formale bloccante dichiarato in ADR-037 §5: "Il Task 2 del piano M2 **deve** iniziare con la
lettura di quel codice (non di questo ADR) prima di raccomandare qualunque azione".
**Metodo:** sola lettura di `D:\Claude\crypto-agent` (repo isolato, nessuna modifica, nessun
commit lì — vedi CLAUDE.md globale). Nessuna azione eseguita, nessuna chiave toccata.
**HEAD crypto-agent al momento dell'analisi:** `0d2afde` (2026-07-05 19:27:07+02:00,
"chore(fleet): final decommission pass").

---

## 0. Finding primario (precede le 4 domande): il guard descritto non è localizzabile

Il gate impone di iniziare dichiarando cosa il guard fa **oggi**, con citazione file:riga del
codice reale — non del changelog. Questo è esattamente il punto in cui il gate ha funzionato
come doveva: **il guard non è risultato localizzabile nel codice attuale**, nonostante ricerca
esaustiva. Di seguito la traccia di evidenza completa, perché questo non è un "non ho trovato
niente" pigro ma una conclusione basata su verifica multipla e incrociata.

### Cosa dice la documentazione storica

- `past project/02_crypto-agent.md:5`: *"Stato (2026-05-19, ultimo handoff): HEAD `eda33034`,
  fleet ridotto, GridBTC promosso HARD..."*
- `past project/02_crypto-agent.md:77-81`: cronologia — 2026-05-10 "Grid BTC PF 1.99 deployed
  only winner"; 2026-05-13/14 "GridBTC guard SHADOW + impulse detector"; 2026-05-16 "GridBTC guard
  PROMOTED shadow→HARD, v3 FREEZED"; 2026-05-19 "Adaptive Range System (HAR-RV + VPVR + Anchored
  VWAP) per GridBTC".
- `crypto-agent/docs/DECOMMISSION-2026-07.md:194,254`: scritto il 2026-07-05 (un giorno prima di
  questa analisi), afferma esplicitamente *"Verificato PRIMA del prune che `docker-compose.yml`
  avesse ancora la definizione di `bot_grid_btc`... intatta"* e *"Bot ancora presenti in
  `docker-compose.yml` (es. GridBTC) restano ricreabili con `docker compose up -d <servizio>`."*

### Cosa risulta dalla verifica diretta sul codice (oggi, HEAD `0d2afde`)

1. **`infra/docker-compose.yml`** (484 righe, letto per intero): 14 servizi bot definiti
   (`bot_trendlong`, `bot_trendshort`, `bot_donchianshort_1h`, `bot_keltnerpullback_15m`,
   `bot_rsibb_15m`, `bot_rsibb_15m_tp15`, `bot_meanrev`, `bot_volbreak`, `bot_mlensemble`,
   `bot_trendlong_b`, `bot_keltnerpullback_b`, `bot_meanrev_b`, `bot_mlensemble_b`,
   `bot_mlensemble_4h`). **Nessun `bot_grid_btc`, nessuna riga contenente "grid" (case-insensitive)
   in tutto il file.**
2. **`infra/docker-compose.backtest.yml`**: stessa verifica, zero occorrenze di "grid".
3. **`infra/bots/*.json`** (14 file di config, uno per bot orchestrato): nessun file con "grid" nel
   nome; lista completa verificata via `ls`.
4. **`user_data/strategies/`** e **`strategies/`** (tutte le strategie Freqtrade presenti,
   elencate per intero): nessun file con "Grid" nel nome. Nomi presenti: BandtasticShortFade,
   BbandRsi, DonchianBreakdownShort1h, KeltnerPullback(15m), MLEnsemble(4h), MeanReversionRange,
   RsiBbHybrid15m(_TP15), TrendCapture(Long/Short), VolatilityBreakout(V2), SimpleArm5min,
   TrendBerni(V2/V3), TrendRiderV1AI.
5. **Ricerca per tecnica** (`HAR-RV`, `VPVR`, `Anchored VWAP`, `impulse detector`, `adaptive
   range`) su tutto il repo (`agent/` + intero albero, esclusi venv): **zero occorrenze**.
6. **`agent/v2/risk/engine.py`** (156 righe, letto per intero): scaffold "Phase 6",
   `RiskEngine.evaluate()` solleva `NotImplementedError`; `shadow_evaluate()` esegue solo check
   generici (`operating_state`, `risk_per_trade_pct`, `daily_loss_limit_pct`, `cost_ratio`) e
   **non veta nulla** — è dichiarato parallel-testing, non controllo. `RISK_LIMITS` non contiene
   nessun limite specifico per GridBTC.
7. **`agent/v2/shadow.py`** (251 righe, letto per intero): `ShadowEmitter`, triplo flag di gating,
   dichiara esplicitamente *"No consumer reads experience.shadow_events to alter runtime"* — v2 è
   osservazionale, non live.
8. **Storia git di `docker-compose.yml`** (`git log --all -- infra/docker-compose.yml`, tutti i
   commit dall'inizio repo): nessun commit ha mai introdotto la stringa "grid" nel contenuto del
   file. **`git log -S"grid" --all`** su tutto il repo: le uniche occorrenze sono in messaggi di
   commit e nel testo prosa di `DECOMMISSION-2026-07.md` — mai nel contenuto di un file di config
   o codice.
9. **`docs/park/*.md`** (doc di parcheggio per bot dismessi, es. `bot_bonk_btc_dca-2026-07.md`,
   `bot_dca_rotator-2026-07.md`): nessun equivalente per GridBTC.

### Conclusione del finding

Il guard descritto (HAR-RV + VPVR + Anchored VWAP, "impulse detector", promosso HARD il
2026-05-16) **non esiste come codice localizzabile nel repository attuale**, e la stringa
`bot_grid_btc`/"grid" **non è mai comparsa nel file `docker-compose.yml` in tutta la storia git
tracciata**. La frase nel `DECOMMISSION-2026-07.md` del 2026-07-05 che dichiara di aver
"verificato" la presenza di `bot_grid_btc` in quel file è **fattualmente non riscontrabile** contro
il contenuto reale del file alla stessa data — non è chiaro se la verifica sia stata fatta su un
file diverso, se il servizio fosse gestito fuori da questo docker-compose (es. processo manuale
sul VPS mai committato), o se l'affermazione fosse semplicemente imprecisa.

**Non è possibile determinare, da questo repo, quale di queste ipotesi sia corretta.** Questo
supera lo scope di un'analisi in sola lettura sul codice: è una domanda sullo stato operativo reale
del VPS Contabo, che solo Andrea può risolvere (es. verificando direttamente `docker ps -a` sul VPS,
o la sua memoria di dove gira/girava GridBTC se non in questo docker-compose).

**Implicazione diretta per il gate:** non posso scrivere una raccomandazione definitiva
stop-vs-chiusura ancorata al comportamento di un guard che non ho potuto leggere. Le sezioni 1-4
sotto rispondono comunque alle domande poste, ma come **analisi condizionale e generale** (valida
per qualunque bot a griglia su Freqtrade in high-vol), non come lettura di un meccanismo verificato
riga per riga. La raccomandazione finale (§5) riflette questa distinzione esplicitamente.

---

## 1. Inventario delle protezioni esistenti

**Nessuna protezione specifica per GridBTC è stata trovata nel codice attuale** (vedi §0).

Ciò che *esiste* nel repo, ma non è specifico di GridBTC e non è live:

- `agent/v2/risk/engine.py`: limiti generici (`max_directional_bias: 0.70`, `risk_per_trade_pct`,
  `daily_loss_limit_pct`, `cost_ratio`) — scaffold non wired, non veta ordini.
- `agent/v2/orchestrator_hooks.py`: `kill_switch_event_from_orchestrator` definisce trigger
  generici di kill-switch (`MANUAL_USER`, `DAILY_LOSS_LIMIT`, `RECONCILIATION_DRIFT_CRITICAL`,
  `EXCHANGE_API_DOWN`, `REGIME_DETECTOR_DOWN`, `DATABASE_UNREACHABLE`,
  `CONNECTIVITY_DEGRADED`, `FLASH_CRASH_DETECTED`, `NEWS_GUARD_EXTREME`, `AGENT_PROCESS_CRASH`),
  azione di default `["STOP_NEW_ENTRIES", "ALERT_USER_TELEGRAM"]`, `auto_recovery: {after_seconds:
  0, requires_manual_clearance: True}` — pattern di design utile (fail-safe "stop-and-alert, mai
  ripresa automatica"), ma è infrastruttura v2/shadow, **non attiva su nessun bot live oggi**
  (confermato da `shadow.py`, §0.7).

**Conseguenza per il wiring M2:** non c'è, ad oggi, nessuna protezione esistente su GridBTC con cui
il nuovo comando di regime (`GridBtcCommand`) possa entrare in conflitto o duplicarsi — perché non
c'è nessuna protezione esistente da leggere. Questo elimina il rischio (b) dichiarato in
ADR-037 §5 ("il nuovo segnale e il guard esistente danno indicazioni contrastanti"), ma non per il
motivo sperato: non perché i due sistemi siano stati progettati per coesistere, ma perché il
secondo sistema non risulta esistere. Resta comunque aperto il rischio (a) — se GridBTC gira con un
meccanismo di protezione non tracciato in questo repo (es. script manuale sul VPS), il wiring
potrebbe comunque duplicarlo o confliggere con qualcosa che io non posso vedere.

## 2. Stop-nuovi-ordini vs chiusura ordinata — analisi del failure mode

Analisi generale per qualunque bot a griglia su Freqtrade in high-vol (non ancorata al codice
specifico di GridBTC, per il motivo dichiarato in §0).

**Il failure mode specifico è reale e va preso sul serio anche senza aver letto codice
GridBTC-specifico**: una griglia compra a intervalli di prezzo decrescenti per costruzione. In un
trend direzionale forte (esattamente ciò che high-vol spesso accompagna, anche se non lo implica
sempre — vol alta può essere anche laterale/whipsaw), la griglia accumula inventario long mentre il
prezzo scende, con ogni livello aggiuntivo che aumenta l'esposizione direzionale netta.

- **Stop-nuovi-ordini (`stopbuy`/equivalente)**: blocca l'apertura di nuovi livelli di griglia, ma
  **le posizioni già aperte restano esposte** senza alcuna azione. Se il trend continua, la perdita
  mark-to-market sull'inventario esistente continua a crescere, non protetta. Il rischio scelto qui
  è: *"accetto l'esposizione direzionale residua sull'inventario già aperto, in cambio di non
  realizzare una perdita che potrebbe essere temporanea (il prezzo potrebbe tornare nel range e la
  griglia richiudersi in profitto)."*
- **Chiusura ordinata (`forceexit` su tutte le posizioni del bot)**: realizza immediatamente la
  perdita mark-to-market sull'intero inventario accumulato, ma **azzera il rischio direzionale**
  da quel momento in poi. Il rischio scelto qui è l'opposto: *"preferisco una perdita certa e
  limitata ora, a un'esposizione aperta e potenzialmente crescente durante un evento di cui non
  conosco la durata."*

**Non esiste una risposta context-free.** La scelta dipende da un fattore che questa analisi non
può determinare da sola: **quanto è già esposta la griglia nel momento in cui scatta
`btc_high_vol=True`.** Se il regime layer rileva l'high-vol *presto* nel movimento (soglie M1.5
calibrate su EWMA reattiva, span=32 ≈ mezza vita ~11 giorni — non istantanea), è plausibile che
l'inventario accumulato al momento del trigger sia già sostanziale prima che il segnale scatti,
il che pesa a favore della chiusura (l'esposizione da proteggere è già consistente, non marginale).

## 3. Interfaccia concreta: comandi reali Freqtrade

Il codice del repo (`agent/v2/orchestrator_hooks.py`) già interagisce con l'API REST Freqtrade
reale (legge `/api/v1/status` per i campi trade — pair, is_short, amount, open_rate, profit_abs,
ecc., vedi `position_state_from_freqtrade_trades`), quindi il pattern di comunicazione via API è
già in uso in questo codebase, non è un'invenzione di questa analisi. Freqtrade espone
nativamente (documentazione REST API Freqtrade) i meccanismi seguenti, che mappano 1:1 sui comandi
già definiti in `src/components/regime_wiring.py`:

- **`HIGH_VOL_STOP_NEW_ORDERS` → `POST /api/v1/stopbuy`** (in versioni più recenti di Freqtrade,
  l'endpoint equivalente è `/api/v1/stopentry`): blocca nuove entry, il bot continua a girare e a
  gestire le posizioni aperte (exit, stop-loss, trailing) normalmente. Reversibile con
  `/api/v1/reload_config` o riavvio.
- **`HIGH_VOL_CLOSE_GRID_ORDERLY` → `POST /api/v1/forceexit` con `tradeid: "all"`** (o iterando i
  singoli trade id se serve un log per-trade): chiude tutte le posizioni aperte al prezzo di
  mercato corrente, ordine per ordine (non un singolo blocco, quindi con slippage per-trade ma
  senza dover cancellare manualmente ogni ordine griglia). Dopo la chiusura, il bot resta in piedi
  con `stopbuy` implicitamente utile per evitare che riapra subito una nuova griglia.
- **Non usare `/api/v1/stop`** (stop totale del processo, interrompe anche il polling dei
  candle/websocket) per nessuno dei due comandi: è più aggressivo del necessario e complica la
  ripresa (richiede `/api/v1/start` esplicito, non solo un cambio di flag). Riservare `/stop` a uno
  scenario di guasto/kill-switch più severo, non al wiring di regime ordinario.

Entrambi i comandi sono chiamate HTTP autenticate verso l'API Freqtrade del bot — **fuori scope del
modulo `regime_wiring` (che produce solo dati/enum, vedi ADR-037 §7)**: l'executor che traduce
`GridBtcCommand` in una chiamata HTTP reale è un componente successivo, non ancora costruito, e
dovrà gestire le credenziali API Freqtrade con lo stesso principio già stabilito (mai in
repo/log, creazione manuale di Andrea).

## 4. Rientro in low-vol: automatico o manuale

**Raccomandazione: manuale**, in accordo con l'inclinazione già dichiarata da Andrea nel messaggio
di autorizzazione del Task 2, e coerente con il principio già stabilito in ADR-036/037: nessuna
decisione che tocca capitale viene presa senza un umano nel loop.

Motivazione aggiuntiva specifica a GridBTC: una ripresa automatica alla prima transizione
`btc_high_vol: True → False` si fiderebbe ciecamente dell'isteresi del regime layer come unico
arbitro del "è sicuro ripartire" — ma l'isteresi (M1.5) è stata calibrata per **evitare flip-flop
sulla soglia**, non per certificare che le condizioni di mercato post-evento siano tornate
compatibili con una griglia (es. uno spread ancora anomalo, una liquidità ancora ridotta, o un
nuovo livello di prezzo strutturalmente diverso da quello in cui la griglia era stata dimensionata
originariamente non sono cose che `vol_state` osserva). Una ripresa automatica sarebbe esattamente
il tipo di "scommessa silenziosa" che ADR-036 vieta per il regime layer. Ripresa manuale =
un'operazione umana esplicita (riattivare `stopbuy` o ricreare la griglia via
`docker compose up -d bot_grid_btc` se chiusa), preceduta da verifica dello stato di mercato, non
solo dello stato del flag.

## 5. Raccomandazione finale

**La raccomandazione stop-vs-chiusura non può essere finalizzata da questa analisi**, per il
motivo dichiarato in §0: il gate richiede di ancorarla al comportamento del guard esistente di
GridBTC, e quel guard non è risultato localizzabile nel codice — quindi non è verificabile se
GridBTC sia oggi effettivamente un servizio live con capitale esposto (come assunto da ADR-037 §5-6
sulla base del changelog storico), oppure se sia stato dismesso/mai deployato come tale nel
docker-compose tracciato, oppure se giri fuori da questo repo in un modo che io non posso vedere in
sola lettura.

**Prima del checkpoint 2 ("wiring implementato pre-deploy"), serve una conferma esplicita di
Andrea su un punto preliminare a qualunque scelta stop-vs-chiusura:** GridBTC è oggi effettivamente
in esecuzione con capitale esposto su Kraken (fuori da questo repo, o altrove), sì o no? Questa non
è una domanda che questa analisi può rispondere da sola.

**Raccomandazione condizionata** (valida nell'ipotesi che GridBTC sia confermato live con
inventario potenzialmente esposto al momento del trigger): **chiusura ordinata
(`CLOSE_GRID_ORDERLY` via `/api/v1/forceexit`)**, non stop-nuovi-ordini. Motivazione: il failure
mode specifico della griglia (§2) è che l'inventario direzionale si accumula proprio nella fase
che precede il trigger di high-vol (l'EWMA a span=32 non è istantanea), quindi al momento in cui
`btc_high_vol` diventa `True` è probabile che l'esposizione da proteggere sia già sostanziale, non
marginale — il rischio di lasciarla aperta (stop-nuovi-ordini) supera, nel giudizio di questa
analisi, il rischio di realizzare la perdita ora (chiusura). Coerente con il principio ADR-036 di
preferire un esito noto e limitato a un'esposizione aperta e non quantificata durante un evento di
durata incerta.

Questa resta comunque **una raccomandazione, non una decisione** — la scelta finale del valore
`GridBtcHighVolAction` è riservata al checkpoint, come da piano, e ora è ulteriormente condizionata
alla risposta di Andrea sul punto preliminare sopra.
