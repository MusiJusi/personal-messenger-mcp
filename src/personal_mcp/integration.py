from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from personal_mcp.config import PROJECT_ROOT

SERVER_KEY = "personal-messenger"


def lmstudio_entry(root: Path = PROJECT_ROOT) -> dict:
    return {
        "command": str(root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
        "args": [str(root / "run_server.py")],
        "env": {"PYTHONUTF8": "1"},
    }


def install_lmstudio(path: Path | None = None, root: Path = PROJECT_ROOT) -> dict:
    """Merge one entry, preserve other servers, and back up an existing configuration."""
    path = path or Path.home() / ".lmstudio" / "mcp.json"
    existing = path.read_text(encoding="utf-8-sig") if path.is_file() else None
    config = json.loads(existing) if existing is not None else {}
    if not isinstance(config, dict) or not isinstance(config.get("mcpServers", {}), dict):
        raise ValueError("mcp.json должен быть объектом с объектом mcpServers.")
    config.setdefault("mcpServers", {})[SERVER_KEY] = lmstudio_entry(root)
    new_text = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    if existing == new_text:
        return {"updated": False, "path": str(path)}
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if existing is not None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(f"mcp.json.backup-{timestamp}")
        backup.write_text(existing, encoding="utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix="mcp-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(new_text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"updated": True, "path": str(path), "backup": str(backup) if backup else None}


def print_config() -> None:
    print(json.dumps({"mcpServers": {SERVER_KEY: lmstudio_entry()}}, indent=2, ensure_ascii=False))


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
