"""Check the downloaded local model against real MCP tools, using demo data only."""

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from mcp import Client, StdioServerParameters

from personal_mcp.integration import configure_console

ROOT = Path(__file__).resolve().parents[1]


def completion(messages: list[dict], tools: list[dict], model: str) -> dict:
    body = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.2,
        "max_tokens": 2048,
        "stream": False,
        "reasoning": "off",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        "http://127.0.0.1:1234/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=180) as response:
        return json.load(response)


async def main(model: str, scenario: str) -> None:
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
    async with Client(parameters, mode="legacy") as client:
        catalog = await client.list_tools()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in catalog.tools
        ]
        prompt = (
            "Найди адрес встречи в переписке с Игорем. Используй инструменты, "
            "сначала узнай режим и найди нужный чат. Ответь по-русски, укажи ID сообщения."
            if scenario == "search"
            else "Отправь в моё Избранное сообщение «Проверка локального помощника». "
            "Используй инструменты и сообщи результат с ID сообщения. "
            "Это поручение на одну отправку."
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Ты личный помощник. Все данные этого теста вымышленные. "
                    "Сначала server_status. Получай факты через MCP. "
                    "Для отправки используй новый request_id вида local-test-20261107-001. "
                    "Не выдумывай вызовы или результаты. При mode=demo явно сообщи, что это демо."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        called = []
        simulated_send = False
        for step in range(1, 9):
            print(f"Model turn {step}: waiting for local inference...", flush=True)
            response = await asyncio.to_thread(completion, messages, tools, model)
            choice = response["choices"][0]
            answer = choice["message"]
            calls = answer.get("tool_calls") or []
            messages.append(
                {
                    key: value
                    for key, value in answer.items()
                    if key in {"role", "content", "tool_calls", "reasoning_content"}
                }
            )
            if not calls:
                text = answer.get("content") or ""
                print(text, flush=True)
                if not text:
                    raise RuntimeError(
                        f"Модель не вернула ответ (finish_reason={choice.get('finish_reason')})."
                    )
                if scenario == "search":
                    assert any(name in called for name in ("search_messages", "get_messages")), called
                    assert "Лесная" in text, text
                else:
                    assert simulated_send, "Нет подтверждённой имитации отправки через инструмент."
                print("PASS: " + " -> ".join(called), flush=True)
                return
            for call in calls:
                name = call["function"]["name"]
                arguments = json.loads(call["function"]["arguments"])
                print(f"MCP call: {name}", flush=True)
                result = await client.call_tool(name, arguments)
                called.append(name)
                payload = result.structured_content
                if payload is None:
                    payload = {"content": [block.model_dump(by_alias=True) for block in result.content]}
                if name == "send_message" and not result.is_error:
                    simulated_send = payload.get("simulated") is True
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                )
        raise RuntimeError("Модель не завершила задачу за 8 шагов.")


if __name__ == "__main__":
    configure_console()
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen/qwen3.5-9b")
    parser.add_argument("--scenario", choices=["search", "send"], default="search")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.model, args.scenario))
    except urllib.error.HTTPError as error:
        print(f"LM Studio HTTP {error.code}: {error.read().decode()}", file=sys.stderr)
        raise SystemExit(1) from None
