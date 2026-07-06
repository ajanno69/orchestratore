# ADR-037 — Wiring del regime layer a capitale (harvester ETH + GridBTC)

**Data:** 2026-07-06
**Stato:** ACCEPTED (2026-07-06) — piano M2 approvato da Andrea, checkpoint 1 ("piano completo")
superato dopo chiusura del punto sulla convenzione temporale UTC (vedi §3) e formalizzazione del
gate GridBTC (vedi piano, Task 2). Vedi `docs/superpowers/plans/2026-07-06-m2-capital-reactivation-wiring.md`.
**Ambito:** M2. Questo ADR è SOLO decisione architetturale — nessuna riga di codice, nessuna chiave,
nessun deploy viene eseguito con questo documento. L'implementazione (Task 1 del piano M2) parte
subito dopo, nel repo, con lo stesso rigore TDD del resto del progetto.
**Precondizione:** ADR-036 (ACCEPTED 2026-07-05, congelato), M1.5 (soglie vol derivate, vedi
`docs/regime-threshold-provenance-2026-07.md`).

**Emendamento 2026-07-06 (ground truth Andrea, dopo Task 2):** §5 e §6 di questo documento
affermavano che GridBTC fosse "già promosso HARD" con capitale reale esposto (2026-05-16, secondo
`past project/02_crypto-agent.md`). Ground truth di Andrea: **GridBTC è stato SOLO shadow, mai
capitale esposto, né allora né ora.** Questo è coerente con il finding forense del Task 2
(`docs/gridbtc-highvol-analysis-m2.md`): nessun `bot_grid_btc` è mai comparso nel contenuto di
`docker-compose.yml` in tutta la storia tracciata del repo crypto-agent. §5 e §6 sono riscritti di
conseguenza: non esiste una "riattivazione" di GridBTC da pianificare, esiste una **prima
attivazione**, senza nessuna eredità di fiducia dallo stato shadow pregresso — stesso protocollo
dell'harvester (shadow → criteri di promozione espliciti → gate G3), non un protocollo diverso e
più permissivo giustificato da un "già in produzione" che non è mai stato vero.

---

## 1. Perché questo ADR

ADR-036 ha stabilito il muro tra Binario A (capitale) e Binario B (ricerca), e ha dichiarato che il
regime layer v0 è "lettura del presente, non scommessa" — cioè misura uno stato, non decide
un'azione. M1/M1.5 hanno costruito e calibrato quella misura (stato di vol EWMA con isteresi,
soglie derivate da storia reale). **Questo ADR decide, per la prima volta, COSA succede quando
quello stato viene letto da un sistema che tocca capitale reale** — il momento esatto in cui il
muro tra "misura" e "azione" viene attraversato, e quindi il punto più delicato dell'intero
progetto dal punto di vista di governance.

## 2. Decisione: wiring per-asset, nessun segnale combinato

- `regime.store.RegimeSnapshot.eth_high_vol` + `eth_harvester_on` → comandi per l'harvester
  (funding-harvester, OKX ETH).
- `regime.store.RegimeSnapshot.btc_high_vol` → comandi per GridBTC (Kraken).
- **Nessuna combinazione BTC+ETH.** Ogni asset legge solo il proprio stato. Questa non è una
  scelta di comodo: è la stessa decisione già presa esplicitamente durante M1.5 (nessun segnale
  combinato nella derivazione delle soglie) estesa al wiring — un'eventuale combinazione futura
  resta una decisione di design separata, con il proprio ADR, mai un default implicito.

## 3. Fail-safe del wiring: assenza/staleness dello snapshot

**Su snapshot assente o stantio: NESSUNA azione automatica.** Il wiring non decide MAI di
modificare una posizione, un ordine, o lo stato on/off di un componente sulla base di dati mancanti
o vecchi. Il comportamento è sempre: **posizione mantenuta così com'è + alert esplicito + decisione
umana**. Questo vale sia per "nessuno snapshot mai scritto" (`RegimeStateStore.read()` restituisce
`None`) sia per "snapshot presente ma più vecchio della soglia di staleness" (soglia esatta da
definire e testare in Task 1 del piano, non in questo ADR).

**Perché non un default ragionevole invece di "nessuna azione":** perché ogni default automatico
su dati mancanti è, per costruzione, una scommessa su cosa sta succedendo nel mondo reale mentre il
regime layer è cieco — esattamente il tipo di comportamento che ADR-036 vieta per il regime layer
("lettura del presente, non scommessa"). Un sistema che non sa se BTC è in high-vol non ha il
diritto di decidere che probabilmente non lo è (o che probabilmente lo è): deve fermarsi e chiedere.

**Convenzione temporale esplicita per il calcolo di staleness (chiusura checkpoint 1, decisione
definitiva, non riaprire):** ogni confronto di età tra "ora" e il timestamp dello snapshot è in
UTC. Un timestamp con offset esplicito va convertito con `astimezone(timezone.utc)` PRIMA di uno
strip dell'offset — mai un `replace(tzinfo=None)` secco, che ignorerebbe silenziosamente l'offset e
sbaglierebbe l'età esattamente dell'ampiezza dell'offset scartato (un `now` in fuso CEST scambiato
per UTC farebbe apparire uno snapshot appena scritto stantio di ~2 ore). "Ora" deve essere
`datetime.now(timezone.utc)` o un naive-UTC dichiarato esplicitamente per convenzione — **mai
`datetime.now()` locale nel path di staleness**. Questa non è un dettaglio implementativo: un
calcolo di staleness sbagliato per un bug di fuso orario produrrebbe silenziosamente l'esatto
comportamento che questo ADR vieta (un'azione — o una non-azione — basata su un giudizio di
freschezza dei dati che è semplicemente falso).

## 4. Harvester ETH in high-vol: modalità difensiva, non chiusura

Quando `eth_high_vol=True` E l'harvester è già attivo (`eth_harvester_on=True`, il segnale di
funding esistente — indipendente dalla volatilità):

- **Blocco nuovi ingressi e scale-up.** Nessuna nuova gamba delta-neutral aperta, nessun
  incremento di size su posizioni esistenti, finché `eth_high_vol` non torna `False`.
- **Check margin buffer con soglia di rabbocco esplicita** (valore esatto da definire in Task 1
  del piano, con test dedicato) — se il buffer di margine scende sotto soglia durante high-vol,
  alert immediato, MAI un rabbocco automatico di capitale (il rabbocco di margine è un'azione che
  tocca capitale, quindi richiede conferma umana, coerente con l'intero impianto di ADR-036).
- **Alert su ogni transizione verso high-vol mentre l'harvester è attivo** — non silenzioso, non
  solo loggato.
- **NESSUNA chiusura automatica delle gambe.** La chiusura resta esclusivamente compito del
  kill-switch esistente dell'harvester (`newcrypto.executor.kill_switch`, trigger propri e
  invariati da questo ADR — vedi `D:\Claude\funding-harvester`, non toccato). Il regime layer non
  duplica né sostituisce quel meccanismo: aggiunge prudenza (blocco di nuova esposizione) sopra un
  meccanismo di chiusura che già esiste e ha una propria logica testata.

**Perché difensiva e non chiusura:** l'harvester è delta-neutral per costruzione — una
gamba+controgamba aperta correttamente non ha esposizione direzionale netta a un movimento di
prezzo, quindi high-vol di per sé non è un motivo per chiuderla (a differenza del margin, che la
vol può erodere via requisiti di mantenimento più alti — da cui il check margin buffer sopra). Il
rischio reale in high-vol non è la posizione esistente, è aggiungerne di nuove in un momento di
maggiore incertezza sui costi di esecuzione/slippage.

## 5. GridBTC in high-vol BTC: analisi e raccomandazione (decisione al gate di promozione)

**Emendata 2026-07-06.** Il testo originale di questa sezione affermava che GridBTC avesse "già un
proprio meccanismo di guardia interno, promosso da shadow a HARD il 2026-05-16" e trattava questa
sezione come "l'unica decisione di questo ADR non ancora presa" nel senso di una scelta operativa
su un sistema già live. **Ground truth di Andrea (2026-07-06): falso — GridBTC è stato SOLO
shadow, mai capitale esposto, né allora né ora.** Il finding forense del Task 2
(`docs/gridbtc-highvol-analysis-m2.md`, coda forense) conferma: nessun `bot_grid_btc` è mai
comparso nel contenuto tracciato di `infra/docker-compose.yml` in tutta la storia del repo
crypto-agent (verificato con `git log --follow`), né in nessun altro file di config o codice. La
frase "promosso HARD" vive solo nel changelog narrativo (`past project/02_crypto-agent.md`) e in
un'affermazione non verificata di `docs/DECOMMISSION-2026-07.md` (2026-07-05) — mai nel codice
reale.

**Conseguenza:** non c'è nessun meccanismo di guardia esistente con cui il wiring debba
coordinarsi oggi, perché non c'è nessun GridBTC live oggi. L'analisi comparativa stop-nuovi-ordini
vs chiusura ordinata (Task 2) resta valida come base di ragionamento generale su qualunque bot a
griglia Freqtrade in high-vol, ma la sua raccomandazione è esplicitamente **condizionale**: si
applica quando/se GridBTC verrà ricostruito e rientrerà in shadow, non ora. La scelta finale del
parametro `GridBtcHighVolAction` (Task 1, nessun default cablato) resta riservata a un checkpoint
umano, ma quel checkpoint è ora il **gate di promozione di GridBTC** (§6, `docs/m2-reactivation-gates.md`),
non un "wiring implementato pre-deploy" pensato per un sistema già in produzione.

## 6. Ordine di attivazione (harvester prima; GridBTC: prima attivazione, non riattivazione)

**Emendata 2026-07-06.** Non esiste una "riattivazione" di GridBTC da pianificare: non è mai stato
attivo con capitale, quindi non c'è nulla da riattivare. Esiste una **prima attivazione**, futura e
non ancora programmata, che **non eredita nessuna fiducia dallo stato shadow pregresso** — il fatto
che una versione precedente di GridBTC sia arrivata in shadow nel 2026-05 non esenta la versione
futura dal rifare l'intera trafila da zero. Questo allinea i due componenti a un **protocollo
unico**, non a due protocolli diversi giustificati da uno stato di maturità che per GridBTC non è
mai esistito:

1. **Harvester (gate G3, ETH-only)** — già pendente indipendentemente da questo ADR (vedi
   `past project/03_newcrypto-funding-harvester.md`, gate G3 ≤$100 USDT). Il wiring regime→harvester
   entra come precondizione aggiuntiva al gate esistente, non lo sostituisce.
2. **GridBTC** — dopo l'harvester, non in parallelo, e comunque non prima che esista di nuovo un
   bot GridBTC reale da mettere in shadow (oggi non esiste, vedi Task 2). Quando esisterà, segue
   **esattamente lo stesso protocollo dell'harvester**: shadow → criteri di promozione espliciti →
   gate G3 (vedi `docs/m2-reactivation-gates.md`, protocollo unificato) — non un protocollo a sé
   con una durata di shadow più lunga giustificata da "capitale già esposto", perché quel capitale
   non è mai stato esposto.

## 7. Chiavi

- Creazione manuale di Andrea, permessi minimi (mai withdraw), MAI chiavi vecchie/scadute riusate
  (stesso principio già nel runbook harvester M1, `docs/runbook-riattivazione-harvester.md`).
- Gestione via `sops`/`age` (cifratura at-rest), MAI nel repo, MAI nei log — né in questo repo
  orchestrator né altrove. Il Task 1 del piano non introduce nessun meccanismo di lettura chiavi:
  il wiring produce COMANDI (dati), non esegue lui stesso operazioni autenticate contro Kraken/OKX.

## 8. Conseguenze e rischi residui dichiarati

- **Il wiring aggiunge un nuovo punto di guasto silenzioso possibile**: se lo snapshot di regime
  smette di aggiornarsi senza che nessuno se ne accorga (es. il processo che lo scrive muore), il
  fail-safe di staleness (§3) lo trasforma in "nessuna azione + alert" — ma l'alert stesso dipende
  da un canale di notifica funzionante. Il Task 5 del piano (runbook operativo) deve includere
  esplicitamente "come verifico che il canale di alert stesso sia vivo", non solo "cosa faccio
  quando l'alert scatta".
- **GridBTC §5 resta una decisione aperta anche ad ADR ACCEPTED**: l'accettazione di questo ADR
  approva l'architettura di wiring (fail-safe, muro per-asset, modalità difensiva harvester,
  convenzione temporale) — NON la scelta stop-nuovi-ordini vs chiusura ordinata per GridBTC, che
  resta esplicitamente riservata al gate di promozione di GridBTC (§6, `docs/m2-reactivation-gates.md`),
  condizionale all'esistenza futura di un bot GridBTC reale in shadow.
- **Emendamento 2026-07-06**: il rischio originariamente dichiarato qui ("interazione con il guard
  esistente di GridBTC non ancora verificata a livello di codice") presupponeva che un guard
  esistente ci fosse. Il finding forense del Task 2 mostra che non c'è — quindi il rischio reale
  non è "un'interazione non verificata con un guard esistente", ma un rischio diverso e più
  generale: **una futura ricostruzione di GridBTC potrebbe re-introdurre un guard proprio senza che
  questo ADR/wiring lo sappia.** Il gate di promozione (`docs/m2-reactivation-gates.md`) deve
  quindi verificare l'esistenza di un guard **al momento**, non fidarsi del changelog storico né di
  questo ADR.
- **Igiene documentale (finding del Task 2, coda forense)**: `docs/DECOMMISSION-2026-07.md`
  (crypto-agent, 2026-07-05) conteneva un'affermazione "verificato che X" non riscontrabile contro
  il contenuto reale del file citato. Regola che ne esce, valida anche per questo repo: ogni
  affermazione "verificato X" in un documento deve includere comando eseguito + output osservato,
  mai una prosa non falsificabile.

## 9. Sequenziamento comandi/alert e rate-limit (pre-registrato al checkpoint 2, 2026-07-06)

`resolve_wiring_decision` (Task 1) è puro: nessuna memoria del tick precedente. Un consumatore
esterno (log, canale alert) ha bisogno di un livello stateful sopra — `WiringSequencer`
(`src/components/wiring_sequencer.py`, costruito durante la dimostrazione del checkpoint 2, non
previsto nel piano originale) — che deduplica i comandi ripetuti e rende gli alert
edge-triggered (solo sulle transizioni), con un rate-limit esplicito per non amplificare un layer
di regime instabile (flip-flop a monte).

**Valore del rate-limit APPROVATO qui, pre-registrato, non rimandato al momento del deploy:**
`max_transitions=3` per `window=timedelta(hours=1)`. Le decisioni operative si fissano prima del
momento in cui contano, non durante — stesso principio già applicato alle soglie di vol (M1.5) e
alla convenzione UTC (checkpoint 1). Vedi `docs/m2-checkpoint2-wiring-demo-report.md` per la
dimostrazione empirica su cui questo valore è stato scelto, e l'eventuale report integrativo di
review per qualunque revisione di questo valore emersa dalla review indipendente del checkpoint 2.
