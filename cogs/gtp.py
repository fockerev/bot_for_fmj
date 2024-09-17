import copy
import inspect
import json
import logging
import logging.config
import re
from dataclasses import dataclass
from pathlib import Path

import discord
import openai
import urlextract
import yaml
from discord.ext import commands, tasks

VERSION = "20240918_0100"


@dataclass
class YamlConfig:
    @classmethod
    def load(cls, config_path: Path):
        def _convert_from_dict(parent_cls, data):
            for key, val in data.items():
                child_class = parent_cls.__dataclass_fields__[key].type
                if inspect.isclass(child_class) and issubclass(child_class, YamlConfig):
                    data[key] = child_class(**_convert_from_dict(child_class, val))
            return data

        if config_path.exists() is False:
            raise FileNotFoundError(f"{str(config_path)} is not found")

        with open(config_path) as f:
            config_data = yaml.safe_load(f)
            config_data = _convert_from_dict(cls, config_data)
            return cls(**config_data)


@dataclass
class gtpConfig(YamlConfig):
    model: str
    max_token: int
    temperature: float
    top_p: float
    save_api_response: bool
    history_size: int
    default_system_promt: str


class BotCog(commands.Cog):
    def __init__(self, bot) -> None:
        # define logger
        with open(str((Path(__file__).resolve().parent / ".." / "logging_config.json").resolve()), "r") as f:
            log_conf = json.load(f)
        logging.config.dictConfig(log_conf)
        self.__logger = logging.getLogger("gtp")

        self.bot = bot
        self.config = gtpConfig.load((Path(__file__).resolve().parent / ".." / "setting.yaml").resolve())

        self.__init_message: list = [{"role": "system", "content": self.config.default_system_promt}]
        self.__history: dict = {}
        self.__token_ranking: dict = {}

    async def reset_history(self, guild_id: int) -> bool:
        """履歴削除"""
        if guild_id in self.__history:
            self.__history[guild_id] = [self.__history[guild_id][0]]
            self.__logger.info("history reset")
            return True
        else:
            return False

    async def reset_charactor(self, guild_id: int) -> bool:
        """性格をリセットする"""
        if guild_id in self.__history.keys():
            self.__history[guild_id] = self.__init_message
            self.__logger.info("system charactor reset")
            return True
        else:
            return False

    async def change_charactor(self, guild_id: int, txt: str) -> bool:
        """gtpにわたす性格設定を変更する

        Args:
            txt (str): 変更先の性格設定文
        """
        if guild_id in self.__history.keys():
            self.__history[guild_id][0] = {"role": "system", "content": txt}
            self.__logger.info(f"system charactor changed -> {txt}")
            return True
        else:
            return False

    def check_history_size(self, guild_id: int) -> int:
        """履歴配列長の確認

        Returns:
            int : 配列長
        """
        return int(len(self.__history[guild_id]))

    async def delete_old_history(self, guild_id: int) -> None:
        """一番古い履歴(index = 1) を削除する"""
        while self.config.history_size < self.check_history_size(guild_id):
            del self.__history[guild_id][1]

    async def parse_message(self, message: discord.message.Message) -> tuple[str, str | None, list]:
        reference_message = None
        attachments_list = []

        #
        plane_message = re.sub(r"<@\d+>", "", message.content)
        plane_message = plane_message.strip()
        if message.reference is not None:
            if message.reference.resolved is not None:
                reference_message = message.reference.resolved.content

        # 添付ファイルの抽出
        # 対応ファイル形式
        extention = re.compile(r".png|.jpg|.gif")
        # 直接メッセージに添付
        if 0 < len(message.attachments):
            for attach in message.attachments:
                if extention.search(attach.url) is not None:
                    attachments_list.append(attach.url)
                else:
                    raise ValueError("そのファイル非対応やで")

        # チャットから画像のURLを抽出
        extractor = urlextract.URLExtract()
        extracted_urls = extractor.find_urls(plane_message)
        if len(extracted_urls) > 0:
            for url in extracted_urls:
                if extention.search(url) is not None:
                    attachments_list.append(url)
                    plane_message = plane_message.replace(url, "")
                else:
                    raise ValueError("そのURL非対応やで")

        return plane_message, reference_message, attachments_list

    async def send_question_gtp(self, question: str, reference: str, attachments: list, guild_id: int) -> tuple[str, int]:
        self.__logger.info(f"[Question] {question}")

        self.__history[guild_id].append({"role": "user", "content": question})
        if reference is not None:
            self.__history[guild_id][-1]["content"] += f"\n## 以下へ言及\n{reference}"
            self.__logger.info(f"[Reference] {reference}")

        input_messages = self.__history[guild_id]
        image_input = []
        if len(attachments) > 0:
            for url in attachments:
                image_input.append({"type": "image_url", "image_url": {"url": url, "detail": "low"}})

            self.__logger.info(f"[Attachments] {attachments}")
            image_content = [{"role": "user", "content": image_input}]
            # Token使用料削減のため画像は履歴として保持しない
            input_messages += image_content

        # APIに送る
        response = openai.chat.completions.create(
            model=self.config.model, messages=input_messages, max_tokens=self.config.max_token, temperature=self.config.temperature, top_p=self.config.top_p
        )
        self.__logger.info(f"[Response] {str(response.choices[0].message.content)}")

        if self.config.save_api_response is True:
            self.__history[guild_id].append({"role": "assistant", "content": str(response.choices[0].message.content)})

        return str(response.choices[0].message.content), response.usage.total_tokens

    async def token_ranking(self, author: discord.Member, usage: int):
        if isinstance(self.__token_ranking, dict) is False:
            self.__token_ranking = {}

        if author.id in self.__token_ranking.keys():
            self.__token_ranking[author.id] += usage
        else:
            self.__token_ranking.setdefault(author.id, usage)

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
    async def change(self, ctx, text):
        ret = await self.change_charactor(guild_id=ctx.guild.id, txt=text)
        if ret:
            await ctx.send("性格を変更しました")
        else:
            await ctx.send("性格の変更に失敗しました")

    @commands.hybrid_command(name="ranking", brief="トークン使用量ランキグン")
    async def ranking(self, ctx):
        if len(self.__token_ranking) < 1:
            await ctx.send("まだ誰もAPIを使用していません")
            return

        ranking_sorted = sorted(self.__token_ranking.items(), key=lambda x: x[1], reverse=True)
        embed = discord.Embed(title="Token使用量ランキング", color=discord.Colour.red())
        for x, dict in enumerate(ranking_sorted):
            if 3 < x:
                break

            user = self.bot.get_user(dict[0])
            if user is not None:
                embed.add_field(name=f"{x + 1}位 {user.global_name}", value=f"{dict[1]} token", inline=False)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="check_config", brief="現在の設定を出力")
    async def check_setting(self, ctx):
        embed = discord.Embed(title="Bot Config", color=0xFF0000)
        embed.set_author(name=self.bot.user, url="https://github.com/fockerev/bot_for_fmj")
        embed.add_field(name="BOT VERSION", value=VERSION, inline=False)
        embed.add_field(name="Model", value=self.config.model, inline=True)
        embed.add_field(name="Temperature", value=self.config.temperature, inline=True)
        embed.add_field(name="Top_p", value=self.config.top_p, inline=True)
        embed.add_field(name="Max token", value=self.config.max_token, inline=True)
        embed.add_field(name="Max history size", value=self.config.history_size, inline=True)
        embed.add_field(name="Save api response", value=self.config.save_api_response, inline=True)
        if ctx.guild.id in self.__history.keys():
            embed.add_field(name="System prompt", value=self.__history[ctx.guild.id][0]["content"], inline=False)

        embed.set_footer(text="made by fockerev")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="check_history", brief="対話履歴を出力")
    async def check_history(self, ctx):
        if ctx.guild.id in self.__history.keys() and len(self.__history[ctx.guild.id]) > 0:
            embed = discord.Embed(title="History", color=0x00FF4C)
            for idx, hist in enumerate(self.__history[ctx.guild.id]):
                embed.add_field(name=f"{idx}\t{hist["role"]}", value=f"{hist["content"]}", inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("対話履歴がありません")

    @commands.hybrid_command(name="help", brief="help")
    async def help(self, ctx, args=None):
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

    # ループ処理
    @tasks.loop(minutes=60)
    async def loop_reset(self):
        if len(self.__history.keys()) > 0:
            for guild_id in self.__history.keys():
                await self.reset_history(guild_id)
        self.__logger.info("cyclic history reset")

    # メッセージ受信時実行
    @commands.Cog.listener()
    async def on_message(self, message: discord.message.Message):
        # Bot自身からの入力なら無視
        if message.author == self.bot.user:
            return

        if self.bot.user.id in [member.id for member in message.mentions]:
            try:
                self.__history.setdefault(message.guild.id, copy.deepcopy(self.__init_message))
                plane_message, reference_message, attatchments = await self.parse_message(message)
                response, usage = await self.send_question_gtp(plane_message, reference_message, attatchments, message.guild.id)
                await self.token_ranking(message.author, usage)
                await self.delete_old_history(guild_id=message.guild.id)
                await message.channel.send(response)
            except Exception as e:
                self.__logger.exception("error occured in gtp processing")
                await message.channel.send(f"なんかエラー出た {e}")
        return


async def setup(bot):
    await bot.add_cog(BotCog(bot))
