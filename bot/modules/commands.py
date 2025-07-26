import discord
from discord.ext import commands
from typing import Optional

from .config import ImageReso, AppConfig
from .gpt_service import GptService


class BotCommands:
    def __init__(self, bot: commands.Bot, gpt_service: GptService, config: AppConfig):
        self.bot = bot
        self.gpt_service = gpt_service
        self.config = config

    def register_commands(self):
        """Register all commands with the bot"""
        @commands.hybrid_command(name="reset_h", brief="会話履歴をリセットする. 60分ごとに自動実行")
        async def reset_h(ctx):
            ret = self.gpt_service.reset_history(guild_id=ctx.guild.id)
            if ret:
                await ctx.send("会話履歴をリセットしました")
            else:
                await ctx.send("会話履歴のリセットに失敗しました")

        @commands.hybrid_command(name="reset_c", brief="性格を初期化する")
        async def reset_c(ctx):
            ret = self.gpt_service.reset_character(guild_id=ctx.guild.id)
            if ret:
                await ctx.send("性格をリセットしました")
            else:
                await ctx.send("性格のリセットに失敗しました")

        @commands.hybrid_command(name="chara", brief="引数で入力した文を性格として設定する")
        async def change(ctx: commands.context.Context, text):
            ret = self.gpt_service.change_character(guild_id=ctx.guild.id, text=text)
            if ret:
                await ctx.send("性格を変更しました")
            else:
                await ctx.send("性格の変更に失敗しました")

        @commands.hybrid_command(name="ranking", brief="トークン使用量ランキング")
        async def ranking(ctx):
            ranking_data = self.gpt_service.get_token_ranking(ctx.guild.id)
            if not ranking_data:
                await ctx.send("まだ誰もAPIを使用していません")
                return

            embed = discord.Embed(title="Token使用量ランキング", color=discord.Colour.red())
            for x, (user_id, token_count) in enumerate(ranking_data.items()):
                if x >= 3:
                    break

                user = self.bot.get_user(user_id)
                if user is not None:
                    embed.add_field(name=f"{x + 1}位 {user.global_name}", value=f"{token_count} token", inline=False)

            await ctx.send(embed=embed)

        @commands.hybrid_command(name="info", brief="現在の設定を出力")
        async def check_setting(ctx):
            embed = discord.Embed(title="Bot Config", color=0xFF0000)
            embed.set_author(name=self.bot.user, url="https://github.com/fockerev/bot_for_fmj")
            embed.add_field(name="BOT VERSION", value="20250527_2100", inline=False)
            embed.add_field(name="Model", value=self.config.gpt.model, inline=True)
            embed.add_field(name="Temperature", value=self.config.gpt.temperature, inline=True)
            embed.add_field(name="Input Image Resolution", value=self.config.gpt.image_resolution, inline=True)
            embed.add_field(name="Max token", value=self.config.gpt.max_token, inline=True)
            embed.add_field(name="Max history size", value=self.config.bot.history_size, inline=True)
            embed.add_field(name="Save api response", value=self.config.bot.save_api_response, inline=True)
            embed.add_field(name="Save image input", value=self.config.bot.save_image_input, inline=True)
            
            system_prompt = self.gpt_service.get_system_prompt(ctx.guild.id)
            if system_prompt:
                embed.add_field(name="System prompt", value=system_prompt, inline=False)

            await ctx.send(embed=embed)

        @commands.hybrid_command(name="change_config", brief="設定を変更")
        async def change_setting(
            ctx: commands.context.Context,
            input_highreso_img: Optional[bool],
            save_image_input: Optional[bool],
            save_response: Optional[bool],
            history_size: Optional[int],
        ):
            msg = ""
            if input_highreso_img is not None:
                self.config.gpt.image_resolution = ImageReso(int(input_highreso_img))
                if self.config.gpt.image_resolution == ImageReso(int(input_highreso_img)):
                    msg += f"[Success] Input Image Resolution -> {self.config.gpt.image_resolution}\n"
                else:
                    msg += "[Fail] Input Image Resolution\n"
            if history_size is not None and history_size > 0:
                self.config.bot.history_size = history_size
                if self.config.bot.history_size == history_size:
                    msg += f"[Success] history_size -> {self.config.bot.history_size}\n"
                else:
                    msg += "[Fail] history_size\n"
            if save_image_input is not None:
                self.config.bot.save_image_input = bool(save_image_input)
                if self.config.bot.save_image_input == bool(save_image_input):
                    msg += f"[Success] save_image_input -> {self.config.bot.save_image_input}\n"
                else:
                    msg += "[Fail] save_image_input\n"
            if save_response is not None:
                self.config.bot.save_api_response = bool(save_response)
                if self.config.bot.save_api_response == bool(save_response):
                    msg += f"[Success] save_api_response -> {self.config.bot.save_api_response}\n"
                else:
                    msg += "[Fail] save_api_response\n"
            if len(msg) == 0:
                msg += "config is unchanged"
            await ctx.send(msg)

        @commands.hybrid_command(name="reset_config", brief="設定をリセット yamlから再読み込み")
        async def reset_setting(ctx):
            from pathlib import Path
            self.config = AppConfig.load((Path(__file__).resolve().parent / ".." / "setting.yaml").resolve())
            await ctx.send("Reload config")

        @commands.hybrid_command(name="history", brief="対話履歴を出力")
        async def check_history(ctx):
            guild_id = ctx.guild.id
            if guild_id in self.gpt_service.chat_histories and len(self.gpt_service.chat_histories[guild_id].messages) > 0:
                embed = discord.Embed(title="History", color=0x00FF4C)
                for idx, msg in enumerate(self.gpt_service.chat_histories[guild_id].messages):
                    content = str(msg.content)
                    if len(content) > 150:
                        content = content[:150]
                    embed.add_field(name=f"{idx}\t{msg.role.value}", value=f"{content}", inline=False)
                await ctx.send(embed=embed)
            else:
                await ctx.send("対話履歴がありません")

        @commands.hybrid_command(name="help", brief="help")
        async def help_command(ctx: commands.context.Context, args=None):
            help_embed = discord.Embed()
            command_names_list = [x.name for x in self.bot.commands]

            # If there are no arguments, just list the commands:
            if not args:
                help_embed.add_field(
                    name="List of supported commands:", 
                    value="\n".join([str(i + 1) + ". " + x.name for i, x in enumerate(self.bot.commands)]), 
                    inline=False
                )
                help_embed.add_field(name="Details", value="Type `.help <command name>` for more details about each command.", inline=False)

            # If the argument is a command, get the help text from that command:
            elif args in command_names_list:
                help_embed.add_field(name=args, value=self.bot.get_command(args).brief)

            # If someone is just trolling:
            else:
                help_embed.add_field(name="Nope.", value="Don't think I got that command, boss!")

            await ctx.send(embed=help_embed)

        # Register all commands
        self.bot.add_command(reset_h)
        self.bot.add_command(reset_c)
        self.bot.add_command(change)
        self.bot.add_command(ranking)
        self.bot.add_command(check_setting)
        self.bot.add_command(change_setting)
        self.bot.add_command(reset_setting)
        self.bot.add_command(check_history)
        self.bot.add_command(help_command)