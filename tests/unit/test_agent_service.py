from agent_framework import Message

from bot.modules.agent_service import AgentConfigurationError, AgentSettings, MCPServerSettings, MicrosoftAgentService
from bot.modules.chat_models import ChatContentPart, ChatMessage


def settings():
    return AgentSettings(
        provider="openai",
        model="gpt-test",
        temperature=0.1,
        max_tokens=100,
        image_detail="low",
    )


def test_convert_messages_uses_agent_framework_types():
    service = MicrosoftAgentService()
    messages = [
        ChatMessage(role="system", content=[ChatContentPart(type="text", text="system prompt")]),
        ChatMessage(
            role="user",
            content=[
                ChatContentPart(type="text", text="look"),
                ChatContentPart(type="image_url", image_url="https://example.com/a.png", detail="high"),
            ],
        ),
    ]

    instructions, converted = service.convert_messages(messages, settings())

    assert instructions == "system prompt"
    assert len(converted) == 1
    assert isinstance(converted[0], Message)
    assert converted[0].role == "user"

    content_dicts = [content.to_dict() for content in converted[0].contents]
    assert content_dicts[0]["type"] == "text"
    assert content_dicts[0]["text"] == "look"
    assert content_dicts[1]["type"] == "uri"
    assert content_dicts[1]["uri"] == "https://example.com/a.png"
    assert content_dicts[1]["media_type"] == "image/png"


def test_convert_messages_adds_x_mcp_search_count_instruction():
    service = MicrosoftAgentService()
    agent_settings = settings()
    agent_settings.mcp_servers = [
        MCPServerSettings(
            name="xapi",
            transport="http",
            command="",
            args=[],
            url="https://api.x.com/mcp",
            env={},
            headers={},
            allowed_tools=[],
            approval_mode="never_require",
            request_timeout=300,
        )
    ]
    agent_settings.mcp_search_result_limit = 50

    instructions, converted = service.convert_messages(
        [
            ChatMessage(role="system", content=[ChatContentPart(type="text", text="system prompt")]),
            ChatMessage(role="user", content=[ChatContentPart(type="text", text="search X")]),
        ],
        agent_settings,
    )

    assert converted
    assert instructions is not None
    assert "system prompt" in instructions
    assert "pass at least 10" in instructions
    assert "Prefer 50 results" in instructions


def test_convert_messages_clamps_x_mcp_search_count_instruction_to_api_minimum():
    service = MicrosoftAgentService()
    agent_settings = settings()
    agent_settings.mcp_servers = [
        MCPServerSettings(
            name="xapi",
            transport="http",
            command="",
            args=[],
            url="https://api.x.com/mcp",
            env={},
            headers={},
            allowed_tools=[],
            approval_mode="never_require",
            request_timeout=300,
        )
    ]
    agent_settings.mcp_search_result_limit = 3

    instructions, _ = service.convert_messages(
        [ChatMessage(role="user", content=[ChatContentPart(type="text", text="search X")])],
        agent_settings,
    )

    assert instructions is not None
    assert "pass at least 10" in instructions
    assert "Prefer 10 results" in instructions


def test_convert_messages_does_not_add_mcp_instruction_without_limit():
    service = MicrosoftAgentService()
    agent_settings = settings()
    agent_settings.mcp_servers = [
        MCPServerSettings(
            name="filesystem",
            transport="stdio",
            command="npx",
            args=["-y", "server"],
            url=None,
            env={},
            headers={},
            allowed_tools=[],
            approval_mode="never_require",
            request_timeout=300,
        )
    ]

    instructions, _ = service.convert_messages(
        [ChatMessage(role="system", content=[ChatContentPart(type="text", text="system prompt")])],
        agent_settings,
    )

    assert instructions == "system prompt"


def test_guess_image_media_type():
    service = MicrosoftAgentService()

    assert service._guess_image_media_type("https://example.com/a.jpg?x=1") == "image/jpeg"
    assert service._guess_image_media_type("https://example.com/a.webp") == "image/webp"
    assert service._guess_image_media_type("https://example.com/a.gif") == "image/gif"
    assert service._guess_image_media_type("https://example.com/a.bin") is None


def test_build_x_mcp_stdio_tool(monkeypatch):
    monkeypatch.setenv("X_CLIENT_ID", "client-id")
    monkeypatch.setenv("X_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("X_REDIRECT_URI", "http://localhost:8080/callback")
    service = MicrosoftAgentService()

    tool = service.build_mcp_tool(
        MCPServerSettings(
            name="xapi",
            transport="stdio",
            command="npx",
            args=["-y", "@xdevplatform/xurl", "mcp", "https://api.x.com/mcp"],
            url=None,
            env={
                "CLIENT_ID": "X_CLIENT_ID",
                "CLIENT_SECRET": "X_CLIENT_SECRET",
                "REDIRECT_URI": "X_REDIRECT_URI",
            },
            headers={},
            allowed_tools=[],
            approval_mode="never_require",
            request_timeout=300,
        )
    )

    assert tool.name == "xapi"
    assert tool.command == "npx"
    assert tool.args == ["-y", "@xdevplatform/xurl", "mcp", "https://api.x.com/mcp"]
    assert tool.env == {
        "CLIENT_ID": "client-id",
        "CLIENT_SECRET": "client-secret",
        "REDIRECT_URI": "http://localhost:8080/callback",
    }
    assert tool.approval_mode == "never_require"
    assert tool.request_timeout == 300


def test_build_mcp_headers_from_bearer_token(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "token-value")
    service = MicrosoftAgentService()

    headers = service._build_headers({"Authorization": "X_BEARER_TOKEN"})

    assert headers == {"Authorization": "Bearer token-value"}


async def test_build_http_mcp_tool_uses_authenticated_http_client(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "token-value")
    service = MicrosoftAgentService()

    tool = service.build_mcp_tool(
        MCPServerSettings(
            name="xapi",
            transport="http",
            command="",
            args=[],
            url="https://api.x.com/mcp",
            env={},
            headers={"Authorization": "X_BEARER_TOKEN"},
            allowed_tools=[],
            approval_mode="never_require",
            request_timeout=300,
        )
    )

    assert tool._httpx_client is not None
    assert tool._httpx_client.headers["authorization"] == "Bearer token-value"
    await tool._httpx_client.aclose()


def test_build_http_mcp_tool_requires_configured_header_env(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    service = MicrosoftAgentService()

    try:
        service.build_mcp_tool(
            MCPServerSettings(
                name="xapi",
                transport="http",
                command="",
                args=[],
                url="https://api.x.com/mcp",
                env={},
                headers={"Authorization": "X_BEARER_TOKEN"},
                allowed_tools=[],
                approval_mode="never_require",
                request_timeout=300,
            )
        )
    except AgentConfigurationError as exc:
        assert "X_BEARER_TOKEN is required" in str(exc)
    else:
        raise AssertionError("expected missing mcp header env to fail")


async def test_generate_closes_http_mcp_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("X_BEARER_TOKEN", "token-value")
    service = MicrosoftAgentService()
    recorded = {}

    class FakeResponse:
        text = "ok"

    class FakeAgent:
        async def run(self, messages, **kwargs):
            recorded["messages"] = messages
            recorded["kwargs"] = kwargs
            return FakeResponse()

    class FakeClient:
        def as_agent(self, **kwargs):
            recorded["agent_kwargs"] = kwargs
            recorded["tool"] = kwargs["tools"][0]
            return FakeAgent()

    monkeypatch.setattr(service, "_get_client", lambda settings, api_key: FakeClient())

    result = await service.generate(
        [ChatMessage(role="user", content=[ChatContentPart(type="text", text="hello")])],
        AgentSettings(
            provider="openai",
            model="gpt-test",
            temperature=0.1,
            max_tokens=100,
            image_detail="low",
            mcp_servers=[
                MCPServerSettings(
                    name="xapi",
                    transport="http",
                    command="",
                    args=[],
                    url="https://api.x.com/mcp",
                    env={},
                    headers={"Authorization": "X_BEARER_TOKEN"},
                    allowed_tools=[],
                    approval_mode="never_require",
                    request_timeout=300,
                )
            ],
        ),
    )

    assert result.text == "ok"
    assert "function_invocation_kwargs" not in recorded["kwargs"]
    assert recorded["tool"]._httpx_client.is_closed
