from agent_framework import Message

from bot.modules.agent_service import AgentSettings, MicrosoftAgentService
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


def test_guess_image_media_type():
    service = MicrosoftAgentService()

    assert service._guess_image_media_type("https://example.com/a.jpg?x=1") == "image/jpeg"
    assert service._guess_image_media_type("https://example.com/a.webp") == "image/webp"
    assert service._guess_image_media_type("https://example.com/a.gif") == "image/gif"
    assert service._guess_image_media_type("https://example.com/a.bin") is None
