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

MISSING_NUMERIC_VOL_NOTE = (
    "Lo schema attuale non persiste il VALORE NUMERICO dell'EWMA vol calcolato da "
    "regime-daemon a ogni ciclo — solo lo stato booleano derivato (alto/basso). Il "
    "valore numerico non è mai scritto da nessuna parte (nemmeno in "
    "regime_state.json), quindi il grafico \"vol nel tempo con soglie enter/exit\" "
    "non è costruibile con i dati oggi disponibili. Sotto: la timeline di stato, "
    "che è tutto ciò che lo storico contiene. Estendere lo schema del collector per "
    "catturare anche il valore numerico è una decisione di schema separata, non presa qui."
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
) -> str:
    """Ritorna il contenuto HTML (senza scheletro `<html>`/`<head>`/`<body>`
    — solo il contenuto, coerente con come questo repo pubblica pagine)."""
    summary = build_header_summary(rows, meta)
    state_chart = _png_to_img_tag(render_state_timeline_png(rows), "timeline stato BTC/ETH")
    staleness_chart = _png_to_img_tag(render_staleness_png(rows), "eta' snapshot alla raccolta")

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

<h2>Limite dichiarato: nessuna vol numerica nello storico</h2>
<p style="background:#fff3cd; padding:0.6em; border:1px solid #d0a000;">
{escape(MISSING_NUMERIC_VOL_NOTE)}
</p>

<h2>Timeline di stato (alto/basso vol) — BTC/ETH</h2>
{state_chart}

<h2>Età dello snapshot alla raccolta (staleness vissuta)</h2>
{staleness_chart}

<h2>Tabella derived (fatti + inferenza)</h2>
<p style="background:#eef; padding:0.6em; border:1px solid #99a;">{escape(LEVEL_EDGE_NOTE)}</p>
{_derived_table_html(rows)}
""".strip()
