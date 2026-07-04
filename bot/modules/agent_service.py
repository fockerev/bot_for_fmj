from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlparse

from httpx import AsyncClient, Timeout
from agent_framework import Content, MCPStdioTool, MCPStreamableHTTPTool, Message
from agent_framework.openai import OpenAIChatClient

from .chat_models import ChatMessage


@dataclass
class AgentSettings:
    provider: str
    model: str
    temperature: float
    max_tokens: int
    image_detail: str
    mcp_servers: list["MCPServerSettings"] = field(default_factory=list)
    mcp_search_result_limit: int | None = None


@dataclass
class MCPServerSettings:
    name: str
    transport: str
    command: str
    args: list[str]
    url: str | None
    env: dict[str, str]
    headers: dict[str, str]
    allowed_tools: list[str]
    approval_mode: str
    request_timeout: int | None


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
            tools = [self.build_mcp_tool(mcp_server) for mcp_server in settings.mcp_servers]
            try:
                agent = client.as_agent(
                    instructions=instructions,
                    tools=tools or None,
                    default_options={
                        "model": settings.model,
                        "temperature": settings.temperature,
                        "max_tokens": settings.max_tokens,
                    },
                )
                response = await agent.run(run_messages)
            finally:
                await self._close_mcp_http_clients(tools)
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
        return self._append_mcp_instructions(instructions, settings), converted

    def _append_mcp_instructions(self, instructions: str | None, settings: AgentSettings) -> str | None:
        if not settings.mcp_servers or settings.mcp_search_result_limit is None:
            return instructions

        search_limit = max(settings.mcp_search_result_limit, 10)
        mcp_instruction = (
            "When using X MCP search tools, pass at least 10 as the search result count "
            f"(such as max_results, count, limit, or similar parameters). Prefer {search_limit} "
            "results unless the user explicitly asks for more. If the user asks for fewer than 10, "
            "still request 10 or more from the tool, then summarize or show only the requested amount."
        )
        if not instructions:
            return mcp_instruction
        return f"{instructions}\n\n{mcp_instruction}"

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

    def build_mcp_tool(self, settings: MCPServerSettings):
        allowed_tools = settings.allowed_tools or None
        approval_mode = settings.approval_mode or None
        if settings.transport == "stdio":
            return MCPStdioTool(
                name=settings.name,
                command=settings.command,
                args=settings.args,
                env=self._build_child_env(settings.env),
                description=f"{settings.name} MCP server",
                approval_mode=approval_mode,
                allowed_tools=allowed_tools,
                request_timeout=settings.request_timeout,
            )
        if settings.transport in {"http", "streamable_http"}:
            if not settings.url:
                raise AgentConfigurationError("mcp.url is required for http transport")
            return MCPStreamableHTTPTool(
                name=settings.name,
                url=settings.url,
                description=f"{settings.name} MCP server",
                approval_mode=approval_mode,
                allowed_tools=allowed_tools,
                request_timeout=settings.request_timeout,
                http_client=self._build_http_client(settings.headers, settings.request_timeout),
            )
        raise AgentConfigurationError(f"unsupported mcp transport: {settings.transport}")

    def _build_child_env(self, env_mapping: dict[str, str]) -> dict[str, str]:
        child_env: dict[str, str] = {}
        for child_key, source_env_key in env_mapping.items():
            value = os.getenv(source_env_key)
            if value:
                child_env[child_key] = value
        return child_env

    def _build_headers(self, header_mapping: dict[str, str]) -> dict[str, str]:
        headers: dict[str, str] = {}
        for header_name, source_env_key in header_mapping.items():
            value = os.getenv(source_env_key)
            if not value:
                raise AgentConfigurationError(f"{source_env_key} is required for mcp header {header_name}")
            if header_name.lower() == "authorization" and not value.lower().startswith("bearer "):
                value = f"Bearer {value}"
            headers[header_name] = value
        return headers

    def _build_http_client(self, header_mapping: dict[str, str], request_timeout: int | None) -> AsyncClient | None:
        headers = self._build_headers(header_mapping)
        if not headers:
            return None
        timeout = Timeout(request_timeout or 30, read=None)
        return AsyncClient(headers=headers, follow_redirects=True, timeout=timeout)

    async def _close_mcp_http_clients(self, tools: list[Any]) -> None:
        for tool in tools:
            http_client = getattr(tool, "_httpx_client", None)
            if http_client is not None:
                await http_client.aclose()


class FakeAgentService:
    def __init__(self, text: str | None = None):
        self.text = text
        self.requests: list[tuple[list[ChatMessage], AgentSettings]] = []

    async def generate(self, messages: list[ChatMessage], settings: AgentSettings) -> AgentResult:
        self.requests.append((messages, settings))
        image_count = sum(1 for message in messages for part in message.content if part.type == "image_url")
        text = self.text or f"fake response: messages={len(messages)}, images={image_count}"
        return AgentResult(text=text)
