from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .chat_models import parse_datetime, utc_now
from .config import AppConfig


@dataclass
class GuildSpecificConfig:
    guild_id: int
    provider: str | None = None
    model: str | None = None
    custom_system_prompt: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.astimezone(timezone.utc).isoformat()
        data["updated_at"] = self.updated_at.astimezone(timezone.utc).isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_provider: str = "openai") -> "GuildSpecificConfig":
        normalized = _normalize_legacy_config(data, default_provider)
        return cls(
            guild_id=int(normalized["guild_id"]),
            provider=normalized.get("provider"),
            model=normalized.get("model"),
            custom_system_prompt=normalized.get("custom_system_prompt"),
            created_at=parse_datetime(normalized.get("created_at")),
            updated_at=parse_datetime(normalized.get("updated_at")),
        )


@dataclass
class EffectiveGuildConfig:
    guild_id: int
    provider: str
    model: str
    custom_system_prompt: str | None
    system_prompt: str
    max_tokens: int
    temperature: float
    image_detail: str
    history_size: int


class GuildConfigManager:
    def __init__(self, default_config: AppConfig, data_dir: Path | str = "data", logger: logging.Logger | None = None):
        self.default_config = default_config
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "guild_configs.json"
        self.logger = logger or logging.getLogger(__name__)
        self.guild_configs: dict[int, GuildSpecificConfig] = {}
        self._load_guild_configs()

    def _load_guild_configs(self) -> None:
        if not self.config_file.exists():
            return
        try:
            with self.config_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for guild_id_str, config_data in data.items():
                config_data.setdefault("guild_id", int(guild_id_str))
                config = GuildSpecificConfig.from_dict(config_data, self.default_config.agent.provider)
                self.guild_configs[config.guild_id] = config
            self._save_guild_configs()
            self.logger.info("Loaded %s guild configurations", len(self.guild_configs))
        except Exception as exc:
            self.logger.error("Failed to load guild configurations: %s", exc)
            self.guild_configs = {}

    def _save_guild_configs(self) -> None:
        data = {str(guild_id): config.to_dict() for guild_id, config in self.guild_configs.items()}
        with self.config_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_effective_config(self, guild_id: int) -> EffectiveGuildConfig:
        guild_config = self.guild_configs.get(guild_id)
        provider = guild_config.provider if guild_config and guild_config.provider else self.default_config.agent.provider
        model = guild_config.model if guild_config and guild_config.model else self.default_config.agent.model
        custom_prompt = guild_config.custom_system_prompt if guild_config else None
        system_prompt = custom_prompt or self.default_config.bot.default_system_prompt
        return EffectiveGuildConfig(
            guild_id=guild_id,
            provider=provider,
            model=model,
            custom_system_prompt=custom_prompt,
            system_prompt=system_prompt,
            max_tokens=self.default_config.agent.max_tokens,
            temperature=self.default_config.agent.temperature,
            image_detail=self.default_config.agent.image_detail,
            history_size=self.default_config.bot.history_size,
        )

    def update_guild_config(self, guild_id: int, **kwargs) -> bool:
        try:
            now = utc_now()
            config = self.guild_configs.get(guild_id)
            if config is None:
                config = GuildSpecificConfig(guild_id=guild_id, created_at=now, updated_at=now)
                self.guild_configs[guild_id] = config

            for key in ("provider", "model", "custom_system_prompt"):
                if key in kwargs:
                    setattr(config, key, kwargs[key])
            config.updated_at = now

            if not config.provider and not config.model and not config.custom_system_prompt:
                self.guild_configs.pop(guild_id, None)

            self._save_guild_configs()
            return True
        except Exception as exc:
            self.logger.error("Failed to update guild config for %s: %s", guild_id, exc)
            return False

    def reset_guild_config(self, guild_id: int) -> bool:
        try:
            self.guild_configs.pop(guild_id, None)
            self._save_guild_configs()
            return True
        except Exception as exc:
            self.logger.error("Failed to reset guild config for %s: %s", guild_id, exc)
            return False

    def get_guild_config(self, guild_id: int) -> GuildSpecificConfig | None:
        return self.guild_configs.get(guild_id)


def _normalize_legacy_config(data: dict[str, Any], default_provider: str) -> dict[str, Any]:
    normalized = dict(data)
    if "provider" not in normalized and "ai_provider" in normalized:
        provider = normalized.get("ai_provider")
        if isinstance(provider, dict):
            provider = provider.get("value")
        normalized["provider"] = provider
    provider = normalized.get("provider") or default_provider
    if "model" not in normalized:
        if provider == "gemini":
            normalized["model"] = normalized.get("gemini_model")
        else:
            normalized["model"] = normalized.get("openai_model")
    return normalized
