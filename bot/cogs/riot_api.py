import asyncio
import json
import logging
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Dict, List

import discord
import requests
from discord.ext import commands
sys.path.append(str(Path(__file__).parent.parent))

from modules.ai_service import AIServiceFactory
from modules.config import AppConfig
from riotwatcher import ApiError, LolWatcher

from semantic_kernel.contents import ChatHistory


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

        # Load configuration and initialize AI service
        try:
            config_path = Path(__file__).parent.parent / "setting.yaml"
            self.config = AppConfig.load(config_path)
            self._initialize_ai_service()
        except Exception as e:
            self.logger.error(f"Failed to initialize AI service: {e}")
            self.ai_service = None

    def _initialize_ai_service(self):
        """Initialize AI service using factory"""
        try:
            self.ai_service = AIServiceFactory.create_service(self.config)
            if self.ai_service:
                self.logger.info(f"AI service initialized with provider: {self.config.gpt.ai_provider.value}")
            else:
                self.logger.warning("AI service initialization failed, review functionality will be disabled")
        except Exception as e:
            self.logger.error(f"Failed to initialize AI service: {e}")
            self.ai_service = None

    def reinitialize_ai_service(self):
        """Reinitialize AI service after configuration changes"""
        self.logger.info("Reinitializing AI service due to configuration change")
        self._initialize_ai_service()

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
            json_data = {"summoner": f"{summoner_name}#{tag_line}", "puuid": puuid, "match_count": len(matches_data), "matches": matches_data}

            # JSONを整形して文字列化
            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)

            # Discordの文字数制限を考慮
            if len(json_str) > 1900:
                # ファイルとして送信
                file_content = json_str.encode("utf-8")
                file = discord.File(fp=BytesIO(file_content), filename=f"match_logs_{summoner_name}_{tag_line}.json")
                await ctx.send(f"**{summoner_name}#{tag_line}** の試合ログ ({count}試合)\nJSONファイルとして送信します:", file=file)
            else:
                # テキストとして送信
                await ctx.send(f"**{summoner_name}#{tag_line}** の試合ログ ({count}試合):\n```json\n{json_str}\n```")

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
            result = {"account": account_data, "summoner": summoner_data}

            json_str = json.dumps(result, ensure_ascii=False, indent=2)

            if len(json_str) > 1900:
                file_content = json_str.encode("utf-8")
                file = discord.File(fp=BytesIO(file_content), filename=f"summoner_info_{summoner_name}_{tag_line}.json")
                await ctx.send(f"**{summoner_name}#{tag_line}** のサモナー情報:", file=file)
            else:
                await ctx.send(f"**{summoner_name}#{tag_line}** のサモナー情報:\n```json\n{json_str}\n```")

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

    @commands.hybrid_command(name="lol_select", brief="試合を選択してレビュー（基本版または詳細版）")
    async def select_and_review_match(self, ctx: commands.Context, summoner_name: str, tag_line: str = "JP1", detailed: bool = False):
        """
        指定したサモナーの直近の試合一覧を表示し、GUIで選択してレビューを実行

        Parameters:
        - summoner_name: サモナー名
        - tag_line: タグライン (デフォルト: JP1)
        - detailed: 詳細レビュー（タイムライン付き）を実行するか (デフォルト: False)
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
                    game_info = match_detail["info"]

                    # プレイヤーの情報を探す
                    player_data = None
                    for participant in game_info["participants"]:
                        if participant["puuid"] == puuid:
                            player_data = participant
                            break

                    if player_data:
                        # 試合結果の簡単な情報
                        champion = player_data["championName"]
                        kda = f"{player_data['kills']}/{player_data['deaths']}/{player_data['assists']}"
                        win = "勝利" if player_data["win"] else "敗北"
                        game_mode = game_info["gameMode"]
                        duration = f"{game_info['gameDuration'] // 60}:{game_info['gameDuration'] % 60:02d}"

                        match_list.append(
                            {"index": i + 1, "match_id": match_id, "champion": champion, "kda": kda, "result": win, "mode": game_mode, "duration": duration}
                        )

                    # API制限対策
                    await asyncio.sleep(0.1)

                except Exception as e:
                    self.logger.warning(f"Failed to get match {match_id}: {e}")
                    continue

            if not match_list:
                await ctx.send("試合情報の取得に失敗しました。")
                return

            # 試合リストを表示
            embed = discord.Embed(title=f"{summoner_name}#{tag_line} の直近試合", description="以下の番号で試合を選択してください", color=0x00FF00)

            match_text = ""
            for match in match_list[:5]:  # 最大5試合表示
                match_text += f"**{match['index']}.** {match['champion']} ({match['kda']}) - {match['result']} - {match['mode']} ({match['duration']})\n"

            embed.add_field(name="試合一覧", value=match_text, inline=False)
            review_type = "詳細レビュー（タイムライン付き）" if detailed else "基本レビュー"
            embed.add_field(name="使用方法", value=f"下のセレクトメニューから試合を選択すると{review_type}を実行します", inline=False)

            # GUI付きのメッセージを送信（詳細レビューオプション付き）
            view = MatchSelectView(self, summoner_name, tag_line, match_list, detailed)
            message = await ctx.send(embed=embed, view=view)
            view.message = message  # タイムアウト時の更新用

            # 試合リストをセッションに保存（既存コマンドとの互換性のため）
            if not hasattr(self, "match_sessions"):
                self.match_sessions = {}

            self.match_sessions[f"{ctx.author.id}_{summoner_name}_{tag_line}"] = match_list

            self.logger.info(f"Successfully displayed match list with GUI for {summoner_name}#{tag_line} (detailed={detailed})")

        except RiotAPIError as e:
            self.logger.error(f"Riot API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except ApiError as e:
            self.logger.error(f"RiotWatcher API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except Exception as e:
            self.logger.exception("Unexpected error in lol_select command")
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
            if not hasattr(self, "match_sessions"):
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
            match_id = selected_match["match_id"]

            self.logger.info(f"Getting detailed match data for {match_id}")

            match_detail = self._get_match_detail(match_id)

            # JSONファイルとして保存
            json_data = {"summoner": f"{summoner_name}#{tag_line}", "selected_match": selected_match, "match_detail": match_detail}

            json_str = json.dumps(json_data, ensure_ascii=False, indent=2)

            # ファイルとして送信
            file_content = json_str.encode("utf-8")
            file = discord.File(fp=BytesIO(file_content), filename=f"match_detail_{summoner_name}_{tag_line}_{match_number}.json")

            embed = discord.Embed(
                title=f"試合詳細 #{match_number}",
                description=f"**{selected_match['champion']}** - {selected_match['result']}\n"
                f"KDA: {selected_match['kda']} | {selected_match['mode']} ({selected_match['duration']})",
                color=0x00FF00 if selected_match["result"] == "勝利" else 0xFF0000,
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

    @commands.hybrid_command(name="lol_review", brief="試合をレビュー（基本版またはタイムライン付き詳細版）")
    async def unified_review(self, ctx: commands.Context, summoner_name: str, tag_line: str = "JP1", match_number: int = 1, detailed: bool = False):
        """
        指定された試合をAIがレビュー。detailedをTrueにするとタイムライン付き詳細レビュー

        Parameters:
        - summoner_name: サモナー名
        - tag_line: タグライン (デフォルト: JP1)
        - match_number: 試合番号 (デフォルト: 1=直近試合)
        - detailed: 詳細レビュー（タイムライン付き）を実行するか (デフォルト: False)
        """
        await ctx.defer()

        try:
            review_type = "詳細" if detailed else "基本"
            self.logger.info(f"{review_type} review for {summoner_name}#{tag_line}, match #{match_number}")

            # 試合番号の妥当性チェック
            if match_number < 1 or match_number > 10:
                await ctx.send("試合番号は1-10の範囲で指定してください。")
                return

            # PUUIDを取得
            puuid = self._get_puuid_by_summoner_name(summoner_name, tag_line)

            # 指定された試合番号まで取得
            match_ids = self._get_match_ids(puuid, match_number)

            if not match_ids:
                await ctx.send(f"プレイヤー {summoner_name}#{tag_line} の試合が見つかりませんでした。")
                return

            if len(match_ids) < match_number:
                await ctx.send(f"試合履歴が{len(match_ids)}試合しかありません。1-{len(match_ids)}の範囲で指定してください。")
                return

            match_id = match_ids[match_number - 1]  # リストは0ベースなので-1

            # 試合詳細を取得
            match_detail = self._get_match_detail(match_id)
            game_info = match_detail["info"]

            # プレイヤーのデータを抽出
            player_data = None
            for participant in game_info["participants"]:
                if participant["puuid"] == puuid:
                    player_data = participant
                    break

            if not player_data:
                await ctx.send("プレイヤーデータが見つかりませんでした。")
                return

            # 試合の基本情報
            champion = player_data["championName"]
            kda = f"{player_data['kills']}/{player_data['deaths']}/{player_data['assists']}"
            result = "勝利" if player_data["win"] else "敗北"
            duration = f"{game_info['gameDuration'] // 60}:{game_info['gameDuration'] % 60:02d}"

            # 詳細レビューの場合はタイムラインを作成
            if detailed:
                timeline_data = self._create_timeline_from_json(match_detail, puuid)

                # タイムライン情報を先に表示
                timeline_embed = discord.Embed(
                    title=f"⏱️ {summoner_name}#{tag_line} - 試合タイムライン",
                    description=f"**{champion}** - {result} | 試合時間: {duration}",
                    color=0x00FF00 if result == "勝利" else 0xFF0000,
                )

                timeline_embed.add_field(name="🌅 序盤 (0-15分)", value=timeline_data["phases"]["early_game"]["summary"].strip(), inline=False)

                timeline_embed.add_field(name="⚔️ 中盤 (15-30分)", value=timeline_data["phases"]["mid_game"]["summary"].strip(), inline=False)

                timeline_embed.add_field(name="🏆 終盤 (30分以降)", value=timeline_data["phases"]["late_game"]["summary"].strip(), inline=False)

                await ctx.send(embed=timeline_embed)

            # より詳細なレビュー用のデータを整理
            review_data = {
                "champion": champion,
                "position": player_data["teamPosition"],
                "result": result,
                "kda": {"kills": player_data["kills"], "deaths": player_data["deaths"], "assists": player_data["assists"]},
                "damage": {
                    "total_damage_dealt": player_data["totalDamageDealtToChampions"],
                    "damage_taken": player_data["totalDamageTaken"],
                    "physical_damage": player_data.get("physicalDamageDealtToChampions", 0),
                    "magic_damage": player_data.get("magicDamageDealtToChampions", 0),
                },
                "farming": {
                    "cs": player_data["totalMinionsKilled"] + player_data.get("neutralMinionsKilled", 0),
                    "gold_earned": player_data["goldEarned"],
                    "cs_per_min": round((player_data["totalMinionsKilled"] + player_data.get("neutralMinionsKilled", 0)) / (game_info["gameDuration"] / 60), 1),
                },
                "vision": {
                    "vision_score": player_data["visionScore"],
                    "wards_placed": player_data["wardsPlaced"],
                    "wards_killed": player_data["wardsKilled"],
                    "control_wards_purchased": player_data.get("visionWardsBoughtInGame", 0),
                },
                "objectives": {
                    "turret_kills": player_data.get("turretKills", 0),
                    "inhibitor_kills": player_data.get("inhibitorKills", 0),
                    "dragon_kills": player_data.get("dragonKills", 0),
                    "baron_kills": player_data.get("baronKills", 0),
                },
                "combat": {
                    "largest_killing_spree": player_data.get("largestKillingSpree", 0),
                    "largest_multi_kill": player_data.get("largestMultiKill", 0),
                    "first_blood_kill": player_data.get("firstBloodKill", False),
                    "first_tower_kill": player_data.get("firstTowerKill", False),
                },
                "items": {
                    "completed_items": [
                        item
                        for item in [
                            player_data.get("item0", 0),
                            player_data.get("item1", 0),
                            player_data.get("item2", 0),
                            player_data.get("item3", 0),
                            player_data.get("item4", 0),
                            player_data.get("item5", 0),
                        ]
                        if item != 0
                    ],
                    "consumables_purchased": player_data.get("consumablesPurchased", 0),
                },
                "team_performance": {
                    "team_result": "勝利" if player_data["win"] else "敗北",
                    "damage_share": round(player_data["totalDamageDealtToChampions"] / max(1, game_info.get("totalDamageDealt", 1)) * 100, 1)
                    if game_info.get("totalDamageDealt")
                    else 0,
                },
                "game_duration": game_info["gameDuration"],
                "game_mode": game_info["gameMode"],
            }

            # レビュープロンプトの生成（詳細レベルに応じて調整）
            if detailed:
                # 詳細レビュー用プロンプト（タイムライン込み）
                review_prompt = f"""
League of Legends の試合をタイムライン分析でレビューしてください。

【プレイヤー情報】
- {summoner_name}#{tag_line}
- チャンピオン: {champion} ({review_data["position"]})
- 結果: {result}
- 試合時間: {duration}

【パフォーマンス統計】
- KDA: {kda}
- ダメージ: {review_data["damage"]["total_damage_dealt"]:,}
- CS: {review_data["farming"]["cs"]}
- ゴールド: {review_data["farming"]["gold_earned"]:,}
- ビジョンスコア: {review_data["vision"]["vision_score"]}

【タイムライン分析】
{timeline_data["phases"]["early_game"]["summary"]}
{timeline_data["phases"]["mid_game"]["summary"]}
{timeline_data["phases"]["late_game"]["summary"]}

このデータとタイムラインを基に、以下の観点で分析してください：
1. **序盤評価** - レーニング効率、初期判断
2. **中盤評価** - チーム貢献、オブジェクト関与  
3. **終盤評価** - 勝敗への影響、キャリー性能
4. **改善点** - 具体的な課題と対策
5. **次回戦略** - 実践的アドバイス

時系列での成長と課題を重視したレビューを日本語でお願いします。
"""
            else:
                # 基本レビュー用プロンプト
                review_prompt = f"""
League of Legendsの試合データを分析して、プレイヤーのパフォーマンスをレビューしてください。

プレイヤー情報:
- サモナー名: {summoner_name}#{tag_line}
- チャンピオン: {champion} ({review_data["position"]})
- 試合結果: {result}
- 試合時間: {duration}

パフォーマンス詳細:
- KDA: {kda}
- ダメージ: {review_data["damage"]["total_damage_dealt"]:,}
- CS: {review_data["farming"]["cs"]} (CS/分: {review_data["farming"]["cs_per_min"]})
- ゴールド: {review_data["farming"]["gold_earned"]:,}
- ビジョンスコア: {review_data["vision"]["vision_score"]}

以下の観点で分析してレビューしてください:
1. **全体的な評価** - パフォーマンスの総合評価
2. **良かった点** - 評価できる動き（1-2点）
3. **改善点** - 具体的な課題（1-2点）
4. **次回アドバイス** - 実践的な改善提案

簡潔で建設的なレビューを日本語でお願いします。
"""

            # AI service でレビュー生成
            if not self.ai_service:
                await ctx.send("AI サービスが初期化されていないため、レビュー機能が利用できません。")
                return

            # チャット履歴を作成
            chat_history = ChatHistory()
            chat_history.add_system_message(self.config.riot_api.system_message)
            chat_history.add_user_message(review_prompt)

            # AI service で応答生成（詳細レベルに応じてトークン数調整）
            settings = {
                "max_tokens": self.config.riot_api.max_tokens_detailed if detailed else self.config.riot_api.max_tokens_basic,
                "temperature": self.config.gpt.temperature
            }

            review_text = await self.ai_service.get_chat_response(chat_history, settings)

            # レビュー結果をEmbedで表示
            match_title = "直近試合" if match_number == 1 else f"#{match_number}番目の試合"
            review_title = "タイムライン分析レビュー" if detailed else "基本レビュー"
            embed = discord.Embed(
                title=f"🎯 {summoner_name}#{tag_line} - {match_title} ({review_title})",
                description=f"**{champion}** - {result}\nKDA: {kda} | 試合時間: {duration}",
                color=0x00FF00 if result == "勝利" else 0xFF0000,
            )

            embed.add_field(
                name="📊 試合データ",
                value=f"ダメージ: {review_data['damage']['total_damage_dealt']:,}\n"
                f"CS: {review_data['farming']['cs']}\n"
                f"ビジョンスコア: {review_data['vision']['vision_score']}",
                inline=True,
            )

            # レビューテキストを適切なサイズに分割
            if len(review_text) <= 1024:
                embed.add_field(name="🤖 AIレビュー", value=review_text, inline=False)
            else:
                # 長い場合は分割
                chunks = [review_text[i : i + 1024] for i in range(0, len(review_text), 1024)]
                for i, chunk in enumerate(chunks[:3]):  # 最大3つのフィールド
                    field_name = "🤖 AIレビュー" if i == 0 else f"🤖 続き {i + 1}"
                    embed.add_field(name=field_name, value=chunk, inline=False)

            await ctx.send(embed=embed)

            self.logger.info(f"Successfully completed {review_type} review for {summoner_name}#{tag_line}")

        except RiotAPIError as e:
            self.logger.error(f"Riot API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except ApiError as e:
            self.logger.error(f"RiotWatcher API error: {e}")
            await ctx.send(f"Riot API エラー: {e}")
        except Exception as e:
            self.logger.exception("Unexpected error in lol_review command")
            await ctx.send(f"予期しないエラーが発生しました: {e}")

    def _create_timeline_from_json(self, match_data: Dict, target_puuid: str) -> Dict:
        """試合データからタイムラインを作成"""
        game_info = match_data["info"]

        # プレイヤー情報を取得
        target_participant = None
        target_team_id = None
        for participant in game_info["participants"]:
            if participant["puuid"] == target_puuid:
                target_participant = participant
                target_team_id = participant["teamId"]
                break

        if not target_participant:
            return {"error": "Player not found"}

        # チーム情報を取得
        player_team = None
        enemy_team = None
        for team in game_info["teams"]:
            if team["teamId"] == target_team_id:
                player_team = team
            else:
                enemy_team = team

        # 全参加者の統計を収集
        team_stats = {"allies": [], "enemies": []}
        for participant in game_info["participants"]:
            stats = {
                "champion": participant["championName"],
                "position": participant["teamPosition"],
                "kda": f"{participant['kills']}/{participant['deaths']}/{participant['assists']}",
                "damage": participant["totalDamageDealtToChampions"],
                "gold": participant["goldEarned"],
                "cs": participant["totalMinionsKilled"] + participant.get("neutralMinionsKilled", 0),
            }

            if participant["teamId"] == target_team_id:
                if participant["puuid"] != target_puuid:
                    team_stats["allies"].append(stats)
            else:
                team_stats["enemies"].append(stats)

        # 基本的なタイムライン情報を構築
        timeline_data = {
            "gameLength": game_info["gameDuration"],
            "participant": target_participant,
            "team_performance": {"player_team": player_team, "enemy_team": enemy_team, "allies": team_stats["allies"], "enemies": team_stats["enemies"]},
            "phases": {
                "early_game": {"start": 0, "end": 900, "summary": ""},  # 0-15分
                "mid_game": {"start": 900, "end": 1800, "summary": ""},  # 15-30分
                "late_game": {"start": 1800, "end": game_info["gameDuration"], "summary": ""},  # 30分以降
            },
        }

        # 試合の推定流れを分析
        game_duration_min = game_info["gameDuration"] // 60

        # チーム全体の統計
        team_total_kills = sum(p["kills"] for p in game_info["participants"] if p["teamId"] == target_team_id)
        enemy_total_kills = sum(p["kills"] for p in game_info["participants"] if p["teamId"] != target_team_id)

        # 序盤分析 (0-15分推定)
        early_game_events = []
        if target_participant.get("firstBloodKill"):
            early_game_events.append("ファーストブラッド獲得")
        if target_participant.get("firstTowerKill"):
            early_game_events.append("ファーストタワー破壊")

        timeline_data["phases"]["early_game"]["summary"] = f"""
序盤フェーズ (0-15分):
【個人パフォーマンス】
- ファーミング: CS {target_participant["totalMinionsKilled"] + target_participant.get("neutralMinionsKilled", 0)}
- 戦闘参加: {target_participant["kills"]}キル/{target_participant["deaths"]}デス/{target_participant["assists"]}アシスト
- 特記事項: {", ".join(early_game_events) if early_game_events else "通常のレーニング"}

【チーム状況】
- 味方チーム総キル: {team_total_kills}
- 敵チーム総キル: {enemy_total_kills}
- 序盤優勢: {"味方優勢" if team_total_kills > enemy_total_kills else "敵優勢" if enemy_total_kills > team_total_kills else "拮抗"}
"""

        # 中盤分析 (15-30分推定)
        mid_game_events = []
        if target_participant.get("dragonKills", 0) > 0:
            mid_game_events.append(f"ドラゴン{target_participant['dragonKills']}体撃破")
        if target_participant.get("turretKills", 0) > 0:
            mid_game_events.append(f"タワー{target_participant['turretKills']}本破壊")

        timeline_data["phases"]["mid_game"]["summary"] = f"""
中盤フェーズ (15-30分):
【チームファイト貢献】
- 与ダメージ: {target_participant["totalDamageDealtToChampions"]:,}
- 被ダメージ: {target_participant["totalDamageTaken"]:,}
- オブジェクト関与: {", ".join(mid_game_events) if mid_game_events else "オブジェクト関与なし"}

【ビジョン管理】
- ワード設置: {target_participant["wardsPlaced"]}個
- ワード破壊: {target_participant["wardsKilled"]}個
- コントロールワード: {target_participant.get("visionWardsBoughtInGame", 0)}個購入

【チーム比較】
- 味方で最高ダメージ: {max(p["totalDamageDealtToChampions"] for p in game_info["participants"] if p["teamId"] == target_team_id):,}
- 自分のダメージ順位: {"上位" if target_participant["totalDamageDealtToChampions"] >= sorted([p["totalDamageDealtToChampions"] for p in game_info["participants"] if p["teamId"] == target_team_id], reverse=True)[1] else "中位以下"}
"""

        # 終盤分析 (30分以降)
        late_game_events = []
        if target_participant.get("baronKills", 0) > 0:
            late_game_events.append(f"バロン{target_participant['baronKills']}回撃破")
        if target_participant.get("largestKillingSpree", 0) >= 3:
            late_game_events.append(f"最大{target_participant['largestKillingSpree']}連続キル")

        # 試合時間による分析
        game_pace = "短期決着" if game_duration_min < 25 else "標準的" if game_duration_min < 35 else "長期戦"

        timeline_data["phases"]["late_game"]["summary"] = f"""
終盤フェーズ (30分-{game_duration_min}分):
【最終パフォーマンス】
- 最終KDA: {target_participant["kills"]}/{target_participant["deaths"]}/{target_participant["assists"]}
- KDA比: {((target_participant["kills"] + target_participant["assists"]) / max(1, target_participant["deaths"])):.1f}
- 特記事項: {", ".join(late_game_events) if late_game_events else "安定した終盤戦"}

【試合への影響】
- 総獲得ゴールド: {target_participant["goldEarned"]:,}
- 試合ペース: {game_pace}
- 勝敗への貢献: {"勝利の立役者" if target_participant["win"] and target_participant["kills"] + target_participant["assists"] >= 10 else "勝利に貢献" if target_participant["win"] else "敗北要因の一つ" if target_participant["deaths"] > target_participant["kills"] + target_participant["assists"] else "健闘"}

【敵との比較】
- 敵最高ダメージ: {max(p["totalDamageDealtToChampions"] for p in game_info["participants"] if p["teamId"] != target_team_id):,}
- 対戦相手との差: {"優勢" if target_participant["totalDamageDealtToChampions"] > max(p["totalDamageDealtToChampions"] for p in game_info["participants"] if p["teamId"] != target_team_id and p["teamPosition"] == target_participant["teamPosition"]) else "劣勢"}
"""

        return timeline_data


class MatchSelectView(discord.ui.View):
    """試合選択用のGUI"""

    def __init__(self, cog, summoner_name: str, tag_line: str, match_list: List[Dict], detailed: bool = False):
        super().__init__(timeout=300)  # 5分でタイムアウト
        self.cog = cog
        self.summoner_name = summoner_name
        self.tag_line = tag_line
        self.match_list = match_list
        self.detailed = detailed

        # セレクトメニューを作成
        options = []
        for match in match_list[:10]:  # 最大10試合
            emoji = "🟢" if match["result"] == "勝利" else "🔴"
            options.append(
                discord.SelectOption(
                    label=f"#{match['index']} {match['champion']} - {match['result']}",
                    description=f"KDA: {match['kda']} | {match['mode']} ({match['duration']})",
                    value=str(match["index"]),
                    emoji=emoji,
                )
            )

        review_type = "詳細レビュー" if self.detailed else "基本レビュー"
        self.select = discord.ui.Select(placeholder=f"{review_type}したい試合を選択してください...", options=options, custom_id="match_select")
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        """セレクトメニューのコールバック - 統合されたレビュー機能を実行"""
        selected_match_number = int(interaction.data["values"][0])

        await interaction.response.defer()

        try:
            # 選択された試合を見つける
            selected_match = None
            for match in self.match_list:
                if match["index"] == selected_match_number:
                    selected_match = match
                    break

            if not selected_match:
                await interaction.followup.send("選択された試合が見つかりませんでした。")
                return

            # レビュー開始のインジケータを表示
            review_type = "詳細レビュー" if self.detailed else "基本レビュー"
            indicator_embed = discord.Embed(
                title="🔄 レビュー処理中...",
                description=f"**{selected_match['champion']}** の試合を分析中です\nレビュータイプ: {review_type}\n⏳ しばらくお待ちください...",
                color=0xFFAA00,  # オレンジ色
            )

            # セレクトメニューを無効化して処理中であることを示す
            self.select.disabled = True
            self.select.placeholder = f"処理中... ({selected_match['champion']} #{selected_match_number})"
            await interaction.edit_original_response(view=self)

            # インジケータメッセージを送信
            await interaction.followup.send(embed=indicator_embed)

            # 統合レビュー機能を実行
            await self._execute_unified_review(interaction, selected_match)

        except Exception as e:
            self.cog.logger.exception("Error in GUI match review")
            # エラー時はセレクトメニューを再有効化
            self.select.disabled = False
            self.select.placeholder = f"{review_type}したい試合を選択してください..."
            await interaction.edit_original_response(view=self)
            await interaction.followup.send(f"予期しないエラーが発生しました: {e}")

    async def _execute_unified_review(self, interaction: discord.Interaction, selected_match: Dict):
        """統合されたレビュー機能を実行"""
        # 試合データを取得
        puuid = self.cog._get_puuid_by_summoner_name(self.summoner_name, self.tag_line)
        match_detail = self.cog._get_match_detail(selected_match["match_id"])
        game_info = match_detail["info"]

        # プレイヤーのデータを抽出
        player_data = None
        for participant in game_info["participants"]:
            if participant["puuid"] == puuid:
                player_data = participant
                break

        if not player_data:
            await interaction.followup.send("プレイヤーデータが見つかりませんでした。")
            return

        # 基本情報
        champion = player_data["championName"]
        kda = f"{player_data['kills']}/{player_data['deaths']}/{player_data['assists']}"
        result = "勝利" if player_data["win"] else "敗北"
        duration = f"{game_info['gameDuration'] // 60}:{game_info['gameDuration'] % 60:02d}"

        # 詳細レビューの場合はタイムラインを作成
        if self.detailed:
            # タイムライン作成中の進捗表示
            progress_embed = discord.Embed(
                title="📊 タイムライン作成中...",
                description=f"**{champion}** の試合データを時系列分析中\n⏳ 数秒お待ちください...",
                color=0x00AAFF,  # 青色
            )
            progress_msg = await interaction.followup.send(embed=progress_embed)

            timeline_data = self.cog._create_timeline_from_json(match_detail, puuid)

            # タイムライン情報を作成
            timeline_embed = discord.Embed(
                title=f"⏱️ {self.summoner_name}#{self.tag_line} - 試合タイムライン",
                description=f"**{champion}** - {result} | 試合時間: {duration}",
                color=0x00FF00 if result == "勝利" else 0xFF0000,
            )

            timeline_embed.add_field(name="🌅 序盤 (0-15分)", value=timeline_data["phases"]["early_game"]["summary"].strip(), inline=False)

            timeline_embed.add_field(name="⚔️ 中盤 (15-30分)", value=timeline_data["phases"]["mid_game"]["summary"].strip(), inline=False)

            timeline_embed.add_field(name="🏆 終盤 (30分以降)", value=timeline_data["phases"]["late_game"]["summary"].strip(), inline=False)

            # 進捗メッセージをタイムライン結果で更新
            await progress_msg.edit(embed=timeline_embed)

        # レビュー用のデータを整理
        review_data = {
            "champion": champion,
            "position": player_data["teamPosition"],
            "result": result,
            "kda": {"kills": player_data["kills"], "deaths": player_data["deaths"], "assists": player_data["assists"]},
            "damage": {"total_damage_dealt": player_data["totalDamageDealtToChampions"]},
            "farming": {
                "cs": player_data["totalMinionsKilled"] + player_data.get("neutralMinionsKilled", 0),
                "cs_per_min": round((player_data["totalMinionsKilled"] + player_data.get("neutralMinionsKilled", 0)) / (game_info["gameDuration"] / 60), 1),
            },
            "vision": {"vision_score": player_data["visionScore"]},
        }

        # レビュープロンプトの生成（詳細レベルに応じて調整）
        if self.detailed:
            # 詳細レビュー用プロンプト（タイムライン込み）
            review_prompt = f"""
League of Legends の試合をタイムライン分析でレビューしてください。

【プレイヤー情報】
- {self.summoner_name}#{self.tag_line}
- チャンピオン: {champion} ({review_data["position"]})
- 結果: {result}
- 試合時間: {duration}

【パフォーマンス統計】
- KDA: {kda}
- ダメージ: {review_data["damage"]["total_damage_dealt"]:,}
- CS: {review_data["farming"]["cs"]}
- ビジョンスコア: {review_data["vision"]["vision_score"]}

【タイムライン分析】
{timeline_data["phases"]["early_game"]["summary"]}
{timeline_data["phases"]["mid_game"]["summary"]}
{timeline_data["phases"]["late_game"]["summary"]}

このデータとタイムラインを基に、以下の観点で分析してください：
1. **序盤評価** - レーニング効率、初期判断
2. **中盤評価** - チーム貢献、オブジェクト関与  
3. **終盤評価** - 勝敗への影響、キャリー性能
4. **改善点** - 具体的な課題と対策
5. **次回戦略** - 実践的アドバイス

時系列での成長と課題を重視したレビューを日本語でお願いします。
"""
        else:
            # 基本レビュー用プロンプト
            review_prompt = f"""
League of Legendsの試合データを分析して、プレイヤーのパフォーマンスをレビューしてください。

プレイヤー情報:
- サモナー名: {self.summoner_name}#{self.tag_line}
- チャンピオン: {champion} ({review_data["position"]})
- 試合結果: {result}
- 試合時間: {duration}

パフォーマンス詳細:
- KDA: {kda}
- ダメージ: {review_data["damage"]["total_damage_dealt"]:,}
- CS: {review_data["farming"]["cs"]} (CS/分: {review_data["farming"]["cs_per_min"]})
- ビジョンスコア: {review_data["vision"]["vision_score"]}

以下の観点で分析してレビューしてください:
1. **全体的な評価** - パフォーマンスの総合評価
2. **良かった点** - 評価できる動き（1-2点）
3. **改善点** - 具体的な課題（1-2点）
4. **次回アドバイス** - 実践的な改善提案

簡潔で建設的なレビューを日本語でお願いします。
"""

        # AI service でレビュー生成
        if not self.cog.ai_service:
            await interaction.followup.send("AI サービスが初期化されていないため、レビュー機能が利用できません。")
            return

        # AIレビュー生成中の進捗表示
        ai_progress_embed = discord.Embed(
            title="🤖 AIレビュー生成中...",
            description=f"**{champion}** の試合データをAIが分析中\n⏳ 30秒程度お待ちください...",
            color=0xAA00FF,  # 紫色
        )
        ai_progress_msg = await interaction.followup.send(embed=ai_progress_embed)

        chat_history = ChatHistory()
        chat_history.add_system_message(self.cog.config.riot_api.system_message)
        chat_history.add_user_message(review_prompt)

        # AI service で応答生成（詳細レベルに応じてトークン数調整）
        settings = {
            "max_tokens": self.cog.config.riot_api.max_tokens_detailed if self.detailed else self.cog.config.riot_api.max_tokens_basic,
            "temperature": self.cog.config.gpt.temperature
        }

        review_text = await self.cog.ai_service.get_chat_response(chat_history, settings)

        # レビュー結果をEmbedで表示
        review_title = "タイムライン分析レビュー" if self.detailed else "基本レビュー"
        embed = discord.Embed(
            title=f"🎯 {self.summoner_name}#{self.tag_line} - #{selected_match['index']}番目の試合 ({review_title})",
            description=f"**{champion}** - {result}\nKDA: {kda} | 試合時間: {duration}",
            color=0x00FF00 if result == "勝利" else 0xFF0000,
        )

        embed.add_field(
            name="📊 試合データ",
            value=f"ダメージ: {review_data['damage']['total_damage_dealt']:,}\n"
            f"CS: {review_data['farming']['cs']}\n"
            f"ビジョンスコア: {review_data['vision']['vision_score']}",
            inline=True,
        )

        # レビューテキストを適切なサイズに分割
        if len(review_text) <= 1024:
            embed.add_field(name="🤖 AIレビュー", value=review_text, inline=False)
        else:
            # 長い場合は分割
            chunks = [review_text[i : i + 1024] for i in range(0, len(review_text), 1024)]
            for i, chunk in enumerate(chunks[:3]):  # 最大3つのフィールド
                field_name = "🤖 AIレビュー" if i == 0 else f"🤖 続き {i + 1}"
                embed.add_field(name=field_name, value=chunk, inline=False)

        # 完了インジケータでセレクトメニューを更新
        review_type = "詳細レビュー" if self.detailed else "基本レビュー"
        self.select.disabled = True
        self.select.placeholder = f"✅ 完了: {champion} #{selected_match['index']} ({review_type})"
        await interaction.edit_original_response(view=self)

        # AI進捗メッセージをレビュー結果で更新
        await ai_progress_msg.edit(embed=embed)

        review_type = "詳細" if self.detailed else "基本"
        self.cog.logger.info(f"Successfully completed GUI {review_type} review for {self.summoner_name}#{self.tag_line}, match #{selected_match['index']}")

    async def on_timeout(self):
        """タイムアウト時の処理"""
        self.select.disabled = True
        try:
            # 元のメッセージを更新
            await self.message.edit(view=self)
        except Exception:
            pass


async def setup(bot):
    await bot.add_cog(RiotAPICog(bot))
