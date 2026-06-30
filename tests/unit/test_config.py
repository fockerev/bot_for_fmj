from pathlib import Path

from bot.modules.config import AppConfig


def test_loads_legacy_gpt_fallback(tmp_path: Path):
    path = tmp_path / "setting.yaml"
    path.write_text(
        """
gpt:
  ai_provider: openai
  openai_model: gpt-test
  max_token: 123
  temperature: 0.5
  image_resolution: 1
bot:
  history_size: 4
  default_system_promt: legacy prompt
""",
        encoding="utf-8",
    )

    config = AppConfig.load(path)

    assert config.agent.model == "gpt-test"
    assert config.agent.max_tokens == 123
    assert config.agent.image_detail == "high"
    assert config.bot.default_system_prompt == "legacy prompt"
    assert config.bot.save_failed_user_message is True
