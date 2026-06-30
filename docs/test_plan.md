# テスト計画

## 1. 目的

Discord 上で毎回レスポンスを確認する運用は手間が大きく、原因の切り分けもしづらい。移行後は Discord を薄い入出力 adapter として扱い、主要な振る舞いをローカルで検証できる構造にする。

本テスト計画では、Microsoft Agent Framework 移行後のチャット機能、画像入力、設定・ログ永続化、Guild 毎セッション分離を、Discord 実機確認に依存せず検証する方針を定義する。

## 2. テスト方針

### 2.1 基本方針

- `ChatService` は Discord の型に依存させない。
- `AgentService` は interface 化し、unit test では fake 実装を使う。
- Discord Cog は入力変換と出力送信だけを担当させる。
- 本物の Microsoft Agent Framework 呼び出しは smoke test として分離する。
- Discord 実機確認は最後の E2E 確認だけに限定する。

### 2.2 テストピラミッド

```text
Discord E2E
  - 最小限の手動確認

CLI Smoke Test
  - 本物 AgentService をローカルから実行

Service Test
  - Fake AgentService で ChatService を検証

Unit Test
  - MessageParser / SessionStore / Config / GuildConfig
```

## 3. テストしやすい設計ルール

### 3.1 ChatService 入力モデル

Discord message を直接渡さず、アプリ独自の入力モデルに変換してから `ChatService` に渡す。

```python
@dataclass
class ChatRequest:
    guild_id: int
    user_id: int
    text: str
    image_urls: list[str]
    reference_text: str | None = None
```

期待する効果:

- Discord を起動せずに同じ処理を `pytest` / CLI から呼べる。
- mention 除去、画像抽出、返信参照の問題と Agent 応答生成の問題を分離できる。
- Guild ID をテストで自由に指定できる。

### 3.2 Fake AgentService

unit / service test では本物の LLM を呼ばない。

```python
class FakeAgentService:
    def __init__(self):
        self.requests = []

    async def generate(self, messages, settings):
        self.requests.append((messages, settings))
        return AgentResult(text=f"fake response: messages={len(messages)}")
```

確認すること:

- system prompt が含まれている。
- user message が正しい content part で渡る。
- 画像 URL が `image_url` part として渡る。
- Guild ごとの履歴が混ざらない。
- Agent settings に model / temperature / max_tokens / image_detail が反映される。

### 3.3 ローカル CLI

手動確認用に Discord を介さず `ChatService` を叩く CLI を用意する。

想定コマンド:

```bash
python -m bot.tools.chat_cli --guild-id 123 --text "こんにちは"
python -m bot.tools.chat_cli --guild-id 123 --text "この画像を説明して" --image-url https://example.com/a.png
python -m bot.tools.chat_cli --guild-id 456 --text "別Guildの会話"
```

CLI で確認すること:

- 本物 AgentService の疎通。
- session JSON の保存。
- Guild ID ごとの履歴分離。
- 画像 URL 入力の変換。
- ログ出力。

## 4. テスト対象と観点

### 4.1 Unit Test

| 対象 | 観点 |
| --- | --- |
| `MessageParser` | mention 除去、本文抽出、返信参照、添付画像 URL、本文中画像 URL、未対応拡張子 |
| `SessionStore` | Guild 別保存、復元、履歴上限、破損 JSON fallback、存在しない session の初期化 |
| `GuildConfigManager` | デフォルト設定、Guild 別 model、custom system prompt、reset |
| `Config` | `setting.yaml` 読み込み、旧 `default_system_promt` 互換、必須項目不足時の error |
| `ChatModels` | JSON serialize / deserialize、画像 part、日時変換 |

### 4.2 Service Test

| 対象 | 観点 |
| --- | --- |
| `ChatService` | user message 保存、assistant response 保存、Agent 呼び出し順序 |
| `ChatService` | system prompt と履歴の組み立て |
| `ChatService` | Guild A / Guild B の session 分離 |
| `ChatService` | 画像付き message の content part 化 |
| `ChatService` | Agent error 時のユーザー向けエラーメッセージ |
| `ChatService` | 履歴上限超過時の切り詰め |

### 4.3 CLI Smoke Test

| 対象 | 観点 |
| --- | --- |
| `chat_cli` + real AgentService | テキスト応答が返る |
| `chat_cli` + real AgentService | 画像 URL 付き応答が返る |
| `chat_cli` + real AgentService | session JSON が保存される |
| `chat_cli` + real AgentService | ログファイルに request / response 概要が出る |

### 4.4 Discord E2E

Discord 上で確認する内容は最小限にする。

| ケース | 観点 |
| --- | --- |
| mention text | Bot が返信する |
| mention image | Bot が画像について返信する |
| `/history` | 現在 Guild の履歴が見える |
| `/history_reset` | 履歴が消える |
| `/chara` / `/chara_reset` | system prompt が変わる |
| 別 Guild | 履歴と設定が混ざらない |

## 5. 推奨テストファイル構成

```text
tests/
  unit/
    test_message_parser.py
    test_session_store.py
    test_guild_config.py
    test_config.py
    test_chat_models.py
  service/
    test_chat_service.py
  smoke/
    test_chat_cli_contract.py
bot/
  tools/
    chat_cli.py
```

`smoke` は外部 API を呼ぶ可能性があるため、通常の `pytest` からは除外できるよう marker を付ける。

```python
@pytest.mark.smoke
@pytest.mark.requires_api_key
async def test_real_agent_text_response():
    ...
```

`pytest.ini` に marker を定義し、通常実行では smoke を除外する。

```ini
[pytest]
markers =
    smoke: calls real external services
    requires_api_key: requires API key environment variables
asyncio_mode = auto
```

## 6. テストデータ方針

### 6.1 一時ディレクトリ

`SessionStore` や Guild 設定のテストでは、必ず `tmp_path` を使う。

確認すること:

- 実際の `bot/data/*.json` を壊さない。
- テストごとに独立した保存先を使う。
- 破損 JSON も fixture として作れる。

### 6.2 画像 URL

unit / service test では実際に画像を download しない。

使用例:

```text
https://cdn.discordapp.com/attachments/1/2/sample.png
https://example.com/image.webp
```

URL 検証のテストは、network に依存しないように検証関数を分離し、必要なら mock を使う。

## 7. テストケース詳細

### 7.1 MessageParser

- mention を除去できる。
- 空白だけの本文を空文字として扱える。
- reply message を `reference_text` として抽出できる。
- Discord attachment の画像 URL を抽出できる。
- 本文中の画像 URL を抽出できる。
- `png` / `jpg` / `jpeg` / `webp` / `gif` を許可する。
- `pdf` / `zip` / 通常ページ URL を拒否する。
- URL 抽出後、本文から画像 URL を除去する。

### 7.2 SessionStore

- 新規 Guild の session を初期化できる。
- session を JSON 保存できる。
- 保存済み session を復元できる。
- Guild A と Guild B を別ファイルに保存する。
- 履歴数が上限を超えたら古い user / assistant message を切り詰める。
- system prompt は通常履歴に混ぜず session 属性として保持する。
- 破損 JSON を読んだ場合は warning log を出して新規 session に fallback する。

### 7.3 ChatService

- テキスト request で user message と assistant message が保存される。
- 画像 request で `text` part と `image_url` part が AgentService に渡る。
- reference text が user message に含まれる。
- Guild 別 custom system prompt が使われる。
- AgentService が例外を投げた場合、履歴を壊さずエラー文を返す。
- AgentService の response が空の場合、fallback message を返す。
- 履歴上限に達した後も最新の会話が残る。

### 7.4 GuildConfig

- default config から effective config を作れる。
- Guild 別 model を保存できる。
- custom system prompt を保存できる。
- reset で default に戻せる。
- 既存 `guild_configs.json` 形式を読み込める。

### 7.5 CLI

- `--guild-id` と `--text` だけで応答を生成できる。
- `--image-url` を複数指定できる。
- `--reset-history` で対象 Guild の履歴を消せる。
- `--show-history` で対象 Guild の履歴を表示できる。
- `--fake-agent` を指定すると API key なしで動く。
- `--fake-agent` の応答には message 件数など検証しやすい情報を含める。

## 8. CI 方針

初期は以下を CI 対象にする。

```bash
pytest tests/unit tests/service -m "not smoke"
```

外部 API が必要な smoke test は CI の通常実行から外す。

```bash
pytest -m smoke
```

CI で確認すること:

- `semantic-kernel` を import しなくても unit / service test が通る。
- 実データではなく temporary data dir を使っている。
- network がなくても unit / service test が通る。

## 9. 手動確認手順

### 9.1 ローカル fake 確認

```bash
python -m bot.tools.chat_cli --guild-id 100 --text "こんにちは" --fake-agent
python -m bot.tools.chat_cli --guild-id 100 --text "この画像を説明して" --image-url https://example.com/a.png --fake-agent
python -m bot.tools.chat_cli --guild-id 100 --show-history
```

### 9.2 ローカル real Agent 確認

```bash
python -m bot.tools.chat_cli --guild-id 100 --text "こんにちは"
python -m bot.tools.chat_cli --guild-id 100 --text "この画像を説明して" --image-url https://example.com/a.png
```

### 9.3 Discord 最終確認

- Bot を起動する。
- テキスト mention で応答を見る。
- 画像添付 mention で応答を見る。
- `/history` で履歴を見る。
- `/history_reset` で履歴を消す。
- 別 Guild で履歴が混ざらないことを確認する。

## 10. 受け入れ条件

- Discord を起動しなくても unit / service test で主要ロジックを検証できる。
- API key がなくても fake AgentService で service test が通る。
- CLI から text / image の smoke test を実行できる。
- Discord 実機確認は最小ケースだけで済む。
- session / guild config のテストは実データを変更しない。
- network なしで unit / service test が通る。
- 失敗時に MessageParser / SessionStore / AgentService / Discord adapter のどこで失敗したか切り分けられる。
