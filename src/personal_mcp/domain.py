from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

MAX_PAGE_SIZE = 30
MAX_QUERY_CHARS = 200
CHAT_ID_PATTERN = r"^(me|-?[0-9]+)$"
REQUEST_ID_PATTERN = r"^[A-Za-z0-9_.:-]{8,100}$"


class MessengerError(Exception):
    """An actionable message safe to return to a model."""


@dataclass(frozen=True)
class Chat:
    chat_id: str
    title: str
    kind: str = "private"
    username: str | None = None
    unread_count: int = 0


@dataclass(frozen=True)
class Message:
    message_id: int
    chat_id: str
    date: datetime
    text: str
    sender_id: str | None = None
    outgoing: bool = False
    reply_to_message_id: int | None = None
    media_type: str | None = None
    url: str | None = None


class Backend(Protocol):
    async def status(self) -> dict: ...
    async def resolve_chat(self, chat_id: str) -> str: ...
    async def dialogs(self) -> list[Chat]: ...
    async def get_message(self, chat_id: str, message_id: int) -> Message | None: ...
    async def messages(
        self,
        chat_id: str,
        limit: int,
        before_id: int,
        since: datetime | None,
        until: datetime | None,
        search: str | None,
    ) -> list[Message]: ...
    async def send(
        self,
        chat_id: str,
        text: str,
        reply_to: int | None,
        random_id: int,
    ) -> Message: ...
    async def close(self) -> None: ...
