"""Exercise the real stdio transport in both protocol eras, with fictional data."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def check(mode: str) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "run_server.py")],
        cwd=str(ROOT),
        env={
            "MESSENGER_MODE": "demo",
            "PYTHONUTF8": "1",
            "TELEGRAM_READ_ONLY": "false",
            "TELEGRAM_ALLOWED_CHAT_IDS": "",
        },
    )
    async with Client(parameters, mode=mode, read_timeout_seconds=15) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert names == {
            "server_status",
            "list_chats",
            "get_messages",
            "get_message",
            "search_messages",
            "send_message",
        }, names
        status = await client.call_tool("server_status", {})
        assert not status.is_error, status
        assert status.structured_content["mode"] == "demo"
        first = await client.call_tool("list_chats", {"limit": 1})
        assert not first.is_error, first
        page = first.structured_content
        second = await client.call_tool(
            "list_chats",
            {"limit": 1, "offset": page["next_offset"], "snapshot_id": page["snapshot_id"]},
        )
        assert not second.is_error, second
        assert second.structured_content["chats"][0]["chat_id"] != page["chats"][0]["chat_id"]
        found = await client.call_tool("search_messages", {"chat_id": "1001", "query": "адрес"})
        assert not found.is_error, found
        assert "Лесная" in json.dumps(found.structured_content, ensure_ascii=False)
        single = await client.call_tool("get_message", {"chat_id": "1001", "message_id": 2})
        assert not single.is_error, single
        assert "Лесная" in single.structured_content["message"]["text"]
        bad = await client.call_tool("get_messages", {"chat_id": "Игорь"})
        assert bad.is_error, bad
        sent = await client.call_tool(
            "send_message",
            {
                "chat_id": "me",
                "text": "Проверка без реальной отправки.",
                "request_id": "smoke-test-001",
            },
        )
        assert not sent.is_error, sent
        assert sent.structured_content["simulated"] is True
        print(f"OK: {mode}, protocol={client.protocol_version}, tools={len(names)}", flush=True)


async def main() -> None:
    for mode in ("legacy", "auto"):
        await check(mode)


if __name__ == "__main__":
    asyncio.run(main())
