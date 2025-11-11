import datetime
import logging
import sys
from pathlib import Path
from typing import Dict, Optional

import openai
from semantic_kernel.contents import ChatMessageContent, ImageContent, TextContent
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.history_reducer.chat_history_truncation_reducer import ChatHistoryTruncationReducer
from semantic_kernel.contents.utils.author_role import AuthorRole

# Add current directory to sys.path for absolute imports
sys.path.append(str(Path(__file__).parent))

from ai_service import AIServiceFactory, AIServiceInterface
from config import AIProvider, AppConfig, ImageReso
from enhanced_history_manager import EnhancedHistoryManager
from guild_config import EffectiveGuildConfig, GuildConfigManager


class GptService:
    """GPT interaction service handling chat histories"""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger

        # Initialize guild configuration manager
        self.guild_config_manager = GuildConfigManager(config)

        # Enhanced history manager (NEW)
        try:
            self.enhanced_history_manager = EnhancedHistoryManager(config, self.guild_config_manager)
            self.use_enhanced_history = True
            self.logger.info("Enhanced history manager initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize enhanced history manager: {e}")
            self.logger.warning("Falling back to legacy history mode")
            self.enhanced_history_manager = None
            self.use_enhanced_history = False

        # Guild-specific AI services
        self.ai_services: Dict[int, AIServiceInterface] = {}

        # Legacy global AI service for compatibility
        self._initialize_ai_service()

        # Legacy chat histories (DEPRECATED - will be phased out)
        self.chat_histories: Dict[int, ChatHistoryTruncationReducer] = {}
        self.last_activity: datetime.datetime = datetime.datetime.now()

    def _initialize_ai_service(self):
        """Initialize AI service using factory"""
        try:
            self.ai_service = AIServiceFactory.create_service(self.config)
            if not self.ai_service:
                self.logger.error("Failed to initialize AI service - factory returned None")
                raise RuntimeError("AI service initialization failed - factory returned None")

            self.logger.info(f"Initialized GPT service with provider: {self.config.gpt.ai_provider.value}")
        except Exception as e:
            self.logger.error(f"Failed to initialize AI service: {e}")
            # Fallback to None - service will still work for image processing
            self.ai_service = None
            self.logger.warning("AI service disabled - text-only features will not work")

    def reinitialize_ai_service(self):
        """Reinitialize AI service after configuration changes"""
        self.logger.info("Reinitializing AI service due to configuration change")
        self._initialize_ai_service()

    def _get_ai_service(self, guild_id: int) -> AIServiceInterface:
        """Get or create AI service for a specific guild"""
        try:
            if guild_id not in self.ai_services:
                # Create AI service using guild-specific configuration
                effective_config = self.guild_config_manager.get_effective_config(guild_id)

                # Create a temporary AppConfig object with effective settings for the factory
                temp_config = AppConfig(
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

                self.ai_services[guild_id] = AIServiceFactory.create_service(temp_config)

                if not self.ai_services[guild_id]:
                    self.logger.error(f"Failed to create AI service for guild {guild_id}")
                    raise RuntimeError(f"AI service creation failed for guild {guild_id}")

                self.logger.info(f"Created AI service for guild {guild_id} with provider: {effective_config.ai_provider.value}")

            return self.ai_services[guild_id]

        except Exception as e:
            self.logger.error(f"Failed to get AI service for guild {guild_id}: {e}")
            # Fallback to global service if guild-specific fails
            if self.ai_service:
                self.logger.warning(f"Falling back to global AI service for guild {guild_id}")
                return self.ai_service
            else:
                raise RuntimeError(f"No AI service available for guild {guild_id}")

    def reinitialize_guild_ai_service(self, guild_id: int):
        """Reinitialize AI service for a specific guild after configuration changes"""
        try:
            if guild_id in self.ai_services:
                del self.ai_services[guild_id]
                self.logger.info(f"Removed cached AI service for guild {guild_id}")

            # The service will be recreated on next access
            self.logger.info(f"Guild {guild_id} AI service will be recreated on next use")

        except Exception as e:
            self.logger.error(f"Failed to reinitialize AI service for guild {guild_id}: {e}")

    def initialize_chat_history(self, guild_id: int) -> None:
        """Initialize chat history for a guild if not exists"""
        if self.use_enhanced_history:
            # Enhanced history manager handles initialization automatically
            return

        if guild_id not in self.chat_histories:
            effective_config = self.guild_config_manager.get_effective_config(guild_id)
            system_prompt = effective_config.custom_system_prompt or effective_config.default_system_prompt

            # Create ChatHistoryTruncationReducer
            self.chat_histories[guild_id] = ChatHistoryTruncationReducer(
                system_message=system_prompt,
                target_count=self.config.bot.history_size,
                threshold_count=self.config.bot.history_size + 5,  # Buffer for critical message pairs
                auto_reduce=False  # Manual control for better performance
            )

            self.logger.info(f"Initialized chat history with manual reduce for guild {guild_id} (target: {self.config.bot.history_size} messages)")

    def _create_new_history_with_system_message(self, system_message: str, guild_id: int) -> ChatHistoryTruncationReducer:
        """Create new chat history with system message

        Args:
            system_message: System message text
            guild_id: Discord guild ID

        Returns:
            ChatHistoryTruncationReducer: New chat history instance
        """
        ai_service = self._get_ai_service(guild_id)
        history = ChatHistoryTruncationReducer(
            service=ai_service,
            system_message=system_message,
            target_count=self.config.bot.history_size,
            threshold_count=self.config.bot.history_size + 5,  # Buffer for critical message pairs
            auto_reduce=False  # Manual control for better performance
        )
        return history

    async def reset_history(self, guild_id: int) -> bool:
        """Reset chat history for a guild while preserving system prompt settings

        Args:
            guild_id: Discord guild ID

        Returns:
            bool: True if successful, False otherwise
        """
        if self.use_enhanced_history and self.enhanced_history_manager:
            # Use enhanced history manager
            try:
                return await self.enhanced_history_manager.reset_history(guild_id)
            except Exception as e:
                self.logger.error(f"Enhanced history reset failed for guild {guild_id}: {e}")
                self.logger.warning("Falling back to legacy mode for this operation")
                # Fall through to legacy mode

        if guild_id in self.chat_histories:
            # Get current system prompt (preserve custom settings)
            current_system_prompt = self.get_system_prompt(guild_id)
            if not current_system_prompt:
                # No existing system prompt, use effective config
                effective_config = self.guild_config_manager.get_effective_config(guild_id)
                current_system_prompt = effective_config.custom_system_prompt or effective_config.default_system_prompt

            self.chat_histories[guild_id] = self._create_new_history_with_system_message(current_system_prompt, guild_id)
            self.logger.info(f"History reset for guild {guild_id} with preserved system prompt")
            return True
        return False

    def reset_character(self, guild_id: int) -> bool:
        """Reset system character for a guild to default (removes custom prompt)

        Args:
            guild_id: Discord guild ID

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Clear custom system prompt setting
            success = self.guild_config_manager.update_guild_config(guild_id, custom_system_prompt=None)
            if not success:
                self.logger.error(f"Failed to clear custom system prompt for guild {guild_id}")
                return False

            # Get default system prompt after clearing custom setting
            effective_config = self.guild_config_manager.get_effective_config(guild_id)
            default_prompt = effective_config.default_system_prompt

            if guild_id in self.chat_histories:
                # Recreate history with default system prompt
                self.chat_histories[guild_id] = self._create_new_history_with_system_message(default_prompt, guild_id)
                self.logger.info(f"System character reset to default for guild {guild_id}")
            else:
                # Initialize new history for guild if it doesn't exist
                self.initialize_chat_history(guild_id)
                self.logger.info(f"Initialized default system character for new guild {guild_id}")

            return True

        except Exception as e:
            self.logger.error(f"Failed to reset system character for guild {guild_id}: {e}")
            return False

    async def change_character(self, guild_id: int, text: str) -> bool:
        """Change system character setting for GPT

        Args:
            guild_id: Discord guild ID
            text: New character setting text

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Save custom system prompt to guild config
            self.guild_config_manager.update_guild_config(guild_id, custom_system_prompt=text)

            if self.use_enhanced_history and self.enhanced_history_manager:
                # Use enhanced history manager
                try:
                    return await self.enhanced_history_manager.change_character(guild_id, text)
                except Exception as e:
                    self.logger.error(f"Enhanced character change failed for guild {guild_id}: {e}")
                    self.logger.warning("Falling back to legacy mode for this operation")
                    # Fall through to legacy mode

            if guild_id in self.chat_histories:
                # Preserve existing chat history, only replace system message
                messages = self.chat_histories[guild_id].messages
                non_system_messages = [msg for msg in messages if msg.role.value != "system"]

                # Create new chat history with new system message
                new_chat_history = self._create_new_history_with_system_message(text, guild_id)

                # Add back all non-system messages
                self._add_messages_to_history(new_chat_history, non_system_messages)

                self.chat_histories[guild_id] = new_chat_history
                self.logger.info(f"System character changed for guild {guild_id}: {text[:50]}...")
            else:
                # Create new chat history for new server
                self.chat_histories[guild_id] = self._create_new_history_with_system_message(text, guild_id)
                self.logger.info(f"Character created for new guild {guild_id}: {text[:50]}...")
        except Exception:
            self.logger.exception(f"Character setting failed for guild {guild_id}")
            return False
        return True

    def check_history_size(self, guild_id: int) -> int:
        """Check chat history size for a guild

        Args:
            guild_id: Discord guild ID

        Returns:
            int: Number of messages in history
        """
        if self.use_enhanced_history:
            return self.enhanced_history_manager.get_history_size(guild_id)

        if guild_id in self.chat_histories:
            return len(self.chat_histories[guild_id].messages)
        return 0

    async def get_history_messages(self, guild_id: int):
        """Get chat history messages for a guild (abstraction layer)

        Args:
            guild_id: Discord guild ID

        Returns:
            list: List of chat messages, or empty list if no history
        """
        try:
            if self.use_enhanced_history and self.enhanced_history_manager:
                # Get history from enhanced manager
                try:
                    history = await self.enhanced_history_manager.get_history(guild_id)
                    return history.messages if history else []
                except Exception as e:
                    self.logger.error(f"Enhanced history retrieval failed for guild {guild_id}: {e}")
                    self.logger.warning("Falling back to legacy mode")
                    # Fall through to legacy mode

            if guild_id in self.chat_histories:
                return self.chat_histories[guild_id].messages
            return []
        except Exception as e:
            self.logger.error(f"Failed to get history messages for guild {guild_id}: {e}")
            return []

    async def add_user_message_to_history(self, guild_id: int, message: str):
        """Add user message to chat history (abstraction layer)

        Args:
            guild_id: Discord guild ID
            message: User message text
        """
        try:
            if self.use_enhanced_history and self.enhanced_history_manager:
                try:
                    await self.enhanced_history_manager.add_user_message(guild_id, message)
                    return
                except Exception as e:
                    self.logger.error(f"Enhanced add user message failed for guild {guild_id}: {e}")
                    self.logger.warning("Falling back to legacy mode")
                    # Fall through to legacy mode

            self.initialize_chat_history(guild_id)
            self.chat_histories[guild_id].add_user_message(message)
        except Exception as e:
            self.logger.error(f"Failed to add user message for guild {guild_id}: {e}")
            raise

    async def add_assistant_message_to_history(self, guild_id: int, message: str):
        """Add assistant message to chat history (abstraction layer)

        Args:
            guild_id: Discord guild ID
            message: Assistant message text
        """
        try:
            if self.use_enhanced_history and self.enhanced_history_manager:
                try:
                    await self.enhanced_history_manager.add_assistant_message(guild_id, message)
                    return
                except Exception as e:
                    self.logger.error(f"Enhanced add assistant message failed for guild {guild_id}: {e}")
                    self.logger.warning("Falling back to legacy mode")
                    # Fall through to legacy mode

            if guild_id in self.chat_histories:
                self.chat_histories[guild_id].add_assistant_message(message)
        except Exception as e:
            self.logger.error(f"Failed to add assistant message for guild {guild_id}: {e}")
            raise

    async def reduce_history(self, guild_id: int) -> bool:
        """Apply history reduction (abstraction layer)

        Args:
            guild_id: Discord guild ID

        Returns:
            bool: True if history was reduced, False otherwise
        """
        if self.use_enhanced_history:
            # Enhanced manager handles reduction automatically in background
            return False
        else:
            if guild_id in self.chat_histories:
                history = self.chat_histories[guild_id]

                # Save system message before reduction
                system_message = None
                for msg in history.messages:
                    if msg.role.value == "system":
                        system_message = str(msg.content)
                        break

                # Apply reduction
                is_reduced = await history.reduce()

                # If reduced and system message was present, restore it
                if is_reduced and system_message:
                    # Check if system message still exists
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

                return is_reduced
            return False

    async def send_question_gpt(self, question: str, reference: Optional[str], attachments: list, guild_id: int) -> str:
        """Send question to GPT using Semantic Kernel and get response

        Args:
            question: User question text
            reference: Referenced message text (optional)
            attachments: List of attachment URLs
            guild_id: Discord guild ID

        Returns:
            str: Response text
        """
        self.logger.info(f"[Question] {question}")

        # Build user message
        user_message = question
        if reference is not None:
            user_message += f"\n## 以下へ言及\n{reference}"
            self.logger.info(f"[Reference] {reference}")

        if self.use_enhanced_history:
            # Use enhanced history manager
            # Handle image attachments using Semantic Kernel ImageContent
            if len(attachments) > 0:
                # Image request handler adds the multimodal message to history internally
                response_text = await self._handle_image_request_enhanced(guild_id, user_message, attachments)
            else:
                # Add text-only user message to history
                await self.enhanced_history_manager.add_user_message(guild_id, user_message)
                # Use Semantic Kernel for text-only conversations
                response_text = await self._handle_text_request_enhanced(guild_id)

            await self.enhanced_history_manager.add_assistant_message(guild_id, response_text)
        else:
            # Legacy mode
            self.initialize_chat_history(guild_id)

            # Handle image attachments using Semantic Kernel ImageContent
            if len(attachments) > 0:
                # Image request handler adds the multimodal message to history internally
                response_text = await self._handle_image_request(guild_id, user_message, attachments)
            else:
                # Add text-only user message to chat history (auto-reduce will trigger if needed)
                self.chat_histories[guild_id].add_user_message(user_message)
                # Use Semantic Kernel for text-only conversations
                response_text = await self._handle_text_request(guild_id, user_message)

            # Add assistant response to chat history
            self.chat_histories[guild_id].add_assistant_message(response_text)

            # Apply history reduction using standard ChatHistoryTruncationReducer method
            is_reduced = await self.chat_histories[guild_id].reduce()
            if is_reduced:
                self.logger.info(f"History reduced to {len(self.chat_histories[guild_id].messages)} messages for guild {guild_id}")

        self.logger.info(f"[Response] {response_text}")
        self.last_activity = datetime.datetime.now()

        return response_text

    async def _handle_image_request(self, guild_id: int, user_message: str, attachments: list) -> str:
        """Handle request with image attachments using Semantic Kernel ImageContent

        Args:
            guild_id: Discord guild ID
            user_message: User message text
            attachments: List of attachment URLs

        Returns:
            str: Response text
        """
        self.logger.info(f"[Attachments] {attachments}")

        # Get AI service for this guild
        ai_service = self._get_ai_service(guild_id)
        effective_config = self.guild_config_manager.get_effective_config(guild_id)

        # Create image resolution detail setting
        reso = "low" if self.config.gpt.image_resolution == ImageReso.LOW else "high"

        # Build message items with text and images using Semantic Kernel content types
        message_items = [TextContent(text=user_message)]

        # Add ImageContent for each attachment URL
        for url in attachments:
            # ImageContent with URI and detail level in metadata for OpenAI
            message_items.append(ImageContent(uri=url, metadata={"detail": reso}))

        # Create ChatMessageContent with text and images
        user_message_with_images = ChatMessageContent(
            role=AuthorRole.USER,
            items=message_items
        )

        # Add the multimodal message to chat history
        self.chat_histories[guild_id].messages.append(user_message_with_images)

        # Get response using AI service with vision support
        settings = {
            "max_tokens": effective_config.max_token,
            "temperature": effective_config.temperature
        }

        try:
            response_text = await ai_service.get_chat_response(
                self.chat_histories[guild_id],
                settings
            )
            return response_text
        except Exception as e:
            self.logger.error(f"Vision API error for guild {guild_id}: {e}")
            # Fallback to direct OpenAI API if service doesn't support vision
            return await self._handle_image_request_fallback(guild_id, user_message, attachments)

    async def _handle_image_request_fallback(self, guild_id: int, user_message: str, attachments: list) -> str:
        """Fallback to direct OpenAI API for image processing

        Args:
            guild_id: Discord guild ID
            user_message: User message text
            attachments: List of attachment URLs

        Returns:
            str: Response text
        """
        self.logger.warning(f"Using fallback OpenAI API for image processing in guild {guild_id}")

        reso = "low" if self.config.gpt.image_resolution == ImageReso.LOW else "high"
        image_input = [{"type": "image_url", "image_url": {"url": url, "detail": reso}} for url in attachments]

        # Convert chat history to OpenAI format
        messages = []
        for msg in self.chat_histories[guild_id].messages[:-1]:  # Exclude the last message we just added
            messages.append({"role": msg.role.value, "content": str(msg.content)})

        # Add current message with images
        messages.append({"role": "user", "content": [{"type": "text", "text": user_message}] + image_input})

        response = openai.chat.completions.create(
            model=self.config.gpt.openai_model,
            messages=messages,
            max_tokens=self.config.gpt.max_token,
            temperature=self.config.gpt.temperature,
        )

        return str(response.choices[0].message.content)

    async def _handle_image_request_enhanced(self, guild_id: int, user_message: str, attachments: list) -> str:
        """Enhanced版: Handle image requests using Semantic Kernel ImageContent

        Args:
            guild_id: Discord guild ID
            user_message: User message text
            attachments: List of attachment URLs

        Returns:
            str: Response text
        """
        self.logger.info(f"[Attachments] {attachments}")

        # Get AI service and effective config for this guild
        ai_service = self._get_ai_service(guild_id)
        effective_config = self.guild_config_manager.get_effective_config(guild_id)

        # Get history from enhanced manager
        history = await self.enhanced_history_manager.get_history(guild_id)

        # Create image resolution detail setting
        reso = "low" if self.config.gpt.image_resolution == ImageReso.LOW else "high"

        # Build message items with text and images using Semantic Kernel content types
        message_items = [TextContent(text=user_message)]

        # Add ImageContent for each attachment URL
        for url in attachments:
            # ImageContent with URI and detail level in metadata for OpenAI
            message_items.append(ImageContent(uri=url, metadata={"detail": reso}))

        # Create ChatMessageContent with text and images
        user_message_with_images = ChatMessageContent(
            role=AuthorRole.USER,
            items=message_items
        )

        # Add the multimodal message to chat history
        history.messages.append(user_message_with_images)

        # Get response using AI service with vision support
        settings = {
            "max_tokens": effective_config.max_token,
            "temperature": effective_config.temperature
        }

        try:
            response_text = await ai_service.get_chat_response(history, settings)
            return response_text
        except Exception as e:
            self.logger.error(f"Enhanced vision API error for guild {guild_id}: {e}")
            # Fallback to direct OpenAI API
            return await self._handle_image_request_enhanced_fallback(guild_id, user_message, attachments, history)

    async def _handle_image_request_enhanced_fallback(self, guild_id: int, user_message: str, attachments: list, history) -> str:
        """Enhanced版: Fallback to direct OpenAI API for image processing

        Args:
            guild_id: Discord guild ID
            user_message: User message text
            attachments: List of attachment URLs
            history: Chat history

        Returns:
            str: Response text
        """
        self.logger.warning(f"Using fallback OpenAI API for enhanced image processing in guild {guild_id}")

        reso = "low" if self.config.gpt.image_resolution == ImageReso.LOW else "high"
        image_input = [{"type": "image_url", "image_url": {"url": url, "detail": reso}} for url in attachments]

        # Convert chat history to OpenAI format
        messages = []
        for msg in history.messages[:-1]:  # Exclude the last message we just added
            messages.append({"role": msg.role.value, "content": str(msg.content)})

        # Add current message with images
        messages.append({"role": "user", "content": [{"type": "text", "text": user_message}] + image_input})

        response = openai.chat.completions.create(
            model=self.config.gpt.openai_model,
            messages=messages,
            max_tokens=self.config.gpt.max_token,
            temperature=self.config.gpt.temperature,
        )

        return str(response.choices[0].message.content)

    async def _handle_text_request_enhanced(self, guild_id: int) -> str:
        """Enhanced版: テキストのみリクエストの処理"""
        try:
            history = await self.enhanced_history_manager.get_history(guild_id)
            ai_service = self._get_ai_service(guild_id)
            effective_config = self.guild_config_manager.get_effective_config(guild_id)

            settings = {"max_tokens": effective_config.max_token, "temperature": effective_config.temperature}

            response_text = await ai_service.get_chat_response(history, settings)
            return response_text

        except Exception as e:
            error_msg = f"AI サービスエラー: {str(e)}"
            self.logger.error(f"AI service error for guild {guild_id}: {e}")
            return error_msg

    async def _handle_text_request(self, guild_id: int, user_message: str) -> str:
        """Handle text-only request using guild-specific AI service

        Args:
            guild_id: Discord guild ID
            user_message: User message text

        Returns:
            str: Response text
        """
        try:
            ai_service = self._get_ai_service(guild_id)
            effective_config = self.guild_config_manager.get_effective_config(guild_id)

            settings = {"max_tokens": effective_config.max_token, "temperature": effective_config.temperature}

            response_text = await ai_service.get_chat_response(self.chat_histories[guild_id], settings)

            return response_text

        except Exception as e:
            error_msg = f"AI サービスエラー: {str(e)}"
            self.logger.error(f"AI service error for guild {guild_id}: {e}")
            return error_msg

    def get_system_prompt(self, guild_id: int) -> str:
        """Get current system prompt for a guild

        Args:
            guild_id: Discord guild ID

        Returns:
            str: System prompt text, empty string if not found
        """
        if self.use_enhanced_history:
            return self.enhanced_history_manager.get_system_prompt(guild_id)

        if guild_id in self.chat_histories:
            system_messages = [msg for msg in self.chat_histories[guild_id].messages if msg.role.value == "system"]
            if system_messages:
                return str(system_messages[0].content)
        return ""

    def should_reset_history(self) -> bool:
        """Check if history should be reset based on inactivity

        Returns:
            bool: True if history should be reset (after 60 minutes of inactivity)
        """
        return (datetime.datetime.now() - self.last_activity).total_seconds() > 60 * 60

    def _reconstruct_chat_history(self, messages, guild_id: int) -> ChatHistoryTruncationReducer:
        """Reconstruct chat history from message list

        Args:
            messages: List of messages to add
            guild_id: Discord guild ID

        Returns:
            ChatHistoryTruncationReducer: Reconstructed chat history
        """
        # Create empty history first, then add messages
        ai_service = self._get_ai_service(guild_id)
        new_chat_history = ChatHistoryTruncationReducer(
            service=ai_service,
            target_count=self.config.bot.history_size,
            threshold_count=self.config.bot.history_size + 5,  # Buffer for critical message pairs
            auto_reduce=False  # Manual control for better performance
        )
        self._add_messages_to_history(new_chat_history, messages)
        return new_chat_history

    def _add_messages_to_history(self, chat_history: ChatHistoryTruncationReducer, messages) -> None:
        """Add messages to chat history based on their role

        Args:
            chat_history: Chat history to add messages to
            messages: List of messages to add
        """
        for msg in messages:
            if msg.role.value == "system":
                chat_history.add_system_message(str(msg.content))
            elif msg.role.value == "user":
                chat_history.add_user_message(str(msg.content))
            elif msg.role.value == "assistant":
                chat_history.add_assistant_message(str(msg.content))

    # Guild configuration management methods
    def update_guild_ai_provider(self, guild_id: int, provider: AIProvider) -> bool:
        """Update AI provider for a specific guild"""
        try:
            result = self.guild_config_manager.update_guild_config(guild_id, ai_provider=provider)
            if result:
                # Reinitialize AI service for this guild
                self.reinitialize_guild_ai_service(guild_id)
            return result
        except Exception as e:
            self.logger.error(f"Failed to update AI provider for guild {guild_id}: {e}")
            return False

    def update_guild_model(self, guild_id: int, openai_model: str = None, gemini_model: str = None) -> bool:
        """Update AI model for a specific guild"""
        try:
            kwargs = {}
            if openai_model is not None:
                kwargs["openai_model"] = openai_model
            if gemini_model is not None:
                kwargs["gemini_model"] = gemini_model

            result = self.guild_config_manager.update_guild_config(guild_id, **kwargs)
            if result:
                # Reinitialize AI service for this guild
                self.reinitialize_guild_ai_service(guild_id)
            return result
        except Exception as e:
            self.logger.error(f"Failed to update model for guild {guild_id}: {e}")
            return False

    def get_guild_effective_config(self, guild_id: int) -> EffectiveGuildConfig:
        """Get effective configuration for a guild"""
        return self.guild_config_manager.get_effective_config(guild_id)

    def reset_guild_config(self, guild_id: int, preserve_system_prompt: bool = False) -> bool:
        """Reset guild configuration to defaults"""
        try:
            result = self.guild_config_manager.reset_guild_config(guild_id, preserve_system_prompt)
            if result:
                # Reinitialize AI service for this guild
                self.reinitialize_guild_ai_service(guild_id)
            return result
        except Exception as e:
            self.logger.error(f"Failed to reset guild config for {guild_id}: {e}")
            return False

    async def update_history_size(self, new_size: int) -> bool:
        """Update history size for all existing chat histories"""
        try:
            # Update the config
            self.config.bot.history_size = new_size

            if self.use_enhanced_history and self.enhanced_history_manager:
                # Use enhanced history manager
                try:
                    return await self.enhanced_history_manager.update_history_size(new_size)
                except Exception as e:
                    self.logger.error(f"Enhanced history size update failed: {e}")
                    self.logger.warning("Falling back to legacy mode for this operation")
                    # Fall through to legacy mode

            # Update all existing chat histories (legacy)
            for guild_id, chat_history in self.chat_histories.items():
                chat_history.target_count = new_size

            self.logger.info(f"Updated history size to {new_size} for {len(self.chat_histories)} chat histories")
            return True
        except Exception as e:
            self.logger.error(f"Failed to update history size: {e}")
            return False
