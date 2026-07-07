"""Canali esterni (Telegram, healthchecks.io) dietro un'interfaccia
iniettabile (ADR-037 §10): entrambi gli entrypoint runtime (regime-daemon,
wiring-loop) devono poter girare end-to-end in locale con `--dry-run`,
senza alcun token reale. I doppioni dry-run qui sotto sono quel confine —
mai un `if dry_run: ...` sparso nel codice di dominio, sempre un
`AlertSink`/`HealthcheckSink` iniettato dal chiamante."""

from __future__ import annotations

import json
import urllib.request
from typing import Protocol


class AlertSink(Protocol):
    def send(self, text: str) -> None: ...


class HealthcheckSink(Protocol):
    def ping(self) -> None: ...


class DryRunAlertSink:
    """Registra i messaggi invece di inviarli — per smoke test locali e
    per la suite di test, mai per produzione."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)
        print(f"[DRY-RUN ALERT] {text}")


class DryRunHealthcheckSink:
    """Conta i ping invece di eseguirli davvero — stesso scopo di
    `DryRunAlertSink`."""

    def __init__(self) -> None:
        self.ping_count = 0

    def ping(self) -> None:
        self.ping_count += 1
        print(f"[DRY-RUN PING] #{self.ping_count}")


def _urllib_post(url: str, data: bytes, headers: dict) -> None:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def _urllib_get(url: str) -> None:
    with urllib.request.urlopen(url, timeout=10) as response:
        response.read()


class TelegramAlertSink:
    """Implementazione reale — POST a `api.telegram.org`, nessuna nuova
    dipendenza (solo stdlib `urllib`). `http_post` è iniettabile per i test
    (il confine testabile è la funzione di trasporto, non il client HTTP
    interno) — di default usa `urllib.request` vero. Qualunque errore di
    trasporto viene propagato, mai inghiottito: un fallimento di invio
    alert deve essere visibile al chiamante (loop di produzione), non
    sparire in silenzio."""

    def __init__(self, bot_token: str, chat_id: str, http_post=_urllib_post) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._http_post = http_post

    def send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = json.dumps(
            {
                "chat_id": self._chat_id,
                "text": text,
                "disable_web_page_preview": True,
            }
        ).encode("utf-8")
        self._http_post(url, payload, {"Content-Type": "application/json"})


class HealthchecksPingSink:
    """Implementazione reale — GET all'URL di ping di healthchecks.io
    (pattern VIVO-MA-CIECO già in uso da funding-harvester, sola lettura
    di riferimento). `http_get` iniettabile per gli stessi motivi di
    `TelegramAlertSink`."""

    def __init__(self, url: str, http_get=_urllib_get) -> None:
        self._url = url
        self._http_get = http_get

    def ping(self) -> None:
        self._http_get(self._url)
