from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from telethon import TelegramClient, functions, types, utils

from personal_mcp.config import Settings
from personal_mcp.domain import Chat, Message, MessengerError


class DemoBackend:
    """Fictional data only; never opens a network connection."""

    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.chats = [
            Chat("1001", "Игорь (демо)", username="igor_demo"),
            Chat("1002", "Александр (демо)", username="alex_demo"),
            Chat("9000", "Избранное (демо)"),
        ]
        self.items = [
            Message(1, "1001", now - timedelta(days=1), "Встречаемся завтра в 19:00.", sender_id="1001"),
            Message(
                2,
                "1001",
                now - timedelta(hours=3),
                "Адрес встречи: Москва, Лесная улица, 7. Кафе «Пример».",
                sender_id="1001",
            ),
            Message(
                3,
                "1001",
                now - timedelta(hours=2),
                "Спасибо, адрес сохранил.",
                sender_id="9000",
                outgoing=True,
            ),
            Message(
                4,
                "1002",
                now - timedelta(hours=5),
                "Договорились: прототип покажем в пятницу, документацию подготовлю я.",
                sender_id="1002",
            ),
            Message(
                5,
                "1002",
                now - timedelta(hours=4),
                "Я займусь MCP-сервером и поиском сообщений.",
                sender_id="9000",
                outgoing=True,
            ),
            Message(
                6,
                "9000",
                now - timedelta(hours=1),
                "Это вымышленные переписки для проверки LM Studio. Реальных отправок нет.",
                sender_id="9000",
                outgoing=True,
            ),
        ]
        self.deliveries: dict[int, Message] = {}

    async def status(self) -> dict:
        return {"authorized": False, "demo": True, "account": "Вымышленный аккаунт"}

    async def resolve_chat(self, chat_id: str) -> str:
        resolved = "9000" if chat_id == "me" else chat_id
        if resolved not in {chat.chat_id for chat in self.chats}:
            raise MessengerError("Демо-чат не найден. Сначала вызовите list_chats.")
        return resolved

    async def dialogs(self) -> list[Chat]:
        return list(self.chats)

    async def get_message(self, chat_id: str, message_id: int) -> Message | None:
        return next(
            (item for item in self.items if item.chat_id == chat_id and item.message_id == message_id),
            None,
        )

    async def messages(
        self,
        chat_id: str,
        limit: int,
        before_id: int,
        since: datetime | None,
        until: datetime | None,
        search: str | None,
    ) -> list[Message]:
        items = (
            message
            for message in sorted(self.items, key=lambda item: item.message_id, reverse=True)
            if message.chat_id == chat_id
            and (not before_id or message.message_id < before_id)
            and (since is None or message.date >= since)
            and (until is None or message.date < until)
            and (search is None or search.casefold() in message.text.casefold())
        )
        result = []
        for message in items:
            result.append(message)
            if len(result) == limit:
                break
        return result

    async def send(
        self,
        chat_id: str,
        text: str,
        reply_to: int | None,
        random_id: int,
    ) -> Message:
        if random_id in self.deliveries:
            return self.deliveries[random_id]
        if reply_to is not None and not any(
            message.message_id == reply_to and message.chat_id == chat_id for message in self.items
        ):
            raise MessengerError("Сообщение для ответа не найдено в выбранном демо-чате.")
        message = Message(
            message_id=max(item.message_id for item in self.items) + 1,
            chat_id=chat_id,
            date=datetime.now(UTC),
            text=text,
            sender_id="9000",
            outgoing=True,
            reply_to_message_id=reply_to,
        )
        self.items.append(message)
        self.deliveries[random_id] = message
        return message

    async def close(self) -> None:
        pass


class TelegramBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: TelegramClient | None = None
        self._lock = asyncio.Lock()
        self._self_id: str | None = None

    async def _connected(self) -> TelegramClient:
        async with self._lock:
            if self._client is not None and self._client.is_connected():
                return self._client
            if not self.settings.credentials_configured:
                raise MessengerError("Нет API ID/hash. Запустите локально: python -m personal_mcp login")
            if not self.settings.session_file.is_file():
                raise MessengerError("Нет сессии Telegram. Запустите: python -m personal_mcp login")
            client = self._client or make_client(self.settings)
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise MessengerError("Сессия Telegram истекла. Повторите локальную команду login.")
                me = await client.get_me()
                if me is None or me.bot:
                    raise MessengerError("Нужна сессия пользовательского аккаунта, а не бота.")
                self._self_id = str(me.id)
            except BaseException:
                await client.disconnect()
                raise
            self._client = client
            return client

    async def status(self) -> dict:
        if not self.settings.credentials_configured or not self.settings.session_file.is_file():
            return {"authorized": False, "demo": False, "next_step": "python -m personal_mcp login"}
        await self._connected()
        return {"authorized": True, "demo": False}

    async def resolve_chat(self, chat_id: str) -> str:
        await self._connected()
        return self._self_id if chat_id == "me" else chat_id

    async def dialogs(self) -> list[Chat]:
        client = await self._connected()
        chats = []
        async for dialog in client.iter_dialogs():
            chats.append(
                Chat(
                    chat_id=str(dialog.id),
                    title=dialog.name or "",
                    kind="private" if dialog.is_user else ("group" if dialog.is_group else "channel"),
                    username=getattr(dialog.entity, "username", None),
                    unread_count=dialog.unread_count,
                )
            )
        return chats

    @staticmethod
    def _message(message, chat_id: str) -> Message:
        media = type(message.media).__name__ if message.media else None
        peer = getattr(message, "peer_id", None)
        channel_id = getattr(peer, "channel_id", None)
        url = None
        if channel_id is not None:
            username = getattr(message.chat, "username", None)
            url = (
                f"https://t.me/{username}/{message.id}"
                if username
                else f"https://t.me/c/{channel_id}/{message.id}"
            )
        return Message(
            message_id=message.id,
            chat_id=chat_id,
            date=message.date,
            text=message.raw_text or "",
            sender_id=str(message.sender_id) if message.sender_id is not None else None,
            outgoing=bool(message.out),
            reply_to_message_id=message.reply_to_msg_id,
            media_type=media,
            url=url,
        )

    async def _peer(self, chat_id: str):
        client = await self._connected()
        try:
            return await client.get_input_entity(int(chat_id))
        except (ValueError, TypeError):
            raise MessengerError(
                "Чат не найден в сессии. Вызовите list_chats и используйте полученный chat_id."
            ) from None

    async def get_message(self, chat_id: str, message_id: int) -> Message | None:
        client = await self._connected()
        peer = await self._peer(chat_id)
        message = await client.get_messages(peer, ids=message_id)
        if message is None or isinstance(message, types.MessageEmpty):
            return None
        # For private chats, lookup by message ID alone is not restricted to the peer.
        if str(utils.get_peer_id(message.peer_id)) != chat_id:
            return None
        return self._message(message, chat_id)

    async def messages(
        self,
        chat_id: str,
        limit: int,
        before_id: int,
        since: datetime | None,
        until: datetime | None,
        search: str | None,
    ) -> list[Message]:
        client = await self._connected()
        peer = await self._peer(chat_id)
        result = []
        async for item in client.iter_messages(
            peer,
            limit=limit,
            offset_id=before_id,
            offset_date=until,
            search=search,
        ):
            if since is not None and item.date < since:
                break
            if until is not None and item.date >= until:
                continue
            result.append(self._message(item, chat_id))
        return result

    async def send(
        self,
        chat_id: str,
        text: str,
        reply_to: int | None,
        random_id: int,
    ) -> Message:
        client = await self._connected()
        peer = await self._peer(chat_id)
        # Supply a stable Telegram random_id so retries don't create a second send.
        request = functions.messages.SendMessageRequest(
            peer=peer,
            message=text,
            random_id=random_id,
            no_webpage=True,
            reply_to=types.InputReplyToMessage(reply_to_msg_id=reply_to) if reply_to else None,
        )
        updates = await client(request)
        if isinstance(updates, types.UpdateShortSentMessage):
            return Message(
                message_id=updates.id,
                chat_id=chat_id,
                date=updates.date,
                text=text,
                sender_id=self._self_id,
                outgoing=True,
                reply_to_message_id=reply_to,
            )
        # Match only the ID assigned to this particular random_id.
        matching_id = next(
            (
                update.id
                for update in getattr(updates, "updates", [])
                if isinstance(update, types.UpdateMessageID) and update.random_id == random_id
            ),
            None,
        )
        for update in getattr(updates, "updates", []):
            if isinstance(update, (types.UpdateNewMessage, types.UpdateNewChannelMessage)):
                message = update.message
                message_chat_id = str(utils.get_peer_id(message.peer_id))
                if message.id == matching_id and message_chat_id == chat_id:
                    return self._message(message, chat_id)
        raise MessengerError(
            "Telegram принял запрос, но ID отправки не распознан. "
            "Проверьте последние сообщения чата. Не повторяйте с новым request_id."
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None


def make_client(settings: Settings) -> TelegramClient:
    return TelegramClient(
        str(settings.session),
        settings.api_id,
        settings.api_hash,
        device_model="Personal Messenger MCP",
        app_version="0.1.0",
        request_retries=0,
        connection_retries=1,
        flood_sleep_threshold=0,
        receive_updates=False,
    )
