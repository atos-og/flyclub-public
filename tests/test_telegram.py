from __future__ import annotations

import json
from typing import Any

import pytest

from flyclub.alerts.telegram import (
    TelegramClient,
    TelegramConfigError,
    TelegramError,
    telegram_credentials_from_env,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_telegram_client_posts_current_bot_api_shape() -> None:
    captured: dict[str, Any] = {}

    def opener(request: Any, *, timeout: int) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse({"ok": True, "result": {"message_id": 123}})

    delivery = TelegramClient("test-token", "test-chat", opener=opener).send_message("Olá")

    request = captured["request"]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url.endswith("/bottest-token/sendMessage")
    assert payload == {
        "chat_id": "test-chat",
        "text": "Olá",
        "link_preview_options": {"is_disabled": True},
    }
    assert captured["timeout"] == 20
    assert delivery.message_id == "123"


def test_telegram_client_supports_html_without_enabling_it_by_default() -> None:
    captured: dict[str, Any] = {}

    def opener(request: Any, *, timeout: int) -> FakeResponse:
        captured["request"] = request
        return FakeResponse({"ok": True, "result": {"message_id": 124}})

    TelegramClient("test-token", "test-chat", opener=opener).send_message(
        '🔗 <a href="https://example.com">Ver oferta</a>',
        parse_mode="HTML",
    )

    payload = json.loads(captured["request"].data.decode("utf-8"))
    assert payload["parse_mode"] == "HTML"


def test_telegram_errors_never_echo_token_or_private_response() -> None:
    token = "super-secret-token"
    private_response = "private-api-description"

    def opener(*_args: object, **_kwargs: object) -> FakeResponse:
        raise RuntimeError(f"{token} {private_response}")

    with pytest.raises(TelegramError) as captured:
        TelegramClient(token, "chat", opener=opener).send_message("test")

    assert token not in str(captured.value)
    assert private_response not in str(captured.value)


def test_telegram_rejection_is_sanitized() -> None:
    def opener(*_args: object, **_kwargs: object) -> FakeResponse:
        return FakeResponse({"ok": False, "description": "private rejection detail"})

    with pytest.raises(TelegramError, match="rejected") as captured:
        TelegramClient("token", "chat", opener=opener).send_message("test")

    assert "private rejection detail" not in str(captured.value)


def test_telegram_credentials_require_both_environment_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    with pytest.raises(TelegramConfigError, match="not configured"):
        telegram_credentials_from_env()


def test_telegram_message_length_is_bounded() -> None:
    client = TelegramClient("token", "chat")

    with pytest.raises(ValueError, match="4096"):
        client.send_message("x" * 4097)
