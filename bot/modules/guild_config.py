import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from config import AppConfig, AIProvider


@dataclass
class GuildSpecificConfig:
    """Discord server specific configuration"""
    guild_id: int
    ai_provider: Optional[AIProvider] = None
    openai_model: Optional[str] = None
    gemini_model: Optional[str] = None
    custom_system_prompt: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        data = asdict(self)
        # Convert datetime objects to ISO strings
        data['created_at'] = self.created_at.isoformat()
        data['updated_at'] = self.updated_at.isoformat()
        # Convert enum to string
        if self.ai_provider:
            data['ai_provider'] = self.ai_provider.value
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'GuildSpecificConfig':
        """Create from dictionary (JSON deserialization)"""
        # Convert datetime strings back to datetime objects
        if 'created_at' in data and isinstance(data['created_at'], str):
            data['created_at'] = datetime.fromisoformat(data['created_at'])
        if 'updated_at' in data and isinstance(data['updated_at'], str):
            data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        # Convert string back to enum
        if 'ai_provider' in data and isinstance(data['ai_provider'], str):
            data['ai_provider'] = AIProvider(data['ai_provider'])
        return cls(**data)


@dataclass
class EffectiveGuildConfig:
    """Effective configuration combining guild-specific and default settings"""
    guild_id: int
    ai_provider: AIProvider
    openai_model: str
    gemini_model: str
    custom_system_prompt: Optional[str]
    max_token: int
    temperature: float
    image_resolution: int
    history_size: int
    default_system_prompt: str


class GuildConfigManager:
    """Manager for per-guild configuration settings"""
    
    def __init__(self, default_config: AppConfig, data_dir: str = "data"):
        self.default_config = default_config
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "guild_configs.json"
        self.guild_configs: Dict[int, GuildSpecificConfig] = {}
        self.logger = logging.getLogger(__name__)
        
        self._load_guild_configs()
    
    def _load_guild_configs(self):
        """Load guild configurations from JSON file"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for guild_id_str, config_data in data.items():
                        guild_id = int(guild_id_str)
                        self.guild_configs[guild_id] = GuildSpecificConfig.from_dict(config_data)
                self.logger.info(f"Loaded {len(self.guild_configs)} guild configurations")
            else:
                self.logger.info("No existing guild configurations found - starting fresh")
        except Exception as e:
            self.logger.error(f"Failed to load guild configurations: {e}")
            self.guild_configs = {}
    
    def _save_guild_configs(self):
        """Save guild configurations to JSON file"""
        try:
            data = {}
            for guild_id, config in self.guild_configs.items():
                data[str(guild_id)] = config.to_dict()
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Saved {len(self.guild_configs)} guild configurations")
        except Exception as e:
            self.logger.error(f"Failed to save guild configurations: {e}")
    
    def get_effective_config(self, guild_id: int) -> EffectiveGuildConfig:
        """Get effective configuration for a guild (guild-specific + defaults)"""
        guild_config = self.guild_configs.get(guild_id)
        
        # Determine effective AI provider and models
        ai_provider = guild_config.ai_provider if guild_config and guild_config.ai_provider else self.default_config.gpt.ai_provider
        openai_model = guild_config.openai_model if guild_config and guild_config.openai_model else self.default_config.gpt.openai_model
        gemini_model = guild_config.gemini_model if guild_config and guild_config.gemini_model else self.default_config.gpt.gemini_model
        custom_system_prompt = guild_config.custom_system_prompt if guild_config else None
        
        return EffectiveGuildConfig(
            guild_id=guild_id,
            ai_provider=ai_provider,
            openai_model=openai_model,
            gemini_model=gemini_model,
            custom_system_prompt=custom_system_prompt,
            max_token=self.default_config.gpt.max_token,
            temperature=self.default_config.gpt.temperature,
            image_resolution=self.default_config.gpt.image_resolution.value,
            history_size=self.default_config.bot.history_size,
            default_system_prompt=self.default_config.bot.default_system_promt
        )
    
    def update_guild_config(self, guild_id: int, **kwargs) -> bool:
        """Update guild-specific configuration"""
        try:
            now = datetime.now()
            
            if guild_id not in self.guild_configs:
                # Create new guild config
                self.guild_configs[guild_id] = GuildSpecificConfig(
                    guild_id=guild_id,
                    created_at=now,
                    updated_at=now
                )
            
            # Update specified fields
            guild_config = self.guild_configs[guild_id]
            guild_config.updated_at = now
            
            if 'ai_provider' in kwargs:
                guild_config.ai_provider = kwargs['ai_provider']
                self.logger.info(f"Updated AI provider for guild {guild_id}: {kwargs['ai_provider'].value}")
            
            if 'openai_model' in kwargs:
                guild_config.openai_model = kwargs['openai_model']
                self.logger.info(f"Updated OpenAI model for guild {guild_id}: {kwargs['openai_model']}")
            
            if 'gemini_model' in kwargs:
                guild_config.gemini_model = kwargs['gemini_model']
                self.logger.info(f"Updated Gemini model for guild {guild_id}: {kwargs['gemini_model']}")
            
            if 'custom_system_prompt' in kwargs:
                if kwargs['custom_system_prompt'] is None:
                    # Clear custom system prompt (reset to default)
                    guild_config.custom_system_prompt = None
                    self.logger.info(f"Cleared custom system prompt for guild {guild_id} (reset to default)")
                else:
                    guild_config.custom_system_prompt = kwargs['custom_system_prompt']
                    self.logger.info(f"Updated custom system prompt for guild {guild_id}")
            
            # Check if guild config is now empty (no custom settings)
            if (not guild_config.ai_provider and 
                not guild_config.openai_model and 
                not guild_config.gemini_model and 
                not guild_config.custom_system_prompt):
                # Remove empty guild config to save space
                del self.guild_configs[guild_id]
                self.logger.info(f"Removed empty guild config for guild {guild_id}")
            
            # Save to file
            self._save_guild_configs()
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update guild config for {guild_id}: {e}")
            return False
    
    def reset_guild_config(self, guild_id: int, preserve_system_prompt: bool = False) -> bool:
        """Reset guild configuration to defaults"""
        try:
            if guild_id in self.guild_configs:
                old_config = self.guild_configs[guild_id]
                custom_prompt = old_config.custom_system_prompt if preserve_system_prompt else None
                
                # Remove the guild config (revert to defaults)
                del self.guild_configs[guild_id]
                
                # If preserving system prompt, create minimal config
                if preserve_system_prompt and custom_prompt:
                    self.guild_configs[guild_id] = GuildSpecificConfig(
                        guild_id=guild_id,
                        custom_system_prompt=custom_prompt,
                        updated_at=datetime.now()
                    )
                
                self._save_guild_configs()
                self.logger.info(f"Reset configuration for guild {guild_id} (preserve_prompt={preserve_system_prompt})")
                return True
            else:
                self.logger.info(f"No configuration to reset for guild {guild_id}")
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to reset guild config for {guild_id}: {e}")
            return False
    
    def get_guild_config(self, guild_id: int) -> Optional[GuildSpecificConfig]:
        """Get raw guild-specific configuration"""
        return self.guild_configs.get(guild_id)
    
    def list_configured_guilds(self) -> Dict[int, GuildSpecificConfig]:
        """Get all guild configurations"""
        return self.guild_configs.copy()
    
    def has_custom_config(self, guild_id: int) -> bool:
        """Check if guild has any custom configuration"""
        return guild_id in self.guild_configs