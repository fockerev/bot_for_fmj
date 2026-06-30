from __future__ import annotations

import asyncio
import os
from pathlib import Path

import discord
from discord.ext import commands

from modules.config import AppConfig
from modules.logging_service import setup_logging


BASE_DIR = Path(__file__).resolve().parent


class DiscordBot(commands.Bot):
    def __init__(self, app_config: AppConfig, app_logger, guild_ids: list[int], command_prefix: str):
        intents = discord.Intents.all()
        super().__init__(intents=intents, command_prefix=command_prefix, help_command=None)
        self.app_config = app_config
        self.app_logger = app_logger
        self.guild_ids = guild_ids

    async def setup_hook(self):
        await self.load_extension("cogs.chat")
        self.app_logger.info("Loaded cog cogs.chat")
        for guild_id in self.guild_ids:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        self.app_logger.info("Command sync completed")

    async def on_ready(self):
        self.app_logger.info("Logged in as %s", self.user)
        await self.change_presence(activity=discord.Game(f"{self.command_prefix}help"))


def load_environment() -> tuple[str, list[int], str]:
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is required")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required")
    guild_id_text = os.getenv("GUILD_ID")
    if not guild_id_text:
        raise RuntimeError("GUILD_ID is required")
    guild_ids = [int(value.strip()) for value in guild_id_text.split(",") if value.strip()]
    if not guild_ids:
        raise RuntimeError("GUILD_ID is required")
    return token, guild_ids, os.getenv("BOT_PREFIX") or "/"


def main() -> None:
    config = AppConfig.load(BASE_DIR / "setting.yaml")
    logger = setup_logging(config.logging)
    token, guild_ids, prefix = load_environment()
    bot = DiscordBot(config, logger, guild_ids, prefix)
    bot.run(token)


if __name__ == "__main__":
    main()
