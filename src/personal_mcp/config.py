from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    root: Path = PROJECT_ROOT
    mode: str = "demo"
    api_id: int | None = None
    api_hash: str = field(default="", repr=False)
    session: Path = PROJECT_ROOT / ".state" / "account"
    timezone: str = "Europe/Moscow"
    allowed_chat_ids: frozenset[str] = frozenset()
    read_only: bool = False

    @property
    def session_file(self) -> Path:
        return Path(f"{self.session}.session")

    @property
    def credentials_configured(self) -> bool:
        return bool(self.api_id and self.api_hash)

    @classmethod
    def load(cls, root: Path = PROJECT_ROOT) -> Settings:
        root = root.resolve()
        values = {**dotenv_values(root / ".env"), **os.environ}
        mode = (values.get("MESSENGER_MODE") or "demo").strip().lower()
        if mode not in {"demo", "telegram"}:
            raise ValueError("MESSENGER_MODE должен быть demo или telegram.")
        raw_id = (values.get("TELEGRAM_API_ID") or "").strip()
        if raw_id and (not raw_id.isdecimal() or int(raw_id) <= 0):
            raise ValueError("TELEGRAM_API_ID должен быть положительным целым числом.")
        api_hash = (values.get("TELEGRAM_API_HASH") or "").strip()
        if api_hash and (len(api_hash) != 32 or any(c not in "0123456789abcdefABCDEF" for c in api_hash)):
            raise ValueError("TELEGRAM_API_HASH должен содержать 32 шестнадцатеричных символа.")
        session = Path(values.get("TELEGRAM_SESSION") or ".state/account").expanduser()
        if session.suffix == ".session":
            session = session.with_suffix("")
        if not session.is_absolute():
            session = root / session
        timezone = (values.get("MESSENGER_TIMEZONE") or "Europe/Moscow").strip()
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            raise ValueError(f"Неизвестный часовой пояс: {timezone}.") from None
        allowed = frozenset(
            part.strip()
            for part in (values.get("TELEGRAM_ALLOWED_CHAT_IDS") or "").split(",")
            if part.strip()
        )
        if any(not value.lstrip("-").isdecimal() for value in allowed):
            raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS должен содержать числовые ID через запятую.")
        raw_read_only = (values.get("TELEGRAM_READ_ONLY") or "false").strip().lower()
        if raw_read_only not in {"true", "false"}:
            raise ValueError("TELEGRAM_READ_ONLY должен быть true или false.")
        return cls(
            root=root,
            mode=mode,
            api_id=int(raw_id) if raw_id else None,
            api_hash=api_hash,
            session=session.resolve(),
            timezone=timezone,
            allowed_chat_ids=allowed,
            read_only=raw_read_only == "true",
        )
