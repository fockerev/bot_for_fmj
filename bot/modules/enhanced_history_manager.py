"""
Enhanced History Manager - 履歴管理システムの改善版
階層化キャッシュとChatHistorySummarizationReducerを使用したスケーラブルな履歴管理
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Union
import aiofiles
import sys
from pathlib import Path

# Add current directory to sys.path for absolute imports
sys.path.append(str(Path(__file__).parent))

from semantic_kernel.contents.history_reducer.chat_history_summarization_reducer import ChatHistorySummarizationReducer
from semantic_kernel.contents.history_reducer.chat_history_truncation_reducer import ChatHistoryTruncationReducer
from semantic_kernel.contents import ChatHistory

from config import AppConfig
from guild_config import GuildConfigManager
from ai_service import AIServiceFactory


class PersistenceLayer:
    """履歴永続化レイヤー"""
    
    def __init__(self, storage_path: str = "data/chat_histories"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("persistence_layer")
        
    async def save_history(self, guild_id: int, history: Union[ChatHistorySummarizationReducer, ChatHistoryTruncationReducer]):
        """履歴の永続化保存"""
        try:
            file_path = self.storage_path / f"guild_{guild_id}.json"
            
            serialized_data = {
                "guild_id": guild_id,
                "timestamp": datetime.now().isoformat(),
                "reducer_type": history.__class__.__name__,
                "target_count": getattr(history, 'target_count', None),
                "messages": [
                    {
                        "role": msg.role.value,
                        "content": str(msg.content),
                        "timestamp": datetime.now().isoformat()
                    }
                    for msg in history.messages
                ]
            }
            
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(serialized_data, ensure_ascii=False, indent=2))
                
            self.logger.info(f"History saved for guild {guild_id}: {len(history.messages)} messages")
            
        except Exception as e:
            self.logger.error(f"Failed to save history for guild {guild_id}: {e}")
    
    async def load_history(self, guild_id: int) -> Optional[dict]:
        """履歴の永続化読み込み"""
        try:
            file_path = self.storage_path / f"guild_{guild_id}.json"
            
            if not file_path.exists():
                return None
                
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
                
            self.logger.info(f"History loaded for guild {guild_id}: {len(data.get('messages', []))} messages")
            return data
            
        except Exception as e:
            self.logger.error(f"Failed to load history for guild {guild_id}: {e}")
            return None
    
    async def delete_history(self, guild_id: int) -> bool:
        """履歴の削除"""
        try:
            file_path = self.storage_path / f"guild_{guild_id}.json"
            
            if file_path.exists():
                file_path.unlink()
                self.logger.info(f"History deleted for guild {guild_id}")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to delete history for guild {guild_id}: {e}")
            return False


class EnhancedHistoryManager:
    """強化された履歴管理システム - 階層化キャッシュとSummarizationReducer使用"""
    
    def __init__(self, config: AppConfig, guild_config_manager: GuildConfigManager):
        self.config = config
        self.guild_config_manager = guild_config_manager
        self.logger = logging.getLogger("enhanced_history_manager")
        
        # 階層化キャッシュ
        self.hot_cache: Dict[int, Union[ChatHistorySummarizationReducer, ChatHistoryTruncationReducer]] = {}
        self.warm_storage: Dict[int, str] = {}  # JSON serialized
        self.last_access: Dict[int, datetime] = {}
        
        # 設定
        self.hot_threshold = timedelta(minutes=15)
        self.warm_threshold = timedelta(hours=24)
        
        # 永続化レイヤー
        self.persistence = PersistenceLayer()
        
        # バックグラウンドタスク
        self.background_tasks: set = set()
        
        # キャッシュ管理タスクを開始
        self._start_cache_management()
        
    def _start_cache_management(self):
        """キャッシュ管理タスクを開始"""
        task = asyncio.create_task(self._cache_management_loop())
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        
    async def _cache_management_loop(self):
        """定期的なキャッシュ管理"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分間隔
                await self._cleanup_inactive_caches()
            except Exception as e:
                self.logger.error(f"Cache management error: {e}")
                
    async def _cleanup_inactive_caches(self):
        """非アクティブなキャッシュのクリーンアップ"""
        now = datetime.now()
        guilds_to_move = []
        
        for guild_id, last_access in self.last_access.items():
            # Hot -> Warm への移動
            if guild_id in self.hot_cache and (now - last_access) > self.hot_threshold:
                guilds_to_move.append(guild_id)
                
        for guild_id in guilds_to_move:
            await self._move_to_warm_storage(guild_id)
            
        self.logger.info(f"Moved {len(guilds_to_move)} guilds from hot to warm storage")
        
    async def _move_to_warm_storage(self, guild_id: int):
        """Hot CacheからWarm Storageへの移動"""
        try:
            if guild_id not in self.hot_cache:
                return
                
            history = self.hot_cache[guild_id]
            
            # 永続化保存
            await self.persistence.save_history(guild_id, history)
            
            # Warm Storageに移動（簡易版として永続化ファイルパスを保存）
            self.warm_storage[guild_id] = f"guild_{guild_id}.json"
            
            # Hot Cacheから削除
            del self.hot_cache[guild_id]
            
            self.logger.info(f"Moved guild {guild_id} to warm storage")
            
        except Exception as e:
            self.logger.error(f"Failed to move guild {guild_id} to warm storage: {e}")
    
    async def get_history(self, guild_id: int) -> Union[ChatHistorySummarizationReducer, ChatHistoryTruncationReducer]:
        """履歴取得（階層化アクセス）"""
        now = datetime.now()
        self.last_access[guild_id] = now
        
        # Hot Cacheから取得
        if guild_id in self.hot_cache:
            return self.hot_cache[guild_id]
            
        # Warm Storageから復元
        if guild_id in self.warm_storage:
            history = await self._restore_from_warm(guild_id)
            if history:
                self.hot_cache[guild_id] = history
                # Warm Storageから削除
                del self.warm_storage[guild_id]
                return history
                
        # 永続化ストレージから復元
        saved_data = await self.persistence.load_history(guild_id)
        if saved_data:
            history = await self._restore_from_persistence(guild_id, saved_data)
            if history:
                self.hot_cache[guild_id] = history
                return history
            
        # 新規作成
        history = await self._create_new_history(guild_id)
        self.hot_cache[guild_id] = history
        return history
    
    async def _restore_from_warm(self, guild_id: int) -> Optional[Union[ChatHistorySummarizationReducer, ChatHistoryTruncationReducer]]:
        """Warm Storageからの履歴復元"""
        try:
            # Warm Storageはファイルパスなので、永続化から読み込み
            saved_data = await self.persistence.load_history(guild_id)
            if saved_data:
                return await self._restore_from_persistence(guild_id, saved_data)
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to restore from warm storage for guild {guild_id}: {e}")
            return None
    
    async def _restore_from_persistence(self, guild_id: int, data: dict) -> Optional[Union[ChatHistorySummarizationReducer, ChatHistoryTruncationReducer]]:
        """永続化データからの履歴復元"""
        try:
            effective_config = self.guild_config_manager.get_effective_config(guild_id)
            system_prompt = effective_config.custom_system_prompt or effective_config.default_system_prompt
            
            # Reducer タイプに基づいて適切なインスタンスを作成
            reducer_type = data.get('reducer_type', 'ChatHistorySummarizationReducer')
            target_count = data.get('target_count', self.config.bot.history_size)
            
            if reducer_type == 'ChatHistorySummarizationReducer':
                # AI Serviceを取得
                ai_service = AIServiceFactory.create_service(self._create_temp_config(guild_id))
                history = ChatHistorySummarizationReducer(
                    service=ai_service,
                    system_message=system_prompt,
                    target_count=target_count
                )
            else:
                # Fallback to TruncationReducer
                history = ChatHistoryTruncationReducer(
                    system_message=system_prompt,
                    target_count=target_count
                )
            
            # メッセージを復元
            for msg_data in data.get('messages', []):
                if msg_data['role'] == 'system':
                    history.add_system_message(msg_data['content'])
                elif msg_data['role'] == 'user':
                    history.add_user_message(msg_data['content'])
                elif msg_data['role'] == 'assistant':
                    history.add_assistant_message(msg_data['content'])
                    
            self.logger.info(f"Restored history for guild {guild_id}: {len(data.get('messages', []))} messages")
            return history
            
        except Exception as e:
            self.logger.error(f"Failed to restore history from persistence for guild {guild_id}: {e}")
            return None
    
    def _create_temp_config(self, guild_id: int) -> AppConfig:
        """ギルド用の一時設定オブジェクトを作成"""
        effective_config = self.guild_config_manager.get_effective_config(guild_id)
        
        return AppConfig(
            gpt=type(self.config.gpt)(
                openai_model=effective_config.openai_model,
                gemini_model=effective_config.gemini_model,
                max_token=effective_config.max_token,
                temperature=effective_config.temperature,
                image_resolution=type(self.config.gpt.image_resolution)(effective_config.image_resolution),
                ai_provider=effective_config.ai_provider,
            ),
            riot_api=self.config.riot_api,
            bot=self.config.bot,
        )
    
    async def _create_new_history(self, guild_id: int) -> ChatHistorySummarizationReducer:
        """新しい履歴の作成（SummarizationReducer使用）"""
        try:
            effective_config = self.guild_config_manager.get_effective_config(guild_id)
            system_prompt = effective_config.custom_system_prompt or effective_config.default_system_prompt
            
            # AI Serviceを作成
            ai_service = AIServiceFactory.create_service(self._create_temp_config(guild_id))
            
            # ChatHistorySummarizationReducerを作成
            history = ChatHistorySummarizationReducer(
                service=ai_service,
                system_message=system_prompt,
                target_count=self.config.bot.history_size
            )
            
            self.logger.info(f"Created new summarization history for guild {guild_id}")
            return history
            
        except Exception as e:
            self.logger.error(f"Failed to create new history for guild {guild_id}: {e}")
            # Fallback to TruncationReducer
            effective_config = self.guild_config_manager.get_effective_config(guild_id)
            system_prompt = effective_config.custom_system_prompt or effective_config.default_system_prompt
            
            return ChatHistoryTruncationReducer(
                system_message=system_prompt,
                target_count=self.config.bot.history_size
            )
    
    async def add_user_message(self, guild_id: int, message: str):
        """ユーザーメッセージを追加"""
        history = await self.get_history(guild_id)
        history.add_user_message(message)
        
    async def add_assistant_message(self, guild_id: int, message: str):
        """アシスタントメッセージを追加"""
        history = await self.get_history(guild_id)
        history.add_assistant_message(message)
        
        # バックグラウンドでの履歴削減と永続化
        task = asyncio.create_task(self._background_optimize(guild_id, history))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
    
    async def _background_optimize(self, guild_id: int, history: Union[ChatHistorySummarizationReducer, ChatHistoryTruncationReducer]):
        """バックグラウンド最適化処理"""
        try:
            # Save system message before reduction
            system_message = None
            for msg in history.messages:
                if msg.role.value == "system":
                    system_message = str(msg.content)
                    break

            # 履歴削減
            is_reduced = await history.reduce()
            if is_reduced:
                self.logger.info(f"History reduced for guild {guild_id}: {len(history.messages)} messages")

                # Restore system message if it was removed
                if system_message:
                    has_system = any(msg.role.value == "system" for msg in history.messages)

                    if not has_system:
                        # Re-add system message at the beginning
                        existing_messages = history.messages.copy()
                        history.messages.clear()
                        history.add_system_message(system_message)

                        # Re-add other messages
                        for msg in existing_messages:
                            if msg.role.value == "user":
                                history.add_user_message(str(msg.content))
                            elif msg.role.value == "assistant":
                                history.add_assistant_message(str(msg.content))

                        self.logger.info(f"System message restored after reduction for guild {guild_id}")

            # 定期的な永続化（Hot Cacheにある間も保存）
            await self.persistence.save_history(guild_id, history)

        except Exception as e:
            self.logger.error(f"Background optimization failed for guild {guild_id}: {e}")
    
    async def reset_history(self, guild_id: int) -> bool:
        """履歴をリセット"""
        try:
            # 全てのキャッシュから削除
            if guild_id in self.hot_cache:
                del self.hot_cache[guild_id]
            if guild_id in self.warm_storage:
                del self.warm_storage[guild_id]
            if guild_id in self.last_access:
                del self.last_access[guild_id]
                
            # 永続化ストレージからも削除
            await self.persistence.delete_history(guild_id)
            
            self.logger.info(f"History reset for guild {guild_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to reset history for guild {guild_id}: {e}")
            return False
    
    async def change_character(self, guild_id: int, system_prompt: str) -> bool:
        """システムプロンプトを変更"""
        try:
            history = await self.get_history(guild_id)
            
            # 既存の非システムメッセージを保存
            non_system_messages = [msg for msg in history.messages if msg.role.value != "system"]
            
            # 新しい履歴を作成
            if isinstance(history, ChatHistorySummarizationReducer):
                ai_service = AIServiceFactory.create_service(self._create_temp_config(guild_id))
                new_history = ChatHistorySummarizationReducer(
                    service=ai_service,
                    system_message=system_prompt,
                    target_count=self.config.bot.history_size
                )
            else:
                new_history = ChatHistoryTruncationReducer(
                    system_message=system_prompt,
                    target_count=self.config.bot.history_size
                )
            
            # 非システムメッセージを復元
            for msg in non_system_messages:
                if msg.role.value == "user":
                    new_history.add_user_message(str(msg.content))
                elif msg.role.value == "assistant":
                    new_history.add_assistant_message(str(msg.content))
            
            # キャッシュを更新
            self.hot_cache[guild_id] = new_history
            self.last_access[guild_id] = datetime.now()
            
            # 永続化
            await self.persistence.save_history(guild_id, new_history)
            
            self.logger.info(f"Character changed for guild {guild_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to change character for guild {guild_id}: {e}")
            return False
    
    def get_history_size(self, guild_id: int) -> int:
        """履歴サイズを取得"""
        if guild_id in self.hot_cache:
            return len(self.hot_cache[guild_id].messages)
        return 0
    
    def get_system_prompt(self, guild_id: int) -> str:
        """システムプロンプトを取得"""
        if guild_id in self.hot_cache:
            history = self.hot_cache[guild_id]
            system_messages = [msg for msg in history.messages if msg.role.value == "system"]
            if system_messages:
                return str(system_messages[0].content)
        return ""
    
    async def update_history_size(self, new_size: int) -> bool:
        """履歴サイズを更新"""
        try:
            self.config.bot.history_size = new_size
            
            # 全ての履歴のtarget_countを更新
            for guild_id, history in self.hot_cache.items():
                history.target_count = new_size
                
            self.logger.info(f"Updated history size to {new_size} for {len(self.hot_cache)} active histories")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update history size: {e}")
            return False
    
    async def shutdown(self):
        """シャットダウン処理"""
        try:
            # 全てのバックグラウンドタスクを停止
            for task in self.background_tasks:
                task.cancel()
                
            # 全てのHot Cacheを永続化
            for guild_id, history in self.hot_cache.items():
                await self.persistence.save_history(guild_id, history)
                
            self.logger.info("Enhanced history manager shutdown completed")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")