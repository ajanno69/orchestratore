# Checkpoint 2 — dimostrazione wiring pre-deploy (M2, binario harvester)

**Data:** 2026-07-06
**Ambito:** dimostrazione eseguibile del wiring completo (lettura snapshot → decisione → comando →
alert). Nessun deploy, nessuna chiave, nessuna modifica a config di produzione. GridBTC resta fuori
scope (condizionale al suo shadow futuro, vedi `docs/gridbtc-highvol-analysis-m2.md` e
`docs/m2-reactivation-gates.md`) — il parametro `GridBtcHighVolAction` è usato negli scenari solo
come placeholder di firma della funzione, non come decisione.

---

## Step 0 — pulizia del pendente

**Comando eseguito:**
```
git status --short
```
**Output:**
```
(vuoto)
```
Nessun file pendente all'apertura di questo checkpoint: l'unico untracked della sessione precedente
(`docs/stato-progetto-2026-07-06.md`, snapshot di ricarico-contesto ormai superato dagli eventi —
scritto quando ADR-037 era ancora PROPOSED) era già stato eliminato ed è già confermato assente. La
barra segnalava quindi lavoro non ancora iniziato di questo stesso checkpoint (il codice e i test
descritti sotto), non un residuo — attribuzione: nessun pendente da un turno precedente, tutto ciò
che segue è stato creato ed è tracciato in questo turno.

---

## Finding emersi durante la costruzione dell'harness (chiusi con TDD prima di questo report)

Come previsto dalla nota del checkpoint ("se durante l'harness emergono difetti nel wiring, fix con
TDD prima del report"), costruire lo scenario 5 (snapshot corrotto) ha esposto due difetti reali in
`resolve_wiring_decision`, entrambi corretti con test-first prima di procedere (commit `15e985d`):

1. **Timestamp malformato non gestito**: `datetime.fromisoformat(snapshot.timestamp)` sollevava un
   `ValueError` non catturato — un'eccezione non gestita che avrebbe fermato il loop di wiring senza
   generare alcun alert, l'opposto del fail-safe richiesto da ADR-037 §3.
2. **Campo booleano di tipo invalido interpretato per truthiness**: un `dataclass` non valida i tipi
   a runtime, quindi uno snapshot con `btc_high_vol="true"` (stringa) veniva costruito senza errori e
   il suo valore veniva usato direttamente in un test di verità — un default silenzioso vietato dalla
   convenzione del progetto. Inquinava anche `WiringDecision.alert`, che diventava la stringa
   `'true'` invece di `bool` (via `or` di Python).

Entrambi corretti con una validazione esplicita (`_malformed_snapshot_reason`) che tratta questi casi
esattamente come uno snapshot assente: `NO_ACTION_STALE_DATA` + `alert=True`, mai un'eccezione, mai
un'interpretazione silenziosa. 2 nuovi test (falliti prima della fix, verdi dopo) in
`tests/components/test_regime_wiring.py`.

Costruire gli scenari 2/3/7 ha inoltre reso evidente che `resolve_wiring_decision` (puro, senza
memoria del tick precedente) da solo non basta per un consumatore esterno: senza uno strato stateful,
un regime stabile per giorni in high-vol produrrebbe lo stesso comando/alert ad ogni tick. Per questo
è stato costruito `src/components/wiring_sequencer.py` (`WiringSequencer`, commit `5051e9b`) — non
era previsto nel piano M2 originale come modulo a sé, ma si è rivelato necessario per soddisfare gli
scenari 2, 3 e 7 del checkpoint senza inventare comportamento ad hoc nello script di dimostrazione.

---

## Harness

**File:** `scripts/demo_wiring_checkpoint2.py` (committabile, eseguibile da solo).
**Sorgente snapshot sintetica:** `regime.store.RegimeStateStore` reale su una directory temporanea
per scenario, alimentato con `build_snapshot` (snapshot validi) o con testo JSON scritto
direttamente sul file (per simulare corruzione reale, scenario 5).
**Sink:** nessun canale reale — gli eventi (`CommandEvent`, `AlertEvent`) emessi da
`WiringSequencer` sono solo raccolti e stampati in tabelle markdown.
**Verifica:** ogni scenario include asserzioni esplicite; lo script esce con errore se un'asserzione
fallisce (comando eseguito, exit code 0, nessuna eccezione — vedi in fondo).

**Comando eseguito:**
```
cd D:/Claude/orchestrator && PYTHONIOENCODING=utf-8 python scripts/demo_wiring_checkpoint2.py
```

**Output reale (integrale, non riformattato a mano):**

Staleness policy: `max_age=1:00:00`. Rate-limit alert: max 3 transizioni / 1:00:00.
`GridBtcHighVolAction` usato solo come placeholder di firma (`stop_new_orders`) — GridBTC resta
condizionale, nessuna decisione presa qui.

### Scenario 1 — vita normale (ETH low-vol stabile)

| tick | now (UTC) | harvester_cmd | gridbtc_cmd | decision.alert | comandi emessi | alert emessi |
|---|---|---|---|---|---|---|
| t+0m | 2026-07-06 12:00:00 | normal | normal | False | normal/normal | - |
| t+15m | 2026-07-06 12:15:00 | normal | normal | False | - | - |
| t+30m | 2026-07-06 12:30:00 | normal | normal | False | - | - |

**Atteso:** nessun comando, nessun alert dopo il primo tick. **Osservato:** conforme.

### Scenario 2 — transizione ETH low→high

| tick | now (UTC) | harvester_cmd | gridbtc_cmd | decision.alert | comandi emessi | alert emessi |
|---|---|---|---|---|---|---|
| t+0m (low-vol) | 2026-07-06 12:00:00 | normal | normal | False | normal/normal | - |
| t+10m (entra high-vol) | 2026-07-06 12:10:00 | defensive | normal | True | defensive/normal | [layer_lavora_difensiva] LAYER LAVORA — snapshot valido, comandi derivati dallo stato di regime corrente. |
| t+20m (ancora high-vol) | 2026-07-06 12:20:00 | defensive | normal | True | - | - |

**Atteso:** comando `defensive` UNA volta, alert LAYER LAVORA UNA volta, non ripetuti al tick
successivo in high-vol stabile. **Osservato:** conforme.

### Scenario 3 — rientro high→low (nessuna ripresa automatica)

| tick | now (UTC) | harvester_cmd | gridbtc_cmd | decision.alert | comandi emessi | alert emessi |
|---|---|---|---|---|---|---|
| t+30m (rientra low-vol) | 2026-07-06 12:30:00 | normal | normal | False | normal/normal | [layer_lavora_rientro] LAYER LAVORA — ETH rientrato in low-vol: NESSUNA ripresa automatica, conferma manuale richiesta prima di uscire dalla modalità difensiva (ADR-037: la ripresa è decisione umana). |
| t+40m (low-vol stabile) | 2026-07-06 12:40:00 | normal | normal | False | - | - |

**Atteso:** nessuna ripresa automatica — solo l'alert di rientro con testo esplicito su conferma
manuale, non ripetuto. **Osservato:** conforme.

### Scenario 4 — snapshot stantio (processo morto)

| tick | now (UTC) | harvester_cmd | gridbtc_cmd | decision.alert | comandi emessi | alert emessi |
|---|---|---|---|---|---|---|
| t+0m (fresco) | 2026-07-06 12:00:00 | normal | normal | False | normal/normal | - |
| t+2h (stantio, processo morto) | 2026-07-06 14:00:00 | no_action_stale_data | no_action_stale_data | True | no_action_stale_data/no_action_stale_data | [layer_cieco] LAYER CIECO — snapshot stantio (età 2:00:00, soglia 1:00:00): nessuna azione automatica, posizione mantenuta. |
| t+2h10m (ancora stantio) | 2026-07-06 14:10:00 | no_action_stale_data | no_action_stale_data | True | - | - |

**Atteso:** nessun comando, fail-safe, alert LAYER CIECO distinguibile da LAYER LAVORA, non ripetuto
ad ogni tick stantio. **Osservato:** conforme.

### Scenario 5 — snapshot corrotto (3 varianti)

| tick | now (UTC) | harvester_cmd | gridbtc_cmd | decision.alert | comandi emessi | alert emessi |
|---|---|---|---|---|---|---|
| campo mancante (eth_harvester_on) | 2026-07-06 12:00:00 | no_action_stale_data | no_action_stale_data | True | no_action_stale_data/no_action_stale_data | [layer_cieco] LAYER CIECO — nessuno snapshot di regime mai scritto: nessuna azione automatica, posizione mantenuta. |
| timestamp malformato | 2026-07-06 12:00:00 | no_action_stale_data | no_action_stale_data | True | no_action_stale_data/no_action_stale_data | [layer_cieco] LAYER CIECO — snapshot con dati invalidi (timestamp non valido: 'non-una-data'): nessuna azione automatica, posizione mantenuta. |
| bool invalido (btc_high_vol='yes') | 2026-07-06 12:00:00 | no_action_stale_data | no_action_stale_data | True | no_action_stale_data/no_action_stale_data | [layer_cieco] LAYER CIECO — snapshot con dati invalidi (campo booleano invalido: btc_high_vol='yes'): nessuna azione automatica, posizione mantenuta. |

**Atteso:** fail-safe esplicito per tutte e tre le varianti di corruzione (campo mancante →
`KeyError` catturato da `RegimeStateStore.read()`, ri-sollevato come `ValueError`, tradotto in `None`
da `load_snapshot_safely`; timestamp malformato e bool invalido → validati esplicitamente in
`resolve_wiring_decision`, vedi sezione finding sopra), mai un default silenzioso. **Osservato:**
conforme — nota bene, il campo `reason` distingue chiaramente le tre origini del fail-safe (assenza
vs dati invalidi), utile per la diagnosi operativa (Task 5, runbook Andrea).

### Scenario 6 — staleness al bordo

| tick | età vs soglia (1h) | esito atteso | esito osservato |
|---|---|---|---|
| t+59m59s (sotto soglia) | 0:59:59 | FRESCO | FRESCO |
| t+60m esatti (== soglia) | 1:00:00 | FRESCO | FRESCO |
| t+60m1s (appena sopra soglia) | 1:00:01 | STANTIO | STANTIO |

**Atteso:** confine netto, età esattamente pari alla soglia trattata come fresca (convenzione già
fissata e testata da M2 Task 1: `age > staleness.max_age`, non `>=`), nessuna ambiguità.
**Osservato:** conforme, nessun codice nuovo necessario — comportamento già corretto e già coperto da
`test_snapshot_exactly_at_staleness_boundary_is_still_fresh`.

### Scenario 7 — flip-flop (rate-limit)

| tick | now (UTC) | harvester_cmd | gridbtc_cmd | decision.alert | comandi emessi | alert emessi |
|---|---|---|---|---|---|---|
| t+0m (baseline low-vol) | 2026-07-06 12:00:00 | normal | normal | False | normal/normal | - |
| t+1m (high-vol, flip #1) | 2026-07-06 12:01:00 | defensive | normal | True | defensive/normal | [layer_lavora_difensiva] LAYER LAVORA — snapshot valido, comandi derivati dallo stato di regime corrente. |
| t+2m (low-vol, flip #2) | 2026-07-06 12:02:00 | normal | normal | False | normal/normal | [layer_lavora_rientro] LAYER LAVORA — ETH rientrato in low-vol: NESSUNA ripresa automatica, conferma manuale richiesta prima di uscire dalla modalità difensiva (ADR-037: la ripresa è decisione umana). |
| t+3m (high-vol, flip #3) | 2026-07-06 12:03:00 | defensive | normal | True | defensive/normal | [layer_lavora_difensiva] LAYER LAVORA — snapshot valido, comandi derivati dallo stato di regime corrente. |
| t+4m (low-vol, flip #4) | 2026-07-06 12:04:00 | normal | normal | False | normal/normal | [layer_instabile] LAYER INSTABILE — 4 transizioni di stato in 1:00:00: possibile flip-flop a monte (layer di regime instabile o dati rumorosi), alert individuali soppressi finché la frequenza non si stabilizza sotto soglia. |
| t+5m (high-vol, flip #5) | 2026-07-06 12:05:00 | defensive | normal | True | defensive/normal | - |
| t+6m (low-vol, flip #6) | 2026-07-06 12:06:00 | normal | normal | False | normal/normal | - |

**Atteso:** il wiring non amplifica un layer di regime buggato — dopo che le transizioni superano la
soglia di rate-limit (3 in 1h, valore proposto per questa dimostrazione, da confermare in fase di
deploy Task 3), i singoli alert LAYER LAVORA vengono soppressi e sostituiti da un unico alert
aggregato LAYER INSTABILE; i comandi restano deduplicati (un evento per ogni cambio reale di stato,
mai amplificati). **Osservato:** conforme — su 6 flip, solo 2 alert individuali (i primi, prima che
il rate-limit scattasse) + 1 aggregato, contro i 6 che si sarebbero avuti senza soppressione.

**Chiusura dello script:**
```
Tutte le asserzioni degli scenari sono passate (nessuna eccezione sollevata).
```
Exit code: `0`.

---

## I due testi di alert reali, fianco a fianco (come appariranno sul canale)

| LAYER LAVORA (il layer legge dati affidabili e agisce/segnala uno stato) | LAYER CIECO (dati inaffidabili: nessuna azione automatica) |
|---|---|
| `LAYER LAVORA — snapshot valido, comandi derivati dallo stato di regime corrente.` (entrata in high-vol) | `LAYER CIECO — snapshot stantio (età 2:00:00, soglia 1:00:00): nessuna azione automatica, posizione mantenuta.` |
| `LAYER LAVORA — ETH rientrato in low-vol: NESSUNA ripresa automatica, conferma manuale richiesta prima di uscire dalla modalità difensiva (ADR-037: la ripresa è decisione umana).` (rientro in low-vol) | `LAYER CIECO — snapshot con dati invalidi (timestamp non valido: 'non-una-data'): nessuna azione automatica, posizione mantenuta.` |

Distinguibili a colpo d'occhio dal prefisso (`LAYER LAVORA` vs `LAYER CIECO`), non solo dal
contenuto — un operatore che scorre un canale Telegram può classificarli senza leggere il testo
completo.

---

## Cosa questa dimostrazione NON copre

| Buco | Dove viene chiuso |
|---|---|
| Canale alert reale (Telegram) — qui gli `AlertEvent` sono solo raccolti in memoria, mai inviati | Smoke test post-deploy, `docs/m2-deploy-runbook.md` Task 3: verifica canary/healthcheck con comando+output reale dopo il primo deploy |
| Unit systemd, `Restart=on-failure`, ciclo di vita del processo reale | `docs/m2-deploy-runbook.md` (Task 3) — non eseguito, resta pianificazione fino al deploy vero |
| Harvester vero (funding-harvester, OKX) che riceve ed esegue `HarvesterCommand` | Nessun executor esiste ancora in questo piano (ADR-037 §7: il wiring produce solo comandi/dati) — è un componente futuro, fuori scope M2 |
| Persistenza reale dello snapshot da un processo di misura live (qui scritta a mano dallo script) | Già costruito e testato in M1 (Task 8, `regime.store`) — non riverificato qui, solo riusato |
| Comportamento sotto carico/concorrenza reale (più processi che scrivono/leggono lo stesso file) | Non nello scope di questo checkpoint — nessun deploy multi-processo pianificato per il wiring |
| Valore reale del rate-limit (`max_transitions=3` in 1h, scelto per questa dimostrazione) | Da confermare/calibrare in fase di deploy con dati reali di frequenza di transizione (Task 3/4) |

---

## Verifica finale

**Comando eseguito:**
```
cd D:/Claude/orchestrator && python -m pytest -q && python -m ruff check src tests scripts
```
**Output:**
```
........................................................................ [ 71%]
.............................                                            [100%]
101 passed in 0.87s
All checks passed!
```

Commit di questo checkpoint (in ordine): `15e985d` (fix fail-safe snapshot invalido, TDD),
`5051e9b` (WiringSequencer), `9e6223e` (harness di dimostrazione), più questo documento.
