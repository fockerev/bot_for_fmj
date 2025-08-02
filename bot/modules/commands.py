import sys
from pathlib import Path

import discord
from discord.ext import commands

# Add parent directory to sys.path for absolute imports
sys.path.append(str(Path(__file__).parent))

from config import AIProvider, AppConfig, ImageReso
from gpt_service import GptService


class ConfigView(discord.ui.View):
    def __init__(self, config: AppConfig):
        super().__init__(timeout=300)
        self.config = config
        self.message = None

        self.add_item(AIProviderSelect(config))
        self.add_item(ModelSelect(config))
        self.add_item(ImageResolutionSelect(config))
        self.add_item(BooleanSettingsSelect(config))
        self.add_item(NumberSettingsButton(config))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class AIProviderSelect(discord.ui.Select):
    def __init__(self, config: AppConfig):
        self.config = config
        options = [
            discord.SelectOption(label="OpenAI", value="openai", description="OpenAI GPT models", emoji="🤖", default=config.gpt.ai_provider.value == "openai"),
            discord.SelectOption(
                label="Gemini", value="gemini", description="Google Gemini models", emoji="💎", default=config.gpt.ai_provider.value == "gemini"
            ),
        ]

        super().__init__(placeholder="AIプロバイダーを選択...", options=options, custom_id="ai_provider_select")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            new_provider = AIProvider(self.values[0])
            self.config.gpt.ai_provider = new_provider

            # Reinitialize AI services after provider change
            await self._reinitialize_services(interaction)

            embed = discord.Embed(title="✅ 設定更新", description=f"AIプロバイダーを **{new_provider.value}** に変更しました", color=0x00FF00)
            await interaction.followup.send(embed=embed, ephemeral=True)

            await self.update_main_embed(interaction)
        except Exception as e:
            embed = discord.Embed(title="❌ エラー", description=f"設定の更新に失敗しました: {str(e)}", color=0xFF0000)
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _reinitialize_services(self, interaction):
        """Reinitialize AI services in all cogs"""
        bot = interaction.client
        
        # Reinitialize GPT service in main commands
        for cog in bot.cogs.values():
            if hasattr(cog, 'gpt_service') and hasattr(cog.gpt_service, 'reinitialize_ai_service'):
                cog.gpt_service.reinitialize_ai_service()
            if hasattr(cog, 'reinitialize_ai_service'):
                cog.reinitialize_ai_service()

    async def update_main_embed(self, interaction):
        active_model = self.config.gpt.openai_model if self.config.gpt.ai_provider.value == "openai" else self.config.gpt.gemini_model
        embed = discord.Embed(title="⚙️ Bot 設定", color=0x00AAFF)
        embed.description = "下のメニューから設定を変更してください"
        embed.add_field(name="現在のモデル", value=f"{active_model} ({self.config.gpt.ai_provider.value})", inline=True)
        embed.add_field(name="画像解像度", value=self.config.gpt.image_resolution.name, inline=True)
        embed.add_field(name="履歴サイズ", value=str(self.config.bot.history_size), inline=True)
        embed.add_field(name="画像保存", value="✅" if self.config.bot.save_image_input else "❌", inline=True)
        embed.add_field(name="レスポンス保存", value="✅" if self.config.bot.save_api_response else "❌", inline=True)

        # Create new view with updated state
        new_view = ConfigView(self.config)
        new_view.message = interaction.message

        try:
            await interaction.edit_original_response(embed=embed, view=new_view)
        except Exception:
            pass


class ModelSelect(discord.ui.Select):
    def __init__(self, config: AppConfig):
        self.config = config

        if config.gpt.ai_provider.value == "openai":
            options = [
                discord.SelectOption(label="gpt-4o", value="gpt-4o", emoji="🚀"),
                discord.SelectOption(label="gpt-4", value="gpt-4", emoji="🧠"),
                # discord.SelectOption(label="gpt-3.5-turbo", value="gpt-3.5-turbo", emoji="⚡"),
            ]
        else:
            options = [
                discord.SelectOption(label="gemini-2.5-pro", value="gemini-2.5-pro", emoji="💎"),
                discord.SelectOption(label="gemini-2.5-flash", value="gemini-2.5-flash", emoji="👑"),
                discord.SelectOption(label="gemini-2.5-flash-lite", value="gemini-2.5-flash-lite", emoji="⚡"),
            ]

        super().__init__(placeholder="モデルを選択...", options=options, custom_id="model_select")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            if self.config.gpt.ai_provider.value == "openai":
                self.config.gpt.openai_model = self.values[0]
            else:
                self.config.gpt.gemini_model = self.values[0]

            # Reinitialize AI services after model change
            await self._reinitialize_services(interaction)

            embed = discord.Embed(title="✅ 設定更新", description=f"モデルを **{self.values[0]}** に変更しました", color=0x00FF00)
            await interaction.followup.send(embed=embed, ephemeral=True)

            await self.update_main_embed(interaction)
        except Exception as e:
            embed = discord.Embed(title="❌ エラー", description=f"設定の更新に失敗しました: {str(e)}", color=0xFF0000)
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _reinitialize_services(self, interaction):
        """Reinitialize AI services in all cogs"""
        bot = interaction.client
        
        # Reinitialize GPT service in main commands
        for cog in bot.cogs.values():
            if hasattr(cog, 'gpt_service') and hasattr(cog.gpt_service, 'reinitialize_ai_service'):
                cog.gpt_service.reinitialize_ai_service()
            if hasattr(cog, 'reinitialize_ai_service'):
                cog.reinitialize_ai_service()

    async def update_main_embed(self, interaction):
        active_model = self.config.gpt.openai_model if self.config.gpt.ai_provider.value == "openai" else self.config.gpt.gemini_model
        embed = discord.Embed(title="⚙️ Bot 設定", color=0x00AAFF)
        embed.description = "下のメニューから設定を変更してください"
        embed.add_field(name="現在のモデル", value=f"{active_model} ({self.config.gpt.ai_provider.value})", inline=True)
        embed.add_field(name="画像解像度", value=self.config.gpt.image_resolution.name, inline=True)
        embed.add_field(name="履歴サイズ", value=str(self.config.bot.history_size), inline=True)
        embed.add_field(name="画像保存", value="✅" if self.config.bot.save_image_input else "❌", inline=True)
        embed.add_field(name="レスポンス保存", value="✅" if self.config.bot.save_api_response else "❌", inline=True)

        # Create new view with updated state
        new_view = ConfigView(self.config)
        new_view.message = interaction.message

        try:
            await interaction.edit_original_response(embed=embed, view=new_view)
        except Exception:
            pass


class ImageResolutionSelect(discord.ui.Select):
    def __init__(self, config: AppConfig):
        self.config = config
        options = [
            discord.SelectOption(label="低解像度", value="0", description="処理速度重視", emoji="⚡", default=config.gpt.image_resolution == ImageReso.LOW),
            discord.SelectOption(label="高解像度", value="1", description="画質重視", emoji="🖼️", default=config.gpt.image_resolution == ImageReso.HIGH),
        ]

        super().__init__(placeholder="画像解像度を選択...", options=options, custom_id="image_resolution_select")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            self.config.gpt.image_resolution = ImageReso(int(self.values[0]))

            embed = discord.Embed(title="✅ 設定更新", description=f"画像解像度を **{self.config.gpt.image_resolution.name}** に変更しました", color=0x00FF00)
            await interaction.followup.send(embed=embed, ephemeral=True)

            await self.update_main_embed(interaction)
        except Exception as e:
            embed = discord.Embed(title="❌ エラー", description=f"設定の更新に失敗しました: {str(e)}", color=0xFF0000)
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def update_main_embed(self, interaction):
        active_model = self.config.gpt.openai_model if self.config.gpt.ai_provider.value == "openai" else self.config.gpt.gemini_model
        embed = discord.Embed(title="⚙️ Bot 設定", color=0x00AAFF)
        embed.description = "下のメニューから設定を変更してください"
        embed.add_field(name="現在のモデル", value=f"{active_model} ({self.config.gpt.ai_provider.value})", inline=True)
        embed.add_field(name="画像解像度", value=self.config.gpt.image_resolution.name, inline=True)
        embed.add_field(name="履歴サイズ", value=str(self.config.bot.history_size), inline=True)
        embed.add_field(name="画像保存", value="✅" if self.config.bot.save_image_input else "❌", inline=True)
        embed.add_field(name="レスポンス保存", value="✅" if self.config.bot.save_api_response else "❌", inline=True)

        # Create new view with updated state
        new_view = ConfigView(self.config)
        new_view.message = interaction.message

        try:
            await interaction.edit_original_response(embed=embed, view=new_view)
        except Exception:
            pass


class BooleanSettingsSelect(discord.ui.Select):
    def __init__(self, config: AppConfig):
        self.config = config
        options = [
            discord.SelectOption(
                label=f"画像保存: {'ON' if config.bot.save_image_input else 'OFF'}",
                value="save_image_input",
                description="入力画像を保存するかどうか",
                emoji="💾",
            ),
            discord.SelectOption(
                label=f"レスポンス保存: {'ON' if config.bot.save_api_response else 'OFF'}",
                value="save_api_response",
                description="APIレスポンスを保存するかどうか",
                emoji="📄",
            ),
        ]

        super().__init__(placeholder="ON/OFF設定を切り替え...", options=options, custom_id="boolean_settings_select")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            setting = self.values[0]
            if setting == "save_image_input":
                self.config.bot.save_image_input = not self.config.bot.save_image_input
                new_value = self.config.bot.save_image_input
                setting_name = "画像保存"
            else:
                self.config.bot.save_api_response = not self.config.bot.save_api_response
                new_value = self.config.bot.save_api_response
                setting_name = "レスポンス保存"

            embed = discord.Embed(title="✅ 設定更新", description=f"{setting_name}を **{'ON' if new_value else 'OFF'}** に変更しました", color=0x00FF00)
            await interaction.followup.send(embed=embed, ephemeral=True)

            await self.update_main_embed(interaction)
        except Exception as e:
            embed = discord.Embed(title="❌ エラー", description=f"設定の更新に失敗しました: {str(e)}", color=0xFF0000)
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def update_main_embed(self, interaction):
        active_model = self.config.gpt.openai_model if self.config.gpt.ai_provider.value == "openai" else self.config.gpt.gemini_model
        embed = discord.Embed(title="⚙️ Bot 設定", color=0x00AAFF)
        embed.description = "下のメニューから設定を変更してください"
        embed.add_field(name="現在のモデル", value=f"{active_model} ({self.config.gpt.ai_provider.value})", inline=True)
        embed.add_field(name="画像解像度", value=self.config.gpt.image_resolution.name, inline=True)
        embed.add_field(name="履歴サイズ", value=str(self.config.bot.history_size), inline=True)
        embed.add_field(name="画像保存", value="✅" if self.config.bot.save_image_input else "❌", inline=True)
        embed.add_field(name="レスポンス保存", value="✅" if self.config.bot.save_api_response else "❌", inline=True)

        # Create new view with updated state
        new_view = ConfigView(self.config)
        new_view.message = interaction.message

        try:
            await interaction.edit_original_response(embed=embed, view=new_view)
        except Exception:
            pass


class NumberSettingsButton(discord.ui.Button):
    def __init__(self, config: AppConfig):
        self.config = config
        super().__init__(label=f"履歴サイズ: {config.bot.history_size}", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="number_settings_button")

    async def callback(self, interaction: discord.Interaction):
        modal = NumberSettingsModal(self.config)
        await interaction.response.send_modal(modal)


class NumberSettingsModal(discord.ui.Modal):
    def __init__(self, config: AppConfig):
        self.config = config
        super().__init__(title="数値設定")

        self.history_size = discord.ui.TextInput(
            label="履歴サイズ", placeholder="1-100の数値を入力してください", default=str(config.bot.history_size), min_length=1, max_length=3
        )
        self.add_item(self.history_size)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_size = int(self.history_size.value)
            if 1 <= new_size <= 100:
                self.config.bot.history_size = new_size

                embed = discord.Embed(title="✅ 設定更新", description=f"履歴サイズを **{new_size}** に変更しました", color=0x00FF00)
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                embed = discord.Embed(title="❌ エラー", description="履歴サイズは1-100の範囲で入力してください", color=0xFF0000)
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except ValueError:
            embed = discord.Embed(title="❌ エラー", description="数値を正しく入力してください", color=0xFF0000)
            await interaction.response.send_message(embed=embed, ephemeral=True)


class BotCommands:
    def __init__(self, bot: commands.Bot, gpt_service: GptService, config: AppConfig):
        self.bot = bot
        self.gpt_service = gpt_service
        self.config = config

    def register_commands(self):
        """Register all commands with the bot"""

        @commands.hybrid_command(name="history_reset", brief="会話履歴をリセットする. 60分ごとに自動実行")
        async def reset_h(ctx):
            ret = self.gpt_service.reset_history(guild_id=ctx.guild.id)
            if ret:
                await ctx.send("会話履歴をリセットしました")
            else:
                await ctx.send("会話履歴のリセットに失敗しました")

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

        @commands.hybrid_command(name="chara_reset", brief="性格を初期化する")
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

        @commands.hybrid_command(name="config", brief="設定を変更")
        async def change_setting(ctx: commands.context.Context):
            view = ConfigView(self.config)
            embed = discord.Embed(title="⚙️ Bot 設定", color=0x00AAFF)
            embed.description = "下のメニューから設定を変更してください"

            active_model = self.config.gpt.openai_model if self.config.gpt.ai_provider.value == "openai" else self.config.gpt.gemini_model
            embed.add_field(name="現在のモデル", value=f"{active_model} ({self.config.gpt.ai_provider.value})", inline=True)
            embed.add_field(name="画像解像度", value=self.config.gpt.image_resolution.name, inline=True)
            embed.add_field(name="履歴サイズ", value=str(self.config.bot.history_size), inline=True)
            embed.add_field(name="画像保存", value="✅" if self.config.bot.save_image_input else "❌", inline=True)
            embed.add_field(name="レスポンス保存", value="✅" if self.config.bot.save_api_response else "❌", inline=True)

            message = await ctx.send(embed=embed, view=view)
            view.message = message

        @commands.hybrid_command(name="config_reset", brief="設定をリセット yamlから再読み込み")
        async def reset_setting(ctx):
            from pathlib import Path

            self.config = AppConfig.load((Path(__file__).resolve().parent / ".." / "setting.yaml").resolve())
            await ctx.send("Reload config")

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
            # Display the active model based on current provider
            active_model = self.config.gpt.openai_model if self.config.gpt.ai_provider.value == "openai" else self.config.gpt.gemini_model
            embed.add_field(name="Model", value=f"{active_model} ({self.config.gpt.ai_provider.value})", inline=True)
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

        @commands.hybrid_command(name="help", brief="help")
        async def help_command(ctx: commands.context.Context, args=None):
            help_embed = discord.Embed()
            command_names_list = [x.name for x in self.bot.commands]

            # If there are no arguments, just list the commands:
            if not args:
                help_embed.add_field(
                    name="List of supported commands:", value="\n".join([str(i + 1) + ". " + x.name for i, x in enumerate(self.bot.commands)]), inline=False
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
