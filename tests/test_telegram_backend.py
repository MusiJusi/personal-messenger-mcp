from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from telethon import types, utils
from telethon.errors import FloodWaitError

from personal_mcp.backends import TelegramBackend
from personal_mcp.config import Settings
from personal_mcp.domain import MessengerError
from personal_mcp.server import invoke

pytestmark = pytest.mark.anyio


async def test_missing_credentials_do_not_attempt_interactive_login_or_create_session(tmp_path):
    backend = TelegramBackend(Settings(mode="telegram", session=tmp_path / "account"))
    with pytest.raises(MessengerError, match="API ID"):
        await backend.resolve_chat("me")
    assert list(tmp_path.iterdir()) == []


async def test_history_passes_cursor_search_and_date_to_telegram(monkeypatch):
    now = datetime.now(UTC)
    source = [
        SimpleNamespace(
            id=i,
            date=now,
            raw_text=f"message {i}",
            media=None,
            sender_id=4,
            out=False,
            reply_to_msg_id=None,
            chat=None,
        )
        for i in (12, 11)
    ]
    arguments = {}

    async def iterator(peer, **kwargs):
        arguments.update(kwargs)
        for message in source:
            yield message

    client = SimpleNamespace(iter_messages=iterator, get_input_entity=AsyncMock(return_value="peer"))
    backend = TelegramBackend(Settings())
    monkeypatch.setattr(backend, "_connected", AsyncMock(return_value=client))
    result = await backend.messages("1001", 3, 20, None, now, "test")
    assert arguments == {"limit": 3, "offset_id": 20, "offset_date": now, "search": "test"}
    assert result == []  # until is exclusive, including when Telegram returns an equal timestamp.


async def test_send_uses_stable_random_id_and_exact_reply_target(monkeypatch):
    client = AsyncMock()
    client.get_input_entity.return_value = types.InputPeerUser(user_id=1001, access_hash=123)
    client.return_value = types.UpdateShortSentMessage(
        id=42,
        pts=1,
        pts_count=1,
        date=datetime.now(UTC),
        out=True,
    )
    backend = TelegramBackend(Settings())
    monkeypatch.setattr(backend, "_connected", AsyncMock(return_value=client))
    result = await backend.send("1001", "Текст без Markdown", 12, 98765)
    request = client.call_args.args[0]
    assert request.random_id == 98765
    assert request.reply_to.reply_to_msg_id == 12
    assert request.message == "Текст без Markdown"
    assert request.entities is None
    assert result.message_id == 42


@pytest.mark.parametrize("include_target", [True, False])
async def test_send_matches_both_channel_and_message_id(monkeypatch, include_target):
    now = datetime.now(UTC)
    target = types.PeerChannel(channel_id=1001)
    other = types.PeerChannel(channel_id=2002)
    wrong = types.Message(id=42, peer_id=other, date=now, message="Другой канал", out=True)
    correct = types.Message(id=42, peer_id=target, date=now, message="Нужный текст", out=True)
    updates = [
        types.UpdateMessageID(id=42, random_id=98765),
        types.UpdateNewChannelMessage(message=wrong, pts=1, pts_count=1),
    ]
    if include_target:
        updates.append(types.UpdateNewChannelMessage(message=correct, pts=2, pts_count=1))
    client = AsyncMock()
    client.get_input_entity.return_value = types.InputPeerChannel(channel_id=1001, access_hash=123)
    client.return_value = types.Updates(updates=updates, users=[], chats=[], date=now, seq=1)
    backend = TelegramBackend(Settings())
    monkeypatch.setattr(backend, "_connected", AsyncMock(return_value=client))
    chat_id = str(utils.get_peer_id(target))
    if include_target:
        result = await backend.send(chat_id=chat_id, text="Нужный текст", reply_to=None, random_id=98765)
        assert result.text == "Нужный текст"
        assert result.chat_id == chat_id
    else:
        with pytest.raises(MessengerError, match="не распознан"):
            await backend.send(chat_id=chat_id, text="Нужный текст", reply_to=None, random_id=98765)


@pytest.mark.parametrize("found", ["correct", "wrong_chat", "missing", "deleted"])
async def test_get_message_only_returns_a_message_from_the_requested_chat(monkeypatch, found):
    peer = types.InputPeerUser(user_id=1001, access_hash=123)
    message = types.Message(
        id=42,
        peer_id=types.PeerUser(user_id=2002 if found == "wrong_chat" else 1001),
        date=datetime.now(UTC),
        message="Полный текст",
    )
    if found == "missing":
        message = None
    elif found == "deleted":
        message = types.MessageEmpty(id=42, peer_id=types.PeerUser(user_id=1001))
    client = SimpleNamespace(
        get_input_entity=AsyncMock(return_value=peer),
        get_messages=AsyncMock(return_value=message),
    )
    backend = TelegramBackend(Settings())
    monkeypatch.setattr(backend, "_connected", AsyncMock(return_value=client))
    result = await backend.get_message(chat_id="1001", message_id=42)
    if found == "correct":
        assert result.text == "Полный текст"
    else:
        assert result is None
    client.get_messages.assert_awaited_once_with(peer, ids=42)


async def test_flood_wait_returns_actionable_error_without_silently_sleeping():
    async def limited():
        raise FloodWaitError(request=None, capture=23)

    with pytest.raises(ToolError, match="23"):
        await invoke(limited())
