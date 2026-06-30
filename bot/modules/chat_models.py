from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


Role = Literal["system", "user", "assistant"]
ContentType = Literal["text", "image_url"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return utc_now()


@dataclass
class ChatContentPart:
    type: ContentType
    text: str | None = None
    image_url: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.type == "text" and not self.text:
            raise ValueError("text content part requires text")
        if self.type == "image_url" and not self.image_url:
            raise ValueError("image_url content part requires image_url")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type}
        if self.text is not None:
            data["text"] = self.text
        if self.image_url is not None:
            data["image_url"] = self.image_url
        if self.detail is not None:
            data["detail"] = self.detail
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatContentPart":
        return cls(
            type=data["type"],
            text=data.get("text"),
            image_url=data.get("image_url"),
            detail=data.get("detail"),
        )


@dataclass
class ChatMessage:
    role: Role
    content: list[ChatContentPart]
    created_at: datetime = field(default_factory=utc_now)

    def text_preview(self, limit: int = 120) -> str:
        text = " ".join(part.text or "" for part in self.content if part.type == "text")
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return text[:limit]

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": [part.to_dict() for part in self.content],
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatMessage":
        return cls(
            role=data["role"],
            content=[ChatContentPart.from_dict(part) for part in data.get("content", [])],
            created_at=parse_datetime(data.get("created_at")),
        )


@dataclass
class GuildSession:
    guild_id: int
    system_prompt: str
    messages: list[ChatMessage] = field(default_factory=list)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "guild_id": self.guild_id,
            "system_prompt": self.system_prompt,
            "updated_at": self.updated_at.astimezone(timezone.utc).isoformat(),
            "messages": [message.to_dict() for message in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GuildSession":
        return cls(
            guild_id=int(data["guild_id"]),
            system_prompt=data.get("system_prompt", ""),
            messages=[ChatMessage.from_dict(message) for message in data.get("messages", [])],
            updated_at=parse_datetime(data.get("updated_at")),
        )


@dataclass
class ChatRequest:
    guild_id: int
    user_id: int
    text: str
    image_urls: list[str]
    reference_text: str | None = None


@dataclass
class ChatResponse:
    text: str
    guild_id: int
    message_count: int
