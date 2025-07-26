import datetime
import inspect
import json
import logging
import logging.config
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Type, TypeVar
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import discord
import openai
import urlextract
import yaml
from discord.ext import commands, tasks

import semantic_kernel as sk
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel.contents.chat_history import ChatHistory

VERSION = "20250527_2100"


class ImageReso(Enum):
    LOW = 0
    HIGH = 1


T = TypeVar("T", bound="YamlConfig")


@dataclass
class YamlConfig:
    @classmethod
    def load(cls: Type[T], config_path: Path) -> T:
        def _convert_from_dict(parent_cls: Type[T], data: Dict[str, Any]) -> Dict[str, Any]:
            valid_data = {key: val for key, val in data.items() if key in parent_cls.__dataclass_fields__}
            for key, val in valid_data.items():
                child_class = parent_cls.__dataclass_fields__[key].type
                if inspect.isclass(child_class) and issubclass(child_class, YamlConfig):
                    valid_data[key] = child_class(**_convert_from_dict(child_class, val))
                elif isinstance(child_class, type) and issubclass(child_class, Enum):
                    valid_data[key] = child_class(val)
            return valid_data

        if config_path.exists() is False:
            raise FileNotFoundError(f"{str(config_path)} is not found")

        with open(config_path) as f:
            config_data = yaml.safe_load(f)
            config_data = _convert_from_dict(cls, config_data)
            return cls(**config_data)


@dataclass
class gptconfig(YamlConfig):
    model: str
    max_token: int
    temperature: float
    image_resolution: ImageReso


@dataclass
class botconfig(YamlConfig):
    save_api_response: bool
    save_image_input: bool
    history_size: int
    default_system_promt: str


@dataclass
class AppConfig(YamlConfig):
    gpt: gptconfig
    bot: botconfig


class BotCog(commands.Cog):
    def __init__(self, bot) -> None:
        # define logger
        with open(str((Path(__file__).resolve().parent / ".." / "logging_config.json").resolve()), "r") as f:
            log_conf = json.load(f)
        logging.config.dictConfig(log_conf)
        self.__logger = logging.getLogger("gpt")

        self.bot = bot
        self.config = AppConfig.load((Path(__file__).resolve().parent / ".." / "setting.yaml").resolve())

        # Initialize Semantic Kernel
        self.kernel = sk.Kernel()
        chat_completion = OpenAIChatCompletion(ai_model_id=self.config.gpt.model, service_id="chat-gpt")
        self.kernel.add_service(chat_completion)

        self.__chat_histories: dict = {}  # Semantic Kernel chat histories
        self.__token_ranking: dict = {}
        self.__last_activity: datetime = datetime.datetime.now()

    async def reset_history(self, guild_id: int) -> bool:
        """履歴削除"""
        if guild_id in self.__chat_histories:
            self.__chat_histories[guild_id] = ChatHistory()
            self.__chat_histories[guild_id].add_system_message(self.config.bot.default_system_promt)
            self.__logger.info("history reset")
            return True
        else:
            return False

    async def reset_charactor(self, guild_id: int) -> bool:
        """性格をリセットする"""
        if guild_id in self.__chat_histories.keys():
            self.__chat_histories[guild_id] = ChatHistory()
            self.__chat_histories[guild_id].add_system_message(self.config.bot.default_system_promt)
            self.__logger.info("system charactor reset")
            return True
        else:
            return False

    async def change_charactor(self, guild_id: int, txt: str) -> bool:
        """gptにわたす性格設定を変更する

        Args:
            txt (str): 変更先の性格設定文
        """
        try:
            self.__chat_histories[guild_id] = ChatHistory()
            self.__chat_histories[guild_id].add_system_message(txt)
            if guild_id in self.__chat_histories.keys():
                self.__logger.info(f"system charactor changed -> {txt}")
            else:
                self.__logger.info(f"charactor created for new server-> {txt}")
        except Exception:
            self.__logger.exception("Charactor setting failed")
            return False
        return True

    def check_history_size(self, guild_id: int) -> int:
        """履歴配列長の確認

        Returns:
            int : 配列長
        """
        if guild_id in self.__chat_histories:
            return len(self.__chat_histories[guild_id].messages)
        return 0

    async def delete_old_history(self, guild_id: int) -> None:
        """一番古い履歴を削除する"""
        if guild_id in self.__chat_histories and len(self.__chat_histories[guild_id].messages) > self.config.bot.history_size:
            # Keep system message and remove oldest user/assistant messages
            messages = self.__chat_histories[guild_id].messages
            system_messages = [msg for msg in messages if msg.role.value == "system"]
            other_messages = [msg for msg in messages if msg.role.value != "system"]
            if len(other_messages) > self.config.bot.history_size - len(system_messages):
                # Remove the oldest non-system messages
                other_messages = other_messages[-(self.config.bot.history_size - len(system_messages)) :]

            # Reconstruct chat history
            new_chat_history = ChatHistory()
            for msg in system_messages:
                new_chat_history.add_system_message(str(msg.content))
            for msg in other_messages:
                if msg.role.value == "user":
                    new_chat_history.add_user_message(str(msg.content))
                elif msg.role.value == "assistant":
                    new_chat_history.add_assistant_message(str(msg.content))

            self.__chat_histories[guild_id] = new_chat_history

    async def parse_message(self, message: discord.message.Message) -> tuple[str, str | None, list]:
        """入力メッセージを処理して、入力・参照・添付ファイルにする

        Args:
            message (discord.message.Message): 入力メッセージ

        Raises:
            ValueError: 非対応な拡張子の場合
            ValueError: 無効なURLの場合

        Returns:
            tuple[str, str | None, list]: 入力, 参照, 添付ファイルのリスト
        """

        reference_message = None
        attachments_list = []

        #
        plane_message = re.sub(r"<@\d+>", "", message.content)
        plane_message = plane_message.strip()
        if message.reference is not None:
            if message.reference.resolved is not None:
                reference_message = message.reference.resolved.content

        # 添付ファイルの抽出
        # 対応ファイル形式の拡張
        supported_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff', '.tif', '.svg'
        }
        extention = re.compile(r"\.(png|jpe?g|gif|webp|bmp|tiff?|svg)(?:\?[^\s]*)?$", re.IGNORECASE)
        # 直接メッセージに添付
        if 0 < len(message.attachments):
            for attach in message.attachments:
                if await self._is_valid_image_url(attach.url, extention):
                    attachments_list.append(attach.url)
                else:
                    supported_formats = ', '.join(sorted(supported_extensions))
                    raise ValueError(f"未対応のファイル形式です。対応形式: {supported_formats}")

        # チャットから画像のURLを抽出
        extractor = urlextract.URLExtract()
        extracted_urls = extractor.find_urls(plane_message)
        if len(extracted_urls) > 0:
            for url in extracted_urls:
                if await self._is_valid_image_url(url, extention):
                    # HTTPSにリダイレクト
                    secure_url = self._ensure_https(url)
                    attachments_list.append(secure_url)
                    plane_message = plane_message.replace(url, "")
                else:
                    supported_formats = ', '.join(sorted(supported_extensions))
                    raise ValueError(f"未対応のURL形式またはアクセスできません。対応形式: {supported_formats}")

        return plane_message, reference_message, attachments_list

    def _ensure_https(self, url: str) -> str:
        """URLをHTTPSに変換する"""
        if url.startswith('http://'):
            return url.replace('http://', 'https://', 1)
        return url

    async def _is_valid_image_url(self, url: str, pattern: re.Pattern) -> bool:
        """画像URLの有効性とアクセス可能性をチェックする"""
        try:
            # URL形式の基本チェック
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False
            
            # 拡張子チェック
            if not pattern.search(url):
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
                return pattern.search(url) is not None
                
        except (URLError, HTTPError, Exception) as e:
            self.__logger.warning(f"URL validation failed for {url}: {e}")
            return False

    async def send_question_gpt(self, question: str, reference: str, attachments: list, guild_id: int) -> tuple[str, int]:
        """Semantic Kernelでリクエストを送信し結果を得る

        Args:
            question (str): 入力テキスト
            reference (str): 参照先テキスト
            attachments (list): 添付ファイル
            guild_id (int): サーバーID

        Returns:
            tuple[str, int]: 応答, 消費トークン数
        """
        self.__logger.info(f"[Question] {question}")

        # Initialize chat history if not exists
        if guild_id not in self.__chat_histories:
            self.__chat_histories[guild_id] = ChatHistory()
            self.__chat_histories[guild_id].add_system_message(self.config.bot.default_system_promt)

        # Build user message
        user_message = question
        if reference is not None:
            user_message += f"\n## 以下へ言及\n{reference}"
            self.__logger.info(f"[Reference] {reference}")

        # Add user message to chat history
        # Will be added later based on whether it's text-only or has images

        # Handle image attachments (fallback to OpenAI direct call for vision)
        if len(attachments) > 0:
            self.__logger.info(f"[Attachments] {attachments}")
            # For vision tasks, fallback to direct OpenAI API call
            if self.config.gpt.image_resolution == ImageReso.LOW:
                reso = "low"
            else:
                reso = "high"

            image_input = []
            for url in attachments:
                image_input.append({"type": "image_url", "image_url": {"url": url, "detail": reso}})

            # Convert chat history to OpenAI format for vision
            messages = []
            for msg in self.__chat_histories[guild_id].messages:
                messages.append({"role": msg.role.value, "content": str(msg.content)})

            # Add user message with images to both histories
            self.__chat_histories[guild_id].add_user_message(user_message)

            # Add current message with images
            messages.append({"role": "user", "content": [{"type": "text", "text": user_message}] + image_input})

            response = openai.chat.completions.create(
                model=self.config.gpt.model,
                messages=messages,
                max_tokens=self.config.gpt.max_token,
                temperature=self.config.gpt.temperature,
            )
            response_text = str(response.choices[0].message.content)
            total_tokens = response.usage.total_tokens

            # Add assistant response to chat history
            self.__chat_histories[guild_id].add_assistant_message(response_text)
        else:
            # Use Semantic Kernel for text-only conversations
            self.__chat_histories[guild_id].add_user_message(user_message)

            chat_completion = self.kernel.get_service("chat-gpt")
            response = await chat_completion.get_chat_message_contents(
                chat_history=self.__chat_histories[guild_id],
                settings=sk.openai.OpenAIChatPromptExecutionSettings(max_tokens=self.config.gpt.max_token, temperature=self.config.gpt.temperature),
            )

            response_text = str(response[0].content)
            # Semantic Kernelのトークン使用量を推定
            total_tokens = self._estimate_token_usage(user_message, response_text)

            # Add assistant response to chat history
            self.__chat_histories[guild_id].add_assistant_message(response_text)

        self.__logger.info(f"[Response] {response_text}")

        # Response is already added to chat history above

        self.__last_activity = datetime.datetime.now()

        return response_text, total_tokens
    
    def _estimate_token_usage(self, input_text: str, output_text: str) -> int:
        """テキストベースのトークン使用量を推定（簡易版）"""
        # 簡易的な推定: 英語では約4文字=1トークン、日本語では約1.5文字=1トークン
        input_tokens = len(input_text) // 3  # 混在を想定した平均値
        output_tokens = len(output_text) // 3
        return input_tokens + output_tokens

    async def token_ranking(self, guild_id: int, author: discord.Member, usage: int):
        if isinstance(self.__token_ranking[guild_id], dict) is False:
            self.__token_ranking = {}

        if author.id in self.__token_ranking[guild_id].keys():
            self.__token_ranking[guild_id][author.id] += usage
        else:
            self.__token_ranking[guild_id].setdefault(author.id, usage)

    # 立ち上げ完了時実行
    @commands.Cog.listener()
    async def on_ready(self):
        self.loop_reset.start()
        self.__logger.info("loop start")

    @commands.hybrid_command(name="reset_h", brief="会話履歴をリセットする. 60分ごとに自動実行")
    async def reset_h(self, ctx):
        ret = await self.reset_history(guild_id=ctx.guild.id)
        if ret:
            await ctx.send("会話履歴をリセットしました")
        else:
            await ctx.send("会話履歴のリセットに失敗しました")

    @commands.hybrid_command(name="reset_c", brief="性格を初期化する")
    async def reset_c(self, ctx):
        ret = await self.reset_charactor(guild_id=ctx.guild.id)
        if ret:
            await ctx.send("性格をリセットしました")
        else:
            await ctx.send("性格のリセットに失敗しました")

    @commands.hybrid_command(name="chara", brief="引数で入力した文を性格として設定する")
    async def change(self, ctx: commands.context.Context, text):
        ret = await self.change_charactor(guild_id=ctx.guild.id, txt=text)
        if ret:
            await ctx.send("性格を変更しました")
        else:
            await ctx.send("性格の変更に失敗しました")

    @commands.hybrid_command(name="ranking", brief="トークン使用量ランキグン")
    async def ranking(self, ctx):
        if ctx.guild.id not in self.__token_ranking.keys() or len(self.__token_ranking[ctx.guild.id]) < 1:
            await ctx.send("まだ誰もAPIを使用していません")
            return

        ranking_sorted = sorted(self.__token_ranking[ctx.guild.id].items(), key=lambda x: x[1], reverse=True)
        embed = discord.Embed(title="Token使用量ランキング", color=discord.Colour.red())
        for x, dict in enumerate(ranking_sorted):
            if 3 < x:
                break

            user = self.bot.get_user(dict[0])
            if user is not None:
                embed.add_field(name=f"{x + 1}位 {user.global_name}", value=f"{dict[1]} token", inline=False)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="info", brief="現在の設定を出力")
    async def check_setting(self, ctx):
        embed = discord.Embed(title="Bot Config", color=0xFF0000)
        embed.set_author(name=self.bot.user, url="https://github.com/fockerev/bot_for_fmj")
        embed.add_field(name="BOT VERSION", value=VERSION, inline=False)
        embed.add_field(name="Model", value=self.config.gpt.model, inline=True)
        embed.add_field(name="Temperature", value=self.config.gpt.temperature, inline=True)
        embed.add_field(name="Input Image Resolution", value=self.config.gpt.image_resolution, inline=True)
        embed.add_field(name="Max token", value=self.config.gpt.max_token, inline=True)
        embed.add_field(name="Max history size", value=self.config.bot.history_size, inline=True)
        embed.add_field(name="Save api response", value=self.config.bot.save_api_response, inline=True)
        embed.add_field(name="Save image input", value=self.config.bot.save_image_input, inline=True)
        if ctx.guild.id in self.__chat_histories.keys():
            system_messages = [msg for msg in self.__chat_histories[ctx.guild.id].messages if msg.role.value == "system"]
            if system_messages:
                embed.add_field(name="System prompt", value=str(system_messages[0].content), inline=False)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="change_config", brief="設定を変更")
    async def change_setting(
        self,
        ctx: commands.context.Context,
        input_highreso_img: bool | None,
        save_image_input: bool | None,
        save_response: bool | None,
        history_size: int | None,
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
    async def reset_setting(self, ctx):
        self.config = AppConfig.load((Path(__file__).resolve().parent / ".." / "setting.yaml").resolve())
        await ctx.send("Reload config")

    @commands.hybrid_command(name="history", brief="対話履歴を出力")
    async def check_history(self, ctx):
        if ctx.guild.id in self.__chat_histories.keys() and len(self.__chat_histories[ctx.guild.id].messages) > 0:
            embed = discord.Embed(title="History", color=0x00FF4C)
            for idx, msg in enumerate(self.__chat_histories[ctx.guild.id].messages):
                content = str(msg.content)
                if len(content) > 150:
                    content = content[:150]
                embed.add_field(name=f"{idx}\t{msg.role.value}", value=f"{content}", inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("対話履歴がありません")

    @commands.hybrid_command(name="help", brief="help")
    async def help(self, ctx: commands.context.Context, args=None):
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

    @commands.hybrid_command(name="search", brief="[beta]Web検索を使用して回答")
    async def web_search_question(self, ctx: commands.context.Context, input: str):
        """サーチAPIを使って回答を生成する"""
        try:
            # 履歴リストの初期化
            self.__token_ranking.setdefault(ctx.guild.id, {})

            # Initialize Semantic Kernel chat history if not exists
            if ctx.guild.id not in self.__chat_histories:
                self.__chat_histories[ctx.guild.id] = ChatHistory()
                self.__chat_histories[ctx.guild.id].add_system_message(self.config.bot.default_system_promt)

            self.__logger.info(f"[Search Input] {str(input)}")
            self.__chat_histories[ctx.guild.id].add_user_message(input)

            await ctx.defer()

            # Use Semantic Kernel for web search (note: web search functionality needs to be added as a plugin)
            # For now, fallback to direct OpenAI API call with web search tool
            messages = []
            for msg in self.__chat_histories[ctx.guild.id].messages:
                messages.append({"role": msg.role.value, "content": str(msg.content)})

            response = openai.responses.create(model=self.config.gpt.model, tools=[{"type": "web_search_preview"}], input=messages, max_output_tokens=800)
            response_text = str(response.output_text)
            self.__logger.info(f"[Response] {response_text}")

            if self.config.bot.save_api_response is True:
                self.__chat_histories[ctx.guild.id].add_assistant_message(response_text)

            await self.delete_old_history(guild_id=ctx.guild.id)

            await self.token_ranking(ctx.guild.id, ctx.author, response.usage.total_tokens)
            await ctx.send(content=response_text)

        except Exception as e:
            self.__logger.exception("error occured in seach api processing")
            await ctx.send(f"なんかエラー出た {e}")

    # ループ処理
    @tasks.loop(minutes=5)
    async def loop_reset(self):
        # 最終アクティビティから60分後に履歴リセット
        if (datetime.datetime.now() - self.__last_activity).total_seconds() > 60 * 60:
            if len(self.__chat_histories.keys()) > 0:
                for guild_id in self.__chat_histories.keys():
                    await self.reset_history(guild_id)

                self.__logger.info("cyclic history reset")
                self.__last_activity = datetime.datetime.now()

    # メッセージ受信時実行
    @commands.Cog.listener()
    async def on_message(self, message: discord.message.Message):
        # Bot自身からの入力なら無視
        if message.author == self.bot.user:
            return

        if self.bot.user.id in [member.id for member in message.mentions]:
            try:
                # 履歴リストの初期化
                self.__token_ranking.setdefault(message.guild.id, {})

                # Initialize Semantic Kernel chat history if not exists
                if message.guild.id not in self.__chat_histories:
                    self.__chat_histories[message.guild.id] = ChatHistory()
                    self.__chat_histories[message.guild.id].add_system_message(self.config.bot.default_system_promt)

                # リクエスト
                plane_message, reference_message, attatchments = await self.parse_message(message)
                response, usage = await self.send_question_gpt(plane_message, reference_message, attatchments, message.guild.id)

                # 履歴リスト更新
                await self.token_ranking(message.guild.id, message.author, usage)
                await self.delete_old_history(guild_id=message.guild.id)
                await message.channel.send(response)

            except Exception as e:
                self.__logger.exception("error occured in gpt processing")
                await message.channel.send(f"なんかエラー出た {e}")
        return


async def setup(bot):
    await bot.add_cog(BotCog(bot))
