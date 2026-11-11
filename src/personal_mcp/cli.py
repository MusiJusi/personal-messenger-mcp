from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import replace
from getpass import getpass

from dotenv import set_key

from personal_mcp.backends import DemoBackend, TelegramBackend, make_client
from personal_mcp.config import Settings
from personal_mcp.integration import configure_console, install_lmstudio, print_config
from personal_mcp.service import MessengerService


async def login(settings: Settings) -> None:
    print("Вход выполняется локально. Не присылайте API hash, код входа или пароль в чат.")
    api_id, api_hash = settings.api_id, settings.api_hash
    if not api_id:
        raw = (await asyncio.to_thread(input, "API ID с https://my.telegram.org/apps: ")).strip()
        if not raw.isdecimal() or int(raw) <= 0:
            raise ValueError("API ID должен быть положительным целым числом.")
        api_id = int(raw)
    if not api_hash:
        api_hash = (await asyncio.to_thread(getpass, "API hash (ввод скрыт): ")).strip()
    if len(api_hash) != 32 or any(c not in "0123456789abcdefABCDEF" for c in api_hash):
        raise ValueError("API hash должен содержать 32 шестнадцатеричных символа.")
    settings = replace(settings, api_id=api_id, api_hash=api_hash, mode="telegram")
    settings.session.parent.mkdir(parents=True, exist_ok=True)
    client = make_client(settings)

    async def phone_input() -> str:
        return (await asyncio.to_thread(input, "Телефон аккаунта в международном формате: ")).strip()

    async def code_input() -> str:
        return (await asyncio.to_thread(getpass, "Код входа из Telegram (ввод скрыт): ")).strip()

    async def password_input() -> str:
        return await asyncio.to_thread(getpass, "Пароль двухфакторной аутентификации (ввод скрыт): ")

    try:
        await client.start(
            phone=phone_input,
            code_callback=code_input,
            password=password_input,
        )
        me = await client.get_me()
        if me is None or me.bot:
            raise ValueError("Нужен пользовательский аккаунт, а не бот.")
        env_file = settings.root / ".env"
        if not env_file.exists():
            env_file.write_text("", encoding="utf-8")
        set_key(str(env_file), "TELEGRAM_API_ID", str(api_id))
        set_key(str(env_file), "TELEGRAM_API_HASH", api_hash)
        set_key(str(env_file), "MESSENGER_MODE", "telegram")
        print("Вход выполнен. Режим telegram сохранён в .env. Перезапустите MCP в LM Studio.")
    finally:
        await client.disconnect()


async def doctor(settings: Settings) -> None:
    backend = DemoBackend() if settings.mode == "demo" else TelegramBackend(settings)
    service = MessengerService(settings, backend)
    try:
        print(json.dumps(await service.status(), ensure_ascii=False, indent=2))
    finally:
        await service.close()


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="Personal Messenger MCP for LM Studio")
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve", "login", "doctor", "lmstudio-config", "install-lmstudio"],
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    try:
        if args.command == "lmstudio-config":
            print_config()
            return 0
        if args.command == "install-lmstudio":
            print(json.dumps(install_lmstudio(), ensure_ascii=False, indent=2))
            return 0
        settings = Settings.load()
        if args.command == "serve":
            from personal_mcp.server import create_server

            create_server(settings).run(transport="stdio")
        elif args.command == "login":
            asyncio.run(login(settings))
        else:
            asyncio.run(doctor(settings))
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Ошибка: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
