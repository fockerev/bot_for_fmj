import pytest
import logging

from bot.modules.agent_service import AgentResult, FakeAgentService
from bot.modules.chat_models import ChatRequest
from bot.modules.chat_models import ChatContentPart, ChatMessage
from bot.modules import image_history
from bot.modules.chat_service import ChatService
from bot.modules.config import AgentConfig, AppConfig, BotConfig, LoggingConfig, MCPConfig, MCPServerConfig
from bot.modules.guild_config import GuildConfigManager
from bot.modules.session_store import SessionStore


def config(save_failed=True):
    return AppConfig(
        agent=AgentConfig("openai", "gpt-test", 100, 0.1, "low"),
        bot=BotConfig(16, save_failed, "system"),
        logging=LoggingConfig("INFO", "logs/test.log"),
        mcp=MCPConfig(enabled=False),
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


async def test_image_history_survives_reload_and_url_expiry(tmp_path, monkeypatch):
    app_config = config()
    logger = logging.getLogger(__name__)
    guild_manager = GuildConfigManager(app_config, tmp_path, logger)
    store = SessionStore(tmp_path / "sessions", app_config.bot.history_size, logger)
    agent = FakeAgentService("ok")
    service = ChatService(app_config, guild_manager, store, agent, logger)
    downloads = []

    async def download(client, url):
        downloads.append(url)
        return "data:image/png;base64,aW1hZ2U="

    monkeypatch.setattr(image_history, "download_image", download)
    url = "https://cdn.discordapp.com/attachments/1/2/a.png?ex=ffffffff"
    assert (await service.handle_chat(ChatRequest(1, 2, "画像を見て", [url]))).text == "ok"
    monkeypatch.setattr(image_history, "is_expired", lambda url: True)
    service.session_store = SessionStore(tmp_path / "sessions", app_config.bot.history_size, logger)

    assert (await service.handle_chat(ChatRequest(1, 2, "昨日の画像について", []))).text == "ok"

    assert downloads == [url]
    assert agent.requests[-1][0][1].content[1].image_url == "data:image/png;base64,aW1hZ2U="
    assert len(store.get_session(1, "system").messages) == 4


async def test_legacy_expired_image_recovers_without_history_reset(tmp_path):
    app_config = config()
    logger = logging.getLogger(__name__)
    store = SessionStore(tmp_path / "sessions", app_config.bot.history_size, logger)
    session = store.get_session(1, "system")
    session.messages = [
        ChatMessage(role="user", content=[ChatContentPart(type="image_url", image_url="https://cdn.discordapp.com/attachments/1/2/a.png?ex=1")]),
        ChatMessage(role="assistant", content=[ChatContentPart(type="text", text="以前の回答")]),
    ]
    store.save_session(session)
    agent = FakeAgentService("ok")
    service = ChatService(app_config, GuildConfigManager(app_config, tmp_path, logger), store, agent, logger)

    assert (await service.handle_chat(ChatRequest(1, 2, "続けて", []))).text == "ok"

    assert agent.requests[0][0][1].content[0].text == image_history.UNAVAILABLE_IMAGE_TEXT
    saved = store.get_session(1, "system")
    assert len(saved.messages) == 4
    assert saved.messages[1].content[0].text == "以前の回答"
    assert saved.messages[0].content[0].type == "text"


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


def test_chat_service_builds_multiple_mcp_server_settings(tmp_path):
    app_config = AppConfig(
        agent=AgentConfig("openai", "gpt-test", 100, 0.1, "low"),
        bot=BotConfig(16, True, "system"),
        logging=LoggingConfig("INFO", "logs/test.log"),
        mcp=MCPConfig(
            enabled=True,
            search_result_limit=50,
            servers=[
                MCPServerConfig("xapi", "http", "", [], url="https://api.x.com/mcp"),
                MCPServerConfig("filesystem", "stdio", "npx", ["-y", "server"]),
            ],
        ),
    )
    logger = logging.getLogger(__name__)
    guild_manager = GuildConfigManager(app_config, tmp_path, logger)
    store = SessionStore(tmp_path / "sessions", app_config.bot.history_size, logger)
    service = ChatService(app_config, guild_manager, store, FakeAgentService("ok"), logger)

    settings = service.build_agent_settings(guild_manager.get_effective_config(1))

    assert [server.name for server in settings.mcp_servers] == ["xapi", "filesystem"]
    assert settings.mcp_search_result_limit == 50


def test_chat_service_does_not_set_x_search_limit_without_x_mcp_server(tmp_path):
    app_config = AppConfig(
        agent=AgentConfig("openai", "gpt-test", 100, 0.1, "low"),
        bot=BotConfig(16, True, "system"),
        logging=LoggingConfig("INFO", "logs/test.log"),
        mcp=MCPConfig(
            enabled=True,
            search_result_limit=50,
            servers=[
                MCPServerConfig("filesystem", "stdio", "npx", ["-y", "server"]),
            ],
        ),
    )
    logger = logging.getLogger(__name__)
    guild_manager = GuildConfigManager(app_config, tmp_path, logger)
    store = SessionStore(tmp_path / "sessions", app_config.bot.history_size, logger)
    service = ChatService(app_config, guild_manager, store, FakeAgentService("ok"), logger)

    settings = service.build_agent_settings(guild_manager.get_effective_config(1))

    assert [server.name for server in settings.mcp_servers] == ["filesystem"]
    assert settings.mcp_search_result_limit is None
