"""Generazione del report HTML statico e autosufficiente (sessione
rendering locale 2026-07-07) — nessun web server, nessuna dipendenza da
CDN, un solo file HTML. Grafici via matplotlib, incorporati come PNG in
base64: nessun asset esterno.

**Limite dichiarato, non taciuto**: lo schema attuale di `regime_history`
persiste solo lo STATO booleano derivato (alto/basso vol), non il valore
NUMERICO dell'EWMA vol che `regime_daemon` calcola transitoriamente a
ogni ciclo — quel numero non è mai persistito da nessuna parte (nemmeno
in `regime_state.json`: solo il risultato booleano di
`VolRegimeState.update()` lo è). Il grafico "vol EWMA nel tempo con soglie
enter/exit sovrapposte" richiesto in origine NON è quindi costruibile con
i dati oggi disponibili — questo modulo rende invece la TIMELINE DI STATO
(alto/basso), che è tutto ciò che lo storico contiene. La nota è
prominente nell'HTML stesso, non solo nel report di sessione."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from datetime import datetime
from html import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from dashboard.queries import HistoryRow  # noqa: E402
from dashboard.sanity import SanityFinding  # noqa: E402
from dashboard.vol_reconstruction import VolSeries  # noqa: E402

MISSING_NUMERIC_VOL_NOTE = (
    "Lo schema attuale non persiste il VALORE NUMERICO dell'EWMA vol calcolato da "
    "regime-daemon a ogni ciclo — solo lo stato booleano derivato (alto/basso). Il "
    "valore numerico non è mai scritto da nessuna parte (nemmeno in "
    "regime_state.json), quindi il grafico \"vol nel tempo con soglie enter/exit\" "
    "non è costruibile con i dati oggi disponibili. Sotto: la timeline di stato, "
    "che è tutto ciò che lo storico contiene. Estendere lo schema del collector per "
    "catturare anche il valore numerico è una decisione di schema separata, non presa qui."
)

EX_POST_RECONSTRUCTION_NOTE = (
    "RICOSTRUZIONE EX-POST — stimatore identico (regime.vol_state.compute_ewma_vol, "
    "span da config/regime.yaml), fetch INDIPENDENTE eseguito ora sulle stesse candele "
    "pubbliche OKX di regime-daemon. NON È IL VALORE OSSERVATO DAL DAEMON: il daemon "
    "calcola questo numero a ogni ciclo ma non lo persiste mai (vedi nota sopra) — "
    "questo grafico lo ricalcola a posteriori, con piccole divergenze attese (revisioni "
    "tardive delle candele OKX, timing del fetch) rispetto a cosa il daemon avrebbe "
    "realmente visto in ciascun momento storico."
)

LEVEL_EDGE_NOTE = (
    "derived_harvester_command / derived_gridbtc_command / derived_alert sono "
    "un'inferenza LEVEL-triggered (stateless, ricalcolata identica ad ogni riga). "
    "derived_alert_category / derived_alert_text sono EDGE-triggered (stateful, dal "
    "sequencer osservativo del collector) — valorizzate solo sulla riga di "
    "transizione, NULL sulle righe successive con stato invariato: atteso, non un "
    "bug. La verità sugli alert REALMENTE inviati resta il canale Telegram."
)


@dataclass(frozen=True)
class HeaderSummary:
    collection_started_at: datetime | None
    row_count: int
    first_snapshot: str | None
    last_snapshot: str | None
    declared_gap_note: str


def build_header_summary(rows: list[HistoryRow], meta: dict[str, datetime]) -> HeaderSummary:
    return HeaderSummary(
        collection_started_at=meta.get("collection_started_at"),
        row_count=len(rows),
        first_snapshot=rows[0].snapshot_timestamp if rows else None,
        last_snapshot=rows[-1].snapshot_timestamp if rows else None,
        declared_gap_note=(
            "Shadow harvester avviato 2026-07-07T08:33:48Z UTC; raccolta storica "
            "avviata 2026-07-07T10:05:35Z UTC — il gap (08:33-10:05 UTC del 07/07) "
            "resta documentato SOLO dal canale Telegram, nessun backfill (decisione "
            "pre-registrata)."
        ),
    )


def _fig_to_png_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    plt.close(fig)
    return buf.getvalue()


def _png_to_img_tag(png_bytes: bytes, alt: str) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f'<img alt="{escape(alt)}" src="data:image/png;base64,{b64}" style="max-width:100%;">'


def render_state_timeline_png(rows: list[HistoryRow]) -> bytes:
    fig, ax = plt.subplots(figsize=(9, 3))
    if rows:
        times = [r.snapshot_time for r in rows]
        btc = [1 if r.btc_high_vol else 0 for r in rows]
        eth = [1 if r.eth_high_vol else 0 for r in rows]
        ax.step(times, btc, where="post", label="BTC high-vol", linewidth=1.5)
        ax.step(times, eth, where="post", label="ETH high-vol", linewidth=1.5)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["low", "high"])
        ax.legend(loc="upper right", fontsize=8)
    else:
        ax.text(0.5, 0.5, "nessuna riga", ha="center", va="center")
    ax.set_title("Timeline di stato (alto/basso vol) — BTC/ETH")
    fig.autofmt_xdate()
    return _fig_to_png_bytes(fig)


def render_staleness_png(rows: list[HistoryRow]) -> bytes:
    fig, ax = plt.subplots(figsize=(9, 2.5))
    if rows:
        times = [r.snapshot_time for r in rows]
        staleness_seconds = [r.staleness.total_seconds() for r in rows]
        ax.plot(times, staleness_seconds, marker=".", linewidth=1)
    else:
        ax.text(0.5, 0.5, "nessuna riga", ha="center", va="center")
    ax.set_title("Età dello snapshot al momento della raccolta (secondi)")
    ax.set_ylabel("secondi")
    fig.autofmt_xdate()
    return _fig_to_png_bytes(fig)


def render_vol_reconstruction_png(vol_series_by_asset: dict[str, VolSeries]) -> bytes:
    """Grafico "principale" richiesto in origine — vedi
    `EX_POST_RECONSTRUCTION_NOTE`: la label compare ANCHE incisa nel
    grafico stesso (non solo nell'HTML circostante), perché un'immagine
    PNG può essere condivisa/salvata separatamente dal resto della
    pagina."""
    fig, ax = plt.subplots(figsize=(9, 4))
    if vol_series_by_asset:
        colors = {"BTC": "#d08000", "ETH": "#4060c0"}
        for asset, series in vol_series_by_asset.items():
            color = colors.get(asset, None)
            ax.plot(series.vol.index, series.vol.values, label=f"{asset} vol EWMA", color=color)
            ax.axhline(
                series.enter_threshold, color=color, linestyle="--", linewidth=0.8, alpha=0.7
            )
            ax.axhline(
                series.exit_threshold, color=color, linestyle=":", linewidth=0.8, alpha=0.7
            )
            ax.axhspan(
                series.exit_threshold, series.enter_threshold, color=color, alpha=0.06
            )
        ax.legend(loc="upper left", fontsize=8)
        ax.set_ylabel("vol EWMA annualizzata")
        ax.text(
            0.5,
            0.97,
            "RICOSTRUZIONE EX-POST — non è il valore osservato dal daemon",
            transform=ax.transAxes,
            ha="center",
            va="top",
            fontsize=8,
            color="#a02020",
            bbox={"boxstyle": "round", "facecolor": "#fff3cd", "edgecolor": "#d0a000"},
        )
    else:
        ax.text(0.5, 0.5, "nessun dato", ha="center", va="center")
    ax.set_title("Vol EWMA ricostruita ex-post con soglie enter/exit — BTC/ETH")
    fig.autofmt_xdate()
    return _fig_to_png_bytes(fig)


def _vol_reconstruction_section_html(vol_series_by_asset: dict[str, VolSeries] | None) -> str:
    if not vol_series_by_asset:
        return (
            '<p style="background:#fff3cd; padding:0.6em; border:1px solid #d0a000;">'
            f"{escape(MISSING_NUMERIC_VOL_NOTE)}</p>"
        )
    chart = _png_to_img_tag(
        render_vol_reconstruction_png(vol_series_by_asset), "vol EWMA ricostruita ex-post"
    )
    thresholds_rows = "\n".join(
        f"<tr><td>{escape(asset)}</td><td>{s.enter_threshold:.2f}</td>"
        f"<td>{s.exit_threshold:.2f}</td></tr>"
        for asset, s in vol_series_by_asset.items()
    )
    return (
        '<p style="background:#fff3cd; padding:0.6em; border:1px solid #d0a000;">'
        f"{escape(EX_POST_RECONSTRUCTION_NOTE)}</p>"
        f"{chart}"
        '<table border="1" cellpadding="4" cellspacing="0">'
        "<tr><th>Asset</th><th>Soglia enter</th><th>Soglia exit</th></tr>"
        f"{thresholds_rows}</table>"
    )


def _findings_html(findings: list[SanityFinding]) -> str:
    if not findings:
        return '<p style="color:#2a7f2a;"><strong>Nessuna anomalia rilevata.</strong></p>'
    rows_html = "\n".join(
        f"<tr><td>{escape(f.severity)}</td><td>{escape(f.check)}</td>"
        f"<td>{escape(f.message)}</td></tr>"
        for f in findings
    )
    return (
        f'<p style="color:#a02020;"><strong>{len(findings)} anomalie rilevate — '
        "vedi tabella sotto.</strong></p>"
        '<table border="1" cellpadding="4" cellspacing="0">'
        "<tr><th>Severità</th><th>Controllo</th><th>Messaggio</th></tr>"
        f"{rows_html}</table>"
    )


def _derived_table_html(rows: list[HistoryRow]) -> str:
    if not rows:
        return "<p>Nessuna riga.</p>"
    body = "\n".join(
        "<tr>"
        f"<td>{escape(r.snapshot_timestamp)}</td>"
        f"<td>{r.btc_high_vol}</td><td>{r.eth_high_vol}</td><td>{r.eth_harvester_on}</td>"
        f"<td>{escape(r.derived_harvester_command)}</td>"
        f"<td>{escape(r.derived_gridbtc_command)}</td>"
        f"<td>{r.derived_alert}</td>"
        f"<td>{escape(r.derived_alert_category or '')}</td>"
        "</tr>"
        for r in rows
    )
    return (
        '<table border="1" cellpadding="4" cellspacing="0" style="font-size:0.85em;">'
        "<tr><th>snapshot_timestamp</th><th>btc_high_vol</th><th>eth_high_vol</th>"
        "<th>eth_harvester_on</th><th>derived_harvester_command</th>"
        "<th>derived_gridbtc_command</th><th>derived_alert</th>"
        "<th>derived_alert_category</th></tr>"
        f"{body}</table>"
    )


def render_html(
    rows: list[HistoryRow],
    rows_by_insertion_order: list[HistoryRow],
    meta: dict[str, datetime],
    findings: list[SanityFinding],
    vol_series_by_asset: dict[str, VolSeries] | None = None,
) -> str:
    """Ritorna il contenuto HTML (senza scheletro `<html>`/`<head>`/`<body>`
    — solo il contenuto, coerente con come questo repo pubblica pagine).

    `vol_series_by_asset` è opzionale: se assente, la sezione vol mostra
    solo la nota sul limite dichiarato (nessun valore numerico nello
    storico); se fornito, mostra la ricostruzione ex-post — vedi
    `EX_POST_RECONSTRUCTION_NOTE`."""
    summary = build_header_summary(rows, meta)
    state_chart = _png_to_img_tag(render_state_timeline_png(rows), "timeline stato BTC/ETH")
    staleness_chart = _png_to_img_tag(render_staleness_png(rows), "eta' snapshot alla raccolta")
    vol_section = _vol_reconstruction_section_html(vol_series_by_asset)

    return f"""
<h1>Dashboard shadow — regime layer (dati reali, generato in locale)</h1>

<h2>Riepilogo</h2>
<ul>
  <li><strong>collection_started_at:</strong> {escape(str(summary.collection_started_at))}</li>
  <li><strong>Righe totali:</strong> {summary.row_count}</li>
  <li><strong>Primo snapshot:</strong> {escape(summary.first_snapshot or "-")}</li>
  <li><strong>Ultimo snapshot:</strong> {escape(summary.last_snapshot or "-")}</li>
</ul>
<p><em>{escape(summary.declared_gap_note)}</em></p>

<h2>Data-sanity (smoke test del collector)</h2>
{_findings_html(findings)}

<h2>Vol EWMA — ricostruzione ex-post</h2>
{vol_section}

<h2>Timeline di stato (alto/basso vol) — BTC/ETH</h2>
{state_chart}

<h2>Età dello snapshot alla raccolta (staleness vissuta)</h2>
{staleness_chart}

<h2>Tabella derived (fatti + inferenza)</h2>
<p style="background:#eef; padding:0.6em; border:1px solid #99a;">{escape(LEVEL_EDGE_NOTE)}</p>
{_derived_table_html(rows)}
""".strip()
