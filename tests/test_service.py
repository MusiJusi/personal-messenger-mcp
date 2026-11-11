import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from mcp import Client

from personal_mcp.backends import DemoBackend
from personal_mcp.config import Settings
from personal_mcp.domain import Chat, Message, MessengerError
from personal_mcp.server import create_server
from personal_mcp.service import MessengerService, parse_date

pytestmark = pytest.mark.anyio


async def test_chat_filter_pagination_does_not_skip_matching_chats():
    backend = DemoBackend()
    backend.chats = [Chat(str(i), f"Игорь {i}") for i in range(20)]
    service = MessengerService(Settings(), backend)
    page1 = await service.list_chats("игорь", limit=3)
    page2 = await service.list_chats(limit=3, offset=page1["next_offset"], snapshot_id=page1["snapshot_id"])
    assert [c["chat_id"] for c in page1["chats"] + page2["chats"]] == [str(i) for i in range(6)]


async def test_title_search_includes_chats_beyond_the_first_200():
    backend = DemoBackend()
    backend.chats = [Chat(str(i), f"Диалог {i}") for i in range(205)]
    backend.chats[-1] = Chat("204", "Игорь")
    service = MessengerService(Settings(), backend)
    result = await service.list_chats("игорь")
    assert result["chats"][0]["chat_id"] == "204"
    assert result["next_offset"] is None


async def test_chat_snapshot_survives_reordering_and_a_new_search():
    backend = DemoBackend()
    backend.chats = [Chat(str(i), f"Чат {i}") for i in range(1, 5)]
    backend.dialogs = AsyncMock(wraps=backend.dialogs)
    service = MessengerService(Settings(), backend)
    first = await service.list_chats(limit=2)

    # A new message moves chat 4 to the top of Telegram's current list.
    backend.chats[:] = [backend.chats[3], *backend.chats[:3]]
    second = await service.list_chats(
        limit=2,
        offset=first["next_offset"],
        snapshot_id=first["snapshot_id"],
    )
    assert [chat["chat_id"] for chat in first["chats"] + second["chats"]] == ["1", "2", "3", "4"]
    backend.dialogs.assert_awaited_once()

    fresh = await service.list_chats(limit=2)
    assert [chat["chat_id"] for chat in fresh["chats"]] == ["4", "1"]
    assert fresh["snapshot_id"] != first["snapshot_id"]
    old_page = await service.list_chats(limit=2, offset=2, snapshot_id=first["snapshot_id"])
    assert old_page["chats"] == second["chats"]


async def test_chat_pagination_rejects_missing_or_stale_snapshot():
    backend = DemoBackend()
    backend.dialogs = AsyncMock(wraps=backend.dialogs)
    service = MessengerService(Settings(), backend)
    with pytest.raises(MessengerError, match="snapshot_id"):
        await service.list_chats(offset=1)
    with pytest.raises(MessengerError, match="устарел"):
        await service.list_chats(snapshot_id="old-server-snapshot")
    backend.dialogs.assert_not_awaited()


async def test_chat_snapshot_is_not_reused_for_another_query():
    service = MessengerService(Settings(), DemoBackend())
    first = await service.list_chats(query="Игорь")
    with pytest.raises(MessengerError, match="нового query"):
        await service.list_chats(query="Александр", snapshot_id=first["snapshot_id"])


async def test_chat_snapshot_eviction_reports_that_search_must_restart():
    service = MessengerService(Settings(), DemoBackend())
    first = await service.list_chats()
    for _ in range(8):
        await service.list_chats()
    with pytest.raises(MessengerError, match="устарел"):
        await service.list_chats(offset=1, snapshot_id=first["snapshot_id"])


async def test_message_pages_have_no_gaps_or_repeats():
    service = MessengerService(Settings(), DemoBackend())
    first = await service.messages("1001", limit=1)
    second = await service.messages("1001", limit=2, before_message_id=first["next_before_message_id"])
    assert [m["message_id"] for m in first["messages"] + second["messages"]] == [3, 2, 1]
    assert second["next_before_message_id"] is None


async def test_date_boundaries_are_inclusive_since_and_exclusive_until():
    backend = DemoBackend()
    start = datetime(2026, 11, 7, tzinfo=UTC)
    backend.items = [
        Message(i + 1, "1001", date, f"адрес {i}")
        for i, date in enumerate([start - timedelta(seconds=1), start, start + timedelta(days=1)])
    ]
    service = MessengerService(Settings(), backend)
    result = await service.messages(
        "1001", since="2026-11-07T00:00:00Z", until="2026-11-08T00:00:00Z", query="адрес"
    )
    assert [m["message_id"] for m in result["messages"]] == [2]
    assert parse_date("2026-11-07", "Europe/Moscow").hour == 21
    with pytest.raises(MessengerError):
        await service.messages("1001", since="2026-11-08", until="2026-11-07")


async def test_message_budget_preserves_cursor_for_unreturned_messages():
    backend = DemoBackend()
    now = datetime.now(UTC)
    backend.items = [Message(i, "1001", now, "я" * 4000) for i in range(1, 21)]
    service = MessengerService(Settings(), backend)
    seen = []
    cursor = 0
    while True:
        page = await service.messages("1001", limit=30, before_message_id=cursor)
        assert all(message["text_truncated"] for message in page["messages"])
        seen.extend(message["message_id"] for message in page["messages"])
        cursor = page["next_before_message_id"]
        if cursor is None:
            break
    assert seen == list(range(20, 0, -1))


async def test_get_message_returns_the_text_truncated_in_a_list():
    backend = DemoBackend()
    text = "Начало " + "я" * 3000 + " ВАЖНЫЙ КОНЕЦ"
    backend.items = [Message(1, "1001", datetime.now(UTC), text)]
    service = MessengerService(Settings(), backend)
    page = await service.messages("1001")
    assert page["messages"][0]["text_truncated"] is True
    assert "ВАЖНЫЙ КОНЕЦ" not in page["messages"][0]["text"]
    full = await service.get_message(chat_id="1001", message_id=1)
    assert full["message"]["text"] == text
    assert full["message"]["next_text_offset"] is None


async def test_get_message_reads_all_long_text_in_bounded_chunks():
    backend = DemoBackend()
    text = "Начало " + "я" * 30000 + " КОНЕЦ"
    backend.items = [Message(1, "1001", datetime.now(UTC), text)]
    service = MessengerService(Settings(), backend)
    chunks = []
    offset = 0
    while offset is not None:
        result = await service.get_message(chat_id="1001", message_id=1, text_offset=offset)
        message = result["message"]
        assert len(message["text"]) <= 12000
        chunks.append(message["text"])
        offset = message["next_text_offset"]
    assert "".join(chunks) == text


async def test_get_message_rejects_missing_message_and_invalid_offsets():
    service = MessengerService(Settings(), DemoBackend())
    with pytest.raises(MessengerError, match="не найдено"):
        await service.get_message(chat_id="1001", message_id=99999)
    with pytest.raises(MessengerError, match="message_id"):
        await service.get_message(chat_id="1001", message_id=0)
    with pytest.raises(MessengerError, match="text_offset"):
        await service.get_message(chat_id="1001", message_id=1, text_offset=-1)


async def test_allowlist_applies_to_listing_reading_and_sending():
    service = MessengerService(Settings(allowed_chat_ids=frozenset({"1001"})), DemoBackend())
    result = await service.list_chats()
    assert [chat["chat_id"] for chat in result["chats"]] == ["1001"]
    with pytest.raises(MessengerError):
        await service.messages("1002")
    with pytest.raises(MessengerError):
        await service.get_message(chat_id="1002", message_id=4)
    with pytest.raises(MessengerError):
        await service.send_message("me", "test", "allowlist-test")


async def test_concurrent_retries_do_not_duplicate_send():
    backend = DemoBackend()
    service = MessengerService(Settings(), backend)
    results = await asyncio.gather(*[service.send_message("me", "Тест", "request-0001") for _ in range(4)])
    ids = {result["message"]["message_id"] for result in results}
    assert len(ids) == 1
    assert len(backend.deliveries) == 1
    assert all(result["simulated"] for result in results)
    with pytest.raises(MessengerError, match="другого текста"):
        await service.send_message("me", "Другой текст", "request-0001")


async def test_retry_after_restart_uses_same_telegram_random_id():
    backend = DemoBackend()
    first = await MessengerService(Settings(), backend).send_message("me", "Тест", "request-0002")
    second = await MessengerService(Settings(), backend).send_message("me", "Тест", "request-0002")
    assert first["message"]["message_id"] == second["message"]["message_id"]


async def test_send_validation_rejects_ambiguous_recipient_and_oversize_text():
    service = MessengerService(Settings(), DemoBackend())
    for recipient, text, key in [
        ("Игорь", "test", "request-0003"),
        ("me", " ", "request-0003"),
        ("me", "🙂" * 2049, "request-0003"),
        ("me", "test", "short"),
    ]:
        with pytest.raises(MessengerError):
            await service.send_message(recipient, text, key)


async def test_mcp_protocol_reports_actionable_errors_and_structured_results():
    server = create_server(Settings())
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("search_messages", {"chat_id": "1001", "query": "адрес"})
        assert not result.is_error
        assert 2 in {message["message_id"] for message in result.structured_content["messages"]}
        single = await client.call_tool("get_message", {"chat_id": "1001", "message_id": 2})
        assert not single.is_error
        assert "Лесная" in single.structured_content["message"]["text"]
        bad = await client.call_tool("get_messages", {"chat_id": "1001", "since": "yesterday"})
        assert bad.is_error
        assert "ISO 8601" in bad.content[0].text


async def test_readonly_excludes_sending_from_tool_catalog():
    server = create_server(replace(Settings(), read_only=True))
    async with Client(server) as client:
        tools = await client.list_tools()
        assert "send_message" not in {tool.name for tool in tools.tools}
        assert "get_message" in {tool.name for tool in tools.tools}
