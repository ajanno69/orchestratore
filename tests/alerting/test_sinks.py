from __future__ import annotations

import json

from alerting.sinks import (
    DryRunAlertSink,
    DryRunHealthcheckSink,
    HealthchecksPingSink,
    TelegramAlertSink,
)


def test_dry_run_alert_sink_records_text_and_does_not_raise():
    sink = DryRunAlertSink()
    sink.send("LAYER LAVORA — test")
    sink.send("LAYER CIECO — test")
    assert sink.sent == ["LAYER LAVORA — test", "LAYER CIECO — test"]


def test_dry_run_healthcheck_sink_records_ping_count():
    sink = DryRunHealthcheckSink()
    assert sink.ping_count == 0
    sink.ping()
    sink.ping()
    assert sink.ping_count == 2


def test_telegram_alert_sink_posts_expected_url_and_payload():
    calls = []

    def fake_post(url: str, data: bytes, headers: dict) -> None:
        calls.append({"url": url, "data": data, "headers": headers})

    sink = TelegramAlertSink(bot_token="TOKEN123", chat_id="CHAT456", http_post=fake_post)
    sink.send("ciao mondo")

    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.telegram.org/botTOKEN123/sendMessage"
    payload = json.loads(calls[0]["data"])
    assert payload["chat_id"] == "CHAT456"
    assert payload["text"] == "ciao mondo"
    assert payload["disable_web_page_preview"] is True
    assert calls[0]["headers"]["Content-Type"] == "application/json"


def test_telegram_alert_sink_propagates_transport_errors():
    def failing_post(url: str, data: bytes, headers: dict) -> None:
        raise ConnectionError("rete non raggiungibile")

    sink = TelegramAlertSink(bot_token="T", chat_id="C", http_post=failing_post)
    try:
        sink.send("qualunque testo")
        raised = False
    except ConnectionError:
        raised = True
    assert raised, "TelegramAlertSink deve propagare l'errore di trasporto, mai inghiottirlo"


def test_healthchecks_ping_sink_calls_expected_url():
    calls = []

    def fake_get(url: str) -> None:
        calls.append(url)

    sink = HealthchecksPingSink(url="https://hc-ping.com/abc-123", http_get=fake_get)
    sink.ping()

    assert calls == ["https://hc-ping.com/abc-123"]


def test_healthchecks_ping_sink_propagates_transport_errors():
    def failing_get(url: str) -> None:
        raise TimeoutError("timeout")

    sink = HealthchecksPingSink(url="https://hc-ping.com/abc-123", http_get=failing_get)
    try:
        sink.ping()
        raised = False
    except TimeoutError:
        raised = True
    assert raised, "HealthchecksPingSink deve propagare l'errore di trasporto, mai inghiottirlo"
