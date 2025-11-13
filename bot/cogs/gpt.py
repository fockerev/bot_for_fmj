import datetime
import json
import logging
import logging.config
import sys
from pathlib import Path

import discord
import openai
from discord.ext import commands, tasks

sys.path.append(str(Path(__file__).parent.parent))

from modules.commands import BotCommands
from modules.config import AppConfig
from modules.gpt_service import GptService
from modules.message_parser import MessageParser
from modules.mcp_client import MCPClient
from modules.web_search_plugin import WebSearchPlugin

VERSION = "20250527_2100"


class BotCog(commands.Cog):
    def __init__(self, bot) -> None:
        # Initialize logger
        self._setup_logger()

        self.bot = bot
        self.config = self._load_config()

        # Initialize services
        self.gpt_service = GptService(self.config, self.logger)
        self.message_parser = MessageParser(self.logger)

        # Initialize MCP client if enabled
        self.mcp_client = None
        if self.config.mcp.enabled:
            self.mcp_client = MCPClient(
                self.config.mcp.command,
                self.config.mcp.args,
                self.logger
            )

        # Initialize commands
        self.bot_commands = BotCommands(self.bot, self.gpt_service, self.config)
        self.bot_commands.register_commands()

    def _setup_logger(self) -> None:
        """Setup logger configuration"""
        try:
            with open(str((Path(__file__).resolve().parent / ".." / "logging_config.json").resolve()), "r") as f:
                log_conf = json.load(f)
            logging.config.dictConfig(log_conf)
            self.logger = logging.getLogger("gpt")
        except Exception as e:
            # Fallback to basic logging if config fails
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger("gpt")
            self.logger.error(f"Failed to load logging config: {e}")

    def _load_config(self) -> AppConfig:
        """Load application configuration"""
        try:
            return AppConfig.load((Path(__file__).resolve().parent / ".." / "setting.yaml").resolve())
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            raise

    @commands.Cog.listener()
    async def on_ready(self):
        """Bot ready event handler"""
        self.loop_reset.start()
        self.logger.info("loop start")

    @commands.hybrid_command(name="search", brief="[beta]Web検索を使用して回答")
    async def web_search_question(self, ctx: commands.context.Context, input: str):
        """サーチAPIを使って回答を生成する"""
        try:
            self.logger.info(f"[Search Input] {str(input)}")

            await ctx.defer()

            # Check if MCP is enabled
            if self.config.mcp.enabled and self.mcp_client:
                # Plugin-based search handles history internally
                response_text = await self._mcp_search_with_plugin(ctx.guild.id, input)

                # Add conversation to history if enabled
                if self.config.bot.save_api_response is True:
                    await self.gpt_service.add_user_message_to_history(ctx.guild.id, input)
                    await self.gpt_service.add_assistant_message_to_history(ctx.guild.id, response_text)
            else:
                # Fallback to OpenAI web search (handles history internally)
                response_text = await self._openai_search(ctx.guild.id, input)

                # Add assistant response to history if enabled
                if self.config.bot.save_api_response is True:
                    await self.gpt_service.add_assistant_message_to_history(ctx.guild.id, response_text)

            self.logger.info(f"[Response] {response_text}")

            # Apply history reduction using abstraction layer
            is_reduced = await self.gpt_service.reduce_history(ctx.guild.id)
            if is_reduced:
                history_size = self.gpt_service.check_history_size(ctx.guild.id)
                self.logger.info(f"History reduced to {history_size} messages for guild {ctx.guild.id}")

            await ctx.send(content=response_text)

        except Exception as e:
            self.logger.exception("error occurred in search api processing")
            await ctx.send(f"なんかエラー出た {e}")

    async def _mcp_search_with_plugin(self, guild_id: int, query: str) -> str:
        """Perform web search using MCP plugin with Semantic Kernel.

        This method uses the WebSearchPlugin which allows the AI to automatically
        call the web search function when needed.
        """
        try:
            self.logger.info("=" * 80)
            self.logger.info("🔍 [MCP SEARCH WITH PLUGIN] Initializing...")
            self.logger.info(f"🏰 Guild ID: {guild_id}")
            self.logger.info(f"📝 Query: {query}")
            self.logger.info(f"🔢 Search result limit: {self.config.mcp.search_result_limit}")
            self.logger.info("=" * 80)

            # Create web search plugin
            self.logger.info("🔌 Creating WebSearchPlugin instance...")
            web_search_plugin = WebSearchPlugin(
                mcp_client=self.mcp_client,
                search_result_limit=self.config.mcp.search_result_limit
            )
            self.logger.info("✅ WebSearchPlugin created")

            # Use AI service with plugin to generate response
            # force_search=True ensures web search is ALWAYS executed
            self.logger.info("🤖 Delegating to GptService.generate_search_response_with_plugin...")
            self.logger.info("🔒 Using force_search=True to ensure web search is always executed")
            response = await self.gpt_service.generate_search_response_with_plugin(
                guild_id=guild_id,
                query=query,
                web_search_plugin=web_search_plugin,
                force_search=True  # Always execute web search for /search command
            )

            self.logger.info("=" * 80)
            self.logger.info("✅ [MCP SEARCH WITH PLUGIN] Completed successfully")
            self.logger.info("=" * 80)

            return response

        except Exception as e:
            self.logger.error("=" * 80)
            self.logger.error(f"❌ [MCP SEARCH WITH PLUGIN] Failed: {e}")
            self.logger.error("=" * 80)
            self.logger.exception("Full error traceback:")
            raise

    async def _openai_search(self, guild_id: int, query: str) -> str:
        """Fallback to OpenAI web search API."""
        # Add user query to history
        await self.gpt_service.add_user_message_to_history(guild_id, query)

        # Get history messages using abstraction layer
        history_messages = await self.gpt_service.get_history_messages(guild_id)
        messages = []
        for msg in history_messages:
            messages.append({"role": msg.role.value, "content": str(msg.content)})

        response = openai.responses.create(
            model=self.config.gpt.openai_model,
            tools=[{"type": "web_search_preview"}],
            input=messages,
            max_output_tokens=800
        )
        return str(response.output_text)

    @tasks.loop(minutes=5)
    async def loop_reset(self):
        """定期的な履歴リセット処理"""
        try:
            if self.gpt_service.should_reset_history():
                # For legacy mode, reset all active chat histories
                if not self.gpt_service.use_enhanced_history:
                    if len(self.gpt_service.chat_histories) > 0:
                        for guild_id in list(self.gpt_service.chat_histories.keys()):
                            await self.gpt_service.reset_history(guild_id)

                        self.logger.info("cyclic history reset")
                else:
                    # Enhanced mode handles history management automatically
                    self.logger.debug("Enhanced mode active - skipping manual reset")

                self.gpt_service.last_activity = datetime.datetime.now()
        except Exception as e:
            self.logger.error(f"Error in loop_reset: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.message.Message):
        """メッセージ受信時の処理"""
        # Bot自身からの入力なら無視
        if message.author == self.bot.user:
            return

        if self.bot.user.id in [member.id for member in message.mentions]:
            try:
                # Initialize services
                self.gpt_service.initialize_chat_history(message.guild.id)

                # Parse message and get GPT response
                plane_message, reference_message, attachments = await self.message_parser.parse_message(message)
                response = await self.gpt_service.send_question_gpt(plane_message, reference_message, attachments, message.guild.id)

                # History cleanup is now handled automatically by ChatHistoryTruncationReducer
                await message.channel.send(response)

            except ValueError as e:
                # Handle validation errors gracefully
                self.logger.warning(f"Validation error: {e}")
                await message.channel.send(str(e))
            except Exception as e:
                self.logger.exception("error occurred in gpt processing")
                await message.channel.send(f"なんかエラー出た {e}")


async def setup(bot):
    await bot.add_cog(BotCog(bot))
