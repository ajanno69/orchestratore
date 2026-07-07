"""Smoke test locale end-to-end per i due entrypoint runtime
(regime-daemon, wiring-loop) — ADR-037 §10. Esegue DAVVERO:

- `regime_daemon.main(["--dry-run", "--once", ...])`: fetch reale da OKX
  (endpoint pubblici, nessuna chiave), scrittura reale dello snapshot sul
  path locale passato.
- `wiring_loop.main(["--dry-run", "--once", ...])` tre volte, su tre stati
  del file di snapshot (l'ultimo scritto a mano, come accadrà nella
  sessione di deploy reale) per dimostrare i due alert reali (LAYER
  LAVORA, LAYER CIECO) attraverso il path CLI vero — non solo la logica
  pura già dimostrata al checkpoint 2.

Nessuna chiave, nessun token reale (`--dry-run` su entrambi: i canali
esterni sono doppioni che registrano soltanto), nessun deploy. Il
`regime-daemon` fa comunque fetch reali da OKX (pubblici, per costruzione
— ADR-037 §10: i dati di mercato non sono dietro dry-run)."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from components import regime_daemon, wiring_loop  # noqa: E402
from regime.store import RegimeStateStore, build_snapshot  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        print("=== Fase 1: regime-daemon --dry-run --once (fetch reale da OKX, nessuna chiave) ===")
        regime_daemon.main(
            [
                "--dry-run",
                "--once",
                "--state-dir",
                tmp,
                "--config",
                "config/regime.yaml",
            ]
        )
        store = RegimeStateStore(tmp)
        snapshot = store.read()
        print(f"Snapshot scritto DAVVERO dal daemon (dati di mercato reali di oggi): {snapshot}")

        print(
            "\n=== Fase 2: wiring-loop --dry-run --once sullo snapshot reale appena scritto ==="
        )
        wiring_loop.main(["--dry-run", "--once", "--state-dir", tmp])

        print(
            "\n=== Fase 3: wiring-loop --dry-run --once su uno snapshot high-vol "
            "scritto a mano (atteso: alert LAYER LAVORA) ==="
        )
        store.write(build_snapshot(False, True, True, now=datetime.utcnow()))
        wiring_loop.main(["--dry-run", "--once", "--state-dir", tmp])

        print(
            "\n=== Fase 4: wiring-loop --dry-run --once su uno snapshot stantio "
            "(atteso: alert LAYER CIECO) ==="
        )
        store.write(
            build_snapshot(False, True, True, now=datetime.utcnow() - timedelta(hours=3))
        )
        wiring_loop.main(
            ["--dry-run", "--once", "--state-dir", tmp, "--staleness-minutes", "60"]
        )

        print("\nSmoke test completato senza eccezioni.")


if __name__ == "__main__":
    main()
