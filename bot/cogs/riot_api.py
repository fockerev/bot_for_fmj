import asyncio
import json
import logging
import os
from typing import Dict, List, Optional
from io import BytesIO

import discord
from discord.ext import commands
from riotwatcher import LolWatcher, ApiError
import requests
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion, OpenAIChatPromptExecutionSettings
from semantic_kernel.contents import ChatHistory
from semantic_kernel.functions import KernelArguments


class RiotAPIError(Exception):
    """Riot API関連のエラー"""
    pass


class RiotAPICog(commands.Cog):
    """RiotWatcherを使用して試合ログを取得するCOG"""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("riot_api")
        self.api_key = os.getenv("RIOT_API_KEY")
        
        if not self.api_key:
            self.logger.warning("RIOT_API_KEY environment variable not set")
            self.watcher = None
        else:
            self.watcher = LolWatcher(self.api_key)
        
        # Semantic Kernel初期化
        self.kernel = Kernel()
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if openai_api_key:
            service_id = "lol_coach"
            self.kernel.add_service(
                OpenAIChatCompletion(
                    service_id=service_id,
                    api_key=openai_api_key,
                    ai_model_id="gpt-4"
                )
            )
            self.chat_completion_service = self.kernel.get_service(type=OpenAIChatCompletion)
        else:
            self.logger.warning("OPENAI_API_KEY not set, review functionality will be disabled")
    
    def _get_puuid_by_summoner_name(self, summoner_name: str, tag_line: str = "JP1") -> str:
        """サモナー名からPUUIDを取得"""
        if not self.api_key:
            raise RiotAPIError("Riot API key not configured")
        
        try:
            url = f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{summoner_name}/{tag_line}"
            headers = {"X-Riot-Token": self.api_key}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            account = response.json()
            return account["puuid"]
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to get PUUID: {e}")
            raise RiotAPIError(f"Failed to get account info: {e}")
    
    def _get_match_ids(self, puuid: str, count: int = 5) -> List[str]:
        """プレイヤーの試合IDリストを取得"""
        if not self.watcher:
            raise RiotAPIError("Riot API key not configured")
        
        try:
            return self.watcher.match.matchlist_by_puuid("asia", puuid, count=count)
        except ApiError as e:
            self.logger.error(f"Failed to get match IDs: {e}")
            raise RiotAPIError(f"Failed to get match list: {e}")
    
    def _get_match_detail(self, match_id: str) -> Dict:
        """試合詳細を取得"""
        if not self.watcher:
            raise RiotAPIError("Riot API key not configured")
        
        try:
            return self.watcher.match.by_id("asia", match_id)
        except ApiError as e:
            self.logger.error(f"Failed to get match detail: {e}")
            raise RiotAPIError(f"Failed to get match detail: {e}")
    
    def _get_summoner_by_puuid(self, puuid: str) -> Dict:
        """PUUIDからサモナー情報を取得"""
        if not self.watcher:
            raise RiotAPIError("Riot API key not configured")
        
        try:
            return self.watcher.summoner.by_puuid("jp1", puuid)
        except ApiError as e:
            self.logger.error(f"Failed to get summoner info: {e}")
            raise RiotAPIError(f"Failed to get summoner info: {e}")
    
    @commands.hybrid_command(name="riot_match", brief="Riot APIで試合ログを取得")
    async def get_match_logs(self, ctx: commands.Context, summoner_name: str, tag_line: str = "JP1", count: int = 1):
        """
        指定したサモナーの試合ログをJSON形式で取得
        
        Parameters:
        - summoner_name: サモナー名
        - tag_line: タグライン (デフォルト: JP1)
        - count: 取得する試合数 (デフォルト: 1, 最大: 5)
        """
        await ctx.defer()
        
        try:
            # 試合数の制限
            count = min(max(1, count), 5)
            
            self.logger.info(f"Getting match logs for {summoner_name}#{tag_line}, count: {count}")
            
            # PUUIDを取得
            puuid = self._get_puuid_by_summoner_name(summoner_name, tag_line)
            self.logger.info(f"Found PUUID: {puuid}")
            
            # 試合IDリストを取得
            match_ids = self._get_match_ids(puuid, count)
            self.logger.info(f"Found {len(match_ids)} matches")
            
            if not match_ids:
                await ctx.send(f"プレイヤー {summoner_name}#{tag_line} の試合が見つかりませんでした。")
                return
            
            # 各試合の詳細を取得
            matches_data = []
            for match_id in match_ids:
                match_detail = self._get_match_detail(match_id)
                matches_data.append(match_detail)
                # API rate limitを考慮した待機
                await asyncio.sleep(0.1)
            
            # JSONファイルとして保存
            json_data = {
                "summoner": f"{summoner_name}#{tag_line}",
                "puuid": puuid,
                "match_count": len(matches_data),
                "matches": matches_data
            }
            
            # JSONを整形して文字列化
            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
            
            # Discordの文字数制限を考慮
            if len(json_str) > 1900:
                # ファイルとして送信
                file_content = json_str.encode('utf-8')
                file = discord.File(
                    fp=BytesIO(file_content),
                    filename=f"match_logs_{summoner_name}_{tag_line}.json"
                )
                await ctx.send(
                    f"**{summoner_name}#{tag_line}** の試合ログ ({count}試合)\n"
                    f"JSONファイルとして送信します:",
                    file=file
                )
            else:
                # テキストとして送信
                await ctx.send(
                    f"**{summoner_name}#{tag_line}** の試合ログ ({count}試合):\n"
                    f"```json\n{json_str}\n```"
                )
            
            self.logger.info(f"Successfully retrieved {len(matches_data)} matches for {summoner_name}#{tag_line}")
            
        except RiotAPIError as e:
            self.logger.error(f"Riot API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except Exception as e:
            self.logger.exception("Unexpected error in riot_match command")
            await ctx.send(f"予期しないエラーが発生しました: {e}")
    
    @commands.hybrid_command(name="riot_summoner", brief="サモナー情報を取得")
    async def get_summoner_info(self, ctx: commands.Context, summoner_name: str, tag_line: str = "JP1"):
        """
        指定したサモナーの基本情報を取得
        
        Parameters:
        - summoner_name: サモナー名
        - tag_line: タグライン (デフォルト: JP1)
        """
        await ctx.defer()
        
        try:
            self.logger.info(f"Getting summoner info for {summoner_name}#{tag_line}")
            
            # アカウント情報を取得
            puuid = self._get_puuid_by_summoner_name(summoner_name, tag_line)
            
            # アカウント詳細情報を取得
            url = f"https://asia.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{summoner_name}/{tag_line}"
            headers = {"X-Riot-Token": self.api_key}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            account_data = response.json()
            
            # サモナー情報を取得
            summoner_data = self._get_summoner_by_puuid(puuid)
            
            # 結果をJSON形式で返す
            result = {
                "account": account_data,
                "summoner": summoner_data
            }
            
            json_str = json.dumps(result, ensure_ascii=False, indent=2)
            
            if len(json_str) > 1900:
                file_content = json_str.encode('utf-8')
                file = discord.File(
                    fp=BytesIO(file_content),
                    filename=f"summoner_info_{summoner_name}_{tag_line}.json"
                )
                await ctx.send(
                    f"**{summoner_name}#{tag_line}** のサモナー情報:",
                    file=file
                )
            else:
                await ctx.send(
                    f"**{summoner_name}#{tag_line}** のサモナー情報:\n"
                    f"```json\n{json_str}\n```"
                )
            
            self.logger.info(f"Successfully retrieved summoner info for {summoner_name}#{tag_line}")
            
        except RiotAPIError as e:
            self.logger.error(f"Riot API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except ApiError as e:
            self.logger.error(f"RiotWatcher API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except Exception as e:
            self.logger.exception("Unexpected error in riot_summoner command")
            await ctx.send(f"予期しないエラーが発生しました: {e}")
    
    @commands.hybrid_command(name="riot_select", brief="試合を選択して詳細を取得")
    async def select_match(self, ctx: commands.Context, summoner_name: str, tag_line: str = "JP1"):
        """
        指定したサモナーの直近の試合一覧を表示し、選択して詳細を取得
        
        Parameters:
        - summoner_name: サモナー名
        - tag_line: タグライン (デフォルト: JP1)
        """
        await ctx.defer()
        
        try:
            self.logger.info(f"Getting match list for selection: {summoner_name}#{tag_line}")
            
            # PUUIDを取得
            puuid = self._get_puuid_by_summoner_name(summoner_name, tag_line)
            
            # 直近10試合のIDを取得
            match_ids = self._get_match_ids(puuid, 10)
            
            if not match_ids:
                await ctx.send(f"プレイヤー {summoner_name}#{tag_line} の試合が見つかりませんでした。")
                return
            
            # 各試合の基本情報を取得してリスト作成
            match_list = []
            for i, match_id in enumerate(match_ids):
                try:
                    match_detail = self._get_match_detail(match_id)
                    game_info = match_detail['info']
                    
                    # プレイヤーの情報を探す
                    player_data = None
                    for participant in game_info['participants']:
                        if participant['puuid'] == puuid:
                            player_data = participant
                            break
                    
                    if player_data:
                        # 試合結果の簡単な情報
                        champion = player_data['championName']
                        kda = f"{player_data['kills']}/{player_data['deaths']}/{player_data['assists']}"
                        win = "勝利" if player_data['win'] else "敗北"
                        game_mode = game_info['gameMode']
                        duration = f"{game_info['gameDuration'] // 60}:{game_info['gameDuration'] % 60:02d}"
                        
                        match_list.append({
                            'index': i + 1,
                            'match_id': match_id,
                            'champion': champion,
                            'kda': kda,
                            'result': win,
                            'mode': game_mode,
                            'duration': duration
                        })
                    
                    # API制限対策
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    self.logger.warning(f"Failed to get match {match_id}: {e}")
                    continue
            
            if not match_list:
                await ctx.send("試合情報の取得に失敗しました。")
                return
            
            # 試合リストを表示
            embed = discord.Embed(
                title=f"{summoner_name}#{tag_line} の直近試合",
                description="以下の番号で試合を選択してください",
                color=0x00ff00
            )
            
            match_text = ""
            for match in match_list[:5]:  # 最大5試合表示
                match_text += f"**{match['index']}.** {match['champion']} ({match['kda']}) - {match['result']} - {match['mode']} ({match['duration']})\n"
            
            embed.add_field(name="試合一覧", value=match_text, inline=False)
            embed.add_field(
                name="使用方法", 
                value=f"試合の詳細を見るには: `/riot_match_detail {summoner_name} {tag_line} [試合番号]`", 
                inline=False
            )
            
            await ctx.send(embed=embed)
            
            # 試合リストをセッションに保存（簡易実装）
            if not hasattr(self, 'match_sessions'):
                self.match_sessions = {}
            
            self.match_sessions[f"{ctx.author.id}_{summoner_name}_{tag_line}"] = match_list
            
            self.logger.info(f"Successfully displayed match list for {summoner_name}#{tag_line}")
            
        except RiotAPIError as e:
            self.logger.error(f"Riot API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except ApiError as e:
            self.logger.error(f"RiotWatcher API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except Exception as e:
            self.logger.exception("Unexpected error in riot_select command")
            await ctx.send(f"予期しないエラーが発生しました: {e}")
    
    @commands.hybrid_command(name="riot_match_detail", brief="選択した試合の詳細を取得")
    async def get_selected_match_detail(self, ctx: commands.Context, summoner_name: str, tag_line: str = "JP1", match_number: int = 1):
        """
        riot_selectで表示された試合から指定した番号の詳細を取得
        
        Parameters:
        - summoner_name: サモナー名
        - tag_line: タグライン (デフォルト: JP1)
        - match_number: 試合番号 (1-5)
        """
        await ctx.defer()
        
        try:
            # セッションから試合リストを取得
            if not hasattr(self, 'match_sessions'):
                await ctx.send("先に `/riot_select` コマンドで試合一覧を表示してください。")
                return
            
            session_key = f"{ctx.author.id}_{summoner_name}_{tag_line}"
            match_list = self.match_sessions.get(session_key)
            
            if not match_list:
                await ctx.send("先に `/riot_select` コマンドで試合一覧を表示してください。")
                return
            
            if match_number < 1 or match_number > len(match_list):
                await ctx.send(f"無効な試合番号です。1-{len(match_list)} の範囲で指定してください。")
                return
            
            # 選択された試合の詳細を取得
            selected_match = match_list[match_number - 1]
            match_id = selected_match['match_id']
            
            self.logger.info(f"Getting detailed match data for {match_id}")
            
            match_detail = self._get_match_detail(match_id)
            
            # JSONファイルとして保存
            json_data = {
                "summoner": f"{summoner_name}#{tag_line}",
                "selected_match": selected_match,
                "match_detail": match_detail
            }
            
            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
            
            # ファイルとして送信
            file_content = json_str.encode('utf-8')
            file = discord.File(
                fp=BytesIO(file_content),
                filename=f"match_detail_{summoner_name}_{tag_line}_{match_number}.json"
            )
            
            embed = discord.Embed(
                title=f"試合詳細 #{match_number}",
                description=f"**{selected_match['champion']}** - {selected_match['result']}\n"
                           f"KDA: {selected_match['kda']} | {selected_match['mode']} ({selected_match['duration']})",
                color=0x00ff00 if selected_match['result'] == "勝利" else 0xff0000
            )
            
            await ctx.send(embed=embed, file=file)
            
            self.logger.info(f"Successfully sent detailed match data for {match_id}")
            
        except RiotAPIError as e:
            self.logger.error(f"Riot API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except ApiError as e:
            self.logger.error(f"RiotWatcher API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except Exception as e:
            self.logger.exception("Unexpected error in riot_match_detail command")
            await ctx.send(f"予期しないエラーが発生しました: {e}")
    
    @commands.hybrid_command(name="riot_review", brief="選択した試合をAIがレビュー")
    async def review_match(self, ctx: commands.Context, summoner_name: str, tag_line: str = "JP1", match_number: int = 1):
        """
        riot_selectで表示された試合をAIがレビューし、改善点を提案
        
        Parameters:
        - summoner_name: サモナー名
        - tag_line: タグライン (デフォルト: JP1)
        - match_number: 試合番号 (1-5)
        """
        await ctx.defer()
        
        try:
            # セッションから試合リストを取得
            if not hasattr(self, 'match_sessions'):
                await ctx.send("先に `/riot_select` コマンドで試合一覧を表示してください。")
                return
            
            session_key = f"{ctx.author.id}_{summoner_name}_{tag_line}"
            match_list = self.match_sessions.get(session_key)
            
            if not match_list:
                await ctx.send("先に `/riot_select` コマンドで試合一覧を表示してください。")
                return
            
            if match_number < 1 or match_number > len(match_list):
                await ctx.send(f"無効な試合番号です。1-{len(match_list)} の範囲で指定してください。")
                return
            
            # 選択された試合の詳細を取得
            selected_match = match_list[match_number - 1]
            match_id = selected_match['match_id']
            
            self.logger.info(f"Reviewing match {match_id} for {summoner_name}#{tag_line}")
            
            match_detail = self._get_match_detail(match_id)
            
            # プレイヤーのPUUIDを取得
            puuid = self._get_puuid_by_summoner_name(summoner_name, tag_line)
            
            # プレイヤーのデータを抽出
            player_data = None
            game_info = match_detail['info']
            
            for participant in game_info['participants']:
                if participant['puuid'] == puuid:
                    player_data = participant
                    break
            
            if not player_data:
                await ctx.send("プレイヤーデータが見つかりませんでした。")
                return
            
            # レビュー用のデータを整理
            review_data = {
                "champion": player_data['championName'],
                "position": player_data['teamPosition'],
                "result": "勝利" if player_data['win'] else "敗北",
                "kda": {
                    "kills": player_data['kills'],
                    "deaths": player_data['deaths'],
                    "assists": player_data['assists']
                },
                "damage": {
                    "total_damage_dealt": player_data['totalDamageDealtToChampions'],
                    "damage_taken": player_data['totalDamageTaken']
                },
                "farming": {
                    "cs": player_data['totalMinionsKilled'] + player_data.get('neutralMinionsKilled', 0),
                    "gold_earned": player_data['goldEarned']
                },
                "vision": {
                    "vision_score": player_data['visionScore'],
                    "wards_placed": player_data['wardsPlaced'],
                    "wards_killed": player_data['wardsKilled']
                },
                "items": [item for item in [
                    player_data.get('item0', 0),
                    player_data.get('item1', 0),
                    player_data.get('item2', 0),
                    player_data.get('item3', 0),
                    player_data.get('item4', 0),
                    player_data.get('item5', 0),
                    player_data.get('item6', 0)
                ] if item != 0],
                "game_duration": game_info['gameDuration'],
                "game_mode": game_info['gameMode']
            }
            
            # GPTによるレビュー生成
            review_prompt = f"""
League of Legendsの試合データを分析して、プレイヤーのパフォーマンスをレビューしてください。

プレイヤー情報:
- サモナー名: {summoner_name}#{tag_line}
- チャンピオン: {review_data['champion']}
- ポジション: {review_data['position']}
- 試合結果: {review_data['result']}

パフォーマンス詳細:
- KDA: {review_data['kda']['kills']}/{review_data['kda']['deaths']}/{review_data['kda']['assists']}
- チャンピオンダメージ: {review_data['damage']['total_damage_dealt']:,}
- 被ダメージ: {review_data['damage']['damage_taken']:,}
- CS: {review_data['farming']['cs']}
- 獲得ゴールド: {review_data['farming']['gold_earned']:,}
- ビジョンスコア: {review_data['vision']['vision_score']}
- ワード設置/破壊: {review_data['vision']['wards_placed']}/{review_data['vision']['wards_killed']}
- 試合時間: {review_data['game_duration'] // 60}分{review_data['game_duration'] % 60}秒

以下の観点で分析してレビューしてください:
1. KDAとダメージ効率の評価
2. ファーミング（CS/分）の評価
3. ビジョンコントロールの評価
4. 改善すべき点
5. 良かった点
6. 次回に向けてのアドバイス

日本語で詳細かつ建設的なレビューをお願いします。
"""
            
            # Semantic Kernelでレビュー生成
            if not hasattr(self, 'chat_completion_service'):
                await ctx.send("OpenAI API キーが設定されていないため、レビュー機能が利用できません。")
                return
            
            # チャット履歴を作成
            chat_history = ChatHistory()
            chat_history.add_system_message("あなたはLeague of Legendsの経験豊富なコーチです。プレイヤーのパフォーマンスを分析し、建設的で具体的なアドバイスを提供してください。")
            chat_history.add_user_message(review_prompt)
            
            # Semantic Kernelで応答生成
            settings = OpenAIChatPromptExecutionSettings(
                max_tokens=1500,
                temperature=0.7
            )
            
            response = await self.chat_completion_service.get_chat_message_contents(
                chat_history=chat_history,
                settings=settings,
                kernel=self.kernel,
                arguments=KernelArguments()
            )
            
            review_text = str(response[0].content)
            
            # レビュー結果をEmbedで表示
            embed = discord.Embed(
                title=f"🎯 試合レビュー #{match_number}",
                description=f"**{selected_match['champion']}** - {selected_match['result']}\n"
                           f"KDA: {selected_match['kda']} | {selected_match['mode']} ({selected_match['duration']})",
                color=0x00ff00 if selected_match['result'] == "勝利" else 0xff0000
            )
            
            # レビューテキストが長い場合は分割
            if len(review_text) > 4000:
                # ファイルとして送信
                review_file_content = f"試合レビュー - {summoner_name}#{tag_line}\n"
                review_file_content += f"試合番号: {match_number}\n"
                review_file_content += f"チャンピオン: {selected_match['champion']}\n"
                review_file_content += f"結果: {selected_match['result']}\n\n"
                review_file_content += review_text
                
                file_content = review_file_content.encode('utf-8')
                file = discord.File(
                    fp=BytesIO(file_content),
                    filename=f"match_review_{summoner_name}_{tag_line}_{match_number}.txt"
                )
                
                embed.add_field(
                    name="📋 レビュー内容",
                    value="レビューが長いためファイルで送信します。",
                    inline=False
                )
                
                await ctx.send(embed=embed, file=file)
            else:
                embed.add_field(
                    name="📋 AIレビュー",
                    value=review_text[:1024],
                    inline=False
                )
                
                if len(review_text) > 1024:
                    remaining_text = review_text[1024:]
                    chunks = [remaining_text[i:i+1024] for i in range(0, len(remaining_text), 1024)]
                    
                    for i, chunk in enumerate(chunks[:2]):  # 最大3つのフィールド
                        embed.add_field(
                            name=f"📋 レビュー続き {i+2}",
                            value=chunk,
                            inline=False
                        )
                
                await ctx.send(embed=embed)
            
            self.logger.info(f"Successfully generated review for match {match_id}")
            
        except RiotAPIError as e:
            self.logger.error(f"Riot API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except ApiError as e:
            self.logger.error(f"RiotWatcher API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except Exception as e:
            self.logger.exception("Unexpected error in riot_review command")
            await ctx.send(f"予期しないエラーが発生しました: {e}")


async def setup(bot):
    await bot.add_cog(RiotAPICog(bot))