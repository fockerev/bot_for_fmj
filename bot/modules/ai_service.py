import logging
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

# Add current directory to sys.path for absolute imports
sys.path.append(str(Path(__file__).parent))

from config import AppConfig

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.google.google_ai.google_ai_prompt_execution_settings import GoogleAIChatPromptExecutionSettings
from semantic_kernel.connectors.ai.google.google_ai.services.google_ai_chat_completion import GoogleAIChatCompletion
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion, OpenAIChatPromptExecutionSettings
from semantic_kernel.contents import ChatHistory
from semantic_kernel.functions import KernelArguments


class AIServiceInterface(ABC):
    """AI service interface"""

    @abstractmethod
    async def get_chat_response(self, chat_history: ChatHistory, settings: dict) -> str:
        """Get chat response from AI service"""
        pass

    @abstractmethod
    def get_chat_completion_service(self):
        """Get the underlying chat completion service (for ChatHistorySummarizationReducer)"""
        pass


class OpenAIService(AIServiceInterface):
    """OpenAI service implementation using Semantic Kernel"""

    def __init__(self, config: AppConfig, shared_kernel: Optional[Kernel] = None):
        self.logger = logging.getLogger("openai_service")

        # Use shared kernel if provided, otherwise create new one
        self.kernel = shared_kernel if shared_kernel is not None else Kernel()

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        self.service_id = "openai_chat"

        # Only add service if it doesn't already exist in the kernel
        try:
            self.chat_completion_service = self.kernel.get_service(service_id=self.service_id)
            self.logger.info("Using existing OpenAI service from shared kernel")
        except Exception:
            self.kernel.add_service(OpenAIChatCompletion(
                service_id=self.service_id,
                api_key=api_key,
                ai_model_id=config.gpt.openai_model
            ))
            self.chat_completion_service = self.kernel.get_service(service_id=self.service_id)
            self.logger.info("Added new OpenAI service to kernel")

    def get_chat_completion_service(self):
        """Get the underlying OpenAI chat completion service"""
        return self.chat_completion_service

    async def get_chat_response(self, chat_history: ChatHistory, settings: dict) -> str:
        """Get chat response from OpenAI"""
        execution_settings = OpenAIChatPromptExecutionSettings(
            max_tokens=settings.get("max_tokens", 1600),
            temperature=settings.get("temperature", 0.7)
        )

        response = await self.chat_completion_service.get_chat_message_contents(
            chat_history=chat_history,
            settings=execution_settings,
            kernel=self.kernel,
            arguments=KernelArguments()
        )

        return str(response[0].content)


class GeminiService(AIServiceInterface):
    """Gemini service implementation using Semantic Kernel"""

    def __init__(self, config: AppConfig, shared_kernel: Optional[Kernel] = None):
        self.logger = logging.getLogger("gemini_service")

        # Use shared kernel if provided, otherwise create new one
        self.kernel = shared_kernel if shared_kernel is not None else Kernel()

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")

        self.service_id = "gemini_chat"

        # Only add service if it doesn't already exist in the kernel
        try:
            self.chat_completion_service = self.kernel.get_service(service_id=self.service_id)
            self.logger.info("Using existing Gemini service from shared kernel")
        except Exception:
            self.kernel.add_service(GoogleAIChatCompletion(
                service_id=self.service_id,
                api_key=api_key,
                gemini_model_id=config.gpt.gemini_model
            ))
            self.chat_completion_service = self.kernel.get_service(service_id=self.service_id)
            self.logger.info("Added new Gemini service to kernel")

    def get_chat_completion_service(self):
        """Get the underlying Gemini chat completion service"""
        return self.chat_completion_service

    async def get_chat_response(self, chat_history: ChatHistory, settings: dict) -> str:
        """Get chat response from Gemini"""
        try:
            execution_settings = GoogleAIChatPromptExecutionSettings(
                max_tokens=settings.get("max_tokens", 1600),
                temperature=settings.get("temperature", 0.7)
            )

            response = await self.chat_completion_service.get_chat_message_contents(
                chat_history=chat_history,
                settings=execution_settings,
                kernel=self.kernel,
                arguments=KernelArguments()
            )

            return str(response[0].content)
        except Exception as e:
            if "quota" in str(e).lower() or "rate" in str(e).lower():
                self.logger.warning(f"Gemini API quota/rate limit reached: {e}")
                return "申し訳ございませんが、Gemini APIの制限に達しました。しばらく待ってから再試行してください。"
            else:
                self.logger.error(f"Gemini API error: {e}")
                raise e


class AIServiceFactory:
    """Factory class for creating AI services with optional shared kernel"""

    _shared_kernel: Optional[Kernel] = None

    @classmethod
    def get_shared_kernel(cls) -> Kernel:
        """Get or create shared kernel instance"""
        if cls._shared_kernel is None:
            cls._shared_kernel = Kernel()
            logging.getLogger("ai_service_factory").info("Created new shared Kernel instance")
        return cls._shared_kernel

    @classmethod
    def reset_shared_kernel(cls):
        """Reset shared kernel (useful for testing or reconfiguration)"""
        cls._shared_kernel = None
        logging.getLogger("ai_service_factory").info("Reset shared Kernel instance")

    @staticmethod
    def create_service(config: AppConfig, use_shared_kernel: bool = True) -> Optional[AIServiceInterface]:
        """
        Create AI service based on configuration

        Args:
            config: Application configuration
            use_shared_kernel: If True, use shared kernel across services (recommended)

        Returns:
            AIServiceInterface implementation or None on error
        """
        logger = logging.getLogger("ai_service_factory")

        try:
            # Get provider value for comparison
            provider_value = config.gpt.ai_provider.value if hasattr(config.gpt.ai_provider, "value") else str(config.gpt.ai_provider)

            # Get shared kernel if requested
            kernel = AIServiceFactory.get_shared_kernel() if use_shared_kernel else None

            if provider_value == "openai":
                logger.info(f"Creating OpenAI service (shared_kernel={use_shared_kernel})")
                return OpenAIService(config, shared_kernel=kernel)
            elif provider_value == "gemini":
                logger.info(f"Creating Gemini service (shared_kernel={use_shared_kernel})")
                return GeminiService(config, shared_kernel=kernel)
            else:
                logger.error(f"Unknown AI provider: {provider_value}")
                return None
        except ValueError as e:
            logger.error(f"Failed to create AI service: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error creating AI service: {e}")
            return None
