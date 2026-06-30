from bot.cogs.chat import split_discord_message


def test_split_discord_message():
    chunks = split_discord_message("a" * 4000, limit=1900)

    assert len(chunks) == 3
    assert all(len(chunk) <= 1900 for chunk in chunks)
