import base64

import httpx
import pytest

from bot.modules import image_history
from bot.modules.chat_models import ChatContentPart, ChatMessage


URL = "https://cdn.discordapp.com/attachments/1/2/image.png?ex=ffffffff&hm=test"


def image_message(url=URL):
    return ChatMessage(role="user", content=[ChatContentPart(type="image_url", image_url=url)])


def mock_downloads(monkeypatch, handler):
    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        image_history.httpx, "AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs),
    )


async def test_download_embeds_image_data(monkeypatch):
    mock_downloads(monkeypatch, lambda request: httpx.Response(200, content=b"image bytes", headers={"content-type": "image/png"}))
    message = image_message()

    await image_history.prepare_image_history([message], message)

    assert message.content[0].image_url == "data:image/png;base64," + base64.b64encode(b"image bytes").decode()


async def test_expired_history_preserves_text_and_image_only_message(monkeypatch):
    def no_download(request):
        pytest.fail("Expired or embedded images must not be downloaded")

    mock_downloads(monkeypatch, no_download)
    old = image_message(URL.replace("ffffffff", "1"))
    mixed = image_message(URL.replace("ffffffff", "1"))
    mixed.content.insert(0, ChatContentPart(type="text", text="元の質問"))
    current = ChatMessage(role="user", content=[ChatContentPart(type="text", text="続けて")])

    await image_history.prepare_image_history([old, mixed, current], current)

    assert old.content[0].text == image_history.UNAVAILABLE_IMAGE_TEXT
    assert mixed.content[0].text == "元の質問"
    assert mixed.content[1].text == image_history.UNAVAILABLE_IMAGE_TEXT
    assert current.content[0].text == "続けて"


@pytest.mark.parametrize("status", [403, 404, 410])
async def test_unavailable_legacy_image_is_repaired(monkeypatch, status):
    mock_downloads(monkeypatch, lambda request: httpx.Response(status))
    old, current = image_message(), image_message("https://example.com/new.png")

    await image_history.prepare_image_history([old, current], current)

    assert old.content[0].text == image_history.UNAVAILABLE_IMAGE_TEXT
    assert current.content[0].image_url == "https://example.com/new.png"


@pytest.mark.parametrize("historical,status", [(False, 404), (True, 500)])
async def test_current_or_transient_errors_do_not_discard_images(monkeypatch, historical, status):
    mock_downloads(monkeypatch, lambda request: httpx.Response(status))
    message = image_message()
    current = image_message() if historical else message

    with pytest.raises(httpx.HTTPStatusError):
        await image_history.prepare_image_history([message], current)

    assert message.content[0].image_url == URL


@pytest.mark.parametrize("body,media_type,limit", [(b"too large", "image/png", 2), (b"html", "text/html", 100), (b"", "image/png", 100)])
async def test_invalid_download_is_not_saved(monkeypatch, body, media_type, limit):
    monkeypatch.setattr(image_history, "MAX_IMAGE_BYTES", limit)
    mock_downloads(monkeypatch, lambda request: httpx.Response(200, content=body, headers={"content-type": media_type}))
    message = image_message()

    with pytest.raises(ValueError):
        await image_history.prepare_image_history([message], message)

    assert message.content[0].image_url == URL
