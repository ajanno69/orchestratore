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

**Ground truth di Andrea (2026-07-06, dopo la prima consegna di questa analisi): GridBTC è stato
SOLO shadow, mai capitale esposto, né allora né ora.** Questo risolve in via definitiva
l'incertezza lasciata aperta nella prima versione di questo documento (che non poteva escludere
che GridBTC girasse fuori da questo repo con capitale reale, senza tracciamento in
`docker-compose.yml`). Non è più un'ipotesi da verificare: non c'è nessun bot GridBTC live da
proteggere, oggi. Vedi anche l'emendamento corrispondente in
`docs/ADR-037-wiring-regime-layer-capitale.md` §5-6.

### Conclusione del finding

Il guard descritto (HAR-RV + VPVR + Anchored VWAP, "impulse detector", promosso HARD il
2026-05-16) **non esiste come codice localizzabile nel repository attuale**, e la stringa
`bot_grid_btc`/"grid" **non è mai comparsa nel file `docker-compose.yml` in tutta la storia git
tracciata**. La frase nel `DECOMMISSION-2026-07.md` del 2026-07-05 che dichiara di aver
"verificato" la presenza di `bot_grid_btc` in quel file è **fattualmente non riscontrabile** contro
il contenuto reale del file alla stessa data — non è chiaro se la verifica sia stata fatta su un
file diverso, se il servizio fosse gestito fuori da questo docker-compose (es. processo manuale
sul VPS mai committato), o se l'affermazione fosse semplicemente imprecisa.

**Aggiornamento post ground-truth:** la domanda "quale di queste ipotesi è corretta" è stata
risolta direttamente da Andrea (non deducibile dal solo repo): GridBTC non ha mai avuto capitale
esposto, in nessun momento — quindi non gira, e non è mai girato, "fuori da questo docker-compose
con capitale reale". L'affermazione nel `DECOMMISSION-2026-07.md` resta comunque un'imprecisione
documentale reale (vedi coda forense sotto), solo non più un mistero operativo urgente.

**Implicazione per il gate:** non è possibile scrivere una raccomandazione definitiva
stop-vs-chiusura ancorata al comportamento di un guard che non esiste. Le sezioni 1-4 sotto
rispondono comunque alle domande poste, come **analisi condizionale e generale** (valida per
qualunque bot a griglia su Freqtrade in high-vol, applicabile quando/se GridBTC verrà
ricostruito), non come lettura di un meccanismo verificato riga per riga. La raccomandazione
finale (§5) riflette questa distinzione esplicitamente.

### Coda forense (2026-07-06): origine dell'affermazione non verificabile in DECOMMISSION-2026-07.md

Su richiesta di Andrea, verifica di igiene documentale (non più urgenza di capitale, essendo
chiarito che GridBTC non ha mai avuto capitale esposto) su dove e quando è nata l'affermazione
"verificato che `docker-compose.yml` avesse ancora la definizione di `bot_grid_btc`... intatta".

**Comando eseguito:**
```
cd D:/Claude/crypto-agent && git log --follow --oneline -- infra/docker-compose.yml
cd D:/Claude/crypto-agent && git log --follow --oneline -- docs/DECOMMISSION-2026-07.md
```

**Output (docker-compose.yml, 17 commit dall'inizio repo, mai rinominato):**
```
885a100 fix(infra): pin cloudflared to 2025.8.1 (2026.3.0 causes tunnel-wide 502)
3de2e2f fix(infra): cloudflared --protocol http2 (avoid QUIC UDP buffer drops causing 502)
76a79f4 fix(infra): cloudflared --token via compose substitution + infra/.env symlink
e68ca7d fix(infra): cloudflared token via shell wrapper (compose substitution fails)
bcef787 fix(infra): cloudflared uses --token CLI flag (2026.3.0 ignores env var)
6a9c8d5 fix(infra): persist user_data:ro mount on agent service
ce50cbb chore(lint): fix 237 ruff warnings + tighten config
9533808 feat(bench): RsiBbHybrid15m-TP15 — A/B benchmark wider TP per letitride sim
d0d012e feat(infra): add 5 new bot configs (Donch1h, KP-15m, KP-B, MLE-4h, RsiBb-15m) + claude_settings + Dockerfile updates
d79de2a feat(sprint1): drift monitor (river ADWIN) + state volume regime_detector
4f81b2d feat(sprint1): RegimeDetector AI service — LightGBM 8-class + FastAPI
a9d5323 feat(sprint0): bridge orchestrator + gate eval + deploy scripts + docker services + bug fix hyperopt cleanup
e44bb26 feat(infra): Postgres 16 + schema-per-bot + notify_user.sh
3f906f1 feat: migrate agent to Claude CLI OAuth (Max plan) + fix APScheduler bug
e5d16d4 Save BotSnapshot on each cycle, fix VPS health via docker.sock, drop SSH dependency
b28fdd3 Add host-gateway for Freqtrade connectivity from Docker containers
c5aee76 Fix Docker build errors, TypeScript config, and optional Kraken credentials
4a3b7ad Initial scaffold: agent SDK + React dashboard + Docker infra
```
Identico all'elenco ottenuto con `git log` semplice (§0.8) — conferma che il file non è mai stato
rinominato/spostato: la sua storia è completa, non tronca per un rename non seguito.

**Output (DECOMMISSION-2026-07.md, 2 commit):**
```
0d2afde chore(fleet): final decommission pass — funding-harvester canary, mft_engine, container prune
9e06127 chore(fleet): park dry-run bots and stop dashboard/tunnel for ADR-036 decommission
```

Verificato il contenuto di entrambi i commit (`git show <hash>`): il primo commit (`9e06127`,
2026-07-05 18:25:56+02:00) **non contiene nessuna menzione di "grid"**, in nessuna forma, né nel
messaggio né nel diff. L'affermazione "verificato che `bot_grid_btc`... intatta" compare
**esclusivamente** nel secondo commit (`0d2afde`, 2026-07-05 19:27:07+02:00, il commit finale di
decommissioning), sia nel messaggio di commit sia nel corpo del documento aggiunto in quel diff.

**Conclusione della coda forense:** l'affermazione è stata scritta in un'unica occasione precisa
(quel commit), senza un comando/output allegato che la sostenga — e il contenuto reale del file
che dichiara di aver verificato (`docker-compose.yml`) non la conferma (§0.8). Non è possibile,
da qui, distinguere se sia stato un controllo fatto su un file/percorso diverso da quello citato,
o un'affermazione scritta senza eseguire davvero il comando di verifica — ma la distinzione non
cambia la regola che ne esce.

**Regola che ne esce (da applicare anche in questo repo, non solo raccomandata a crypto-agent):**
ogni affermazione "verificato X" in un documento deve riportare il comando eseguito e l'output
osservato, non solo la conclusione in prosa. Una frase come "verificato che il file contenesse Y"
senza il comando+output allegato non è distinguibile, a posteriori, da un'affermazione mai
verificata — esattamente il problema che questa coda forense ha dovuto ricostruire a ritroso
invece di poter semplicemente leggere.

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

## 5. Raccomandazione finale — RINVIATA al gate di promozione di GridBTC, non più sospesa

**Aggiornamento 2026-07-06 (ground truth Andrea):** GridBTC è stato SOLO shadow, mai capitale
esposto, né allora né ora. Questo chiude la domanda preliminare che la prima versione di questo
documento lasciava aperta ("GridBTC è oggi live con capitale esposto, fuori da questo repo?" —
risposta: no, e non lo è mai stato). Non è più un caso di "raccomandazione sospesa in attesa di
un fatto ignoto": è un caso di **raccomandazione non ancora applicabile, perché non esiste ancora
un bot da proteggere.**

**La raccomandazione stop-vs-chiusura non viene quindi finalizzata qui — viene RINVIATA al gate di
promozione di GridBTC** (`docs/m2-reactivation-gates.md`, protocollo unificato con l'harvester:
shadow → criteri di promozione espliciti → G3, vedi ADR-037 §6 emendato). Quando/se GridBTC verrà
ricostruito e rientrerà in shadow, quel momento — non questa consegna — è il punto naturale per
riprendere l'analisi condizionale già fatta qui (§1-4) e trasformarla in raccomandazione
definitiva, verificando allora se esiste un guard reale con cui coordinarsi (§0: oggi non esiste,
ma "oggi" è vero solo finché GridBTC non viene ricostruito — il gate di promozione deve riverificarlo
da capo al momento, non fidarsi di questo documento come se fosse ancora attuale a distanza di
mesi).

**Raccomandazione condizionata già disponibile per quel momento futuro** (base per il gate di
promozione, non decisione presa ora): **chiusura ordinata (`CLOSE_GRID_ORDERLY` via
`/api/v1/forceexit`)**, non stop-nuovi-ordini. Motivazione: il failure mode specifico della griglia
(§2) è che l'inventario direzionale si accumula proprio nella fase che precede il trigger di
high-vol (l'EWMA a span=32 non è istantanea), quindi al momento in cui `btc_high_vol` diventa
`True` è probabile che l'esposizione da proteggere sia già sostanziale, non marginale — il rischio
di lasciarla aperta (stop-nuovi-ordini) supera, nel giudizio di questa analisi, il rischio di
realizzare la perdita ora (chiusura). Coerente con il principio ADR-036 di preferire un esito noto
e limitato a un'esposizione aperta e non quantificata durante un evento di durata incerta.

Questa resta **una raccomandazione, non una decisione** — la scelta finale del valore
`GridBtcHighVolAction` è riservata al gate di promozione di GridBTC (non più a un ipotetico
"checkpoint wiring pre-deploy" pensato per un sistema già live, che non si applica: vedi ADR-037
§5-6 emendato), quando quel gate esisterà davvero da attraversare.
