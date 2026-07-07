# Report — grafico vol EWMA ricostruzione ex-post (2026-07-07, Parte 1)

**Esito: costruito, testato, eseguito per davvero. Vincolo sovrano rispettato — nessuna modifica
al VPS, solo lettura (export storico) + fetch pubblico OKX indipendente (nessuna chiave).**

Risponde alla richiesta: "grafico vol come RICOSTRUZIONE EX-POST — fetch pubblico candles OKX
daily, riuso di compute_ewma_vol span=32, sovrapposizione soglie enter/exit per asset, banda
evidenziata, label prominente nel grafico".

## 1. Cosa è stato costruito (TDD)

- **`src/dashboard/vol_reconstruction.py`** (già presente da sessione precedente): `VolSeries`
  dataclass + `reconstruct_vol_series(exchange, asset, regime_config, limit=200)`. Riusa
  `components.regime_daemon.fetch_latest_returns` (stesso percorso dati pubblico di M1.5/daemon)
  e `regime.vol_state.compute_ewma_vol` (stimatore già approvato, **mai reimplementato**). Soglie
  e span presi da `regime_config` (mai hardcoded).
- **`src/dashboard/render.py`**:
  - `render_vol_reconstruction_png(vol_series_by_asset)` — un grafico con una linea per asset
    (BTC/ETH), soglie enter (tratteggio) ed exit (punteggiato) sovrapposte per ciascun asset, banda
    evidenziata tra le due soglie (`axhspan`), e la label ex-post **incisa nel grafico stesso**
    (riquadro rosso in alto, non solo nel testo HTML circostante — richiesta esplicita "label
    prominente nel grafico").
  - `render_html()` esteso con parametro opzionale `vol_series_by_asset`: se assente, mostra solo
    la nota sul limite dichiarato (comportamento pre-esistente, retro-compatibile); se fornito,
    mostra il grafico + la nota `EX_POST_RECONSTRUCTION_NOTE` + una tabella con le soglie esatte
    per asset.
- **`scripts/render_shadow_dashboard.py`**: fetcha OKX (`ccxt.okx()`, stesso pattern di
  `regime_daemon.main()`) per BTC ed ETH e passa il risultato a `render_html`. Fallimento di
  rete/ccxt per un singolo asset non fa cadere l'intera dashboard (try/except per asset, con avviso
  stampato) — i dati reali già raccolti dal collector restano comunque preziosi anche se il fetch
  OKX fallisce.

TDD: 199/199 test locali verdi (nessuna rete nella suite — `FakeExchange` nei test), ruff pulito.

## 2. Bug trovato durante l'esecuzione reale (non dai test)

Prima formattazione delle soglie in tabella: `.2f`. La soglia enter ETH (calibrata M1.5 a
`0.9990`) veniva mostrata come **`1.00`** — falsa impressione che il trigger fosse esattamente 1.0
anziché 0.999. I test esistenti usavano soglie BTC a 2 decimali (`0.87`/`0.59`), che non
coprivano il caso. Fix: formattazione a `.4f` (coerente con la precisione del config reale
`config/regime.yaml`), più un test di regressione esplicito (`assert "0.9990" in html` e
`assert "1.00" not in html`). Commit separato (`505a402`), prima della seconda esecuzione reale.

## 3. Estensione pre-07/07 (contesto)

Nessuna modifica necessaria: `reconstruct_vol_series` chiama `fetch_latest_returns` con
`limit=LOOKBACK_CANDLES=200` di default (candele giornaliere) — la serie ricostruita copre quindi
sempre ~200 giorni di contesto storico precedente, indipendentemente da quando il collector ha
iniziato a scrivere (2026-07-07T10:01Z). Il grafico mostra quindi il contesto pre-avvio del
collector "gratis", per costruzione.

## 4. Esecuzione reale — comando e output integrale

Prima esecuzione (bug soglie ancora presente, usata per scoprirlo):
```
$ python scripts/render_shadow_dashboard.py --ssh-host 207.180.247.38 --ssh-user freqbot
Export consistente (Online Backup API) da freqbot@207.180.247.38 ...
  backup remoto: BACKUP_OK
  scaricato in: ...\history_export_20260707T122338Z.db
  temporaneo remoto rimosso: /tmp/history_export_20260707T122338Z.db
Righe caricate: 9
Anomalie data-sanity: 0
Ricostruzione ex-post vol (fetch OKX indipendente) ...
  asset ricostruiti: ['BTC', 'ETH']
Report scritto in: ...\dashboard.html
```

Seconda esecuzione, dopo il fix di precisione (`505a402` pushato):
```
$ python scripts/render_shadow_dashboard.py --ssh-host 207.180.247.38 --ssh-user freqbot
Export consistente (Online Backup API) da freqbot@207.180.247.38 ...
  backup remoto: BACKUP_OK
  scaricato in: ...\history_export_20260707T122458Z.db
  temporaneo remoto rimosso: /tmp/history_export_20260707T122458Z.db
Righe caricate: 9
Anomalie data-sanity: 0
Ricostruzione ex-post vol (fetch OKX indipendente) ...
  asset ricostruiti: ['BTC', 'ETH']
Report scritto in: ...\dashboard.html
```

**Verifica del contenuto HTML generato** (estrazione reale dal file, non un'affermazione):
```
$ python -c "... estrae tabella soglie ..."
<tr><td>BTC</td><td>0.8711</td><td>0.5940</td></tr>
<tr><td>ETH</td><td>0.9990</td><td>0.8301</td></tr>

data:image/png;base64 occorrenze: 3   # timeline stato + staleness + vol ex-post
ricostruzione ex-post occorrenze: 2   # nota HTML + testo inciso nel grafico
```

**Verifica indipendente del cleanup remoto** (non fidata dalla sola dichiarazione dello script):
```
$ ssh freqbot@207.180.247.38 "ls -la /tmp/ | grep history_export"
(nessun output — grep exit 1, nessun file temporaneo residuo)
```

## 5. Righe accumulate e range temporale (al momento del render)

- Righe totali: **9** (collector attivo da ~2h15min).
- Primo snapshot: `2026-07-07T10:01:14Z`.
- Ultimo snapshot: `2026-07-07T12:16:41Z`.
- Anomalie data-sanity: **0**.

## 6. File toccati in questa sessione (repo)

- `src/dashboard/render.py` — `render_vol_reconstruction_png`, sezione HTML condizionale,
  parametro opzionale `vol_series_by_asset` su `render_html`, fix precisione soglie.
- `scripts/render_shadow_dashboard.py` — fetch OKX BTC/ETH + wiring a `render_html`, flag
  `--skip-vol-reconstruction` e `--regime-config`.
- `tests/dashboard/test_render.py` — 3 nuovi test + test di regressione sulla precisione soglie.
- Questo documento.

**Non committato** (rigenerabile, escluso da `.gitignore` via la regola `var/` esistente):
`var/dashboard-output/dashboard.html`, `var/dashboard-output/history_export_*.db`.

**Fuori dal repo:** nessuna modifica al VPS — solo lettura (backup temporaneo creato e rimosso
nello stesso comando, verificato) + fetch pubblico OKX indipendente (nessuna chiave, nessun
impatto sui processi in shadow).

## 7. Commit

- `d6c958c` — feat: grafico vol EWMA ricostruzione ex-post (TDD).
- `505a402` — fix: precisione soglie vol a 4 decimali nel render.

Entrambi pushati su `master`.
