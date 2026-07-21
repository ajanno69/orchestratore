# Gate 21/07 — istruttoria di fine shadow (regime layer, wiring)

**Solo analisi. Nessun deploy, nessuna modifica al VPS in questa sessione.** Finestra shadow
dichiarata: `2026-07-07T08:33Z → 2026-07-21T08:33Z` (14 giorni, durata minima da protocollo
rispettata). Dati reali disponibili fino a `2026-07-21T12:28Z` (raccolta ancora in corso al
momento dell'istruttoria) — usati dove utile a dare un quadro più aggiornato, la finestra
dichiarata resta il riferimento per il conteggio ufficiale.

---

## Passo 0 — Riconciliazione (obbligatoria, fatta prima di tutto)

**Contraddizione segnalata**: il report del gate dice "streak max 1, mai raggiunto N=2"; un
controllo precedente (in chat, non mai committato come tale) aveva descritto due episodi del
09/07 come "doppio fallimento consecutivo, near-miss staleness".

**Verifica — stesso dataset, due metodi a confronto, comando+output:**

```
$ ssh freqbot@... "sqlite3 history.db \"SELECT snapshot_timestamp FROM regime_history ORDER BY snapshot_timestamp ASC;\""
$ python reconcile_streak.py   # (script ad-hoc, non nel repo — vedi sotto)

=== FINESTRA SHADOW COMPLETA: 2026-07-07 08:33:00 -> 2026-07-21 08:33:00 ===
righe totali nel DB: 1232  righe nella finestra dichiarata: 1217

--- METODO A (naive: gap>20min come evento isolato -- quello del primo controllo) ---
eventi (gap>20min): 118
  ADIACENTI: 2026-07-09 05:05:36 -> 2026-07-09 05:35:37 -> 2026-07-09 06:05:38
    NOTA: 2026-07-09 05:35:37 e' una riga PRESENTE nel DB (un successo), non un buco
  ADIACENTI: 2026-07-09 16:07:33 -> 2026-07-09 16:37:34 -> 2026-07-09 17:07:35
    NOTA: 2026-07-09 16:37:34 e' una riga PRESENTE nel DB (un successo), non un buco
  [... altre 14 coppie adiacenti dello stesso tipo, in tutto il periodo ...]
coppie di gap adiacenti trovate: 16

--- METODO B (rigoroso: simula consecutive_failures di run_loop, azzerato ad ogni successo) ---
eventi di fallimento (streak): 118
streak massimo di fallimenti CONSECUTIVI mai osservato: 1
eventi con streak >= 2 (soglia N=2 raggiunta): 0
```

**Verdetto della riconciliazione**: l'affermazione **errata** era "due episodi di doppio
fallimento consecutivo, near-miss staleness". L'affermazione **corretta** è "streak massimo mai
osservato = 1, N=2 mai raggiunto".

**Causa dell'errore**: il Metodo A (usato nella primissima analisi, prima che esistesse una
simulazione rigorosa del contatore) elenca ogni gap `>20min` come "evento", stampati in sequenza.
Quando due di questi eventi capitano temporalmente vicini (16 casi in 14 giorni, non solo i 2 del
09/07), è facile leggerli — a colpo d'occhio, in una lista — come un unico fallimento prolungato.
Ma il timestamp che li separa è **una riga presente nel database**, cioè un ciclo RIUSCITO — e
`consecutive_failures` in `run_loop` si azzera esplicitamente ad ogni successo (`else:
consecutive_failures = 0`, vedi `src/components/regime_daemon.py`). Il Metodo A non modellava
questo azzeramento; il Metodo B lo fa, chiamata per chiamata, esattamente come il codice reale.

**Stato della correzione**: questa riconciliazione conferma — su un dataset più ampio (14 giorni
pieni contro le ~43h originarie) — la correzione già fatta e committata l'11/7
(`5100694`, doc `docs/m2-shadow-network-resilience-finding-2026-07-09.md` §1bis/§3bis). Nessuna
contraddizione residua tra i documenti attuali. Se il riferimento del "controllo del 12/07" era
proprio quella correzione letta prima che fosse pubblicata, il numero corretto è questo; se
esisteva un report intermedio con il numero sbagliato non ancora corretto, è superato da qui.

*(Script `reconcile_streak.py`: ad-hoc, eseguito in locale contro un export dello storico, non
fa parte del repo — analisi usa e getta, non un componente di produzione.)*

---

## 1. Export finale + render dashboard (allegato d'istruttoria)

```
$ python scripts/render_shadow_dashboard.py --ssh-host 207.180.247.38 --ssh-user freqbot \
    --output var/dashboard-output/dashboard-gate-2026-07-21.html
Export consistente (Online Backup API) da freqbot@207.180.247.38 ...
  backup remoto: BACKUP_OK
  scaricato in: history_export_20260721T122701Z.db
  temporaneo remoto rimosso: /tmp/history_export_20260721T122701Z.db
Righe caricate: 1232
Anomalie data-sanity: 0
```

Verifica contenuto reale del file generato:
```
Righe totali: 1232
Primo: 2026-07-07T10:01:14Z
Ultimo: 2026-07-21T12:08:19Z
Nessuna anomalia: True
```

**0 anomalie data-sanity** su 1232 righe — nessun duplicato di PK, nessuna inconsistenza
level/derived, nessun buco di cadenza non spiegato, timestamp monotoni (vedi `dashboard/sanity.py`,
5 controlli).

**Nota**: la ricostruzione ex-post del grafico vol (fetch OKX indipendente) è fallita in questa
esecuzione — `NetworkError` persistente su 3 tentativi dalla macchina locale (non dal VPS,
verificato separatamente: `ccxt.okx().load_markets()` fallisce anche in isolamento). Non
correlato alla diagnosi VPS→OKX già documentata (percorso di rete diverso). Il render è comunque
completo e valido per l'istruttoria: la sezione vol mostra la nota di fallback dichiarata, non un
dato falso. File non committato (escluso da `.gitignore` via `var/`, rigenerabile).

---

## 2. Dossier eventi

### 2.1 Restart — cronologia completa, comando+output

```
$ ssh freqbot@... "sudo journalctl -u 'orchestrator-*' --since '2026-07-07 08:00:00' ... | grep -E 'Stopped|Started'"
```

| Quando | Unit | Causa | Tipo |
|---|---|---|---|
| 07-07 09:42→10:30 CEST | daemon, wiring-loop | Sessione di deploy + incident credenziali in argv (documentato: `m2-deploy-report-2026-07-07.md`) | **Pre-shadow** (prima delle 08:33Z dichiarate come inizio) |
| 07-07 12:05→12:12 CEST | collector | Deploy iniziale collector (documentato: `m2-history-collector-deploy-report-2026-07-07.md`) | **Pre-shadow** |
| **07-08 06:46:48-49 CEST** | **tutti e 3** | `unattended-upgrades`: `python3.12`/`libpython3.12*` | **Durante shadow** — benigno |
| **07-21 06:50:14 CEST** | **solo collector** | `unattended-upgrades`: `libsqlite3-0`/`sqlite3` (solo il collector dipende da sqlite3) | **Durante shadow** — benigno |

**Durante lo shadow effettivo (dopo le 08:33Z del 07-07): esattamente 2 eventi di restart, entrambi
aggiornamenti di sicurezza OS automatici, zero crash.** `NRestarts` (contatore di riavvio-per-crash
di systemd, distinto dai riavvii per upgrade) = **0 su tutti e tre i servizi, sempre**. Nessun
altro restart trovato scandendo l'intera finestra.

### 2.2 Episodi di rete (riconciliati, Passo 0)

**118 eventi di fallimento isolato** (streak sempre =1), meccanismo diagnosticato l'11/7 e mai
cambiato: `RequestTimeout` ccxt (timeout client 10s mai sovrascritto) su coda di latenza rara
dell'endpoint pubblico OKX candele. Ogni evento: nessuno snapshot corrotto, ripresa automatica al
ciclo successivo, comportamento di fail-safe corretto 118 volte su 118.

### 2.3 Staleness — mai scattata

```
$ sqlite3 history.db "SELECT COUNT(*) FROM regime_history WHERE derived_alert=1;"
0
$ sqlite3 history.db "SELECT snapshot_timestamp, derived_alert_category FROM regime_history WHERE derived_alert_category IS NOT NULL;"
(nessuna riga)
```

Zero volte il collector (che ricalcola `resolve_wiring_decision` in proprio, in sola osservazione,
sugli stessi dati) ha rilevato una condizione di staleness o un qualunque alert. Coerente con
l'evidenza strutturale: lo streak massimo osservato (1 = 30 min di buco) resta ben sotto la soglia
di staleness (60 min) — non solo "non c'è stato un falso positivo", non c'è mai stata nessuna
condizione di staleness, vera o falsa.

### 2.4 Alert LAYER CIECO totali (col codice attualmente deployato, senza soglia)

**118** — uno per ogni evento di rete isolato (§2.2). Il pacchetto post-gate (retry+N=2, ancora IN
CODA) ridurrebbe questo numero a **0** su questo stesso campione (nessuno streak ha mai raggiunto
N=2) — vedi `docs/m2-shadow-network-resilience-finding-2026-07-09.md` §1bis per la validazione
retrospettiva completa.

### 2.5 Transizioni di regime osservate

```
$ sqlite3 history.db "SELECT DISTINCT btc_high_vol, eth_high_vol, eth_harvester_on FROM regime_history;"
0|0|0
$ sqlite3 history.db "SELECT DISTINCT derived_harvester_command, derived_gridbtc_command FROM regime_history;"
off|normal
```

**Zero transizioni.** Su 1232+ righe in 14 giorni, lo stato di regime è rimasto costantemente
`btc_high_vol=False, eth_high_vol=False, eth_harvester_on=False` — bassa volatilità su entrambi
gli asset, harvester mai in condizione di attivazione per tutto lo shadow. Non "poche", **zero**
— condizione di mercato, non un difetto del sistema di misura (il regime layer riporta fedelmente
ciò che osserva).

---

## 3. Criteri di promozione (Task 4 / `docs/m2-reactivation-gates.md`) — uno per uno

| # | Criterio | Evidenza | Fonte | Esito |
|---|---|---|---|---|
| 1 | Zero eccezioni non gestite nel loop di wiring per l'intera durata dello shadow | Journal `orchestrator-wiring-loop` ripulito da righe di lifecycle systemd: **nessuna riga anomala** in 14 giorni. `NRestarts=0`. L'unico riavvio è un aggiornamento OS esterno (§2.1), non un'eccezione applicativa. | `journalctl -u orchestrator-wiring-loop.service --since '2026-07-07 08:00:00'` (comando+output sopra) | **PASS** |
| 2 | Ogni transizione di stato di regime osservata durante lo shadow è stata alertata correttamente | **Zero transizioni sono avvenute** (§2.5) — non c'è nulla da verificare contro lo storico degli alert, perché lo storico degli alert di transizione è vuoto quanto lo storico delle transizioni stesse. Criterio soddisfatto per assenza di casi, non per casi verificati positivamente. | `regime_history`, query §2.5 | **PASS (vacuo) — vedi caveat sotto** |
| 3 | Nessun falso `NO_ACTION_STALE_DATA` durante lo shadow dovuto a un bug di staleness | Zero eventi di staleness, veri o falsi, in tutto lo shadow (§2.3). La soglia (60 min) non è mai stata avvicinata (streak massimo reale: 30 min, metà della soglia). | `regime_history.derived_alert`, query §2.3 | **PASS — vedi caveat sotto** |
| 4 | Conferma esplicita di Andrea (non promozione automatica) | — | — | **In attesa — decisione tua** |

**Caveat onesto sui criteri 2 e 3** (non nascosto, dichiarato qui perché rilevante per il
verdetto): entrambi sono soddisfatti per **assenza di eventi da testare**, non perché l'evento sia
stato osservato e gestito correttamente dal vivo. Il mercato è rimasto in bassa volatilità per
tutti i 14 giorni — nessuna transizione reale ha mai esercitato il percorso "alert su transizione"
del wiring-loop in produzione, e nessun gap di rete si è mai avvicinato alla soglia di staleness
abbastanza da metterla sotto stress reale. La LOGICA di entrambi i percorsi è comunque validata
in modo indipendente e pesante: test unitari dedicati (inclusi gli scenari di transizione e di
staleness-boundary nel checkpoint 2, `scripts/demo_wiring_checkpoint2.py`, 7 scenari con
assertion reali) più due round di review indipendente su quel codice — ma restano **prove
costruite**, non un evento vissuto dal sistema in produzione.

---

## 4. Verdetto raccomandato

**Raccomandazione: PROMOZIONE**, con una richiesta di follow-up mirata invece di un'estensione
generica.

**Perché promozione, non estensione:**
- Durata minima (2 settimane) rispettata con margine.
- Criterio 1 (zero eccezioni non gestite) è un PASS pieno, non vacuo — e il sistema è stato
  messo sotto stress reale non pianificato: 118 fallimenti di rete genuini, 2 riavvii per
  patch di sicurezza — tutti assorbiti senza corruzione, senza crash, senza intervento umano.
  Questa è più validazione della resilienza di quanto uno shadow "tranquillo" avrebbe dato.
- I criteri 2 e 3, per quanto vacui nella loro forma "osservato durante lo shadow", poggiano su
  una base di test unitari e review indipendente insolitamente pesante per questo progetto (vedi
  caveat sopra) — non è "speriamo funzioni", è "verificato a tavolino con lo stesso rigore, solo
  non ancora sul campo".
- Un'estensione indefinita in attesa che "il mercato faccia qualcosa" non è una variabile che lo
  shadow controlla — potrebbe non succedere per settimane, senza aggiungere informazione reale
  oltre quella già raccolta.

**La richiesta di follow-up mirata** (non una condizione bloccante, una raccomandazione operativa
per dopo la promozione): la PRIMA transizione di regime reale che accadrà — anche dopo la
promozione — va verificata a mano con lo stesso rigore di questa istruttoria (comando+output:
l'alert Telegram ricevuto confrontato con lo storico `regime_history` reale) invece di essere data
per scontata. Non blocca il gate oggi, ma chiude il caveat sopra con un evento reale alla prima
occasione, invece di aspettarla prima di decidere.

**Cosa NON è parte di questa raccomandazione**: il pacchetto post-gate (retry+N=2, schema-prep vol,
separazione misura/ping — tutto repo-only, review indipendente già GO su ciascun pezzo) resta
esplicitamente **fuori da questa decisione**. Se confermi la promozione, quel pacchetto è pronto
per una sessione di deploy dedicata, separata, con lo stesso rito già rodato — ma è una decisione
successiva e distinta, non implicita in un "sì" al gate.

**La decisione resta tua.**

---

## 5. File di questa sessione

- Questo documento.
- `var/dashboard-output/dashboard-gate-2026-07-21.html` — non committato (`.gitignore` `var/`),
  rigenerabile con il comando in §1.
- Script di riconciliazione ad-hoc — non nel repo, usa e getta.

**Nessuna modifica al VPS. Nessun deploy. Nessun cambiamento di codice.**
