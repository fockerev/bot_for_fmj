from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    pass


@dataclass
class AgentConfig:
    provider: str
    model: str
    max_tokens: int
    temperature: float
    image_detail: str


@dataclass
class BotConfig:
    history_size: int
    save_failed_user_message: bool
    default_system_prompt: str


@dataclass
class LoggingConfig:
    level: str
    file: str


@dataclass
class MCPServerConfig:
    name: str
    transport: str
    command: str
    args: list[str]
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    approval_mode: str = "never_require"
    request_timeout: int | None = 300


@dataclass
class MCPConfig:
    enabled: bool
    servers: list[MCPServerConfig] = field(default_factory=list)
    search_result_limit: int = 3


@dataclass
class AppConfig:
    agent: AgentConfig
    bot: BotConfig
    logging: LoggingConfig
    mcp: MCPConfig

    @classmethod
    def load(cls, path: Path | str) -> "AppConfig":
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"{config_path} is not found")

        try:
            with config_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid yaml: {config_path}") from exc

        try:
            agent_data = _agent_data(data)
            bot_data = _bot_data(data)
            logging_data = data.get("logging") or {}
            mcp_data = data.get("mcp") or {}
            _require(agent_data, "provider", "model", "max_tokens", "temperature", "image_detail")
            _require(bot_data, "history_size", "save_failed_user_message", "default_system_prompt")

            return cls(
                agent=AgentConfig(
                    provider=str(agent_data["provider"]),
                    model=str(agent_data["model"]),
                    max_tokens=int(agent_data["max_tokens"]),
                    temperature=float(agent_data["temperature"]),
                    image_detail=str(agent_data["image_detail"]),
                ),
                bot=BotConfig(
                    history_size=int(bot_data["history_size"]),
                    save_failed_user_message=bool(bot_data["save_failed_user_message"]),
                    default_system_prompt=str(bot_data["default_system_prompt"]),
                ),
                logging=LoggingConfig(
                    level=str(logging_data.get("level", "INFO")),
                    file=str(logging_data.get("file", "logs/bot.log")),
                ),
                mcp=_mcp_config(mcp_data),
            )
        except KeyError as exc:
            raise ConfigError(f"required config key missing: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise ConfigError("invalid config value") from exc


def _agent_data(data: dict[str, Any]) -> dict[str, Any]:
    agent = dict(data.get("agent") or {})
    gpt = data.get("gpt") or {}

    agent.setdefault("provider", gpt.get("ai_provider", "openai"))
    if "model" not in agent:
        provider = agent["provider"]
        agent["model"] = gpt.get("gemini_model") if provider == "gemini" else gpt.get("openai_model")
    agent.setdefault("max_tokens", gpt.get("max_token", 1600))
    agent.setdefault("temperature", gpt.get("temperature", 1.0))
    agent.setdefault("image_detail", _image_detail_from_legacy(gpt.get("image_resolution", 0)))
    return agent


def _bot_data(data: dict[str, Any]) -> dict[str, Any]:
    bot = dict(data.get("bot") or {})
    if "default_system_prompt" not in bot and "default_system_promt" in bot:
        bot["default_system_prompt"] = bot["default_system_promt"]
    bot.setdefault("history_size", 16)
    bot.setdefault("save_failed_user_message", True)
    return bot


def _mcp_config(data: dict[str, Any]) -> MCPConfig:
    enabled = bool(data.get("enabled", False))
    raw_servers = data.get("servers")
    if raw_servers is None:
        raw_servers = [_default_mcp_server_data(data)]
    servers = [_mcp_server_config(server_data) for server_data in list(raw_servers or [])]
    return MCPConfig(
        enabled=enabled,
        servers=servers,
        search_result_limit=int(data.get("search_result_limit", 3)),
    )


def _default_mcp_server_data(data: dict[str, Any]) -> dict[str, Any]:
    default_server = _xapi_stdio_defaults()
    for key in (
        "name",
        "transport",
        "command",
        "args",
        "url",
        "env",
        "headers",
        "allowed_tools",
        "approval_mode",
        "request_timeout",
    ):
        if key in data:
            default_server[key] = data[key]
    return default_server


def _mcp_server_config(data: dict[str, Any]) -> MCPServerConfig:
    server_data = _xapi_stdio_defaults()
    server_data.update(dict(data or {}))
    return MCPServerConfig(
        name=str(server_data["name"]),
        transport=str(server_data["transport"]),
        command=str(server_data.get("command", "")),
        args=list(server_data.get("args") or []),
        url=str(server_data["url"]) if server_data.get("url") else None,
        env={str(key): str(value) for key, value in dict(server_data.get("env") or {}).items()},
        headers={str(key): str(value) for key, value in dict(server_data.get("headers") or {}).items()},
        allowed_tools=[str(value) for value in list(server_data.get("allowed_tools") or [])],
        approval_mode=str(server_data.get("approval_mode", "never_require")),
        request_timeout=(
            int(server_data["request_timeout"]) if server_data.get("request_timeout") is not None else 300
        ),
    )


def _xapi_stdio_defaults() -> dict[str, Any]:
    return {
        "name": "xapi",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@xdevplatform/xurl", "mcp", "https://api.x.com/mcp"],
        "url": None,
        "env": {},
        "headers": {},
        "allowed_tools": [],
        "approval_mode": "never_require",
        "request_timeout": 300,
    }


def _image_detail_from_legacy(value: Any) -> str:
    if str(value) == "1":
        return "high"
    return "low"


def _require(data: dict[str, Any], *keys: str) -> None:
    for key in keys:
        if data.get(key) is None:
            raise KeyError(key)
