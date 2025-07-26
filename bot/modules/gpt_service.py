import datetime
import logging
from typing import Dict, Optional, Tuple

import openai
import semantic_kernel as sk
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.open_ai_prompt_execution_settings import OpenAIChatPromptExecutionSettings
from semantic_kernel.contents.chat_history import ChatHistory

from .config import AppConfig, ImageReso


class GptService:
    """GPT interaction service handling chat histories and token management"""
    
    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        # Initialize Semantic Kernel
        self.kernel = sk.Kernel()
        chat_completion = OpenAIChatCompletion(ai_model_id=self.config.gpt.model, service_id="chat-gpt")
        self.kernel.add_service(chat_completion)

        self.chat_histories: Dict[int, ChatHistory] = {}
        self.token_ranking: Dict[int, Dict[int, int]] = {}
        self.last_activity: datetime.datetime = datetime.datetime.now()

    def initialize_chat_history(self, guild_id: int) -> None:
        """Initialize chat history for a guild if not exists"""
        if guild_id not in self.chat_histories:
            self.chat_histories[guild_id] = ChatHistory()
            self.chat_histories[guild_id].add_system_message(self.config.bot.default_system_promt)

    def _create_new_history_with_system_message(self, system_message: str) -> ChatHistory:
        """Create new chat history with system message
        
        Args:
            system_message: System message text
            
        Returns:
            ChatHistory: New chat history instance
        """
        history = ChatHistory()
        history.add_system_message(system_message)
        return history

    def reset_history(self, guild_id: int) -> bool:
        """Reset chat history for a guild
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        if guild_id in self.chat_histories:
            self.chat_histories[guild_id] = self._create_new_history_with_system_message(self.config.bot.default_system_promt)
            self.logger.info("history reset")
            return True
        return False

    def reset_character(self, guild_id: int) -> bool:
        """Reset system character for a guild
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        if guild_id in self.chat_histories:
            self.chat_histories[guild_id] = self._create_new_history_with_system_message(self.config.bot.default_system_promt)
            self.logger.info("system character reset")
            return True
        return False

    def change_character(self, guild_id: int, text: str) -> bool:
        """Change system character setting for GPT
        
        Args:
            guild_id: Discord guild ID
            text: New character setting text
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if guild_id in self.chat_histories:
                # Preserve existing chat history, only replace system message
                messages = self.chat_histories[guild_id].messages
                non_system_messages = [msg for msg in messages if msg.role.value != "system"]
                
                # Create new chat history with new system message
                new_chat_history = ChatHistory()
                new_chat_history.add_system_message(text)
                
                # Add back all non-system messages
                self._add_messages_to_history(new_chat_history, non_system_messages)
                
                self.chat_histories[guild_id] = new_chat_history
                self.logger.info(f"system character changed -> {text}")
            else:
                # Create new chat history for new server
                self.chat_histories[guild_id] = self._create_new_history_with_system_message(text)
                self.logger.info(f"character created for new server-> {text}")
        except Exception:
            self.logger.exception("Character setting failed")
            return False
        return True

    def check_history_size(self, guild_id: int) -> int:
        """Check chat history size for a guild
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            int: Number of messages in history
        """
        if guild_id in self.chat_histories:
            return len(self.chat_histories[guild_id].messages)
        return 0

    def delete_old_history(self, guild_id: int) -> None:
        """Delete oldest history entries when limit is exceeded
        
        Args:
            guild_id: Discord guild ID
        """
        if guild_id in self.chat_histories and len(self.chat_histories[guild_id].messages) > self.config.bot.history_size:
            # Keep system message and remove oldest user/assistant messages
            messages = self.chat_histories[guild_id].messages
            system_messages = [msg for msg in messages if msg.role.value == "system"]
            other_messages = [msg for msg in messages if msg.role.value != "system"]
            if len(other_messages) > self.config.bot.history_size - len(system_messages):
                # Remove the oldest non-system messages
                other_messages = other_messages[-(self.config.bot.history_size - len(system_messages)) :]

            # Reconstruct chat history
            new_chat_history = self._reconstruct_chat_history(system_messages + other_messages)

            self.chat_histories[guild_id] = new_chat_history

    async def send_question_gpt(self, question: str, reference: Optional[str], attachments: list, guild_id: int) -> Tuple[str, int]:
        """Send question to GPT using Semantic Kernel and get response
        
        Args:
            question: User question text
            reference: Referenced message text (optional)
            attachments: List of attachment URLs
            guild_id: Discord guild ID
            
        Returns:
            Tuple[str, int]: Response text and token usage count
        """
        self.logger.info(f"[Question] {question}")

        # Initialize chat history if not exists
        self.initialize_chat_history(guild_id)

        # Build user message
        user_message = question
        if reference is not None:
            user_message += f"\n## 以下へ言及\n{reference}"
            self.logger.info(f"[Reference] {reference}")

        # Add user message to chat history
        self.chat_histories[guild_id].add_user_message(user_message)

        # Handle image attachments (fallback to OpenAI direct call for vision)
        if len(attachments) > 0:
            response_text, total_tokens = await self._handle_image_request(guild_id, user_message, attachments)
        else:
            # Use Semantic Kernel for text-only conversations
            response_text, total_tokens = await self._handle_text_request(guild_id, user_message)

        # Add assistant response to chat history
        self.chat_histories[guild_id].add_assistant_message(response_text)

        self.logger.info(f"[Response] {response_text}")
        self.last_activity = datetime.datetime.now()

        return response_text, total_tokens

    async def _handle_image_request(self, guild_id: int, user_message: str, attachments: list) -> Tuple[str, int]:
        """Handle request with image attachments using OpenAI direct API
        
        Args:
            guild_id: Discord guild ID
            user_message: User message text
            attachments: List of attachment URLs
            
        Returns:
            Tuple[str, int]: Response text and token usage
        """
        self.logger.info(f"[Attachments] {attachments}")
        
        reso = "low" if self.config.gpt.image_resolution == ImageReso.LOW else "high"
        
        image_input = [{"type": "image_url", "image_url": {"url": url, "detail": reso}} for url in attachments]
        
        # Convert chat history to OpenAI format for vision
        messages = [{"role": msg.role.value, "content": str(msg.content)} for msg in self.chat_histories[guild_id].messages]
        
        # Add current message with images
        messages.append({"role": "user", "content": [{"type": "text", "text": user_message}] + image_input})
        
        response = openai.chat.completions.create(
            model=self.config.gpt.model,
            messages=messages,
            max_tokens=self.config.gpt.max_token,
            temperature=self.config.gpt.temperature,
        )
        
        return str(response.choices[0].message.content), response.usage.total_tokens

    async def _handle_text_request(self, guild_id: int, user_message: str) -> Tuple[str, int]:
        """Handle text-only request using Semantic Kernel
        
        Args:
            guild_id: Discord guild ID
            user_message: User message text
            
        Returns:
            Tuple[str, int]: Response text and token usage
        """
        chat_completion = self.kernel.get_service("chat-gpt")
        response = await chat_completion.get_chat_message_content(
            chat_history=self.chat_histories[guild_id],
            settings=OpenAIChatPromptExecutionSettings(max_tokens=self.config.gpt.max_token, temperature=self.config.gpt.temperature),
        )
        
        response_text = str(response.content)
        total_tokens = self._estimate_token_usage(user_message, response_text)
        
        return response_text, total_tokens
    
    def _estimate_token_usage(self, input_text: str, output_text: str) -> int:
        """Estimate token usage for text-based interactions (simplified version)
        
        Args:
            input_text: Input text
            output_text: Output text
            
        Returns:
            int: Estimated token count
        """
        # Simple estimation: ~4 chars = 1 token for English, ~1.5 chars = 1 token for Japanese
        input_tokens = len(input_text) // 3  # Average for mixed content
        output_tokens = len(output_text) // 3
        return input_tokens + output_tokens

    def update_token_ranking(self, guild_id: int, author_id: int, usage: int) -> None:
        """Update token usage ranking for a user
        
        Args:
            guild_id: Discord guild ID
            author_id: Discord user ID
            usage: Token usage count to add
        """
        if guild_id not in self.token_ranking:
            self.token_ranking[guild_id] = {}

        if author_id in self.token_ranking[guild_id]:
            self.token_ranking[guild_id][author_id] += usage
        else:
            self.token_ranking[guild_id][author_id] = usage

    def get_token_ranking(self, guild_id: int) -> Dict[int, int]:
        """Get token usage ranking for a guild
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            Dict[int, int]: Ranking dictionary (user_id -> token_count) sorted by usage
        """
        if guild_id not in self.token_ranking or len(self.token_ranking[guild_id]) < 1:
            return {}
        return dict(sorted(self.token_ranking[guild_id].items(), key=lambda x: x[1], reverse=True))

    def get_system_prompt(self, guild_id: int) -> str:
        """Get current system prompt for a guild
        
        Args:
            guild_id: Discord guild ID
            
        Returns:
            str: System prompt text, empty string if not found
        """
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

    def _reconstruct_chat_history(self, messages) -> ChatHistory:
        """Reconstruct chat history from message list
        
        Args:
            messages: List of messages to add
            
        Returns:
            ChatHistory: Reconstructed chat history
        """
        new_chat_history = ChatHistory()
        self._add_messages_to_history(new_chat_history, messages)
        return new_chat_history

    def _add_messages_to_history(self, chat_history: ChatHistory, messages) -> None:
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