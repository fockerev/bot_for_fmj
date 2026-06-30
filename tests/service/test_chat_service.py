import pytest
import logging

from bot.modules.agent_service import AgentResult, FakeAgentService
from bot.modules.chat_models import ChatRequest
from bot.modules.chat_service import ChatService
from bot.modules.config import AgentConfig, AppConfig, BotConfig, LoggingConfig, MCPConfig
from bot.modules.guild_config import GuildConfigManager
from bot.modules.session_store import SessionStore


def config(save_failed=True):
    return AppConfig(
        agent=AgentConfig("openai", "gpt-test", 100, 0.1, "low"),
        bot=BotConfig(16, save_failed, "system"),
        logging=LoggingConfig("INFO", "logs/test.log"),
        mcp=MCPConfig(False, "node", [], 3),
    )


@pytest.mark.asyncio
async def test_chat_service_saves_user_and_assistant(tmp_path):
    app_config = config()
    logger = logging.getLogger(__name__)
    guild_manager = GuildConfigManager(app_config, tmp_path, logger)
    store = SessionStore(tmp_path / "sessions", app_config.bot.history_size, logger)
    service = ChatService(app_config, guild_manager, store, FakeAgentService("ok"), logger)

    response = await service.handle_chat(ChatRequest(1, 2, "hello", []))

    assert response.text == "ok"
    session = store.get_session(1, "system")
    assert [message.role for message in session.messages] == ["user", "assistant"]


class FailingAgent:
    async def generate(self, messages, settings):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_chat_service_saves_failed_user_when_configured(tmp_path):
    app_config = config(save_failed=True)
    logger = logging.getLogger(__name__)
    guild_manager = GuildConfigManager(app_config, tmp_path, logger)
    store = SessionStore(tmp_path / "sessions", app_config.bot.history_size, logger)
    service = ChatService(app_config, guild_manager, store, FailingAgent(), logger)

    await service.handle_chat(ChatRequest(1, 2, "hello", []))

    session = store.get_session(1, "system")
    assert [message.role for message in session.messages] == ["user"]
