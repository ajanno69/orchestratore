# Provenienza soglie vol regime — derivazione 2026-07 (M1.5)

**Data derivazione:** 2026-07-05
**Prossima ri-derivazione:** 2026-10-05 (+3 mesi) — **non eseguire senza prima risolvere le
questioni aperte in fondo a questo documento**
**Script:** `scripts/derive_vol_thresholds.py`
**Modulo puro:** `src/regime/threshold_derivation.py`
**Piano:** `docs/superpowers/plans/2026-07-05-m1.5-vol-threshold-derivation.md`

## Dati usati

- BTC: OKX (`BTC/USDT`), copertura completa dal 2019-01-01 (nessun fallback Kraken necessario),
  periodo 2019-01-02 — 2026-07-05, 2742 osservazioni di rendimento.
- ETH: OKX (`ETH/USDT`), stessa copertura, stesso periodo, 2742 osservazioni.

## Stimatore

EWMA su rendimenti giornalieri, `span=32` (ancoraggio RiskMetrics λ=0.94, half-life ≈11.2 giorni —
vedi `docs/nota-ancoraggio-soglie-vol-regime-2026-07.md`), annualizzato ×√365.

## Criterio (pre-registrato, ADR-036 §3 / piano M1.5)

Frazione target tempo in high-vol: 20-25%. Vincoli aggiuntivi sui candidati: mediana transizioni/anno
<= 8, dwell time minimo osservato >= 3 giorni. Nessun segnale combinato BTC+ETH: le due soglie sono
derivate e valutate indipendentemente (chiarito esplicitamente con Andrea in fase di piano).

## Soglie scelte

| Asset | enter | exit | frazione effettiva | mediana transizioni/anno | dwell time minimo | dwell time (min/mediana/max) |
|---|---|---|---|---|---|---|
| BTC | 0.8711 | 0.5940 | 21.55% | 2.0 | 23 giorni | 23 / 95 / 1162 giorni |
| ETH | 0.9990 | 0.8301 | 23.19% | 4.0 | 9 giorni | 9 / 52 / 531 giorni |

## Transizioni per anno solare

| Anno | BTC | ETH |
|---|---|---|
| 2019 | 4 | 7 |
| 2020 | 2 | 4 |
| 2021 | 4 | 6 |
| 2022 | 6 | 4 |
| 2023 | **0** | 0 |
| 2024 | **0** | 4 |
| 2025 | **0** | 6 |
| 2026 (parziale, fino al 2026-07-05) | 2 | 2 |

**Evidenza esplicita — BTC 2023-2025: zero transizioni.** Con queste soglie, il rilevatore BTC non
scatta mai nel triennio 2023-2025. Questo è dichiarato qui come **caratteristica attesa della
derivazione**, non un difetto scoperto dopo: le soglie sono ancorate alla storia COMPLETA
(2019-2026), un periodo in cui la volatilità di BTC era strutturalmente più alta (2019-2022,
inclusi i crash 2020 e 2022); calibrare su tutta quella storia produce soglie assolute che l'era
più matura e meno volatile (2023-2025) raramente raggiunge. **Chi fa il wiring in M2 deve leggere
questa tabella prima di collegare il regime layer a qualunque decisione live**: un layer che non
scatta per tre anni consecutivi va usato con la piena consapevolezza di questo comportamento, non
scoperto in produzione.

## Regola di tie-break usata

Per ciascun asset, la griglia di ricerca (percentili enter 0.60-0.90, percentili exit 0.40-0.70,
step 0.05) ha prodotto 3 candidati conformi al criterio pre-registrato. Il tie-break applicato:
**candidato con frazione di tempo high-vol più vicina al centro del range target (22.5%)**. Per
BTC ed ETH, i candidati scelti (0.8711/0.5940 e 0.9990/0.8301) sono risultati anche quelli con
frazione più vicina al 22.5% tra i 3 conformi alla griglia originale.

## Verifica griglia estesa (richiesta esplicita di Andrea prima della conferma)

Prima di scrivere queste soglie nel config, è stata eseguita una verifica: la griglia di ricerca
originale (percentili enter fino a 0.90) censura un ottimo migliore? Estendendo la griglia enter
fino al 97° percentile:

| Asset | Candidato griglia originale (0.90) | Candidato griglia estesa (0.97) |
|---|---|---|
| BTC | enter=0.8711, exit=0.5940 — frazione 21.55%, mediana 2.0 transizioni/anno, dwell min 23gg | enter=1.0038, exit=0.5336 — frazione 22.93%, mediana **0.5** transizioni/anno, dwell min **58gg** |
| ETH | enter=0.9990, exit=0.8301 — frazione 23.19%, mediana 4.0 transizioni/anno, dwell min 9gg | enter=1.3160, exit=0.7258 — frazione 22.53%, mediana **0.5** transizioni/anno, dwell min **32gg** |

**Esito della verifica:** nessun ottimo censurato in senso letterale (il valore 0.9990 di ETH
proveniva dal percentile 0.85, non dal bordo 0.90 della griglia). Tuttavia, estendendo la griglia
oltre il cap originale emergono candidati alternativi conformi al criterio pre-registrato ma con
un carattere diverso: frazione più vicina al centro 22.5%, ma mediana transizioni/anno di sole 0.5
all'anno (contro 2.0-4.0) e dwell time minimo 2-3x più lungo.

**Scelta dichiarata:** a parità di criterio pre-registrato (che i candidati griglia estesa
soddisfano comunque), si preferisce il segnale più reattivo (griglia originale, 0.8711/0.5940 e
0.9990/0.8301). Motivazione: un layer di rilevamento con mediana 0.5 transizioni/anno non scatta
nell'anno tipico — aggraverebbe il pattern già osservato per BTC 2023-2025 (muto) ed estenderebbe
lo stesso comportamento anche a ETH. Il tie-break "più vicino al centro" è quindi **declassato**
in questa derivazione: si è rivelato un proxy debole che, su griglie ampie, seleziona candidati con
un cambio di carattere (raro/persistente) invece di un affinamento del candidato originale.

I candidati della griglia estesa sono registrati qui come **considerati e scartati**, con questa
motivazione, a scopo di tracciabilità della decisione (governance).

## Limiti dichiarati

- Nessun segnale combinato BTC+ETH: le due soglie sono derivate e valutate indipendentemente.
- Nessun backtest/PnL: le metriche riportate misurano solo il comportamento della macchina a stati
  sulla storia (frazione di tempo, transizioni, dwell time), mai un risultato economico.
- Nessun fallback Kraken necessario in questa derivazione (OKX copriva l'intero periodo richiesto).

## QUESTIONI APERTE pre-registrate per la ri-derivazione di ottobre 2026

**Non decidere silenziosamente al prossimo giro. Entrambe le questioni vanno risolte con un'ADR o
una nota dedicata PRIMA di rieseguire lo script — non durante l'esecuzione, non dopo.**

1. **Finestra di derivazione: full-history (sempre crescente) vs mobile (ultimi 3-4 anni).**
   Questa derivazione ha usato l'intera storia disponibile (2019-2026). Il prossimo giro, la
   finestra sarà 2019-2026-10 (ancora più lunga) o si passa a una finestra mobile (es. solo
   2022-2026)? Le due scelte producono soglie sistematicamente diverse: full-history pesa
   ugualmente le crisi 2020/2022 e l'era matura 2023-2025 (producendo soglie "alte" che l'era
   matura raramente raggiunge, come osservato sopra); una finestra mobile peserebbe di più il
   regime recente, probabilmente abbassando le soglie e facendo scattare il rilevatore più spesso
   anche nell'era matura — un trade-off diretto con la scelta di tie-break appena fatta in questo
   documento (segnale reattivo vs raro).

2. **Il criterio pre-registrato manca di una dimensione di reattività esplicita.** Questa
   derivazione ha dovuto scartare manualmente candidati "matematicamente ottimi" (più vicini al
   centro del range target) perché troppo poco reattivi (mediana 0.5 transizioni/anno) — il
   criterio attuale (frazione 20-25%, mediana transizioni/anno <= 8, dwell minimo >= 3gg) non
   esclude un segnale che non scatta quasi mai, purché soddisfi il tetto superiore di 8
   transizioni/anno. Prima della prossima derivazione, il criterio va emendato per includere un
   vincolo esplicito di reattività — es. un **floor** di transizioni mediane/anno (non solo un
   tetto), oppure un test contro episodi di stress noti (il rilevatore deve scattare durante crash
   documentati, non solo rispettare le medie aggregate). Questa è un'estensione del criterio, non
   una correzione: il criterio attuale ha fatto il suo lavoro (ha scartato i candidati non
   conformi), ma ha lasciato al giudizio umano una scelta che si ripresenterà identica al prossimo
   giro se non viene codificata.
