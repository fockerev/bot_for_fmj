# Microsoft Agent Framework 最小移行設計書

## 1. 目的

本リポジトリは Discord 上で動作する Python 製チャットボットであり、現状は Semantic Kernel を利用してチャット応答、画像入力、Web 検索、Riot API レビューなどを実装している。

移行時には機能を一度シンプルにし、Microsoft Agent Framework への移行対象を次の3機能に限定する。

1. チャット機能
2. 設定・ログの永続化機能
3. Guild 毎のセッション分離機能

チャット機能にはテキスト入力に加えて画像入力も含める。Riot API レビューは移行後の復旧対象から外す。履歴要約はコンテキスト品質に直結するため、初期移行後の最優先追加機能とする。MCP 連携と Web 検索は、その後に段階的に追加する。

## 2. 初期移行スコープ

### 2.1 含める機能

| 機能 | 内容 |
| --- | --- |
| Discord チャット応答 | Bot が mention されたときにテキストメッセージへ応答する |
| 画像入力 | Discord 添付画像または本文中の画像 URL を Agent へ渡して応答する |
| Guild 毎セッション | Guild ID ごとに会話履歴、設定、Agent session を分離する |
| システムプロンプト | Guild ごとにデフォルトまたはカスタム system prompt を使用する |
| モデル設定 | provider / model / temperature / max tokens を設定から読み込む |
| 設定永続化 | `setting.yaml` と Guild 別 JSON 設定を読み書きする |
| ログ永続化 | アプリケーションログをファイルに出力し、起動・応答・エラーを追跡できるようにする |
| 会話履歴永続化 | Guild ID ごとの会話履歴を JSON で保存・復元する |
| 基本コマンド | 履歴確認、履歴リセット、キャラクター変更、設定確認を残す |

### 2.2 初期移行から外す機能

| 機能 | 初期移行での扱い | 後続方針 |
| --- | --- | --- |
| MCP Web 検索 | 無効化または未搭載 | Agent tool として追加 |
| OpenAI Responses Web Search fallback | 無効化 | MCP 追加後に必要性を再判断 |
| Semantic Kernel plugin | 削除対象 | Microsoft Agent Framework tool に置換 |
| Riot API レビュー | 廃止 | 事後対応でも復旧しない |
| Gemini | 初期は任意。OpenAI のみでも可 | Agent Framework 側の対応に合わせて追加 |
| 履歴要約 | 初期は切り詰めのみ | 初期移行後の最優先で要約 Agent を追加 |
| Discord 設定 UI の複雑な Select / Modal | 最小化 | 必要に応じて戻す |

## 3. 現状整理

### 3.1 現状の主要ファイル

| ファイル | 現状の責務 | 初期移行での扱い |
| --- | --- | --- |
| `bot/main.py` | Discord Bot 起動、Cog 読み込み | 維持 |
| `bot/cogs/gpt.py` | mention 応答、`/search`、周期履歴リセット | チャット Cog として簡素化 |
| `bot/modules/gpt_service.py` | 会話履歴、画像、検索、AI 応答 | チャット専用 service に再構成 |
| `bot/modules/ai_service.py` | Semantic Kernel 経由の OpenAI / Gemini 呼び出し | Agent Framework adapter に置換 |
| `bot/modules/enhanced_history_manager.py` | SK reducer と履歴永続化 | framework 非依存の session store に置換 |
| `bot/modules/guild_config.py` | Guild 別設定 JSON | 維持・簡素化 |
| `bot/modules/config.py` | YAML 設定読み込み | 維持・必要最小限に整理 |
| `bot/modules/commands.py` | Discord コマンドと設定 UI | 最小コマンドのみに整理 |
| `bot/modules/message_parser.py` | mention 除去、返信、画像 URL 抽出 | テキストと画像入力の抽出に絞って維持 |
| `bot/modules/mcp_client.py` | MCP stdio client | 初期移行では未使用として残すか退避 |
| `bot/modules/web_search_plugin.py` | SK plugin | 初期移行では削除対象 |
| `bot/cogs/riot_api.py` | Riot API / AI レビュー | 移行対象外。読み込まない |

### 3.2 現状の Semantic Kernel 依存

初期移行で除去したい依存は次の通り。

- `Kernel`
- `OpenAIChatCompletion`
- `GoogleAIChatCompletion`
- `ChatHistory`
- `ChatHistoryTruncationReducer`
- `ChatHistorySummarizationReducer`
- `ChatMessageContent`
- `TextContent`
- `ImageContent`
- `@kernel_function`
- `FunctionChoiceBehavior`

移行後は、アプリ内部で Semantic Kernel の型を扱わない。

## 4. 移行後の最小アーキテクチャ

```text
Discord Bot
  |
  v
ChatCog
  - mention 受信
  - テキスト / 画像抽出
  - 最小コマンド
  |
  v
ChatService
  - Guild session 取得
  - user message / image input 追加
  - Agent 実行
  - assistant message 保存
  |
  v
AgentService
  - Microsoft Agent Framework 呼び出し
  - model / settings 適用
  |
  v
SessionStore / ConfigStore / Logging
  - Guild 別会話履歴
  - Guild 別設定
  - アプリケーションログ
```

## 5. モジュール設計

### 5.1 新規または置換モジュール

| モジュール | 責務 |
| --- | --- |
| `bot/modules/chat_models.py` | framework 非依存の message / session dataclass |
| `bot/modules/agent_service.py` | Agent 実行 interface と Microsoft Agent Framework 実装 |
| `bot/modules/session_store.py` | Guild 別 session / 履歴の保存・復元 |
| `bot/modules/chat_service.py` | Discord 入力から Agent 応答までのアプリケーション処理 |
| `bot/modules/logging_service.py` | ログ出力の初期化、ファイル出力設定 |

既存ファイルを活かす場合は、`gpt_service.py` を `chat_service.py` 相当に薄くする。ただし Semantic Kernel 移行を明確にするなら、新規 `chat_service.py` を作り、旧 `gpt_service.py` を段階的に外す方が安全。

### 5.2 最小 message model

初期移行ではテキストと画像 URL を扱う。Microsoft Agent Framework 固有の型は使わず、アプリ独自の content part として保持する。

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

Role = Literal["system", "user", "assistant"]
ContentType = Literal["text", "image_url"]

@dataclass
class ChatContentPart:
    type: ContentType
    text: Optional[str] = None
    image_url: Optional[str] = None
    detail: Optional[str] = None

@dataclass
class ChatMessage:
    role: Role
    content: list[ChatContentPart]
    created_at: datetime = field(default_factory=datetime.now)

@dataclass
class GuildSession:
    guild_id: int
    system_prompt: str
    messages: list[ChatMessage] = field(default_factory=list)
```

assistant の応答は通常 `text` part 1件として保存する。画像 URL は Discord CDN URL または本文中の画像 URL を保存し、`detail` には `low` / `high` などの画像解像度設定を入れる。

### 5.3 Agent service interface

```python
from dataclasses import dataclass
from typing import Protocol

@dataclass
class AgentSettings:
    provider: str
    model: str
    temperature: float
    max_tokens: int
    image_detail: str

@dataclass
class AgentResult:
    text: str

class AgentService(Protocol):
    async def generate(
        self,
        messages: list[ChatMessage],
        settings: AgentSettings,
    ) -> AgentResult:
        ...
```

初期移行では tool 呼び出しを interface に含めない。MCP 追加時に `tools` 引数を追加する。

### 5.4 Session store

Guild ID ごとに session を分離して保存する。

保存先例:

```text
bot/data/sessions/
  guild_123456789.json
  guild_987654321.json
```

保存形式例:

```json
{
  "version": 1,
  "guild_id": 123456789,
  "system_prompt": "Briefly reply unless otherwise mentioned.",
  "updated_at": "2026-06-30T12:00:00+09:00",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "この画像を説明して"},
        {"type": "image_url", "image_url": "https://cdn.discordapp.com/attachments/example.png", "detail": "low"}
      ],
      "created_at": "2026-06-30T12:00:00+09:00"
    },
    {
      "role": "assistant",
      "content": [
        {"type": "text", "text": "画像には..."}
      ],
      "created_at": "2026-06-30T12:00:01+09:00"
    }
  ]
}
```

履歴サイズは `setting.yaml` の `bot.history_size` を上限にして、古い user / assistant message から切り詰める。system prompt は履歴に混ぜず、session の属性として保持する。

## 6. 設定・ログ永続化設計

### 6.1 設定ファイル

初期移行では `setting.yaml` を簡素化する。

```yaml
agent:
  provider: "openai"
  model: "gpt-4.1"
  max_tokens: 1600
  temperature: 1.0
  image_detail: "low"

bot:
  history_size: 16
  save_failed_user_message: true
  default_system_prompt: "Briefly reply unless otherwise mentioned. speaking Kansai dialect"

logging:
  level: "INFO"
  file: "logs/bot.log"

mcp:
  enabled: false
  command: "node"
  args: ["/app/mcp-server/dist/index.js"]
  search_result_limit: 3
```

互換性のため、既存の `bot.default_system_promt` は loader で読み取れるようにする。ただし新設定では `default_system_prompt` に寄せる。

現行の `gpt.*` 設定は初期移行時に新しい `agent.*` へ置き換える。ただし移行直後の起動事故を避けるため、loader は当面 `gpt.ai_provider`、`gpt.openai_model`、`gpt.max_token`、`gpt.temperature`、`gpt.image_resolution` を fallback として読む。

### 6.2 Guild 別設定

既存の `bot/data/guild_configs.json` は概念として維持する。

初期移行で保持する項目:

- `guild_id`
- `provider`
- `model`
- `custom_system_prompt`
- `created_at`
- `updated_at`

初期移行では Guild 別 temperature / max tokens は持たせない。必要になったら追加する。

既存の `ai_provider`、`openai_model`、`gemini_model` を持つ `guild_configs.json` は loader で読み込み、新形式の `provider` / `model` へ変換して保存する。初期 provider が `openai` の場合は `openai_model`、`gemini` の場合は `gemini_model` を `model` に採用する。

### 6.3 ログ

ログは標準出力とファイルの両方へ出す。

記録対象:

- Bot 起動 / shutdown
- Cog 読み込み
- Guild session 作成 / 読み込み / 保存
- user message 受信
- 画像入力の件数、URL host、検証失敗
- Agent request 開始 / 完了
- Agent error
- 設定変更

ログには Discord token、API key、全文の長大な prompt、画像 URL の query string は出さない。user message は長さを制限して preview のみ記録する。

## 7. Discord コマンド設計

初期移行で残すコマンド:

| コマンド | 内容 |
| --- | --- |
| `/history` | 現在 Guild の履歴を表示 |
| `/history_reset` | 現在 Guild の履歴を削除 |
| `/chara` | 現在 Guild の system prompt を変更 |
| `/chara_reset` | 現在 Guild の system prompt をデフォルトへ戻す |
| `/config` | 現在 Guild の有効設定を表示 |
| `/config_set_model` | 現在 Guild の model を変更 |
| `/config_reset` | 現在 Guild の設定をデフォルトへ戻す |
| `/help` | コマンド一覧 |

初期移行では複雑な Select / Modal UI は必須にしない。slash command の引数で変更できる形を優先する。

## 8. 初期移行の補足と拡張ポイント

### 8.1 MCP

MCP は初期移行では無効化する。ただし設定と拡張ポイントは残す。

後続で追加する設計:

```python
class AgentTool(Protocol):
    name: str
    description: str

    async def invoke(self, arguments: dict) -> str:
        ...

class MCPWebSearchTool:
    name = "web_search"
    description = "Searches the web and returns relevant results."
```

MCP 追加時の方針:

1. `mcp.enabled: true` の場合だけ tool を登録する。
2. 初期の検索コマンドは `/search` として通常チャットから分離する。
3. 安定後に通常チャットへ tool calling を許可する。

### 8.2 画像入力の扱い

画像入力は初期移行に含める。

対応対象:

- Discord attachment の画像 URL
- メッセージ本文中の直接画像 URL
- 返信先メッセージ本文の参照テキスト

対応形式:

- `png`
- `jpg` / `jpeg`
- `webp`
- `gif`

初期移行では画像ファイルをローカル保存しない。Discord CDN URL または外部画像 URL を Agent に渡し、会話履歴には URL と detail のみ保存する。URL 検証は network に依存させず、Discord attachment の `content_type` と URL 拡張子で判定する。

画像入力の制約:

- `https` のみ許可する。
- `http` URL は自動変換しない。
- 最大画像数は1メッセージあたり4件。
- 重複 URL は1件にまとめる。
- 返信先メッセージの画像添付は初期実装では含めない。
- unsupported attachment が混ざっている場合は request 全体を validation error にする。

### 8.3 Riot API レビュー

Riot API レビューは移行対象外とし、事後対応でも復旧しない。`RiotAPICog` は Docker 起動時に読み込まない構成にする。

### 8.4 履歴要約

履歴要約は初期移行後の最優先追加機能とする。初期移行では単純な件数ベースの切り詰めで動作させ、チャット / 画像入力 / Guild 分離が安定した後に要約を追加する。

要約追加時の方針:

1. Guild session ごとに `summary` フィールドを持つ。
2. 古い会話を削除する前に、要約 Agent で短い要約へ圧縮する。
3. Agent 実行時は `system_prompt`、`summary`、直近履歴の順でコンテキストを組み立てる。
4. 画像入力の要約では画像 URL 自体を長期保持せず、画像から読み取った内容のテキスト要約を残す。
5. 要約失敗時は直近履歴の切り詰めに fallback し、チャット応答を止めない。

## 9. 段階移行計画

### Phase 0: 最小仕様の確定

- 初期移行対象をチャット、画像入力、永続化、Guild 別 session に限定する。
- `RiotAPICog` を廃止対象、`/search` を後続 MCP 対象として明記する。
- Docker 起動時に読み込む Cog を最小化する。

### Phase 1: framework 非依存モデルの追加

- `ChatMessage`
- `ChatContentPart`
- `GuildSession`
- `AgentSettings`
- `AgentResult`
- `SessionStore`

この段階ではまだ既存 Semantic Kernel 実装を残してもよいが、新しいアプリ層には SK 型を出さない。

### Phase 2: Microsoft Agent Framework adapter の追加

- `MicrosoftAgentService` を実装する。
- `ChatService` から `AgentService.generate()` を呼ぶ。
- 通常チャット応答を Microsoft Agent Framework 経由へ切り替える。

### Phase 3: 旧 Semantic Kernel 実装の削除

- `semantic-kernel` 依存を `requirements.txt` から削除する。
- `web_search_plugin.py` を初期構成から外す。
- `enhanced_history_manager.py` を `session_store.py` に置き換える。
- `gpt_service.py` の不要処理を削除または `chat_service.py` に置換する。

### Phase 4: 履歴要約追加

- `GuildSession` に `summary` を追加する。
- `HistorySummarizer` を追加する。
- 履歴上限を超えた場合に古い履歴を要約へ統合する。
- Agent request では summary を直近履歴より前に挿入する。
- 要約処理の失敗時は既存の切り詰めに fallback する。

### Phase 5: MCP 追加

- `MCPClient` を新しい tool interface に接続する。
- `/search` を復活させる。
- 必要に応じて通常チャットへの tool calling を有効化する。

### Phase 6: その他の追加機能

優先順位は次の通り。

1. Gemini など provider 拡張
2. Discord 設定 UI の改善

## 10. リスクと対策

| リスク | 内容 | 対策 |
| --- | --- | --- |
| スコープ肥大化 | 既存機能を一度に戻すと移行が止まりやすい | 初期移行では対象外機能を Cog 読み込みから外す |
| 履歴互換性 | SK reducer 形式の既存履歴を読めない | 初期移行では既存履歴移行を任意にし、必要なら role/content のみ移行 |
| 要約品質 | 要約が薄いと長期文脈が失われる | 要約専用 prompt を分け、重要なユーザー設定・継続中の話題・未完了タスクを優先保存する |
| 画像入力互換性 | Agent Framework の画像入力形式が provider ごとに異なる | `AgentService` 内で content part を provider 別形式へ変換する |
| Guild 設定不整合 | Guild 別 model / system prompt が session とずれる | response 前に毎回 effective config から system prompt を解決する |
| ログ肥大化 | 会話全文を保存しすぎる | アプリログは preview のみ、会話履歴は session JSON に分離 |
| Agent Framework 差分 | provider や tool 対応が想定と異なる | AgentService interface に閉じ込め、アプリ層へ漏らさない |
| Discord timeout | 応答生成に時間がかかる | slash command は `defer()`、mention 応答は typing indicator を検討 |

## 11. 受け入れ条件

初期移行完了の条件:

- Docker で Bot が起動する。
- `semantic-kernel` なしで通常チャットと画像入力が動作する。
- mention されたテキストに Microsoft Agent Framework 経由で応答できる。
- mention された画像付きメッセージに Microsoft Agent Framework 経由で応答できる。
- Guild A と Guild B の履歴が混ざらない。
- Guild 別 system prompt が反映される。
- 会話履歴が `bot/data/sessions/guild_<id>.json` に保存される。
- Bot 再起動後に Guild 別履歴を復元できる。
- 設定変更が `bot/data/guild_configs.json` に保存される。
- ログが標準出力とファイルに出力される。
- `/history`、`/history_reset`、`/chara`、`/chara_reset`、`/config` が動作する。
- `/search` は初期移行では未対応であることが明確に返される、またはコマンドとして登録されない。
- Riot API レビュー関連コマンドは登録されない。

## 12. 推奨される初回実装スコープ

最初の実装では、既存機能の整理を優先する。

実装対象:

- `bot/modules/chat_models.py`
- `bot/modules/session_store.py`
- `bot/modules/agent_service.py`
- `bot/modules/chat_service.py`
- `bot/cogs/chat.py` または既存 `gpt.py` の簡素化
- 画像添付 / 画像 URL を扱う `MessageParser` の最小化
- `setting.yaml` の最小構成への更新
- `requirements.txt` から不要依存を削除
- Docker 起動時に読み込む Cog をチャット系のみに制限

実装しないもの:

- MCP
- Web 検索
- Riot API レビュー
- 複雑な Discord 設定 UI
- 履歴要約

このスコープで Microsoft Agent Framework への移行を完了させ、その後に履歴要約を追加し、さらに後続で MCP を Agent tool として追加する。

## 13. 実装前の確定事項

`docs/microsoft_agent_framework_migration_missing_info.md` の確認結果として、初期実装では以下を採用する。

### 13.1 未確定として残す事項

Microsoft Agent Framework の Python API は実装直前に公式ドキュメントで確認する。特に以下は adapter 実装時に確定する。

- Python パッケージ名とバージョン
- Agent / client の作成方法
- OpenAI 接続方法
- system instruction の渡し方
- text / image URL の message 形式
- `max_tokens` / `temperature` の指定方法

これらは `AgentService` 内に閉じ込め、`ChatService`、`SessionStore`、`MessageParser` には漏らさない。

### 13.2 環境変数

Discord Bot 起動時の必須環境変数:

- `DISCORD_BOT_TOKEN`
- `OPENAI_API_KEY`
- `GUILD_ID`

任意環境変数:

- `BOT_PREFIX`: 未設定時は `/`

CLI の fake agent 実行では API key を不要とする。real agent 実行では `OPENAI_API_KEY` を必須とする。

### 13.3 Cog 読み込み

`bot/main.py` は `cogs/*.py` の全読み込みをやめ、allowlist 方式で `cogs.chat` のみ読み込む。`riot_api.py` は初期移行・事後対応とも読み込まない。

### 13.4 Agent error 時の履歴保存

`bot.save_failed_user_message` を追加し、初期値は `true` とする。Agent 実行に失敗しても user message は保存し、assistant fallback message は保存しない。

### 13.5 Discord 返信長

Discord の message 上限を超える応答は 1900 文字程度で分割送信する。切り詰めは行わない。

### 13.6 SessionStore

- timestamp は timezone aware ISO 文字列で保存する。
- timezone は実行環境の local timezone ではなく UTC に統一する。
- `history_size` は user / assistant を含む message 件数とする。
- 切り詰め時は可能な範囲で user / assistant のペアを維持する。
- 破損 JSON は `.bak` に退避して新規 session に fallback する。
- 既存 Semantic Kernel 履歴は初期移行では移行しない。

### 13.7 Logging

既存 `logging_config.json` ではなく、新しい `logging_service.py` を正とする。ログファイル directory は自動作成する。message preview は最大120文字、画像 URL は query string を除いた host + path までを記録する。

### 13.8 CLI / Test

`pytest` と `pytest-asyncio` を開発・テスト用依存に追加する。smoke test は `pytest.ini` の marker で通常テストから分離する。`chat_cli --fake-agent` は固定文言に加えて入力件数を含む応答にし、テストで検証しやすくする。
