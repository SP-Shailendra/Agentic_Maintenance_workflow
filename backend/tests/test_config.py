from pathlib import Path

from app.config import Settings


def test_settings_environment_overrides_dotenv(monkeypatch, tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("HITL_MIN_CONFIDENCE=0.73\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", dotenv)
    monkeypatch.setenv("HITL_MIN_CONFIDENCE", "0.91")

    assert Settings().hitl_min_confidence == 0.91


def test_settings_read_dotenv_when_environment_is_unset(monkeypatch, tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("HITL_MIN_CONFIDENCE=0.73\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", dotenv)
    monkeypatch.delenv("HITL_MIN_CONFIDENCE", raising=False)

    assert Settings().hitl_min_confidence == 0.73