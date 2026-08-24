"""Minimal, sanitized Telegram Bot API client using the Python standard library."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ID_ENV = "TELEGRAM_CHAT_ID"


class TelegramError(RuntimeError):
    """Telegram delivery failed without exposing credentials or private API responses."""


class TelegramConfigError(TelegramError):
    """Required Telegram credentials are missing."""


@dataclass(frozen=True, slots=True)
class TelegramDelivery:
    message_id: str


def telegram_credentials_from_env() -> tuple[str, str]:
    token = os.environ.get(BOT_TOKEN_ENV, "").strip()
    chat_id = os.environ.get(CHAT_ID_ENV, "").strip()
    if not token or not chat_id:
        raise TelegramConfigError("Telegram credentials are not configured")
    return token, chat_id


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout_seconds: int = 20,
    ) -> None:
        if not bot_token or not chat_id:
            raise TelegramConfigError("Telegram credentials are not configured")
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._opener = opener
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> TelegramClient:
        return cls(*telegram_credentials_from_env())

    def send_message(self, text: str, *, parse_mode: str | None = None) -> TelegramDelivery:
        if not 1 <= len(text) <= 4096:
            raise ValueError("Telegram text must contain between 1 and 4096 characters")
        payload_data = {
            "chat_id": self._chat_id,
            "text": text,
            "link_preview_options": {"is_disabled": True},
        }
        if parse_mode is not None:
            payload_data["parse_mode"] = parse_mode
        payload = json.dumps(payload_data).encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise TelegramError(f"Telegram request failed ({type(error).__name__})") from None

        message_id = decoded.get("result", {}).get("message_id") if decoded.get("ok") else None
        if message_id is None:
            raise TelegramError("Telegram rejected the message")
        return TelegramDelivery(message_id=str(message_id))
