import json
from pathlib import Path

import pytest

from personal_mcp.config import Settings
from personal_mcp.integration import install_lmstudio


def test_dotenv_is_project_relative_and_environment_overrides(tmp_path, monkeypatch):
    monkeypatch.delenv("MESSENGER_MODE", raising=False)
    monkeypatch.delenv("TELEGRAM_SESSION", raising=False)
    (tmp_path / ".env").write_text(
        "MESSENGER_MODE=demo\nTELEGRAM_SESSION=.state/test.session\n", encoding="utf-8"
    )
    settings = Settings.load(tmp_path)
    assert settings.session_file == tmp_path / ".state" / "test.session"
    monkeypatch.setenv("MESSENGER_MODE", "telegram")
    assert Settings.load(tmp_path).mode == "telegram"


def test_secrets_are_not_in_configuration_repr():
    settings = Settings(api_hash="a" * 32)
    assert "a" * 32 not in repr(settings)


def test_install_preserves_other_servers_and_backs_up_exact_original(tmp_path):
    target = tmp_path / "mcp.json"
    original = '{"mcpServers":{"existing":{"command":"keep-me"}},"other":42}'
    target.write_text(original, encoding="utf-8")
    result = install_lmstudio(target, tmp_path)
    config = json.loads(target.read_text(encoding="utf-8"))
    assert config["mcpServers"]["existing"]["command"] == "keep-me"
    assert config["other"] == 42
    assert config["mcpServers"]["personal-messenger"]["args"] == [str(tmp_path / "run_server.py")]
    assert Path(result["backup"]).read_text(encoding="utf-8") == original
    assert install_lmstudio(target, tmp_path)["updated"] is False


@pytest.mark.parametrize("original", ["not json", "[]", '{"mcpServers": []}'])
def test_invalid_lmstudio_config_is_never_overwritten(tmp_path, original):
    target = tmp_path / "mcp.json"
    target.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        install_lmstudio(target, tmp_path)
    assert target.read_text(encoding="utf-8") == original
