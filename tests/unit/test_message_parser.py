import logging

import pytest

from bot.modules.message_parser import MessageParser, MessageValidationError


def test_extract_image_urls_https_only():
    parser = MessageParser(logging.getLogger(__name__))

    text, urls = parser.extract_image_urls("look https://example.com/a.png")

    assert text == "look"
    assert urls == ["https://example.com/a.png"]


def test_extract_rejects_http_url():
    parser = MessageParser(logging.getLogger(__name__))

    with pytest.raises(MessageValidationError):
        parser.extract_image_urls("look http://example.com/a.png")


def test_dedupes_image_urls():
    parser = MessageParser(logging.getLogger(__name__))

    _, urls = parser.extract_image_urls("https://example.com/a.png https://example.com/a.png")

    assert urls == ["https://example.com/a.png"]
