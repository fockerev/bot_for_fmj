import asyncio
import json
import logging
import os
from typing import Dict, List, Optional

import discord
from discord.ext import commands
from riotwatcher import LolWatcher, ApiError
import requests


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
                    fp=discord.utils._BytesLike(file_content),
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
                    fp=discord.utils._BytesLike(file_content),
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


async def setup(bot):
    await bot.add_cog(RiotAPICog(bot))