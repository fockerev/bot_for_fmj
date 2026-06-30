import logging

from bot.modules.chat_models import ChatContentPart, ChatMessage
from bot.modules.session_store import SessionStore


def test_session_store_saves_and_restores(tmp_path):
    store = SessionStore(tmp_path, history_size=2, logger=logging.getLogger(__name__))
    session = store.get_session(1, "system")
    session.messages.append(ChatMessage(role="user", content=[ChatContentPart(type="text", text="hello")]))

    store.save_session(session)
    restored = store.get_session(1, "system")

    assert restored.guild_id == 1
    assert restored.messages[0].content[0].text == "hello"
    assert restored.updated_at.tzinfo is not None


def test_broken_json_is_moved_to_backup(tmp_path):
    path = tmp_path / "guild_1.json"
    path.write_text("{broken", encoding="utf-8")
    store = SessionStore(tmp_path, history_size=2, logger=logging.getLogger(__name__))

    session = store.get_session(1, "system")

    assert session.messages == []
    assert (tmp_path / "guild_1.json.bak").exists()
