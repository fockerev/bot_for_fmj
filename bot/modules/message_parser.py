from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class MessageValidationError(ValueError):
    pass


@dataclass
class ParsedMessage:
    text: str
    image_urls: list[str]
    reference_text: str | None = None


class MessageParser:
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    extension_pattern = re.compile(r"\.(png|jpe?g|webp|gif)$", re.IGNORECASE)
    url_pattern = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
    max_images = 4

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def parse_discord_message(self, message: Any, bot_user_id: int) -> ParsedMessage:
        text = self._remove_bot_mentions(message.content or "", bot_user_id).strip()
        reference_text = self._reference_text(message)
        image_urls: list[str] = []

        for attachment in message.attachments:
            if self._is_supported_attachment(attachment):
                image_urls.append(attachment.url)
            else:
                raise MessageValidationError("未対応のファイル形式です。対応形式: png, jpg, jpeg, webp, gif")

        text, extracted_urls = self.extract_image_urls(text)
        image_urls.extend(extracted_urls)
        image_urls = self._dedupe(image_urls)

        if len(image_urls) > self.max_images:
            raise MessageValidationError(f"画像は1メッセージあたり最大{self.max_images}件までです。")
        if not text.strip() and not image_urls:
            raise MessageValidationError("本文または画像を指定してください。")

        return ParsedMessage(text=text.strip(), image_urls=image_urls, reference_text=reference_text)

    async def parse_message(self, message: Any):
        parsed = self.parse_discord_message(message, message.guild.me.id if message.guild and message.guild.me else 0)
        return parsed.text, parsed.reference_text, parsed.image_urls

    def extract_image_urls(self, text: str) -> tuple[str, list[str]]:
        urls = self.url_pattern.findall(text)
        image_urls: list[str] = []
        cleaned_text = text
        for url in urls:
            if self.is_supported_image_url(url):
                image_urls.append(url)
                cleaned_text = cleaned_text.replace(url, "")
            elif self._looks_like_url(url):
                raise MessageValidationError("未対応のURL形式です。画像URLは https の png, jpg, jpeg, webp, gif のみ対応しています。")
        return cleaned_text.strip(), self._dedupe(image_urls)

    def is_supported_image_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            return False
        return self.extension_pattern.search(parsed.path) is not None

    def _is_supported_attachment(self, attachment: Any) -> bool:
        content_type = getattr(attachment, "content_type", None)
        if content_type:
            return content_type.lower().startswith("image/")
        return self.is_supported_image_url(attachment.url)

    def _remove_bot_mentions(self, text: str, bot_user_id: int) -> str:
        patterns = [rf"<@{bot_user_id}>", rf"<@!{bot_user_id}>"]
        for pattern in patterns:
            text = re.sub(pattern, "", text)
        return text

    def _reference_text(self, message: Any) -> str | None:
        if message.reference is None or message.reference.resolved is None:
            return None
        return getattr(message.reference.resolved, "content", None)

    def _dedupe(self, urls: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for url in urls:
            if url not in seen:
                result.append(url)
                seen.add(url)
        return result

    def _looks_like_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.scheme and parsed.netloc)
