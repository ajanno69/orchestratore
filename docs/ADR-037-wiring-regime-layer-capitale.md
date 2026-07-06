# ADR-037 — Wiring del regime layer a capitale (harvester ETH + GridBTC)

**Data:** 2026-07-06
**Stato:** PROPOSED — non ACCEPTED finché Andrea non supera il checkpoint bloccante sul piano
(vedi `docs/superpowers/plans/2026-07-06-m2-capital-reactivation-wiring.md`)
**Ambito:** M2. Questo ADR è SOLO decisione architetturale — nessuna riga di codice, nessuna chiave,
nessun deploy viene eseguito con questo documento. L'implementazione (Task 1 del piano M2) segue
SOLO dopo che questo ADR è ACCEPTED.
**Precondizione:** ADR-036 (ACCEPTED 2026-07-05, congelato), M1.5 (soglie vol derivate, vedi
`docs/regime-threshold-provenance-2026-07.md`).

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

## 5. GridBTC in high-vol BTC: analisi e raccomandazione (decisione al checkpoint)

**Questa è l'unica decisione di questo ADR che NON è ancora presa.** Il piano M2 (Task 2) presenta
l'analisi comparativa stop-nuovi-ordini vs chiusura ordinata della griglia, con una raccomandazione
motivata — ma la scelta finale è esplicitamente riservata al checkpoint "wiring implementato
pre-deploy" (vedi piano, non a questo ADR e non al codice). Il codice del wiring (Task 1) espone
questa scelta come un parametro esplicito e obbligatorio, senza un default cablato: nessun valore
verrà scelto per omissione.

**Vincolo noto e dichiarato qui:** GridBTC ha già un proprio meccanismo di guardia interno
(promosso da shadow a HARD il 2026-05-16, secondo `past project/02_crypto-agent.md`), basato su
realized volatility HAR-RV, VPVR e Anchored VWAP ("impulse detector"). Questo ADR **non ha
verificato il codice esatto di quel guard** (vive in `D:\Claude\crypto-agent`, un repo isolato per
policy — vedi CLAUDE.md globale, "non mischiare mai dati/config/blacklist fra progetti"). Il Task 2
del piano M2 **deve** iniziare con la lettura di quel codice (non di questo ADR) prima di
raccomandare qualunque azione, per evitare due esiti entrambi pericolosi: (a) il nuovo segnale di
regime duplica una protezione che GridBTC ha già, aggiungendo complessità senza beneficio; (b) il
nuovo segnale e il guard esistente danno indicazioni contrastanti nello stesso momento, e nessuno
dei due sistemi lo sa.

## 6. Ordine di riattivazione

1. **Harvester (gate G3, ETH-only)** — già pendente indipendentemente da questo ADR (vedi
   `past project/03_newcrypto-funding-harvester.md`, gate G3 ≤$100 USDT). Il wiring regime→harvester
   entra come precondizione aggiuntiva al gate esistente, non lo sostituisce.
2. **GridBTC** — dopo l'harvester, non in parallelo. GridBTC è già "promosso HARD" (produzione, su
   capitale dedicato) — il wiring qui non è un'attivazione da zero ma un'aggiunta di prudenza a un
   sistema già live. Proprio per questo va per ultimo: è il sistema con più capitale reale già
   esposto, quindi il sistema su cui un errore di wiring costerebbe di più.

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
- **GridBTC §5 resta una decisione aperta**: questo ADR non può essere considerato "chiuso" nel
  senso di ADR-036 finché quella scelta non è fatta al checkpoint dedicato.
- **Interazione con il guard esistente di GridBTC (§5) non ancora verificata a livello di codice**:
  rischio esplicitamente dichiarato, non silenziosamente assunto risolto.
