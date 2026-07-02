from __future__ import annotations

import logging

from .agent_service import AgentExecutionError, AgentResult, AgentService, AgentSettings, MCPServerSettings
from .chat_models import ChatContentPart, ChatMessage, ChatRequest, ChatResponse
from .config import AppConfig
from .guild_config import GuildConfigManager
from .logging_service import safe_preview
from .session_store import SessionStore, SessionStoreError


class ChatService:
    def __init__(
        self,
        config: AppConfig,
        guild_config_manager: GuildConfigManager,
        session_store: SessionStore,
        agent_service: AgentService,
        logger: logging.Logger,
    ):
        self.config = config
        self.guild_config_manager = guild_config_manager
        self.session_store = session_store
        self.agent_service = agent_service
        self.logger = logger

    async def handle_chat(self, request: ChatRequest) -> ChatResponse:
        effective_config = self.guild_config_manager.get_effective_config(request.guild_id)
        session = self.session_store.get_session(request.guild_id, effective_config.system_prompt)
        user_message = self.build_user_message(request, effective_config.image_detail)
        session.messages.append(user_message)

        self.logger.info(
            "Received chat guild=%s images=%s preview=%s",
            request.guild_id,
            len(request.image_urls),
            safe_preview(request.text),
        )

        try:
            messages = self.build_agent_messages(session)
            settings = self.build_agent_settings(effective_config)
            result = await self.agent_service.generate(messages, settings)
        except Exception as exc:
            self.logger.exception("Agent error for guild %s", request.guild_id)
            if self.config.bot.save_failed_user_message:
                self._save_session_best_effort(session)
            else:
                session.messages.remove(user_message)
            return ChatResponse(text="なんかエラー出た。時間を置いてもう一度試してな。", guild_id=request.guild_id, message_count=len(session.messages))

        response_text = result.text.strip() if result.text else "応答が空やった。もう一度試してな。"
        session.messages.append(
            ChatMessage(role="assistant", content=[ChatContentPart(type="text", text=response_text)])
        )
        self._save_session_best_effort(session)
        return ChatResponse(text=response_text, guild_id=request.guild_id, message_count=len(session.messages))

    def build_user_message(self, request: ChatRequest, image_detail: str) -> ChatMessage:
        parts: list[ChatContentPart] = []
        text = request.text.strip()
        if request.reference_text:
            reference = request.reference_text.strip()
            text = f"{text}\n\n## 以下へ言及\n{reference}" if text else f"## 以下へ言及\n{reference}"
        if text:
            parts.append(ChatContentPart(type="text", text=text))
        for image_url in request.image_urls:
            parts.append(ChatContentPart(type="image_url", image_url=image_url, detail=image_detail))
        return ChatMessage(role="user", content=parts)

    def build_agent_messages(self, session) -> list[ChatMessage]:
        system = ChatMessage(role="system", content=[ChatContentPart(type="text", text=session.system_prompt)])
        return [system, *session.messages]

    def build_agent_settings(self, effective_config) -> AgentSettings:
        return AgentSettings(
            provider=effective_config.provider,
            model=effective_config.model,
            temperature=effective_config.temperature,
            max_tokens=effective_config.max_tokens,
            image_detail=effective_config.image_detail,
            mcp_servers=self.build_mcp_server_settings(),
        )

    def build_mcp_server_settings(self) -> list[MCPServerSettings]:
        mcp = self.config.mcp
        if not mcp.enabled:
            return []
        return [
            MCPServerSettings(
                name=server.name,
                transport=server.transport,
                command=server.command,
                args=server.args,
                url=server.url,
                env=server.env,
                headers=server.headers,
                allowed_tools=server.allowed_tools,
                approval_mode=server.approval_mode,
                request_timeout=server.request_timeout,
            )
            for server in mcp.servers
        ]

    def _save_session_best_effort(self, session) -> None:
        try:
            self.session_store.save_session(session)
        except SessionStoreError:
            self.logger.exception("Failed to save session for guild %s", session.guild_id)
