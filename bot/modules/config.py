import inspect
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Type, TypeVar

import yaml


class ImageReso(Enum):
    LOW = 0
    HIGH = 1


T = TypeVar("T", bound="YamlConfig")


@dataclass
class YamlConfig:
    @classmethod
    def load(cls: Type[T], config_path: Path) -> T:
        def _convert_from_dict(parent_cls: Type[T], data: Dict[str, Any]) -> Dict[str, Any]:
            valid_data = {key: val for key, val in data.items() if key in parent_cls.__dataclass_fields__}
            for key, val in valid_data.items():
                child_class = parent_cls.__dataclass_fields__[key].type
                if inspect.isclass(child_class) and issubclass(child_class, YamlConfig):
                    valid_data[key] = child_class(**_convert_from_dict(child_class, val))
                elif isinstance(child_class, type) and issubclass(child_class, Enum):
                    valid_data[key] = child_class(val)
            return valid_data

        if config_path.exists() is False:
            raise FileNotFoundError(f"{str(config_path)} is not found")

        with open(config_path) as f:
            config_data = yaml.safe_load(f)
            config_data = _convert_from_dict(cls, config_data)
            return cls(**config_data)


@dataclass
class GptConfig(YamlConfig):
    model: str
    max_token: int
    temperature: float
    image_resolution: ImageReso


@dataclass
class BotConfig(YamlConfig):
    save_api_response: bool
    save_image_input: bool
    history_size: int
    default_system_promt: str


@dataclass
class AppConfig(YamlConfig):
    gpt: GptConfig
    bot: BotConfig