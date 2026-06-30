from __future__ import annotations

import sys
from pathlib import Path

import discord
from discord.ext import commands

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from modules.agent_service import MicrosoftAgentService
from modules.chat_models import ChatRequest
from modules.chat_service import ChatService
from modules.config import AppConfig
from modules.guild_config import GuildConfigManager
from modules.message_parser import MessageParser, MessageValidationError
from modules.session_store import SessionStore


def split_discord_message(text: str, limit: int = 1900) -> list[str]:
    if not text:
        return [""]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    chunks.append(remaining)
    return chunks


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config: AppConfig = bot.app_config
        self.logger = bot.app_logger
        self.guild_config_manager = GuildConfigManager(self.config, BASE_DIR / "data", self.logger)
        self.session_store = SessionStore(BASE_DIR / "data" / "sessions", self.config.bot.history_size, self.logger)
        self.agent_service = MicrosoftAgentService()
        self.chat_service = ChatService(
            self.config,
            self.guild_config_manager,
            self.session_store,
            self.agent_service,
            self.logger,
        )
        self.message_parser = MessageParser(self.logger)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return
        if message.guild is None:
            return
        if self.bot.user not in message.mentions:
            await self.bot.process_commands(message)
            return

        try:
            async with message.channel.typing():
                parsed = self.message_parser.parse_discord_message(message, self.bot.user.id)
                response = await self.chat_service.handle_chat(
                    ChatRequest(
                        guild_id=message.guild.id,
                        user_id=message.author.id,
                        text=parsed.text,
                        image_urls=parsed.image_urls,
                        reference_text=parsed.reference_text,
                    )
                )
            for chunk in split_discord_message(response.text):
                await message.channel.send(chunk)
        except MessageValidationError as exc:
            await message.channel.send(str(exc))
        except Exception:
            self.logger.exception("error occurred in chat processing")
            await message.channel.send("なんかエラー出た。時間を置いてもう一度試してな。")

    @commands.hybrid_command(name="history", brief="現在Guildの履歴を表示")
    async def history(self, ctx: commands.Context):
        effective = self.guild_config_manager.get_effective_config(ctx.guild.id)
        session = self.session_store.get_session(ctx.guild.id, effective.system_prompt)
        lines = []
        for message in session.messages[-10:]:
            lines.append(f"{message.role}: {message.text_preview(160)}")
        text = "\n".join(lines) or "履歴はまだありません。"
        for chunk in split_discord_message(text):
            await ctx.send(chunk)

    @commands.hybrid_command(name="history_reset", brief="現在Guildの履歴を削除")
    async def history_reset(self, ctx: commands.Context):
        self.session_store.reset_session(ctx.guild.id)
        await ctx.send("履歴をリセットしました。")

    @commands.hybrid_command(name="chara", brief="現在Guildのsystem promptを変更")
    async def chara(self, ctx: commands.Context, *, text: str):
        if self.guild_config_manager.update_guild_config(ctx.guild.id, custom_system_prompt=text):
            self.session_store.refresh_system_prompt(ctx.guild.id, text)
            await ctx.send("キャラクター設定を更新しました。")
        else:
            await ctx.send("設定更新に失敗しました。")

    @commands.hybrid_command(name="chara_reset", brief="system promptをデフォルトへ戻す")
    async def chara_reset(self, ctx: commands.Context):
        if self.guild_config_manager.update_guild_config(ctx.guild.id, custom_system_prompt=None):
            effective = self.guild_config_manager.get_effective_config(ctx.guild.id)
            self.session_store.refresh_system_prompt(ctx.guild.id, effective.system_prompt)
            await ctx.send("キャラクター設定をリセットしました。")
        else:
            await ctx.send("設定更新に失敗しました。")

    @commands.hybrid_command(name="config", brief="現在Guildの有効設定を表示")
    async def config(self, ctx: commands.Context):
        effective = self.guild_config_manager.get_effective_config(ctx.guild.id)
        text = "\n".join(
            [
                f"provider: {effective.provider}",
                f"model: {effective.model}",
                f"max_tokens: {effective.max_tokens}",
                f"temperature: {effective.temperature}",
                f"image_detail: {effective.image_detail}",
                f"history_size: {effective.history_size}",
                f"custom_system_prompt: {bool(effective.custom_system_prompt)}",
            ]
        )
        await ctx.send(text)

    @commands.hybrid_command(name="config_set_model", brief="現在Guildのmodelを変更")
    async def config_set_model(self, ctx: commands.Context, provider: str, model: str):
        if provider != "openai":
            await ctx.send("初期実装では provider は openai のみ対応しています。")
            return
        if self.guild_config_manager.update_guild_config(ctx.guild.id, provider=provider, model=model):
            await ctx.send("モデル設定を更新しました。")
        else:
            await ctx.send("設定更新に失敗しました。")

    @commands.hybrid_command(name="config_reset", brief="現在Guildの設定をデフォルトへ戻す")
    async def config_reset(self, ctx: commands.Context):
        if self.guild_config_manager.reset_guild_config(ctx.guild.id):
            effective = self.guild_config_manager.get_effective_config(ctx.guild.id)
            self.session_store.refresh_system_prompt(ctx.guild.id, effective.system_prompt)
            await ctx.send("Guild設定をリセットしました。")
        else:
            await ctx.send("設定更新に失敗しました。")

    @commands.hybrid_command(name="help", brief="コマンド一覧")
    async def help_bot(self, ctx: commands.Context):
        await ctx.send("/history /history_reset /chara /chara_reset /config /config_set_model /config_reset")


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatCog(bot))
