# ソフトウェア全体設計書

## 1. 目的

本ソフトウェアは Discord 上で動作するチャットボットである。ユーザーが Bot をメンションしたメッセージを受け取り、テキストおよび画像 URL / 画像添付を Microsoft Agent Framework 経由で OpenAI モデルへ渡し、生成された応答を Discord に返す。

会話履歴と Guild 固有設定はファイルへ永続化し、Guild ごとに会話コンテキストと設定を分離する。実行環境は Docker を前提とする。

## 2. システム範囲

### 2.1 対象機能

| 機能 | 概要 |
| --- | --- |
| Discord メンション応答 | Bot がメンションされたメッセージのみチャット処理を行う |
| テキスト入力 | メンション除去後の本文を Agent へ渡す |
| 画像入力 | Discord 添付画像および本文中の HTTPS 画像 URL を Agent へ渡す |
| 返信参照 | Discord の返信先本文をユーザー入力へ追記する |
| Guild 別会話履歴 | `bot/data/sessions/guild_<guild_id>.json` に保存する |
| Guild 別設定 | `bot/data/guild_configs.json` に provider / model / system prompt 差分を保存する |
| チャット設定 | `bot/setting.yaml` から既定モデル、履歴数、ログ設定を読み込む |
| Slash / hybrid command | 履歴表示、履歴削除、キャラクター設定、設定確認、モデル変更を提供する |
| ログ出力 | 標準出力とローテーションファイルへログを出力する |
| ローカル CLI | Discord を介さず ChatService を実行確認できる |

### 2.2 対象外または未使用機能

| 項目 | 現状 |
| --- | --- |
| MCP 連携 | 設定モデルは存在するが、実行経路では未使用 |
| Web 検索 | 未実装 |
| Riot API レビュー | 未実装 |
| Gemini provider | legacy 設定読み込みの互換処理はあるが、Agent 実行は `openai` のみ対応 |
| 履歴要約 | 未実装。履歴数上限で古いメッセージを切り詰める |

## 3. 実行構成

```text
Docker container
  /app
    main.py
    setting.yaml
    cogs/chat.py
    modules/
    data/
      guild_configs.json
      sessions/
    logs/
```

Docker イメージは `dockerfile` で定義し、`bot/` 配下を `/app` へコピーする。起動コマンドは `python3 ./main.py` である。

`docker-compose.yaml` から次の環境変数を渡す。

| 環境変数 | 必須 | 用途 |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | yes | Discord Bot の認証トークン |
| `OPENAI_API_KEY` | yes | OpenAI Chat Client の API key |
| `GUILD_ID` | yes | command sync 対象 Guild ID。カンマ区切りで複数指定可能 |
| `BOT_PREFIX` | no | prefix command 用。未指定時は `/` |
| `TZ` | no | コンテナの timezone |

## 4. アーキテクチャ

```text
Discord
  |
  v
bot/main.py
  - AppConfig load
  - logging setup
  - DiscordBot startup
  - cogs.chat load
  - Guild command sync
  |
  v
ChatCog
  - Discord event / command adapter
  - MessageParser 呼び出し
  - ChatService 呼び出し
  - Discord 返信
  |
  v
ChatService
  - 有効 Guild 設定解決
  - GuildSession 取得
  - user message 作成
  - AgentSettings 作成
  - AgentService 実行
  - assistant message 保存
  |
  +--> GuildConfigManager
  |     - Guild 固有設定 load / save
  |
  +--> SessionStore
  |     - Guild 別履歴 load / save / trim / reset
  |
  +--> MicrosoftAgentService
        - app 内部モデルを Agent Framework 型へ変換
        - OpenAIChatClient を使って Agent 実行
```

Discord 依存は `ChatCog`、Microsoft Agent Framework 依存は `MicrosoftAgentService` に閉じ込める。アプリケーション層の `ChatService` は独自 dataclass と protocol に依存し、外部 SDK の型を直接扱わない。

## 5. 起動フロー

1. `main()` が `bot/setting.yaml` を `AppConfig.load()` で読み込む。
2. `setup_logging()` が logger `bot_for_fmj` を初期化する。
3. `load_environment()` が `DISCORD_BOT_TOKEN`, `OPENAI_API_KEY`, `GUILD_ID`, `BOT_PREFIX` を検証する。
4. `DiscordBot` を生成し、`bot.run(token)` で Discord に接続する。
5. `DiscordBot.setup_hook()` が `cogs.chat` をロードする。
6. 指定 Guild ごとに slash command を同期する。
7. `on_ready()` でログ出力し、presence を設定する。

## 6. チャット処理フロー

1. `ChatCog.on_message()` が Discord message を受信する。
2. Bot 自身の message、DM、Bot メンションなし message はチャット処理しない。
3. `MessageParser.parse_discord_message()` が本文、画像 URL、返信先本文を抽出する。
4. `ChatRequest` を作成して `ChatService.handle_chat()` へ渡す。
5. `GuildConfigManager.get_effective_config()` が Guild 固有設定と既定設定を合成する。
6. `SessionStore.get_session()` が Guild の履歴を読み込む。存在しない場合は新規作成する。
7. `ChatService.build_user_message()` が user message を構築し、session に追加する。
8. `ChatService.build_agent_messages()` が system message と履歴を結合する。
9. `MicrosoftAgentService.generate()` が Agent Framework 形式に変換し、Agent を実行する。
10. 応答 text を assistant message として session に追加する。
11. `SessionStore.save_session()` が履歴数を調整して JSON へ保存する。
12. `ChatCog` が Discord の文字数制限に備えて応答を 1900 文字単位に分割し送信する。

## 7. データ設計

### 7.1 アプリ内データモデル

| モデル | 用途 |
| --- | --- |
| `ChatContentPart` | text または image_url の content part |
| `ChatMessage` | role, content, created_at を持つ会話メッセージ |
| `GuildSession` | Guild ID、system prompt、会話履歴、更新日時 |
| `ChatRequest` | Discord 入力から作るチャット要求 |
| `ChatResponse` | Discord へ返す応答 |
| `AgentSettings` | Agent 実行時の provider / model / temperature / max_tokens / image_detail |
| `GuildSpecificConfig` | Guild 固有の上書き設定 |
| `EffectiveGuildConfig` | 既定設定と Guild 固有設定を合成した実効設定 |

### 7.2 永続化ファイル

| ファイル | 内容 |
| --- | --- |
| `bot/setting.yaml` | アプリ全体の既定設定 |
| `bot/data/guild_configs.json` | Guild ごとの provider / model / custom_system_prompt |
| `bot/data/sessions/guild_<guild_id>.json` | Guild ごとの会話履歴 |
| `logs/bot.log` | アプリケーションログ |

セッション JSON は `version`, `guild_id`, `system_prompt`, `updated_at`, `messages` を持つ。日時は timezone 付き ISO 8601 文字列で保存する。

## 8. 設定設計

`setting.yaml` の主要項目は次の通り。

| セクション | 項目 | 説明 |
| --- | --- | --- |
| `agent` | `provider` | 現状は `openai` のみ実行可能 |
| `agent` | `model` | Agent 実行モデル |
| `agent` | `max_tokens` | 最大出力 token |
| `agent` | `temperature` | 生成温度 |
| `agent` | `image_detail` | 画像 detail。履歴には保存されるが Agent 変換では現状 media type 推定のみ使用 |
| `bot` | `history_size` | 保存履歴の最大 message 数 |
| `bot` | `save_failed_user_message` | Agent 失敗時に user message を残すか |
| `bot` | `default_system_prompt` | 既定 system prompt |
| `logging` | `level` | ログレベル |
| `logging` | `file` | ログファイルパス |
| `mcp` | `enabled`, `command`, `args`, `search_result_limit` | 現状は設定読み込みのみ |

legacy `gpt` セクション、および typo を含む `default_system_promt` は互換読み込みされる。

## 9. コマンド設計

| コマンド | 概要 |
| --- | --- |
| `/history` | 現在 Guild の直近 10 件の履歴 preview を表示 |
| `/history_reset` | 現在 Guild の履歴ファイルを削除 |
| `/chara <text>` | 現在 Guild の custom system prompt を設定 |
| `/chara_reset` | custom system prompt を削除し既定へ戻す |
| `/config` | 実効設定を表示 |
| `/config_set_model <provider> <model>` | provider / model を Guild 設定へ保存。provider は `openai` のみ許可 |
| `/config_reset` | Guild 固有設定を削除 |
| `/help` | コマンド一覧を表示 |

## 10. エラー設計

| 発生箇所 | 方針 |
| --- | --- |
| 起動時必須環境変数なし | `RuntimeError` で起動停止 |
| 設定 YAML 不正 | `ConfigError` または例外で起動停止 |
| Discord 入力 validation | ユーザー向けエラーメッセージを Discord へ返す |
| Agent 設定不正 / 実行失敗 | ログへ stack trace を記録し、汎用エラー文を返す |
| session 保存失敗 | ログへ記録し、Discord 応答自体は継続する |
| 壊れた session JSON | `.bak` へ退避し、新規 session を返す |
| Guild 設定保存失敗 | command へ「設定更新に失敗しました。」を返す |

## 11. ログ設計

logger 名は `bot_for_fmj` である。ログは標準出力と `RotatingFileHandler` に出力する。

| 項目 | 値 |
| --- | --- |
| format | `[LEVEL] timestamp logger: message` |
| maxBytes | 1,000,000 |
| backupCount | 3 |
| encoding | UTF-8 |

入力本文は `safe_preview()` で空白正規化と長さ制限をした preview のみログ出力する。

## 12. セキュリティ・運用方針

- Discord token と OpenAI API key は環境変数で注入する。
- 秘密情報を設計書、ログ、履歴 JSON に記録しない。
- 本文中 URL は HTTPS の画像 URL のみ受け付ける。
- Discord 添付は `content_type` が `image/` で始まるもの、または対応画像 URL のみ受け付ける。
- 1 メッセージの画像数上限は 4 件とする。
- Discord 送信は 1900 文字単位で分割し、API 制限に余裕を持たせる。

## 13. テスト方針

既存テストは次を検証する。

| テスト対象 | 主な検証内容 |
| --- | --- |
| config | legacy `gpt` 設定から現行 `agent` / `bot` 設定への読み替え |
| message_parser | HTTPS 画像 URL 抽出、HTTP URL 拒否、重複排除 |
| session_store | 保存復元、timezone 付き日時、壊れた JSON の `.bak` 退避 |
| agent_service | Agent Framework `Message` / `Content` への変換、画像 media type 推定 |
| chat_service | user / assistant 保存、Agent 失敗時の user message 保存 |
| chat_cog | Discord 応答分割 |
