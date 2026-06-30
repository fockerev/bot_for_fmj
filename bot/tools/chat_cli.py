from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from modules.agent_service import AgentConfigurationError, AgentExecutionError, FakeAgentService, MicrosoftAgentService
from modules.chat_models import ChatRequest
from modules.chat_service import ChatService
from modules.config import AppConfig, ConfigError
from modules.guild_config import GuildConfigManager
from modules.logging_service import setup_logging
from modules.session_store import SessionStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--guild-id", type=int, required=True)
    parser.add_argument("--user-id", type=int, default=0)
    parser.add_argument("--text", default="")
    parser.add_argument("--image-url", action="append", default=[])
    parser.add_argument("--show-history", action="store_true")
    parser.add_argument("--reset-history", action="store_true")
    parser.add_argument("--fake-agent", action="store_true")
    return parser


async def run(args) -> int:
    config = AppConfig.load(BASE_DIR / "setting.yaml")
    logger = setup_logging(config.logging)
    guild_config_manager = GuildConfigManager(config, BASE_DIR / "data", logger)
    session_store = SessionStore(BASE_DIR / "data" / "sessions", config.bot.history_size, logger)

    if args.reset_history:
        session_store.reset_session(args.guild_id)
        print("history reset")
        return 0

    effective = guild_config_manager.get_effective_config(args.guild_id)
    if args.show_history:
        session = session_store.get_session(args.guild_id, effective.system_prompt)
        for message in session.messages:
            print(f"{message.role}: {message.text_preview(200)}")
        return 0

    if not args.text and not args.image_url:
        print("--text or --image-url is required", file=sys.stderr)
        return 1

    agent_service = FakeAgentService() if args.fake_agent else MicrosoftAgentService()
    chat_service = ChatService(config, guild_config_manager, session_store, agent_service, logger)
    try:
        response = await chat_service.handle_chat(
            ChatRequest(
                guild_id=args.guild_id,
                user_id=args.user_id,
                text=args.text,
                image_urls=args.image_url,
            )
        )
    except (AgentConfigurationError, ConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except AgentExecutionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 3

    print(response.text)
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
