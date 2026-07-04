# モジュール詳細設計書

## 1. 対象モジュール

```text
bot/
  main.py
  cogs/
    chat.py
  modules/
    agent_service.py
    chat_models.py
    chat_service.py
    config.py
    guild_config.py
    logging_service.py
    message_parser.py
    session_store.py
  tools/
    chat_cli.py
```

## 2. `bot/main.py`

### 責務

- アプリ設定の読み込み。
- ログ初期化。
- 必須環境変数の検証。
- Discord Bot の生成、Cog ロード、Guild command sync、起動。

### 主要定数

| 名前 | 内容 |
| --- | --- |
| `BASE_DIR` | `bot/` ディレクトリの絶対パス |

### `DiscordBot`

`commands.Bot` を継承する Bot 本体。

| 属性 | 説明 |
| --- | --- |
| `app_config` | `AppConfig` インスタンス |
| `app_logger` | `setup_logging()` が返す logger |
| `guild_ids` | command sync 対象 Guild ID list |

#### `__init__(app_config, app_logger, guild_ids, command_prefix)`

Discord intents は `discord.Intents.all()` を使用する。`help_command` は無効化する。

#### `setup_hook()`

処理順序:

1. `cogs.chat` を extension としてロードする。
2. 各 Guild ID に global command をコピーする。
3. Guild 単位で application command を同期する。
4. 完了ログを出力する。

#### `on_ready()`

ログインユーザーをログ出力し、presence を `discord.Game(f"{self.command_prefix}help")` に設定する。

### `load_environment()`

| 入力 | 出力 |
| --- | --- |
| process environment | `(token, guild_ids, prefix)` |

検証:

- `DISCORD_BOT_TOKEN` が空なら `RuntimeError`。
- `OPENAI_API_KEY` が空なら `RuntimeError`。
- `GUILD_ID` が空、またはカンマ区切り後に有効値がなければ `RuntimeError`。
- `BOT_PREFIX` が空なら `/` を使う。

### `main()`

処理順序:

1. `AppConfig.load(BASE_DIR / "setting.yaml")`。
2. `setup_logging(config.logging)`。
3. `load_environment()`。
4. `DiscordBot` 生成。
5. `bot.run(token)`。

## 3. `bot/cogs/chat.py`

### 責務

- Discord message / command の adapter。
- Discord 固有オブジェクトをアプリ内 DTO へ変換する。
- ChatService の結果を Discord へ送信する。

### `split_discord_message(text, limit=1900)`

Discord 送信用に文字列を分割する。

処理:

1. 空文字なら `[""]`。
2. `limit` を超える間、直近の改行位置で分割する。
3. 改行がなければ `limit` 位置で分割する。
4. 残り文字列の先頭空白を削除して継続する。

### `ChatCog.__init__(bot)`

生成する依存:

| 依存 | 生成内容 |
| --- | --- |
| `GuildConfigManager` | `BASE_DIR / "data"` を使用 |
| `SessionStore` | `BASE_DIR / "data" / "sessions"` と `history_size` を使用 |
| `MicrosoftAgentService` | 実 Agent 実装 |
| `ChatService` | アプリケーションサービス |
| `MessageParser` | Discord message parser |

### `on_message(message)`

処理順序:

1. Bot 自身の message を無視する。
2. DM を無視する。
3. Bot メンションがなければ `bot.process_commands(message)` のみ行う。
4. typing 表示中に `MessageParser.parse_discord_message()` を実行する。
5. `ChatRequest` を作成する。
6. `ChatService.handle_chat()` を実行する。
7. `split_discord_message()` で分割して `message.channel.send()` する。

エラー:

- `MessageValidationError` は例外 message をそのまま Discord へ返す。
- その他例外は stack trace をログ出力し、汎用エラー文を返す。

### hybrid commands

| コマンド | 入力 | 処理 |
| --- | --- | --- |
| `history` | `ctx.guild.id` | session の直近 10 件を `role: preview` 形式で表示 |
| `history_reset` | `ctx.guild.id` | `SessionStore.reset_session()` |
| `chara` | `text` | `custom_system_prompt` を保存し、session の system prompt を更新 |
| `chara_reset` | なし | `custom_system_prompt` を削除し、既定 prompt へ更新 |
| `config` | なし | 実効設定を text 表示 |
| `config_set_model` | `provider`, `model` | `openai` のみ許可して Guild 設定へ保存 |
| `config_reset` | なし | Guild 固有設定を削除し、session の system prompt を更新 |
| `help_bot` | なし | command list を表示 |

## 4. `bot/modules/chat_models.py`

### 責務

- Discord SDK や Agent Framework に依存しないアプリ内データモデルを定義する。
- JSON 永続化用の変換処理を提供する。
- datetime を timezone 付きとして扱う。

### 関数

#### `utc_now()`

timezone UTC 付きの現在時刻を返す。

#### `parse_datetime(value)`

| 入力 | 出力 |
| --- | --- |
| <code>str &#124; datetime &#124; None</code> | timezone 付き `datetime` |

仕様:

- `datetime` が timezone なしなら UTC を付与する。
- ISO 8601 文字列を parse する。
- `None` は `utc_now()`。

### `ChatContentPart`

| 項目 | 型 | 説明 |
| --- | --- | --- |
| `type` | <code>"text" &#124; "image_url"</code> | content 種別 |
| `text` | <code>str &#124; None</code> | text part の本文 |
| `image_url` | <code>str &#124; None</code> | image_url part の URL |
| `detail` | <code>str &#124; None</code> | 画像 detail |

制約:

- `type == "text"` の場合、`text` は必須。
- `type == "image_url"` の場合、`image_url` は必須。

### `ChatMessage`

| 項目 | 型 | 説明 |
| --- | --- | --- |
| `role` | <code>"system" &#124; "user" &#124; "assistant"</code> | 発話 role |
| `content` | `list[ChatContentPart]` | content part list |
| `created_at` | `datetime` | 作成日時 |

`text_preview(limit)` は text part のみを空白正規化して返す。長い場合は `limit` で切る。

### `GuildSession`

| 項目 | 型 | 説明 |
| --- | --- | --- |
| `guild_id` | `int` | Discord Guild ID |
| `system_prompt` | `str` | 有効 system prompt |
| `messages` | `list[ChatMessage]` | user / assistant 履歴 |
| `updated_at` | `datetime` | 更新日時 |

`to_dict()` は `version: 1` を含む JSON 形式へ変換する。

### `ChatRequest`

Discord 入力から ChatService へ渡す DTO。

| 項目 | 型 |
| --- | --- |
| `guild_id` | `int` |
| `user_id` | `int` |
| `text` | `str` |
| `image_urls` | `list[str]` |
| `reference_text` | <code>str &#124; None</code> |

### `ChatResponse`

ChatService から Discord adapter へ返す DTO。

| 項目 | 型 |
| --- | --- |
| `text` | `str` |
| `guild_id` | `int` |
| `message_count` | `int` |

## 5. `bot/modules/config.py`

### 責務

- YAML 設定を dataclass へ変換する。
- 現行 `agent` / `bot` 設定と legacy `gpt` 設定の互換読み込みを行う。

### dataclass

| クラス | 項目 |
| --- | --- |
| `AgentConfig` | `provider`, `model`, `max_tokens`, `temperature`, `image_detail` |
| `BotConfig` | `history_size`, `save_failed_user_message`, `default_system_prompt` |
| `LoggingConfig` | `level`, `file` |
| `MCPServerConfig` | `name`, `transport`, `command`, `args`, `url`, `env`, `headers`, `allowed_tools`, `approval_mode`, `request_timeout` |
| `MCPConfig` | `enabled`, `servers`, `search_result_limit` |
| `AppConfig` | `agent`, `bot`, `logging`, `mcp` |

### `AppConfig.load(path)`

処理順序:

1. YAML ファイル存在確認。
2. `yaml.safe_load()`。
3. `_agent_data()` で agent 設定を作る。
4. `_bot_data()` で bot 設定を作る。
5. `_require()` で必須項目を検証する。
6. 型変換して `AppConfig` を返す。

エラー:

- ファイルなしは `FileNotFoundError`。
- YAML parse error は `ConfigError`。
- 必須 key 不足は `ConfigError`。
- 型変換失敗は `ConfigError`。

### legacy 互換

| legacy | 現行 |
| --- | --- |
| `gpt.ai_provider` | `agent.provider` |
| `gpt.openai_model` / `gpt.gemini_model` | `agent.model` |
| `gpt.max_token` | `agent.max_tokens` |
| `gpt.temperature` | `agent.temperature` |
| `gpt.image_resolution == 1` | `agent.image_detail == "high"` |
| `bot.default_system_promt` | `bot.default_system_prompt` |

## 6. `bot/modules/guild_config.py`

### 責務

- Guild 固有設定を JSON で管理する。
- Guild 固有設定と既定設定を合成した実効設定を返す。
- legacy Guild 設定を正規化する。

### 永続化

保存先は `data_dir / "guild_configs.json"`。JSON は Guild ID 文字列を key とし、値に `GuildSpecificConfig` を保存する。

### `GuildSpecificConfig`

| 項目 | 説明 |
| --- | --- |
| `guild_id` | Discord Guild ID |
| `provider` | Guild 固有 provider。未指定なら既定値 |
| `model` | Guild 固有 model。未指定なら既定値 |
| `custom_system_prompt` | Guild 固有 system prompt |
| `created_at` | 作成日時 |
| `updated_at` | 更新日時 |

### `EffectiveGuildConfig`

| 項目 | 説明 |
| --- | --- |
| `provider`, `model` | Guild 固有値があれば優先 |
| `custom_system_prompt` | Guild 固有 prompt |
| `system_prompt` | custom prompt または default system prompt |
| `max_tokens`, `temperature`, `image_detail`, `history_size` | 既定設定から取得 |

### `GuildConfigManager`

#### `__init__(default_config, data_dir, logger)`

`data_dir` を作成し、`guild_configs.json` を読み込む。

#### `_load_guild_configs()`

読み込み成功時、legacy 正規化後の設定を memory map へ格納する。正規化後の形式で再保存する。読み込み失敗時はログ出力し、空設定として扱う。

#### `_save_guild_configs()`

memory map を JSON へ保存する。

#### `get_effective_config(guild_id)`

Guild 固有値が存在する場合は `provider`, `model`, `custom_system_prompt` に反映する。その他は `AppConfig` の既定値を使用する。

#### `update_guild_config(guild_id, **kwargs)`

更新可能 key は `provider`, `model`, `custom_system_prompt`。すべて空になった場合は Guild 固有設定を削除する。成功時 `True`、失敗時 `False`。

#### `reset_guild_config(guild_id)`

Guild 固有設定を削除して保存する。

## 7. `bot/modules/session_store.py`

### 責務

- Guild ごとの会話 session を JSON へ保存・復元する。
- 履歴数上限を適用する。
- 壊れた JSON を退避する。

### `SessionStore.__init__(base_dir, history_size, logger)`

`base_dir` を作成し、履歴上限と logger を保持する。

### `session_path(guild_id)`

`base_dir / f"guild_{guild_id}.json"` を返す。

### `get_session(guild_id, system_prompt)`

処理:

1. session file があれば `_load_session()`。
2. なければ新規 `GuildSession`。
3. 保存済み `system_prompt` が実効 prompt と異なる場合は更新する。
4. session を返す。

### `_load_session(path, guild_id, system_prompt)`

JSON を読み込み `GuildSession.from_dict()` で復元する。失敗した場合は元ファイルを `.bak` へ移動し、新規 session を返す。

### `save_session(session)`

処理:

1. `updated_at` を現在時刻に更新する。
2. `trim_messages()` を実行する。
3. `.tmp` ファイルへ JSON を書き込む。
4. `.tmp` を本ファイルへ atomic replace する。

`OSError` は `SessionStoreError` として送出する。

### `reset_session(guild_id)`

session file が存在すれば削除する。戻り値は常に `True`。

### `trim_messages(session)`

仕様:

- `history_size <= 0` なら履歴を空にする。
- message 数が上限以下なら変更しない。
- 上限超過時は末尾 `history_size` 件を残す。
- 残した先頭が `assistant` で、かつ 2 件以上ある場合は先頭を削除する。

### `refresh_system_prompt(guild_id, system_prompt)`

session file が存在する場合のみ読み込み、`system_prompt` を更新して保存する。

## 8. `bot/modules/message_parser.py`

### 責務

- Discord message から Bot mention を除去する。
- 添付画像と本文中画像 URL を抽出する。
- 返信先本文を取得する。
- 入力 validation を行う。

### 制約

| 項目 | 値 |
| --- | --- |
| 対応拡張子 | `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif` |
| URL scheme | `https` のみ |
| 最大画像数 | 4 |

### `ParsedMessage`

| 項目 | 型 |
| --- | --- |
| `text` | `str` |
| `image_urls` | `list[str]` |
| `reference_text` | <code>str &#124; None</code> |

### `parse_discord_message(message, bot_user_id)`

処理順序:

1. `message.content` から `<@id>` と `<@!id>` を除去する。
2. 返信先本文を `_reference_text()` で取得する。
3. `message.attachments` を検査し、対応画像なら URL を追加する。
4. 本文中の画像 URL を `extract_image_urls()` で抽出し、本文から除去する。
5. URL を重複排除する。
6. 画像数上限を検証する。
7. 本文も画像も空なら validation error。
8. `ParsedMessage` を返す。

### validation error

| 条件 | message |
| --- | --- |
| 未対応添付 | `未対応のファイル形式です。対応形式: png, jpg, jpeg, webp, gif` |
| 未対応 URL | `未対応のURL形式です。画像URLは https の png, jpg, jpeg, webp, gif のみ対応しています。` |
| 画像数超過 | `画像は1メッセージあたり最大4件までです。` |
| 本文・画像なし | `本文または画像を指定してください。` |

## 9. `bot/modules/chat_service.py`

### 責務

- チャット処理のユースケースを実装する。
- Guild 設定、session、Agent 実行、履歴保存を orchestration する。
- Discord や Agent Framework の具象型を直接扱わない。

### `ChatService.__init__(...)`

| 依存 | 用途 |
| --- | --- |
| `AppConfig` | 失敗時保存方針など |
| `GuildConfigManager` | 実効 Guild 設定 |
| `SessionStore` | 履歴取得・保存 |
| `AgentService` | 応答生成 |
| `logging.Logger` | ログ |

### `handle_chat(request)`

処理順序:

1. `get_effective_config()` で Guild の実効設定を取得する。
2. `get_session()` で Guild session を取得する。
3. `build_user_message()` で user message を作り、session に追加する。
4. 受信ログを出力する。
5. `build_agent_messages()` で system + history を作る。
6. `build_agent_settings()` で Agent 設定を作る。
7. `agent_service.generate()` を実行する。
8. Agent 成功時は応答 text を整形し、空なら代替文を使う。
9. assistant message を session に追加する。
10. `_save_session_best_effort()` で保存する。
11. `ChatResponse` を返す。

Agent 失敗時:

- stack trace をログ出力する。
- `save_failed_user_message` が true なら user message だけ保存する。
- false なら追加した user message を session から削除する。
- 汎用エラー文の `ChatResponse` を返す。

### `build_user_message(request, image_detail)`

本文を trim し、返信先本文があれば次の形式で追記する。

```text
<user text>

## 以下へ言及
<reference text>
```

画像 URL は `ChatContentPart(type="image_url", detail=image_detail)` として追加する。

### `build_agent_messages(session)`

session の `system_prompt` から system message を作成し、session messages の先頭に追加して返す。

### `build_agent_settings(effective_config)`

`EffectiveGuildConfig` から `AgentSettings` を作成する。`AppConfig.mcp` から作成した `MCPServerSettings` も含める。

X MCP server が設定されている場合のみ、`AppConfig.mcp.search_result_limit` を `AgentSettings.mcp_search_result_limit` に設定する。X MCP server の判定は server 名 `xapi`、HTTP URL `https://api.x.com/mcp`、または stdio args に同 URL を含むかで行う。X MCP server がない場合は `None` とし、Agent instructions には検索件数指示を追加しない。

### `build_mcp_server_settings()`

`AppConfig.mcp` から `list[MCPServerSettings]` を作成する。`mcp.enabled` が false の場合は空 list を返す。

### `_save_session_best_effort(session)`

`SessionStoreError` を握り、ログ出力のみ行う。

## 10. `bot/modules/agent_service.py`

### 責務

- Agent 実行 interface を定義する。
- Microsoft Agent Framework の具体 API を adapter 内に閉じ込める。
- アプリ内 `ChatMessage` を Agent Framework `Message` / `Content` へ変換する。
- `mcp.enabled` の場合に MCP tool を生成し、Agent へ渡す。
- テスト用 fake service を提供する。

### dataclass

| クラス | 項目 |
| --- | --- |
| `AgentSettings` | `provider`, `model`, `temperature`, `max_tokens`, `image_detail`, `mcp_servers`, `mcp_search_result_limit` |
| `MCPServerSettings` | `name`, `transport`, `command`, `args`, `url`, `env`, `headers`, `allowed_tools`, `approval_mode`, `request_timeout` |
| `AgentResult` | `text`, `raw` |

### exceptions

| 例外 | 用途 |
| --- | --- |
| `AgentConfigurationError` | provider や API key の設定不備 |
| `AgentExecutionError` | Agent 実行中の失敗 |

### `AgentService` protocol

```python
async def generate(messages: list[ChatMessage], settings: AgentSettings) -> AgentResult:
    ...
```

### `MicrosoftAgentService`

#### `__init__(api_key_env="OPENAI_API_KEY")`

API key 環境変数名と、`(provider, model)` を key にした `OpenAIChatClient` cache を保持する。

#### `generate(messages, settings)`

処理順序:

1. `settings.provider != "openai"` なら `AgentConfigurationError`。
2. API key 環境変数が空なら `AgentConfigurationError`。
3. `_get_client()` で `OpenAIChatClient` を取得する。
4. `convert_messages()` で system instructions と run messages へ変換する。
5. `settings.mcp_servers` の各 server から `build_mcp_tool()` で MCP tool を作成する。
6. `client.as_agent()` で Agent を作成する。MCP tools がある場合は `tools` に渡す。
7. `agent.run(run_messages)` を await する。
8. HTTP MCP tool 用に作成した `httpx.AsyncClient` があれば close する。
9. `response.text` を `AgentResult.text` に詰める。

`AgentConfigurationError` 以外の例外は `AgentExecutionError` へ包む。

#### `convert_messages(messages, settings)`

変換仕様:

- role が `system` の message は `instructions` に変換し、run messages には含めない。
- text part は `Content.from_text()`。
- image_url part は `Content.from_uri(uri, media_type=...)`。
- `Message(message.role, contents)` を作成する。
- `mcp_search_result_limit` が設定されている場合は、X MCP 検索 tool へ 10 件以上の取得件数を渡すよう `instructions` に補足する。
- `mcp_search_result_limit < 10` の場合、Agent への推奨値は 10 に丸める。

#### `_guess_image_media_type(url)`

URL path の拡張子から media type を推定する。

| 拡張子 | media type |
| --- | --- |
| `.png` | `image/png` |
| `.jpg`, `.jpeg` | `image/jpeg` |
| `.webp` | `image/webp` |
| `.gif` | `image/gif` |
| その他 | `None` |

#### `build_mcp_tool(settings)`

`MCPServerSettings` から Agent Framework の MCP tool を作成する。

| `transport` | 生成 tool | 必須設定 |
| --- | --- | --- |
| `stdio` | `MCPStdioTool` | `name`, `command`, `args` |
| `http`, `streamable_http` | `MCPStreamableHTTPTool` | `name`, `url` |

X API MCP server は token-only 構成では `http` transport で `https://api.x.com/mcp` へ直接接続する。OAuth user context が必要な場合は `stdio` transport で次の bridge を起動する。

```text
npx -y @xdevplatform/xurl mcp https://api.x.com/mcp
```

`env` は `{"CLIENT_ID": "X_CLIENT_ID"}` のような mapping とし、key を MCP 子プロセスへ渡す環境変数名、value を Bot 実行環境から読む環境変数名として扱う。

#### `_build_child_env(env_mapping)`

`env_mapping` に従い、Bot 実行環境から値が存在するものだけを子プロセス用 env dict へ変換する。

#### `_build_header_provider(header_mapping)`

HTTP MCP server 用の header provider を作成する。`headers` は `{"Authorization": "X_BEARER_TOKEN"}` のような mapping とし、value を Bot 実行環境から読む。`Authorization` の値が `Bearer ` で始まらない場合は自動で `Bearer ` を付与する。

### `FakeAgentService`

テスト・CLI 用の fake 実装。呼び出し引数を `requests` に記録し、指定 text または `fake response: messages=<n>, images=<n>` を返す。

## 11. `bot/modules/logging_service.py`

### 責務

- logger 初期化。
- 入力本文や URL のログ用安全化 helper を提供する。

### `setup_logging(config)`

処理:

1. `config.level` から logging level を決定する。不明値は `INFO`。
2. logger `bot_for_fmj` の handler をクリアする。
3. 標準出力 handler を追加する。
4. `config.file` の親ディレクトリを作成する。
5. `RotatingFileHandler(maxBytes=1_000_000, backupCount=3)` を追加する。

### `safe_preview(text, limit=120)`

空白を 1 つに正規化し、`limit` で切る。空なら空文字。

### `safe_url_for_log(url)`

URL の query と fragment を取り除く。

## 12. `bot/tools/chat_cli.py`

### 責務

- Discord を起動せず、ChatService をコマンドラインから実行する。
- 履歴確認、履歴削除、fake Agent 実行を提供する。

### 引数

| 引数 | 説明 |
| --- | --- |
| `--guild-id` | 必須 Guild ID |
| `--user-id` | user ID。既定値 0 |
| `--text` | 入力本文 |
| `--image-url` | 画像 URL。複数指定可 |
| `--show-history` | 履歴を表示 |
| `--reset-history` | 履歴を削除 |
| `--fake-agent` | 実 Agent ではなく `FakeAgentService` を使う |

### `run(args)`

処理:

1. `setting.yaml` を読み込む。
2. logger、GuildConfigManager、SessionStore を初期化する。
3. `--reset-history` なら履歴削除して終了。
4. `--show-history` なら履歴表示して終了。
5. `--text` も `--image-url` もなければ終了コード 1。
6. fake または実 AgentService を作成する。
7. `ChatService.handle_chat()` を実行する。
8. 応答 text を stdout に出す。

終了コード:

| code | 意味 |
| --- | --- |
| 0 | 正常 |
| 1 | 入力不備、設定不備 |
| 2 | Agent 実行失敗 |
| 3 | その他例外 |

## 13. モジュール間依存

```text
main.py
  -> modules.config
  -> modules.logging_service
  -> cogs.chat

cogs.chat
  -> modules.agent_service
  -> modules.chat_models
  -> modules.chat_service
  -> modules.config
  -> modules.guild_config
  -> modules.message_parser
  -> modules.session_store

chat_service
  -> agent_service.AgentService protocol
  -> chat_models
  -> config
  -> guild_config
  -> logging_service.safe_preview
  -> session_store

agent_service
  -> agent_framework
  -> agent_framework.openai
  -> agent_framework.MCPStdioTool
  -> agent_framework.MCPStreamableHTTPTool
  -> chat_models

guild_config
  -> chat_models datetime helpers
  -> config.AppConfig

session_store
  -> chat_models
```

設計上、`chat_service` は Discord SDK と Agent Framework の具象型に依存しない。外部入出力の境界は `cogs.chat`, `agent_service`, `session_store`, `guild_config`, `logging_service` に分離する。
