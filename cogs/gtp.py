import os
import pprint
import re

import discord
import openai
from discord.ext import commands, tasks


class BotCog(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.__gtp_content = "Briefly reply unless otherwise mentioned. speaking Kansai dialect"
        self.__messages = [{ "role": "system", "content": self.__gtp_content}]


    async def reset_history(self) -> None:
        """履歴削除
        """
        # print(len(messages))
        if len(self.__messages) > 2:
            del self.__messages[1:]
            print("history reset")
        # print(len(messages))


    async def reset_charactor(self) -> None:
        """性格をリセットする
        """
        del self.__messages[0:]
        self.__messages.append({"role": "system","content":self.__gtp_content})


    async def change_charactor(self, txt:str) -> None:
        """gtpにわたす性格設定を変更する

        Args:
            txt (str): 変更先の性格設定文
        """

        del self.__messages[0:]
        self.__messages.append({"role": "system","content":txt})
        # print(messages)


    async def ask_chatgpt(self, question:str, reference_message:str = "") -> str:
        """_summary_

        Args:
            question (str): ユーザ側の発言
            reference_message (str): 同時に入力したい発言

        Returns:
            str: apiからの応答
        """

        if reference_message != "":
            self.__messages.append({"role": "assistant", "content": reference_message})

        self.__messages.append({"role": "user", "content": question})

        await self.delete_old_history()

        pprint.pprint(self.__messages,width=100)
        try:
            # ChatGPT APIを呼び出して返答を取得
            response = openai.chat.completions.create(model="gpt-4-0125-preview", messages=self.__messages, n=3)
            if len(str(response.choices[0].message.content)) > 0:
                print(response.usage)
                return str(response.choices[0].message.content)
            else:
                return "APIからの無効な応答です。"
        except openai.APIError as e:
            return f"APIでエラーが発生しました: {e}"

    def check_history_size(self):
        return int(len(self.__messages))

    async def delete_old_history(self):
        while 6 < self.check_history_size() :
            del self.__messages[1]

    @commands.Cog.listener()
    async def on_ready(self):
        self.loop_reset.start()
        print("loop start")
        self.guild_id = os.getenv("GUILD_ID")
        print(self.bot.tree.get_commands())
        id = os.getenv("GUILD_ID")
        await self.bot.tree.sync(guild=discord.Object(id))
        print("sync")


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


    @commands.hybrid_command(name="help", brief="help")
    async def help(self, ctx, args=None):
        help_embed = discord.Embed()
        command_names_list = [x.name for x in self.bot.commands]

        # If there are no arguments, just list the commands:
        if not args:
            help_embed.add_field(
                name="List of supported commands:",
                value="\n".join([str(i+1)+". "+x.name for i,x in enumerate(self.bot.commands)]),
                inline=False
            )
            help_embed.add_field(
                name="Details",
                value="Type `.help <command name>` for more details about each command.",
                inline=False
            )

        # If the argument is a command, get the help text from that command:
        elif args in command_names_list:
            help_embed.add_field(
                name=args,
                value=self.bot.get_command(args).brief
            )

        # If someone is just trolling:
        else:
            help_embed.add_field(
                name="Nope.",
                value="Don't think I got that command, boss!"
            )

        await ctx.send(embed=help_embed)


    @tasks.loop(minutes=60)
    async def loop_reset(self):
        await self.reset_history()
        print("reset")


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
            plane_message = re.sub(r'<@\d+>', "", message.content)
            plane_message = plane_message.strip()
            print(f"input\t\t{plane_message}")

            # GTPへ投げる
            response = await self.ask_chatgpt(plane_message, reference_message)
            # チャットに出力
            await message.channel.send(response)


async def setup(bot):
    await bot.add_cog(BotCog(bot))

