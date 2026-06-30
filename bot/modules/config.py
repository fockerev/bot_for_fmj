from __future__ import annotations

from dataclasses import dataclass
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
class MCPConfig:
    enabled: bool
    command: str
    args: list[str]
    search_result_limit: int


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
                mcp=MCPConfig(
                    enabled=bool(mcp_data.get("enabled", False)),
                    command=str(mcp_data.get("command", "node")),
                    args=list(mcp_data.get("args", [])),
                    search_result_limit=int(mcp_data.get("search_result_limit", 3)),
                ),
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


def _image_detail_from_legacy(value: Any) -> str:
    if str(value) == "1":
        return "high"
    return "low"


def _require(data: dict[str, Any], *keys: str) -> None:
    for key in keys:
        if data.get(key) is None:
            raise KeyError(key)
