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
            # Use abstraction layer to add user message
            await self.gpt_service.add_user_message_to_history(ctx.guild.id, input)
            self.logger.info(f"[Search Input] {str(input)}")

            await ctx.defer()

            # Check if MCP is enabled
            if self.config.mcp.enabled and self.mcp_client:
                response_text = await self._mcp_search(ctx.guild.id, input)
            else:
                # Fallback to OpenAI web search
                response_text = await self._openai_search(ctx.guild.id)

            self.logger.info(f"[Response] {response_text}")

            if self.config.bot.save_api_response is True:
                # Use abstraction layer to add assistant message
                await self.gpt_service.add_assistant_message_to_history(ctx.guild.id, response_text)

            # Apply history reduction using abstraction layer
            is_reduced = await self.gpt_service.reduce_history(ctx.guild.id)
            if is_reduced:
                history_size = self.gpt_service.check_history_size(ctx.guild.id)
                self.logger.info(f"History reduced to {history_size} messages for guild {ctx.guild.id}")

            await ctx.send(content=response_text)

        except Exception as e:
            self.logger.exception("error occurred in search api processing")
            await ctx.send(f"なんかエラー出た {e}")

    async def _mcp_search(self, guild_id: int, query: str) -> str:
        """Perform web search using MCP server."""
        try:
            # Start MCP client
            await self.mcp_client.start()

            # Perform full web search
            search_results = await self.mcp_client.full_web_search(
                query,
                limit=self.config.mcp.search_result_limit
            )

            # Format search results for AI processing
            search_context = self._format_search_results(search_results)

            # Use AI service to generate response based on search results
            # This will use the guild's chat history and system prompt
            response = await self.gpt_service.generate_search_response(guild_id, query, search_context)

            return response

        except Exception as e:
            self.logger.error(f"MCP search failed: {e}")
            raise
        finally:
            # Stop MCP client
            if self.mcp_client:
                await self.mcp_client.stop()

    def _format_search_results(self, results: list) -> str:
        """Format search results into a readable context string."""
        if not results:
            return "検索結果が見つかりませんでした。"

        formatted = "以下は検索結果です:\n\n"
        for i, result in enumerate(results, 1):
            if isinstance(result, dict):
                title = result.get("title", "No title")
                url = result.get("url", "")
                content = result.get("content", result.get("snippet", ""))

                formatted += f"{i}. {title}\n"
                if url:
                    formatted += f"   URL: {url}\n"
                formatted += f"   {content[:500]}...\n\n"
            else:
                formatted += f"{i}. {str(result)[:500]}...\n\n"

        return formatted

    async def _openai_search(self, guild_id: int) -> str:
        """Fallback to OpenAI web search API."""
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
