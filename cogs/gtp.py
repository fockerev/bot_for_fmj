import copy
import pprint
import re

import discord
import openai
import urlextract
from discord.ext import commands, tasks

OPENAI_API_DICT = {"gtp4turbo": "gpt-4-turbo", "gtp4o": "gpt-4o"}


class BotCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.__model = OPENAI_API_DICT["gtp4o"]
        self.__gtp_content = "Briefly reply unless otherwise mentioned. speaking Kansai dialect"
        self.__messages = [{"role": "system", "content": self.__gtp_content}]
        self.__history_size = 8  # 会話履歴保存数
        self.__max_token = 800  # 最大Token数
        self.__temperature = 1  # 0 ~ 2 default:1
        self.__token_ranking = {}
        self.__urlextrator = urlextract.URLExtract()

    async def reset_history(self) -> None:
        """履歴削除"""
        # print(len(messages))
        if len(self.__messages) > 2:
            del self.__messages[1:]
            print("history reset")
        # print(len(messages))

    async def reset_charactor(self) -> None:
        """性格をリセットする"""
        del self.__messages[0:]
        self.__messages.append({"role": "system", "content": self.__gtp_content})

    async def change_charactor(self, txt: str) -> None:
        """gtpにわたす性格設定を変更する

        Args:
            txt (str): 変更先の性格設定文
        """

        del self.__messages[0:]
        self.__messages.append({"role": "system", "content": txt})
        # print(messages)

    def check_history_size(self):
        """履歴配列長の確認

        Returns:
            int : 配列長
        """
        return int(len(self.__messages))

    async def delete_old_history(self):
        """一番古い配列(index = 1) を削除する"""
        while self.__history_size < self.check_history_size():
            del self.__messages[1]

    async def add_token_ranking(self, author, response):
        """トークン使用料ランキングを作成する

        Args:
            author (_type_): メッセージ送信者
            response (ChatCompletion): OpenAI APIからの応答
        """

        if isinstance(self.__token_ranking, dict) is False:
            self.__token_ranking = {}

        if author.id in self.__token_ranking.keys():
            self.__token_ranking[author.id] += response.usage.total_tokens
        else:
            self.__token_ranking.setdefault(author.id, response.usage.total_tokens)

    async def ask_chatgpt(self, author, question: str, reference_message: str = "", attachments: str = None) -> str:
        """_summary_

        Args:
            author: 発言者
            question (str): ユーザ側の発言
            reference_message (str): 同時に入力したい発言
            attachments : 添付ファイル
        Returns:
            str: apiからの応答
        """

        if reference_message != "":
            self.__messages.append({"role": "assistant", "content": reference_message})

        await self.delete_old_history()

        # 添付ファイルの抽出
        # 画像が添付されている場合それも入力する
        attachments_list = []
        # 対応ファイル形式
        extention = re.compile(r".png|.jpg|.gif")
        # 直接メッセージに添付
        if 0 < len(attachments):
            for attach in attachments:
                if extention.search(attach.url) is not None:
                    attachments_list.append(attach.url)
                else:
                    return "非対応やで"
        # URLで添付
        extracted_urls = self.__urlextrator.find_urls(question)
        if len(extracted_urls) > 0:
            for url in extracted_urls:
                if extention.search(url) is not None:
                    attachments_list.append(url)
                    question = question.replace(url, "")
                else:
                    return "それ非対応や"

        print(attachments_list)

        self.__messages.append({"role": "user", "content": question})

        # 画像は連続で入力すると爆発するので専用のメッセージデータを作成
        include_image_content = copy.deepcopy(self.__messages)
        if len(attachments_list) > 0:
            image_input = []
            for url in attachments_list:
                image_input.append({"type": "image_url", "image_url": {"url": url, "detail": "low"}})

            include_image_content.append({"role": "user", "content": image_input})

        pprint.pprint(include_image_content, width=100)

        try:
            # ChatGPT APIを呼び出して返答を取得
            response = openai.chat.completions.create(model=self.__model, messages=include_image_content, max_tokens=self.__max_token, temperature=self.__temperature)

            await self.add_token_ranking(author, response)

            if len(str(response.choices[0].message.content)) > 0:
                print(response.usage)
                return str(response.choices[0].message.content)
            else:
                return "変な応答帰ってきましたよ"
        except openai.APIError as e:
            return f"無理ンゴォオオオオオオオオオオ: {e.message}"
        except Exception as e:
            return f"なんかエラー出て無理ンゴォオオオオオオオ {e}"

    # 立ち上げ完了時実行
    @commands.Cog.listener()
    async def on_ready(self):
        self.loop_reset.start()
        print("loop start")

    # コマンド実行時
    @commands.hybrid_command(name="ping", brief="ping")
    async def ping(self, ctx):
        await ctx.send("pong")

    @commands.hybrid_command(name="reset_h", brief="会話履歴をリセットする. 60分ごとに自動実行")
    async def reset_h(self, ctx):
        await self.reset_history()
        await ctx.send("会話履歴をリセットしました")

    @commands.hybrid_command(name="reset_c", brief="性格を初期化する")
    async def reset_c(self, ctx):
        await self.reset_charactor()
        await ctx.send("性格をリセットしました")

    @commands.hybrid_command(name="chara", brief="引数で入力した文を性格として設定する")
    async def change(self, ctx, text):
        await self.change_charactor(text)
        await ctx.send("性格を変更しました")

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

    @commands.hybrid_command(name="help", brief="help")
    async def help(self, ctx, args=None):
        help_embed = discord.Embed()
        command_names_list = [x.name for x in self.bot.commands]

        # If there are no arguments, just list the commands:
        if not args:
            help_embed.add_field(name="List of supported commands:", value="\n".join([str(i + 1) + ". " + x.name for i, x in enumerate(self.bot.commands)]), inline=False)
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
        await self.reset_history()
        print("reset")

    # メッセージ受信時実行
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        reference_message = ""
        if self.bot.user.id in [member.id for member in message.mentions]:
            # print("Mention")

            if message.reference is not None:
                if message.reference.resolved is not None:
                    reference_message = message.reference.resolved.content
            print("")
            print(f"reference\t{reference_message}")

            # メンションを除いたテキストを生成
            plane_message = re.sub(r"<@\d+>", "", message.content)
            plane_message = plane_message.strip()
            print(f"input\t\t{plane_message}")

            # GTPへ投げる
            response = await self.ask_chatgpt(message.author, plane_message, reference_message, message.attachments)
            # チャットに出力
            await message.channel.send(response)


async def setup(bot):
    await bot.add_cog(BotCog(bot))
