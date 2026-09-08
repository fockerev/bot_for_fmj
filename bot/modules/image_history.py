from __future__ import annotations

import base64
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse

import httpx

from .chat_models import ChatContentPart, ChatMessage, utc_now


UNAVAILABLE_IMAGE_TEXT = "[以前の添付画像は期限切れまたは削除済みのため参照できません。必要なら再添付してください。]"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}


def is_discord_attachment(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"cdn.discordapp.com", "media.discordapp.net"}
        and parsed.path.startswith(("/attachments/", "/ephemeral-attachments/"))
    )


def is_expired(url: str) -> bool:
    expiry = parse_qs(urlparse(url).query).get("ex", [""])[0]
    try:
        return int(expiry, 16) <= utc_now().timestamp()
    except ValueError:
        return False


async def download_image(client: httpx.AsyncClient, url: str) -> str:
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type in {"", "application/octet-stream"}:
            media_type = IMAGE_TYPES.get(PurePosixPath(urlparse(url).path).suffix.lower(), "")
        if media_type not in IMAGE_TYPES.values():
            raise ValueError("Unsupported attachment image type")
        data = bytearray()
        async for chunk in response.aiter_bytes():
            if len(data) + len(chunk) > MAX_IMAGE_BYTES:
                raise ValueError("Attachment image exceeds 20 MiB")
            data.extend(chunk)
        if not data:
            raise ValueError("Attachment image is empty")
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


async def prepare_image_history(messages: list[ChatMessage], current_message: ChatMessage) -> None:
    """Persist Discord images inline; repair unavailable images in legacy history.

    Only definite expiry/deletion is repaired. Transient download errors propagate
    so a temporary outage does not discard historical image content.
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        for message in messages:
            for index, part in enumerate(message.content):
                url = part.image_url or ""
                if part.type != "image_url" or not is_discord_attachment(url):
                    continue
                historical = message is not current_message
                if historical and is_expired(url):
                    message.content[index] = ChatContentPart(type="text", text=UNAVAILABLE_IMAGE_TEXT)
                    continue
                try:
                    part.image_url = await download_image(client, url)
                except httpx.HTTPStatusError as exc:
                    if not historical or exc.response.status_code not in {403, 404, 410}:
                        raise
                    message.content[index] = ChatContentPart(type="text", text=UNAVAILABLE_IMAGE_TEXT)
