import asyncio
import json
import logging
import logging.config
import os
from pathlib import Path

import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID_LIST = [id.strip() for id in os.getenv("GUILD_ID").split(",")]
PREFIX = os.getenv("BOT_PREFIX")

# Setup logger
def setup_logger():
    """Setup logger configuration"""
    try:
        with open(str(Path(__file__).resolve().parent / "logging_config.json"), "r") as f:
            log_conf = json.load(f)
        logging.config.dictConfig(log_conf)
        return logging.getLogger("__main__")
    except Exception as e:
        # Fallback to basic logging if config fails
        logging.basicConfig(level=logging.INFO, format='[%(levelname)s] [%(funcName)s] %(asctime)s: %(message)s')
        logger = logging.getLogger("__main__")
        logger.error(f"Failed to load logging config: {e}")
        return logger

logger = setup_logger()
logger.info(f"Guild ID List: {GUILD_ID_LIST}")


class DiscordBot(commands.Bot):
    """DiscordのBotを設定するクラス"""

    def __init__(self, intents: discord.Intents, command_prefix: str, help_command=None):
        super().__init__(intents=intents, command_prefix=command_prefix, help_command=help_command)

    async def sync_all_server(self):
        """コマンドの同期処理"""
        for id in GUILD_ID_LIST:
            self.tree.copy_global_to(guild=discord.Object(id=id))
            await self.tree.sync(guild=discord.Object(id=id))
        logger.info("Command sync completed")

    async def setup_hook(self):
        """Setup時に実行する処理"""

        # Botコマンドの動機
        await self.sync_all_server()
        return await super().setup_hook()


# Botインスタンス生成
# DiscordBot側のIntentsの設定をすべてOnにしておく必要がある（面倒なので）
intents = discord.Intents.all()
bot = DiscordBot(intents=intents, command_prefix=PREFIX)


async def cog_boot():
    """Cogの読み込み処理\r\n
    ./cogs内のファイルを読み込む
    """
    asyncio.gather(*[bot.load_extension(f"cogs.{cog[:-3]}") for cog in os.listdir("cogs") if cog.endswith(".py")])


@bot.event
async def on_ready():
    logger.info(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game(f"{PREFIX}help"))


if __name__ == "__main__":
    asyncio.run(cog_boot())
    bot.run(TOKEN)
