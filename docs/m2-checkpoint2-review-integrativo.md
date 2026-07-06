# Checkpoint 2 — report integrativo: review indipendente di `WiringSequencer`

**Data:** 2026-07-06
**Ambito:** review indipendente (Opus, contesto fresco, sola lettura + verifica empirica) del
componente `src/components/wiring_sequencer.py` — nuovo, stateful, non previsto nel piano
originale, sul percorso capitale — richiesta da Andrea come passo di rito prima del sign-off del
checkpoint 2. Nessuna esecuzione, nessuna chiave, nessun deploy.

## Esito

**Un difetto reale di severità alta, trovato e chiuso con TDD prima di questo report; due
non-difetti la cui sicurezza dipendeva da un contratto implicito, ora dichiarato esplicitamente;
un finding minore di stile chiuso con una nota.**

## (b) Rate-limit sotto flip-flop prolungato — DIFETTO REALE, chiuso

**Trovato:** la potatura della finestra di rate-limit e il reset di `_aggregate_alert_active`
avvenivano solo dentro il blocco "categoria cambiata" — un flip-flop che continua a produrre
transizioni non lascia mai spazio a un tick "senza transizione" per essere rivalutato, quindi
l'alert `LAYER_INSTABILE` scattava una sola volta e poi restava silenzioso per l'intera durata del
guasto (verificato empiricamente dal reviewer: 1 alert su 6 ore di flip-flop continuo). Peggio:
`_aggregate_alert_active` non si disarmava mai per pura stabilizzazione, quindi una tempesta
successiva rischiava di non riarmare l'alert.

**Fix (commit `37c4bb2`):** potatura e ricalcolo di `is_unstable` spostati fuori dal blocco
condizionale, eseguiti a ogni tick. Aggiunto un promemoria periodico (stessa cadenza della finestra
già approvata, nessun nuovo parametro) finché l'instabilità persiste. 2 nuovi test (verificati
falliti col codice precedente).

**Re-review:** confermato corretto **per costruzione generale**, non solo sui due scenari di test
forniti — la rivalutazione essendo ora ad ogni tick, il comportamento non dipende più da quanti
tick o quale distribuzione di flip. Nota di bordo non bloccante: un conteggio che oscilla proprio
intorno alla soglia può produrre una cadenza di promemoria più fitta di "una volta per finestra"
(sovra-notifica, non il difetto originale) — documentata con un commento nel codice
(`wiring_sequencer.py`, blocco `if is_unstable`).

## (a) Contratto di riavvio — non un difetto di comportamento, era non dichiarato

Lo stato di dedup è in-memory ed effimero: un riavvio riemette sempre lo stato corrente al primo
tick. Sicuro oggi solo perché ogni comando è level-triggered/idempotente — **non** dichiarato prima
della review. Chiuso con un blocco esplicito nel docstring del modulo (rischio nominato
concretamente: `GridBtcCommand.HIGH_VOL_CLOSE_GRID_ORDERLY`, già nell'enum, se mai interpretato
come azione one-shot) + un test che congela il comportamento + un riferimento aggiunto in
ADR-037 §9 per chi legge l'ADR senza aprire il codice. Decisione di non persistere lo stato su
disco confermata dal reviewer: aggiungerebbe un secondo punto di guasto in un componente il cui
scopo è il fail-safe.

## (c) Contratto di concorrenza — non un difetto, era non dichiarato

`process()` non è thread-safe; il modello di deploy previsto (un processo, loop seriale) lo rende
sicuro oggi. Chiuso con un blocco esplicito nel docstring — nessun lock aggiunto (raccomandazione
del reviewer: un lock qui darebbe falsa sicurezza in un componente che per contratto gira già
seriale; da introdurre solo se il modello di deploy cambiasse, come emendamento pre-registrato).

## Finding minore — `_categorize` non pura

Nota inline aggiunta nel codice; nessun refactor necessario (chiamata una volta sola per tick).

## Verifica finale

```
python -m pytest -q        → 104 passed
python -m ruff check src tests scripts   → All checks passed!
```

Commit di questo round: `37c4bb2` (fix + contratti + test), più questo documento e il rimando in
ADR-037 §9.

## Per il sign-off

Rate-limit `max_transitions=3`/`window=1h` approvato come pre-registrato (ADR-037 §9). Nessun
finding residuo bloccante. Le due note minori non bloccanti (cadenza reminder in caso di
oscillazione al bordo; ADR-037 come specchio del docstring) sono documentate, non azioni aperte.
