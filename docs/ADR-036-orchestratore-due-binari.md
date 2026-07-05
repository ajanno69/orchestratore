# ADR-036 — Progetto Orchestratore: edge strutturali + predittore in shadow mode

**Data:** 2026-07-XX
**Stato:** ACCEPTED (2026-07-05) — budget €5k, orizzonti 24h/72h confermati da Andrea
**Sostituisce:** la bozza ADR-036-chiusura (non confermata)
**Chiude:** ADR-035 (ciclo Quantpedia, 10/10 FAIL, report agli atti)

---

## 1. Ridefinizione dell'obiettivo (la decisione fondante)

L'obiettivo del progetto NON e' il rendimento del capitale: e' un SISTEMA VIVO
— orchestratore autonomo di componenti a edge strutturale, con meta-layer di
regime e un programma di ricerca ML di lungo periodo. Il capitale live e'
dichiarato come budget operativo di laboratorio (perdibile per intero senza
che il progetto fallisca), non come investimento.

- Budget live: €5.000. Cap assoluto. Tranche 1: €850 da IBKR (in transito 2026-07-05, etichetta "tranche 1 ADR-036" al deposito su Kraken); resto da bonifico dedicato quando M2 lo richiede.
- Rendimento atteso dichiarato: 5-15% netto/anno sul deployato, regime-
  dipendente, con anni ~0%. Cifre da laboratorio (€250-750/anno su 5k), non da
  patrimonio. Chi legge questo ADR tra un anno non ha diritto di sorprendersi.
- Aumento capitale: SOLO via scaling ladder (§6), mai per decisione a caldo.

## 2. Architettura a due binari (condividono infrastruttura, MAI capitale)

```
                    [ Data layer comune: collectors, NATS, Postgres ]
                                   |
        +--------------------------+---------------------------+
        |                                                      |
  BINARIO A — CAPITALE                              BINARIO B — RICERCA
  Orchestratore strutturale                         Predittore direzionale
  (edge misurati, autonomo)                         (SHADOW MODE, zero ordini)
        |                                                      |
  regime layer (STATO) -> risk manager -> exchange       tabella forecasts
                                                        scoring vs realta'
```

**Muro invalicabile:** il predittore non manda ordini, non parla col risk
manager, non influenza pesi. Scrive previsioni in una tabella append-only.
Punto. Qualunque violazione = incidente di governance.

## 3. Binario A — componenti day-1 e regime layer

| Componente | Stato | Azione |
|---|---|---|
| GridBTC (Kraken) | fermo dal 2026-06-06 (cryptO-trim v2), verdetto GO storico valido | RIATTIVAZIONE pulita dentro questo repo (M2+), chiavi nuove, mai riavvio del vecchio stack |
| Funding-harvester ETH (OKX) | code-complete, 520 test, parcheggiato (timer canary spento in bonifica) | RIATTIVAZIONE a size ridotta in M2 su conferma esplicita; chiavi OKX nuove a permessi minimi; attrito fiscale accettato come costo dichiarato |
| Basis/carry BTC | opportunistico | modulo futuro, entra solo quando il premio osservato supera soglia |

**Regime layer (rilevazione di STATO, non previsione di direzione):**
- v0 = regole semplici e trasparenti: soglie su vol realizzata EWMA
  (on/off e larghezza grid) e su funding osservato (on/off harvester).
  Va live col sistema: e' lettura del presente, non scommessa.
- v1 = ML (LightGBM/HMM sulle feature di vol/funding) con keep-or-kill:
  sostituisce v0 SOLO se batte v0 su metrica pre-registrata in shadow
  comparison >= 3 mesi. Se non lo batte, si tiene v0 per sempre.

**Vietato per costruzione:** corto-vol in ogni forma; componenti direzionali
predittivi nel Binario A (quelli vivono solo nel B, senza capitale).

## 4. Binario B — protocollo del predittore (il programma di lungo periodo)

**Orizzonti congelati:** 24h (primario) e 72h (secondario), emissione a
orario FISSO (00:00 UTC, post-chiusura daily bar — anti cherry-picking),
asset BTC ed ETH, output = P(rendimento>0) calibrata. Il 72h ha previsioni
sovrapposte: lo scoring usa blocchi non sovrapposti o correzione per
autocorrelazione (obbligatorio, pena CI90 sovra-confidente). Feature
orderflow aggregate daily (CVD, taker imbalance, delta OI, funding) ammesse
nel feature set dal giorno uno. Aggiunta di un terzo orizzonte = emendamento
pre-registrato, mai silenzioso.

Ogni previsione registrata con: timestamp, asset, orizzonte (24h|72h),
output (direzione + probabilita'), versione modello (hash), feature snapshot
reference. Append-only, mai cancellazioni.

**Scoring mensile automatico contro la realta':**
- hit rate e Brier score (calibrazione: quando dice 70%, ha ragione il 70%?)
- valore economico simulato di una policy basata sulle previsioni,
  confrontato con DUE baseline: (a) persistenza/caso, (b) regime layer v0
- report mensile nel repo; ogni retrain/nuova versione = trial nel registry

**Gate di promozione (pre-registrato ORA, immutabile):** il predittore guadagna
influenza sull'allocazione SOLO se, su >= 12 mesi di forecast live e >= [200]
previsioni: valore economico con CI90 lower bound > 0 vs ENTRAMBE le baseline
+ calibrazione stabile. E anche allora: influenza limitata a tilt di sizing
(±20% sui pesi dei componenti), MAI posizioni direzionali autonome. Un secondo
gate, piu' avanti, per qualunque cosa in piu'.

**Aspettativa dichiarata:** l'esito piu' probabile (>70%) e' che il predittore
NON batta le baseline — e il registro di 12 mesi di previsioni scored sara'
comunque il dataset piu' onesto mai prodotto in questo hub. Il binario B e'
ricerca: si giudica dalla qualita' della misurazione, non dal PASS.

## 5. Criteri di successo del progetto (operativi, non di P&L)

1. Sistema in esercizio continuo >= 6 mesi: uptime, riconciliazione ordini/
   posizioni pulita, alert chain funzionante, zero interventi manuali
   d'emergenza non documentati
2. Report mensile automatico: P&L per componente, regime attivo, costi,
   posizione fiscale progressiva (riuso motore fiscale, classe crypto)
3. Binario B: 12 mesi di forecast registrati e scored senza buchi
3-bis. Inventario VPS automatico nel report settimanale (unit/timer/cron/
   container/processi + diff vs settimana precedente) — lezione mft_engine:
   mai piu' processi non censiti
4. Il P&L si osserva e si riporta; non e' un criterio di successo ne'
   di fallimento nel primo anno

## 6. Scaling ladder e condizioni terminali

- Scala capitale (es. →€10k) SOLO dopo 12 mesi di esercizio pulito E
  evidenza che i premi incassati sono coerenti con l'atteso. Decisione
  con ADR dedicato.
- Revisione annuale obbligatoria: se il costo (tempo/denaro/interesse)
  supera il valore di laboratorio dichiarato, il sistema si parcheggia
  ORDINATAMENTE (runbook di spegnimento, stato committato) — parcheggiare
  bene e' un esito rispettabile, abbandonare no.
- Il fallimento tecnico ripetuto (3 incidenti di riconciliazione o
  perdita di controllo) sospende il live fino a post-mortem.

## 7. Perche' questo ADR non e' il ritorno dei sei mesi passati

- I componenti a capitale hanno edge GIA' validati (GridBTC) o misurati
  (harvester) — non promesse.
- La direzione — il compito impossibile falsificato 35 volte — e' confinata
  in un binario senza capitale, con misurazione forward e gate immutabile.
- Il rendimento e' dichiarato irrilevante per il primo anno: nessun numero
  potra' "deludere" perche' nessun numero e' stato promesso.
