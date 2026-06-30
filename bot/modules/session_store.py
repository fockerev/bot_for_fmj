from __future__ import annotations

import json
import logging
from pathlib import Path

from .chat_models import GuildSession, utc_now


class SessionStoreError(Exception):
    pass


class SessionStore:
    def __init__(self, base_dir: Path | str, history_size: int, logger: logging.Logger):
        self.base_dir = Path(base_dir)
        self.history_size = history_size
        self.logger = logger
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def session_path(self, guild_id: int) -> Path:
        return self.base_dir / f"guild_{guild_id}.json"

    def get_session(self, guild_id: int, system_prompt: str) -> GuildSession:
        path = self.session_path(guild_id)
        if path.exists():
            session = self._load_session(path, guild_id, system_prompt)
        else:
            session = GuildSession(guild_id=guild_id, system_prompt=system_prompt)
            self.logger.info("Created new session for guild %s", guild_id)

        if session.system_prompt != system_prompt:
            session.system_prompt = system_prompt
            session.updated_at = utc_now()
        return session

    def _load_session(self, path: Path, guild_id: int, system_prompt: str) -> GuildSession:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            session = GuildSession.from_dict(data)
            self.logger.info("Loaded session for guild %s", guild_id)
            return session
        except Exception as exc:
            backup = path.with_suffix(path.suffix + ".bak")
            try:
                path.replace(backup)
                self.logger.warning("Moved broken session for guild %s to %s: %s", guild_id, backup, exc)
            except OSError as backup_exc:
                self.logger.warning("Failed to backup broken session for guild %s: %s", guild_id, backup_exc)
            return GuildSession(guild_id=guild_id, system_prompt=system_prompt)

    def save_session(self, session: GuildSession) -> None:
        session.updated_at = utc_now()
        self.trim_messages(session)
        path = self.session_path(session.guild_id)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
            tmp_path.replace(path)
            self.logger.info("Saved session for guild %s", session.guild_id)
        except OSError as exc:
            raise SessionStoreError(f"failed to save session for guild {session.guild_id}") from exc

    def reset_session(self, guild_id: int) -> bool:
        path = self.session_path(guild_id)
        if path.exists():
            path.unlink()
            self.logger.info("Reset session for guild %s", guild_id)
        return True

    def trim_messages(self, session: GuildSession) -> GuildSession:
        if self.history_size <= 0:
            session.messages = []
            return session
        if len(session.messages) <= self.history_size:
            return session

        trimmed = session.messages[-self.history_size :]
        if trimmed and trimmed[0].role == "assistant" and len(trimmed) > 1:
            trimmed = trimmed[1:]
        session.messages = trimmed
        return session

    def refresh_system_prompt(self, guild_id: int, system_prompt: str) -> None:
        path = self.session_path(guild_id)
        if not path.exists():
            return
        session = self.get_session(guild_id, system_prompt)
        session.system_prompt = system_prompt
        self.save_session(session)
