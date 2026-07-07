"""CLI: pull read-only del DB di storia dal VPS + rendering di un report
HTML statico locale (sessione rendering 2026-07-07). VINCOLO SOVRANO:
nessuna modifica al VPS/al database remoto/alle unit — solo `export`
(Online Backup API, sola lettura) e `render` (locale).

Uso:
    python scripts/render_shadow_dashboard.py --ssh-host 207.180.247.38 --ssh-user freqbot

Richiede l'extra opzionale "dashboard" (matplotlib): `pip install -e ".[dashboard]"`.
MAI installato sul VPS — solo per questo script, in locale."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dashboard.export import export_history_db  # noqa: E402
from dashboard.queries import load_meta, load_rows, load_rows_by_insertion_order  # noqa: E402
from dashboard.render import render_html  # noqa: E402
from dashboard.sanity import run_all_checks  # noqa: E402
from dashboard.vol_reconstruction import VolSeries, reconstruct_vol_series  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "var" / "dashboard-output"


def _fetch_vol_reconstruction(config_path: str) -> dict[str, VolSeries]:
    """Fetch pubblico OKX indipendente + ricalcolo con lo stimatore già
    approvato (vedi `dashboard.vol_reconstruction`). Fallimento di rete/
    ccxt non deve far cadere l'intero render: il resto della dashboard
    (dati reali già raccolti dal collector) resta prezioso comunque —
    la sezione vol degrada alla nota sul limite dichiarato."""
    import ccxt

    from regime.config import load_regime_config

    regime_config = load_regime_config(config_path)
    exchange = ccxt.okx()
    series_by_asset: dict[str, VolSeries] = {}
    for asset in regime_config.vol_by_asset:
        try:
            series_by_asset[asset] = reconstruct_vol_series(exchange, asset, regime_config)
        except Exception as exc:  # noqa: BLE001 — degradazione, non un crash della dashboard
            print(f"  [avviso] ricostruzione ex-post vol {asset} fallita: {exc}")
    return series_by_asset


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Dashboard shadow — export + render locale")
    parser.add_argument("--ssh-host", default="207.180.247.38")
    parser.add_argument("--ssh-user", default="freqbot")
    parser.add_argument(
        "--remote-db-path", default="/opt/orchestrator/var/history/history.db"
    )
    parser.add_argument(
        "--local-db-path",
        default=None,
        help="se fornito, salta l'export via SSH e usa direttamente questo file locale",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR / "dashboard.html"))
    parser.add_argument(
        "--regime-config",
        default="config/regime.yaml",
        help="usato SOLO per la ricostruzione ex-post della vol (stessi span/soglie del daemon)",
    )
    parser.add_argument(
        "--skip-vol-reconstruction",
        action="store_true",
        help="salta il fetch OKX indipendente per il grafico vol ex-post",
    )
    args = parser.parse_args(argv)

    if args.local_db_path:
        db_path = Path(args.local_db_path)
        print(f"Uso DB locale già esportato: {db_path}")
    else:
        print(f"Export consistente (Online Backup API) da {args.ssh_user}@{args.ssh_host} ...")
        result = export_history_db(
            ssh_host=args.ssh_host,
            ssh_user=args.ssh_user,
            remote_db_path=args.remote_db_path,
            local_output_dir=DEFAULT_OUTPUT_DIR,
            now=datetime.now(UTC),
        )
        db_path = result.local_path
        print(f"  backup remoto: {result.backup_output.strip()}")
        print(f"  scaricato in: {db_path}")
        print(f"  temporaneo remoto rimosso: {result.remote_tmp_path}")

    rows = load_rows(db_path)
    rows_by_insertion = load_rows_by_insertion_order(db_path)
    meta = load_meta(db_path)
    findings = run_all_checks(rows, rows_by_insertion, meta)

    print(f"Righe caricate: {len(rows)}")
    print(f"Anomalie data-sanity: {len(findings)}")
    for finding in findings:
        print(f"  [{finding.severity}] {finding.check}: {finding.message}")

    vol_series_by_asset: dict[str, VolSeries] = {}
    if not args.skip_vol_reconstruction:
        print("Ricostruzione ex-post vol (fetch OKX indipendente) ...")
        vol_series_by_asset = _fetch_vol_reconstruction(args.regime_config)
        print(f"  asset ricostruiti: {sorted(vol_series_by_asset)}")

    html = render_html(rows, rows_by_insertion, meta, findings, vol_series_by_asset)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Report scritto in: {output_path}")


if __name__ == "__main__":
    main()
