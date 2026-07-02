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


def test_loads_x_mcp_defaults(tmp_path: Path):
    path = tmp_path / "setting.yaml"
    path.write_text(
        """
agent:
  provider: openai
  model: gpt-test
  max_tokens: 100
  temperature: 0.1
  image_detail: low
bot:
  history_size: 4
  save_failed_user_message: true
  default_system_prompt: system
""",
        encoding="utf-8",
    )

    config = AppConfig.load(path)

    assert config.mcp.enabled is False
    assert len(config.mcp.servers) == 1
    server = config.mcp.servers[0]
    assert server.name == "xapi"
    assert server.transport == "stdio"
    assert server.command == "npx"
    assert server.args == ["-y", "@xdevplatform/xurl", "mcp", "https://api.x.com/mcp"]
    assert server.request_timeout == 300
    assert server.headers == {}


def test_loads_x_mcp_env_mapping(tmp_path: Path):
    path = tmp_path / "setting.yaml"
    path.write_text(
        """
agent:
  provider: openai
  model: gpt-test
  max_tokens: 100
  temperature: 0.1
  image_detail: low
bot:
  history_size: 4
  save_failed_user_message: true
  default_system_prompt: system
mcp:
  enabled: true
  servers:
    - name: xapi
      transport: http
      url: https://api.x.com/mcp
      headers:
        Authorization: X_BEARER_TOKEN
    - name: filesystem
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
""",
        encoding="utf-8",
    )

    config = AppConfig.load(path)

    assert config.mcp.enabled is True
    assert len(config.mcp.servers) == 2
    assert config.mcp.servers[0].headers == {"Authorization": "X_BEARER_TOKEN"}
    assert config.mcp.servers[1].name == "filesystem"
    assert config.mcp.servers[1].args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]


def test_loads_legacy_single_mcp_server_shape(tmp_path: Path):
    path = tmp_path / "setting.yaml"
    path.write_text(
        """
agent:
  provider: openai
  model: gpt-test
  max_tokens: 100
  temperature: 0.1
  image_detail: low
bot:
  history_size: 4
  save_failed_user_message: true
  default_system_prompt: system
mcp:
  enabled: true
  transport: http
  url: https://api.x.com/mcp
  headers:
    Authorization: X_BEARER_TOKEN
""",
        encoding="utf-8",
    )

    config = AppConfig.load(path)

    assert len(config.mcp.servers) == 1
    assert config.mcp.servers[0].transport == "http"
    assert config.mcp.servers[0].headers == {"Authorization": "X_BEARER_TOKEN"}
