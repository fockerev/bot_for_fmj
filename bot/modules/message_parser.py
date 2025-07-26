import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import logging

import discord
import urlextract


class MessageParser:
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.supported_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.svg'
        }
        self.extension_pattern = re.compile(r"\.(png|jpe?g|gif|webp|bmp|tiff?|svg)(?:\?[^\s]*)?$", re.IGNORECASE)

    async def parse_message(self, message: discord.message.Message) -> Tuple[str, Optional[str], List[str]]:
        """入力メッセージを処理して、入力・参照・添付ファイルにする"""
        reference_message = None
        attachments_list = []

        # Remove mentions and strip
        plane_message = re.sub(r"<@\d+>", "", message.content)
        plane_message = plane_message.strip()
        
        # Handle reference message
        if message.reference is not None:
            if message.reference.resolved is not None:
                reference_message = message.reference.resolved.content

        # Handle direct attachments
        if len(message.attachments) > 0:
            for attach in message.attachments:
                if await self._is_valid_image_url(attach.url):
                    attachments_list.append(attach.url)
                else:
                    supported_formats = ', '.join(sorted(self.supported_extensions))
                    raise ValueError(f"未対応のファイル形式です。対応形式: {supported_formats}")

        # Extract URLs from message content
        extractor = urlextract.URLExtract()
        extracted_urls = extractor.find_urls(plane_message)
        if len(extracted_urls) > 0:
            for url in extracted_urls:
                if await self._is_valid_image_url(url):
                    # Convert to HTTPS
                    secure_url = self._ensure_https(url)
                    attachments_list.append(secure_url)
                    plane_message = plane_message.replace(url, "")
                else:
                    supported_formats = ', '.join(sorted(self.supported_extensions))
                    raise ValueError(f"未対応のURL形式またはアクセスできません。対応形式: {supported_formats}")

        return plane_message, reference_message, attachments_list

    def _ensure_https(self, url: str) -> str:
        """URLをHTTPSに変換する"""
        if url.startswith('http://'):
            return url.replace('http://', 'https://', 1)
        return url

    async def _is_valid_image_url(self, url: str) -> bool:
        """画像URLの有効性とアクセス可能性をチェックする"""
        try:
            # URL形式の基本チェック
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False
            
            # 拡張子チェック
            if not self.extension_pattern.search(url):
                return False
            
            # HTTPSに変換してアクセス可能性をチェック
            secure_url = self._ensure_https(url)
            
            # HEAD リクエストでアクセス可能性とContent-Typeをチェック
            request = Request(secure_url)
            request.add_header('User-Agent', 'Mozilla/5.0 (compatible; DiscordBot)')
            request.get_method = lambda: 'HEAD'
            
            with urlopen(request, timeout=10) as response:
                content_type = response.headers.get('Content-Type', '').lower()
                # Content-Typeが画像かチェック
                if content_type.startswith('image/'):
                    return True
                # Content-Typeが不明でも拡張子が画像なら許可
                return self.extension_pattern.search(url) is not None
                
        except (URLError, HTTPError, Exception) as e:
            self.logger.warning(f"URL validation failed for {url}: {e}")
            return False