


import asyncio
import os

import discord
import dotenv
from discord.ext import commands

dotenv.load_dotenv(verbose=True)

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
PREFIX= os.getenv("BOT_PREFIX")

class DiscordBot(commands.Bot):
    """DiscordのBotを設定するクラス"""
    def __init__(self, intents: discord.Intents, command_prefix: str, help_command=None):
        super().__init__(intents=intents, command_prefix=command_prefix, help_command=help_command)

    async def setup_hook(self):
        """Setup時に実行する処理"""

        # Botコマンドの動機
        self.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
        await self.tree.sync(guild=discord.Object(id=GUILD_ID))
        return await super().setup_hook()

# Botインスタンス生成
# DiscordBot側のIntentsの設定をすべてOnにしておく必要がある（面倒なので）
intents = discord.Intents.all()
bot = DiscordBot(intents=intents, command_prefix=PREFIX)

async def cog_boot():
    """ Cogの読み込み処理\r\n
        ./cogs内のファイルを読み込む
    """
    asyncio.gather(*[bot.load_extension(f"cogs.{cog[:-3]}") for cog in os.listdir("cogs") if cog.endswith(".py")])

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game(f"{PREFIX}help"))

if __name__ == "__main__":
    asyncio.run(cog_boot())
    bot.run(TOKEN)
