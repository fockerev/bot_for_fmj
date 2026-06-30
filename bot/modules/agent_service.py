from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlparse

from agent_framework import Content, Message
from agent_framework.openai import OpenAIChatClient

from .chat_models import ChatMessage


@dataclass
class AgentSettings:
    provider: str
    model: str
    temperature: float
    max_tokens: int
    image_detail: str


@dataclass
class AgentResult:
    text: str
    raw: Any | None = None


class AgentConfigurationError(Exception):
    pass


class AgentExecutionError(Exception):
    pass


class AgentService(Protocol):
    async def generate(self, messages: list[ChatMessage], settings: AgentSettings) -> AgentResult:
        ...


class MicrosoftAgentService:
    """Adapter boundary for Microsoft Agent Framework.

    The public interface is stable for the app layer. The concrete Microsoft
    Agent Framework Python API is intentionally contained here because package
    and message APIs are the most likely part to change.
    """

    def __init__(self, api_key_env: str = "OPENAI_API_KEY"):
        self.api_key_env = api_key_env
        self._clients: dict[tuple[str, str], OpenAIChatClient] = {}

    async def generate(self, messages: list[ChatMessage], settings: AgentSettings) -> AgentResult:
        if settings.provider != "openai":
            raise AgentConfigurationError(f"unsupported provider: {settings.provider}")
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise AgentConfigurationError(f"{self.api_key_env} is required")

        try:
            client = self._get_client(settings, api_key)
            instructions, run_messages = self.convert_messages(messages, settings)
            agent = client.as_agent(
                instructions=instructions,
                default_options={
                    "model": settings.model,
                    "temperature": settings.temperature,
                    "max_tokens": settings.max_tokens,
                },
            )
            response = await agent.run(run_messages)
            return AgentResult(text=response.text or "", raw=response)
        except AgentConfigurationError:
            raise
        except Exception as exc:
            raise AgentExecutionError("agent execution failed") from exc

    def _get_client(self, settings: AgentSettings, api_key: str) -> OpenAIChatClient:
        key = (settings.provider, settings.model)
        if key not in self._clients:
            self._clients[key] = OpenAIChatClient(model=settings.model, api_key=api_key)
        return self._clients[key]

    def convert_messages(self, messages: list[ChatMessage], settings: AgentSettings) -> tuple[str | None, list[Message]]:
        instructions: str | None = None
        converted: list[Message] = []
        for message in messages:
            if message.role == "system":
                instructions = self._message_text(message)
                continue

            contents: list[Content] = []
            for part in message.content:
                if part.type == "text":
                    contents.append(Content.from_text(part.text or ""))
                elif part.type == "image_url":
                    contents.append(
                        Content.from_uri(
                            part.image_url or "",
                            media_type=self._guess_image_media_type(part.image_url or ""),
                        )
                    )
            converted.append(Message(message.role, contents))
        return instructions, converted

    def _message_text(self, message: ChatMessage) -> str:
        return "\n".join(part.text or "" for part in message.content if part.type == "text").strip()

    def _guess_image_media_type(self, url: str) -> str | None:
        suffix = PurePosixPath(urlparse(url).path).suffix.lower()
        if suffix == ".png":
            return "image/png"
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".webp":
            return "image/webp"
        if suffix == ".gif":
            return "image/gif"
        return None


class FakeAgentService:
    def __init__(self, text: str | None = None):
        self.text = text
        self.requests: list[tuple[list[ChatMessage], AgentSettings]] = []

    async def generate(self, messages: list[ChatMessage], settings: AgentSettings) -> AgentResult:
        self.requests.append((messages, settings))
        image_count = sum(1 for message in messages for part in message.content if part.type == "image_url")
        text = self.text or f"fake response: messages={len(messages)}, images={image_count}"
        return AgentResult(text=text)
