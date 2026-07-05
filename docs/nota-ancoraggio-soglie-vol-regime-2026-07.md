# Nota di ricerca — Ancoraggio soglie regime layer v0 (stato di volatilità)

**Data:** 2026-07-06
**Ambito:** `src/regime/vol_state.py`, `config/regime.yaml` (Task 5/7 del repo orchestratore)
**Vincolo non negoziabile:** regime layer v0 è SOLO A REGOLE (ADR-036 §3) — nessun modello ML in questa
sessione, nessun backtest (sessione solo documentale), nessuna modifica al codice.
**Fonte primaria dichiarata:** Quantpedia (Prime, consultato dall'utente — io non ho accesso diretto
all'area riservata, solo alle pagine pubbliche del blog; dove serve la copertura Prime lo segnalo
esplicitamente). Integrato con letteratura accademica/practitioner pubblica via web search.
**Time-box:** una sessione. Dove la letteratura non converge su un numero preciso, lo dichiaro invece
di forzare un valore inventato (vedi §"Limiti").

## Sintesi operativa

| # | Domanda | Esito | Azione sul config |
|---|---|---|---|
| 1 | Stimatore di vol | **MODIFICA parziale** | `ewma_span`: 20 → **32** (ancora a RiskMetrics λ=0.94). Lo stimatore range-based (Garman-Klass) è documentato come superiore ma richiede dati OHLC non ancora nel pipeline: task di implementazione separato, non un numero di config. |
| 2 | Soglie assolute vs percentili | **MODIFICA di meccanismo, valori deferred** | La letteratura favorisce soglie percentili/rolling su soglie assolute fisse. I livelli numerici equivalenti per BTC/ETH richiedono un calcolo storico (= backtest), esplicitamente fuori scope in questa sessione documentale. |
| 3 | Isteresi anti-whipsaw | **CONFERMA** | La banda morta enter>exit già implementata è il meccanismo corretto, con base sia pratica che accademica. Nessun numero universale di letteratura per la larghezza della banda (dipende dalla distribuzione dello strumento — si lega al punto 2). |

Criterio di successo pre-registrato soddisfatto: la sessione cambia un valore di config (`ewma_span`)
E conferma esplicitamente un meccanismo esistente (isteresi) con riferimenti — non chiude con un vago
"interessante, da approfondire".

---

## 1. Stimatore di volatilità

### Cosa dice la letteratura

**EWMA (RiskMetrics):** JP Morgan/RiskMetrics ha popolarizzato l'EWMA con λ=0.94 su dati giornalieri,
trovando che questo valore produce previsioni di varianza più vicine alla varianza realizzata rispetto
ad altri valori testati su un ampio ventaglio di variabili di mercato; per dati mensili RiskMetrics usa
λ=0.97. L'half-life di uno shock di volatilità a λ=0.94 è ≈11.2 giorni
(ln(0.5)/ln(0.94)). Ricerca successiva nota che il λ ottimale dipende dall'orizzonte di previsione e
non è stazionario nel tempo (dovrebbe essere ri-stimato periodicamente) — vedi "Asset volatility
forecasting: The optimal decay parameter in the EWMA model" (arXiv 2105.14382).

**Realized vol semplice (somma di rendimenti al quadrato su finestra fissa):** non distorta, ma
richiede di tenere in memoria l'intera finestra (O(N) vs O(1) per EWMA) e pesa ogni osservazione
allo stesso modo, quindi reagisce più lentamente a shock recenti rispetto a EWMA a parità di finestra.

**Stimatori range-based (Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang):** usano l'intero range
OHLC (open/high/low/close), non solo il close-to-close. L'evidenza è consistente e forte su più fonti
indipendenti: Parkinson è 2.5-5x più efficiente statisticamente del close-to-close al quadrato,
Garman-Klass ≈7.4x, Rogers-Satchell ≈6.0x; più in generale gli stimatori range-based sono
teoricamente 5-7x più efficienti della misura a rendimenti al quadrato. Yang-Zhang è riportato come
ulteriormente superiore perché robusto ai salti in apertura pur usando tutta l'informazione
giornaliera disponibile. Applicazione specifica a crypto: uno studio applica Garman-Klass
direttamente a misure di volatilità di criptovalute (ScienceDirect, "On the speculative nature of
cryptocurrencies: A study on Garman and Klass volatility measure").

**Nota di onestà sulla fonte primaria:** non ho potuto estrarre parametri numerici specifici dalle
pagine pubbliche di Quantpedia consultate ("An Introduction to Volatility Targeting",
"A Few Tips for Volatility Trading") — quella con più dettaglio menziona un half-life di 20 giorni in
un esempio di vol targeting tattico e un cap di leva massima a 2x, ma non affronta esplicitamente
range-based vs close-to-close né soglie assolute vs percentili. Se hai accesso Prime a un report
specifico su questo tema, vale la pena un controllo manuale da parte tua — io ho lavorato solo sulle
pagine pubbliche.

### Conclusione operativa

**MODIFICA parziale, in due parti separate per costo di implementazione:**

**(a) Span EWMA — cambio di config, applicabile subito.** Lo `span=20` attuale (pandas
`ewm(span=20, adjust=False)`) corrisponde a λ≈0.905 e half-life≈6.9 giorni (derivazione:
α=2/(span+1)=2/21≈0.0952, λ=1-α≈0.9048, half-life=ln(0.5)/ln(0.9048)≈6.93). Questo è quasi la metà
dell'half-life del benchmark RiskMetrics più citato e validato empiricamente (λ=0.94, half-life
≈11.2gg). Il valore attuale non è "sbagliato" — crypto ha vol-of-vol strutturalmente più alta di
molti mercati TradFi, quindi una reattività maggiore ha una razionale economica — ma non era ancorato
a nessuna fonte, e RiskMetrics è l'ancora più citata e cross-asset disponibile. Ancoraggio proposto:
`span=32` (α=2/33≈0.0606, λ≈0.9394≈0.94, half-life≈11.2gg), cioè la trasposizione diretta di λ=0.94
nel parametro `span` che questo codebase già usa.

**(b) Famiglia di stimatore — MODIFICA di roadmap, non di config oggi.** L'evidenza per stimatori
range-based (Garman-Klass in particolare, già applicato in letteratura a crypto) è forte e
convergente su più fonti indipendenti: 5-8x più efficiente del close-to-close al quadrato su cui si
basa l'EWMA attuale. Non lo implemento ora: `compute_ewma_vol` accetta solo una Series di rendimenti,
non OHLC — passare a Garman-Klass richiede ristrutturare l'input (serve open/high/low/close per bar,
non solo il close), un cambio di interfaccia che tocca a monte tutta la pipeline dati. Raccomando un
task dedicato in M2 (o prima, se il collector dati OHLC è già disponibile) per valutare la
sostituzione, NON un'estensione affrettata di `vol_state.py` oggi.

---

## 2. Soglie: assolute vs percentili/quantili rolling

### Cosa dice la letteratura

Ricerca accademica su classificazione di regime di volatilità impiega tipicamente finestre rolling
con condizioni di soglia percentile — es. volatilità sopra l'85° percentile della propria
distribuzione storica. Un pattern ricorrente: la soglia percentile spesso NON è il parametro più
sensibile — è la condizione relativa (es. sopra la media mobile a 12 mesi) a fare la maggior parte
del lavoro nell'identificare scostamenti dalla baseline recente, mentre i percentili assoluti fungono
da guardrail. Un lavoro correlato (Conditional Threshold Autoregression, CoTAR) sposta esplicitamente
da soglia costante a soglia tempo-variante, specificata come quantile empirico di osservazioni
recenti di una variabile soglia — la soglia condizionale traccia le fluttuazioni di incertezza nel
tempo invece di restare fissa. In un altro studio, terzili rolling a 252 giorni corrispondono in
media a soglie del 33°/67° percentile; per il VIX, soglie come "VIX>30" non sono arbitrarie ma si
allineano a breakpoint nella distribuzione dei rendimenti (es. il 95° percentile del movimento
giornaliero supera il 4.5% quando VIX>30) — cioè anche le soglie "assolute" più citate nella pratica
sono in realtà ancorate a un'analisi percentile ex-post, non scelte a caso.

**Rilevanza specifica per crypto:** la letteratura su maturazione del mercato crypto (es.
"Cryptocurrency Market Maturation and Evolving Risk Profiles: A Comparative Analysis of Bitcoin and
Ethereum Tail Risk Dynamics", che usa finestre rolling di 365 giorni su dati 2015-2026) documenta che
il profilo di rischio di BTC/ETH è cambiato strutturalmente nel tempo con la maturazione dell'asset
class. Questo è il punto più importante per la tua config: **una soglia assoluta fissata oggi (0.80
per BTC) rischia di diventare mal calibrata tra qualche anno se la vol strutturale del mercato scende
ulteriormente** — esattamente il meccanismo per cui la letteratura preferisce soglie rolling.

### Conclusione operativa

**MODIFICA di meccanismo — confermata dalla letteratura, ma valori numerici NON derivabili in questa
sessione.** La direzione è chiara e la dichiaro esplicitamente perché cambia il config concettualmente
(come richiesto dal criterio di successo): le soglie assolute attuali (BTC 0.80/0.60, ETH 1.00/0.75)
dovrebbero, in una versione futura, diventare percentili rolling (es. entra sopra l'80° percentile
della distribuzione EWMA-vol storica dell'asset su finestra di ~1-2 anni, esce sotto il 60°
percentile — stessa struttura di banda morta enter>exit già implementata, solo espressa in percentile
invece che in valore assoluto).

Non posso però fornire QUI i valori assoluti equivalenti per BTC/ETH: calcolarli richiede applicare
`compute_ewma_vol` alla storia reale dei rendimenti BTC/ETH e leggerne la distribuzione — questo è,
per definizione, un backtest (anche se descrittivo, non di P&L), esplicitamente fuori scope per una
sessione "solo documentale". Questo è il gap che la sessione lascia esplicitamente aperto (vedi
"Limiti" sotto) invece di far finta di chiuderlo con un numero non verificato.

**Raccomandazione per il prossimo passo (non eseguito qui):** un task separato, ancora senza ML e
senza P&L, che calcoli la distribuzione storica di `compute_ewma_vol` su BTC/ETH (con lo `span`
aggiornato del punto 1) e derivi i percentili 60°/80° (o altri livelli, da discutere con te) come
nuovi valori di soglia — un'estensione naturale di `regime.config.py`, non una riscrittura.

---

## 3. Isteresi anti-whipsaw

### Cosa dice la letteratura

**Meccanismo pratico (dead-band/hysteresis):** filtri di trend/regime nella pratica algoritmica usano
principi di isteresi per ridurre i falsi segnali (whipsaw): la regola per "iniziare" un cambio di
stato è più stringente della regola per "restare" nello stato — esattamente la convenzione
enter>exit già implementata in `regime/hysteresis.py`. I filtri dead-band tipici mantengono una
baseline e costruiscono bande di ingresso/uscita dove la banda di uscita è più stretta di quella di
ingresso.

**Fondamento teorico (control theory):** switching con isteresi e dwell-time sono tecniche di
controllo consolidate per prevenire il "chattering" (l'equivalente controllistico del whipsaw);
gli switching a dwell-time garantiscono stabilità quando i cambi di modalità rispettano un vincolo
di permanenza minima.

**Fondamento econometrico:** modelli espliciti di "regime isteretico" (Hysteretic Vector
Autoregressive - HVAR, modelli di volatilità stocastica a soglia isteretica) formalizzano il
passaggio tra regimi come condizionato all'uscita da una "zona di isteresi" predefinita — non un
salto immediato al superamento di un'unica soglia. La letteratura descrive questo come un meccanismo
"fisicamente significativo" per il regime-switching, con prestazioni predittive migliori rispetto a
soglie singole, e nota esplicitamente che impostare la soglia troppo vicino alla tipica ampiezza del
segnale induce attraversamenti frequenti e trading ad alto turnover dominato da fluttuazioni di breve
durata — cioè il rischio di whipsaw se la banda è troppo stretta è documentato, non solo intuitivo.

**Conferma multi-periodo (dwell time / N barre):** qui l'evidenza è più debole. Le fonti trovate sono
prevalentemente pratiche/community (TradingView, blog di trading), non letteratura peer-reviewed:
un default comune citato è "3 barre consecutive" prima di confermare un cambio di regime, ma senza
la stessa base empirica della banda morta. È un meccanismo complementare difendibile, non uno che la
letteratura impone.

### Conclusione operativa

**CONFERMA.** Il meccanismo di isteresi a doppia soglia (enter>exit, banda morta) già implementato in
`regime/hysteresis.py` e testato (incl. test di flip-flop sia lato ON che lato OFF, Task 4-5) è
esattamente il meccanismo che la letteratura — sia pratica sia accademica/control-theoretic —
raccomanda per prevenire whipsaw in un cambio di stato binario. Nessuna modifica al meccanismo.

Nessun numero universale di letteratura per la LARGHEZZA della banda morta: va calibrata sulla
distribuzione specifica dello strumento (si ricollega al punto 2 — se le soglie diventano percentili,
la larghezza della banda si esprimerà naturalmente in punti percentili, es. 60°-80°, invece che in
unità assolute di vol).

**Nota su dwell-time/conferma multi-periodo:** non raccomando di aggiungerlo ora. L'evidenza è
debole rispetto alla banda morta, e il principio di parsimonia dei parametri (ogni parametro in più
deve avere una razionale economica e superare un test di sensibilità — non è gratis) sconsiglia di
aggiungere un secondo meccanismo anti-whipsaw senza una ragione empirica specifica per questo
strumento. Se in futuro emergesse whipsaw residuo anche con la banda morta ben calibrata, un dwell
time minimo (es. 3 osservazioni) è un'estensione difendibile e a basso costo — non oggi.

---

## Annotazione fuori scope (una riga, come richiesto)

Modelli di regime-switching ML (Markov-Switching GARCH, HVAR isteretico) sono documentati in
letteratura come superiori ai modelli a soglia fissa per la stima di regime — coerente con la
previsione di ADR-036 §3 che un v1 ML possa sostituire le regole v0 se le batte su shadow comparison
pre-registrata ≥3 mesi; annotazione per il futuro meta-layer, nessuna azione ora.

---

## Config YAML risultante

```yaml
# Soglie regime layer v0 (ADR-036 §3) — regole semplici, isteresi obbligatoria.
# ewma_span=32 ancorato a RiskMetrics lambda=0.94 (half-life ~11.2gg), aggiornato
# 2026-07-06 dopo sessione di ancoraggio letteratura (docs/nota-ancoraggio-soglie-vol-regime-2026-07.md).
# Le soglie enter/exit di BTC/ETH restano ai valori precedenti: la letteratura raccomanda
# soglie percentili rolling al posto di valori assoluti fissi, ma i livelli numerici
# equivalenti richiedono un calcolo storico (backtest descrittivo) fuori scope per questa
# sessione documentale — vedi la nota, sezione 2, per il task di follow-up proposto.
vol:
  ewma_span: 32
  btc:
    enter_threshold: 0.80   # vol annualizzata EWMA, soglia di ingresso high-vol (provvisoria, vedi nota §2)
    exit_threshold: 0.60    # soglia di uscita (isteresi: exit < enter)
  eth:
    enter_threshold: 1.00   # provvisoria, vedi nota §2
    exit_threshold: 0.75
funding:
  eth:
    enter_threshold: 0.0005   # funding rate, soglia harvester ON (fuori scope di questa sessione)
    exit_threshold: 0.0002
```

**Nota:** solo `ewma_span` cambia in questo file. Le soglie enter/exit di vol restano invariate ma ora
etichettate esplicitamente come "provvisorie" nel commento, in attesa del task di derivazione
percentile. Le soglie di funding non sono state oggetto di questa sessione (fuori scope, la domanda
era solo sullo stato di vol).

---

## Limiti di questa sessione (dichiarati esplicitamente, come da time-box)

1. **Nessun accesso diretto a Quantpedia Prime.** Ho letto solo le pagine pubbliche del blog
   (`quantpedia.com/an-introduction-to-volatility-targeting/`,
   `quantpedia.com/a-few-tips-for-volatility-trading/`), che non contenevano il dettaglio numerico
   cercato. Se hai un report Prime specifico su regime di volatilità o "Market Phases" con parametri
   espliciti, vale la pena un controllo manuale tuo — non l'ho potuto verificare io.
2. **Nessun valore percentile equivalente per BTC/ETH (punto 2).** Derivarlo richiede applicare lo
   stimatore alla storia reale dei rendimenti — un calcolo descrittivo che è comunque un "backtest"
   nel senso stretto del vincolo di questa sessione. Lasciato come task di follow-up esplicito, non
   come promessa vaga.
3. **Due PDF accademici non completamente leggibili** (arXiv 2510.03236, arXiv 2603.02898) —
   l'estrazione via fetch non ha reso il testo completo delle sezioni metodologiche; i numeri citati
   nel testo (85° percentile, terzili 252gg) vengono dalla sintesi del motore di ricerca su più fonti
   aggregate, non da una singola citazione verificata riga per riga. Trattali come indicazione di
   direzione (soglie percentili sono comuni in letteratura), non come singola fonte pin-point.

Ancoraggio parziale con riferimenti dichiarati, non ancoraggio perfetto mai finito — come da
time-box.

## Verifica Prime (2026-07-05)

Verifica documentale svolta via Chrome già loggato sull'account Prime (`a.janno69`), sola lettura,
nessuna azione sull'account. Nota già acquisita in partenza: `/market-phases/` reindirizza alla home
— i report "Market Phases" sono tier Pro, NON inclusi in Prime.

### Cosa offre davvero il tier Prime (censimento)

**Screener Prime** (212 strategie accessibili: 82 Free + 130 Prime, su un totale di 1000+; il resto è
Premium/Pro, bloccato). Cercato per tag `volatility`, `trend-following`, `market timing`, `regime`:

- Tag `volatility` (4 risultati: #0007, #0020, #0155, ecc.) → tutte strategie fattoriali/anomalia
  (*Low Volatility Factor Effect*, *Volatility Risk Premium Effect*) — vendono/comprano volatilità
  come premio di rischio, non definiscono uno stato di regime.
- Tag `trend-following` (4 risultati: #0001, #0143, #0144, ecc.) → segnali di trend prezzo
  (SMA, momentum), nessuna soglia di volatilità con isteresi.
- Tag `market timing` (5 risultati: #0043, #0131, #0267, #0855, #1115) → controllato in dettaglio
  #0855 *"Avoid Equity Bear Markets with a Market Timing Strategy"* (Ďurian & Vojtko 2023): usa una
  combinazione AND/OR di segnali trend (SMA 200gg, Rachev ratio) e macro (yield curve, retail sales,
  industrial production, housing starts) — un meccanismo anti-whipsaw "a composizione di segnali",
  non una banda morta su un singolo segnale di volatilità.
- Tag `regime` (1 risultato: #0830) → regime di politica monetaria, non di volatilità.

**Nessuna strategia Prime nello screener implementa esplicitamente lo schema delle 3 domande**
(stato EWMA + soglia assoluta/percentile + isteresi enter/exit su un'unica variabile di volatilità).
Le strategie più vicine usano meccanismi diversi: composizione di più segnali, o sizing continuo.

**Blog Quantpedia**, articolo rilevante trovato e letto per intero: *"Hedging Tail Risk with Robust
VIXY Models"* (David Belobrad, Radovan Vojtko — Head of Research; own-research, 29 settembre 2025;
tag `own-research`, `market timing`, `volatility effect`). Copre tutte e tre le domande:

- **Stimatore:** usa deviazione standard rolling (5-120gg testati) dei rendimenti S&P500 e media
  mobile semplice di VIX/VXV (10-120gg testati) — nessun EWMA. Finding esplicito dell'articolo: la
  finestra a 10 giorni è la più robusta ("stabile su più orizzonti di test, evita gli esiti negativi
  pronunciati delle finestre più lunghe"), preferita a finestre di 60-120gg.
- **Soglie:** il segnale primario è `VIX > VIX3M` — cioè VIX **relativo alla propria media mobile a
  90 giorni**, non un livello assoluto fisso (tipo "VIX>30"). L'articolo nota esplicitamente che un
  benchmark con soglia meno raffinata (il semplice segnale VIX-vs-VXV) **performa peggio** in Sharpe
  e rendimento della versione con eVRP + smoothing. Un raffinamento ulteriore usa il **livello di VIX
  come size continua** (es. VIX=28 → 28% di allocazione), non una soglia binaria.
- **Isteresi:** nessuna banda morta enter/exit esplicita su un singolo segnale. L'anti-whipsaw viene
  dalla **combinazione AND di due condizioni** (eVRP≤0 E VIX>VIX3M) — l'articolo nota che "l'hedge si
  attiva solo raramente", un effetto della composizione di segnali, non di una banda morta dedicata.

### Esito per le 3 conclusioni della nota originale

| # | Conclusione originale | Esito verifica Prime |
|---|---|---|
| 1 | `ewma_span` 20→32 (ancoraggio RiskMetrics λ=0.94) | **NON COPERTO direttamente** — nessun materiale Prime trovato usa EWMA; usano deviazione standard rolling o SMA. Corroborazione debole, solo di ordine di grandezza: la finestra più robusta trovata empiricamente (10gg, testata 5-120gg) è nello stesso ordine di grandezza della half-life RiskMetrics (~11.2gg) proposta — non è una conferma del valore specifico, ma nemmeno una contraddizione, e conferma indipendentemente che finestre corte (10-20gg) battono finestre lunghe (60-120gg) in un'applicazione pratica reale. |
| 2 | Percentili/rolling > soglie assolute (meccanismo; valori TBD) | **CONFERMA** — l'articolo Quantpedia usa esplicitamente un confronto relativo (VIX vs propria media mobile) come segnale primario, non un livello assoluto, e documenta che la versione a soglia assoluta-semplice performa peggio. Conferma indipendente della direzione già proposta nella nota. Il gap sui valori numerici per BTC/ETH resta comunque scoperto: il materiale trovato è su equity/VIX, non su crypto — non applicabile a livelli numerici, solo al meccanismo. |
| 3 | Banda morta enter/exit confermata | **NON COPERTO / nessuna conferma né contraddizione da questo materiale.** Il meccanismo anti-whipsaw usato in pratica da Quantpedia nel materiale trovato è diverso (composizione AND di più segnali, o sizing continuo) — non contraddice la banda morta enter/exit (nessuna evidenza contraria), ma non la conferma da questa fonte specifica. La CONFERMA della nota originale resta in piedi sulla base della letteratura accademica/control-theoretic già citata (HVAR isteretico, dwell-time switching), non su questo controllo Prime. |

### Il gap sulla domanda 2 resta scoperto, come previsto

Il gap Pro-vs-Prime (niente "Market Phases") lascia la domanda 2 (valori percentili equivalenti per
BTC/ETH) comunque scoperta — il materiale Prime conferma il *meccanismo* (soglie relative preferibili
ad assolute) ma non offre valori numerici applicabili a BTC/ETH. Il task di follow-up già previsto
nella nota (derivazione percentile su dati storici BTC/ETH con `span=32`) resta l'unica via per
chiudere quel punto: nessuna scorciatoia trovata nel materiale Prime disponibile.

## Fonti citate

- RiskMetrics λ=0.94: [What should the value of lambda be in the EWMA volatility model?](https://www.researchgate.net/publication/282240091_What_should_the_value_of_lambda_be_in_the_exponentially_weighted_moving_average_volatility_model) — [PDF](https://www.une.edu.au/__data/assets/pdf_file/0009/76464/unebsop14-1.pdf)
- Lambda ottimale tempo-variante: [Asset volatility forecasting: The optimal decay parameter in the EWMA model](https://arxiv.org/pdf/2105.14382)
- Efficienza stimatori range-based: [Historical Volatility: Parkinson, Garman-Klass & Rogers-Satchell](https://ryanoconnellfinance.com/historical-volatility-estimators/); [Properties of range-based volatility estimators](https://www.sciencedirect.com/science/article/abs/pii/S1057521911000731); [Do extreme range estimators improve realized volatility forecasts?](https://www.sciencedirect.com/science/article/pii/S1544612323003641)
- Garman-Klass su crypto: [On the speculative nature of cryptocurrencies: A study on Garman and Klass volatility measure](https://www.sciencedirect.com/science/article/abs/pii/S1544612318305105)
- Soglie percentili/rolling: [Range-Based Volatility Estimators for Monitoring Market Stress](https://arxiv.org/pdf/2603.02898); [Improving S&P 500 Volatility Forecasting through Regime-Switching Methods](https://arxiv.org/html/2510.03236v1)
- Maturazione crypto / vol strutturale: [Cryptocurrency Market Maturation and Evolving Risk Profiles: Bitcoin and Ethereum Tail Risk Dynamics](https://www.mdpi.com/2674-1032/5/2/28)
- Isteresi pratica (dead-band): [Deadband Hysteresis Filter — BackQuant](https://www.tradingview.com/script/TPvNyPwv-Deadband-Hysteresis-Filter-BackQuant/); [Building A Better Trend Filter](https://easylanguagemastery.com/building-a-better-trend-filter-2-2/)
- Isteresi control-theoretic: [A Control-Theoretic Foundation for Agentic Systems](https://arxiv.org/pdf/2603.10779)
- Isteresi econometrica (HVAR): [Forecasting with a Bivariate Hysteretic Time Series Model](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12294434/); [Modelling time series of counts with hysteresis](https://arxiv.org/pdf/2509.15508)
- Quantpedia (pagine pubbliche consultate): [An Introduction to Volatility Targeting](https://quantpedia.com/an-introduction-to-volatility-targeting/); [A Few Tips for Volatility Trading](https://quantpedia.com/a-few-tips-for-volatility-trading/)
