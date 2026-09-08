# bot_for_fmj

Discord で動作する Python 製チャットボットです。Bot がメンションされたメッセージを受け取り、Microsoft Agent Framework 経由で OpenAI モデルを呼び出して応答します。

## 主な機能

| 機能 | 内容 |
| --- | --- |
| メンション応答 | Discord 上で Bot がメンションされたメッセージへ返信 |
| テキスト / 画像入力 | 本文、Discord 添付画像、本文中の HTTPS 画像 URL に対応 |
| Guild 別履歴 | `bot/data/sessions/guild_<guild_id>.json` に会話履歴を保存 |
| Guild 別設定 | `bot/data/guild_configs.json` にモデル設定や system prompt を保存 |
| X MCP 連携 | X API MCP server を Agent tool として利用 |
| Slash / hybrid command | 履歴表示、履歴削除、キャラクター設定、設定確認など |
| ローカル CLI | Discord を起動せずチャット処理を確認可能 |

Discord 添付画像は取得時に画像データを会話履歴へ保存するため、添付 URL の有効期限後も参照できます（1画像20 MiBまで）。従来の履歴にある期限切れ・削除済み画像は、次の会話時に参照できない旨の説明文へ置き換えます。本文や応答の履歴は保持されますが、その画像を再び参照する場合は再添付が必要です。外部サイトの画像 URL は従来どおり URL のまま扱います。

## 動作環境

- Docker / Docker Compose
- Discord Bot token
- OpenAI API key

## ファイル構成

```text
.
├── README.md
├── bot
│   ├── cogs
│   │   └── chat.py
│   ├── data
│   │   ├── guild_configs.json
│   │   └── sessions/
│   ├── main.py
│   ├── modules
│   ├── tools
│   │   └── chat_cli.py
│   ├── requirements.txt
│   └── setting.yaml
├── docs
│   ├── software_overall_design.md
│   ├── module_detail_design.md
│   └── test_plan.md
├── docker-compose.yaml
├── dockerfile
└── tests
```

## セットアップ

1. Discord Developer Portal で Bot の intents を許可する。
2. `.env.example` を元に `.env` を作成し、環境変数を設定する。

```bash
cp .env.example .env
```

3. `docker-compose.yaml` または実行環境に以下の環境変数を設定する。

| key | 必須 | 値 |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | yes | Discord Bot の token |
| `OPENAI_API_KEY` | yes | OpenAI API key |
| `GUILD_ID` | yes | 動作させる Guild ID。カンマ区切りで複数指定可能 |
| `BOT_PREFIX` | no | prefix command 用。未指定時は `/` |
| `TZ` | no | timezone。例: `Asia/Tokyo` |
| `INSTALL_NODE` | no | OAuth xurl bridge を使う場合のみ `true`。token-only HTTP route では `false` のままでよい |
| `X_CLIENT_ID` | MCP 使用時 | X app の OAuth 2.0 Client ID |
| `X_CLIENT_SECRET` | MCP 使用時 | X app の OAuth 2.0 Client Secret |
| `X_BEARER_TOKEN` | token-only MCP 使用時 | X app の App-only Bearer token |
| `X_REDIRECT_URI` | MCP 使用時 | X app に登録した OAuth redirect URI。未指定時は `http://localhost:8080/callback` |

4. コンテナを起動する。

```bash
docker compose up -d
```

設定や依存関係を変更した場合は再ビルドする。

```bash
docker compose up --build -d
```

ログ確認:

```bash
docker compose logs -f bot
```

停止:

```bash
docker compose down
```

## アプリ設定

アプリの既定設定は `bot/setting.yaml` で管理します。

| セクション | 主な項目 | 内容 |
| --- | --- | --- |
| `agent` | `provider`, `model`, `max_tokens`, `temperature`, `image_detail` | Agent 実行設定 |
| `bot` | `history_size`, `save_failed_user_message`, `default_system_prompt` | 履歴と system prompt 設定 |
| `logging` | `level`, `file` | ログ設定 |
| `mcp` | `enabled`, `servers`, `search_result_limit` | MCP tool 設定 |

現状の Agent 実行 provider は `openai` のみ対応しています。

## X MCP 連携

`bot/setting.yaml` の `mcp.enabled` を `true` にすると、Microsoft Agent Framework の MCP tool 経由で X API MCP server を Agent tool として利用します。OAuth user context が必要な場合は X 公式の `xurl` bridge を使います。

`mcp.search_result_limit` は X MCP の検索 tool に渡す推奨取得件数です。X MCP は検索件数の最小値が 10 のため、10 未満に設定しても Agent への指示では 10 件以上を要求し、必要な件数だけ要約・表示します。現在の既定値は `30` です。

```yaml
mcp:
  enabled: true
  servers:
    - name: "xapi"
      transport: "stdio"
      command: "npx"
      args: ["-y", "@xdevplatform/xurl", "mcp", "https://api.x.com/mcp"]
      env:
        CLIENT_ID: "X_CLIENT_ID"
        CLIENT_SECRET: "X_CLIENT_SECRET"
        REDIRECT_URI: "X_REDIRECT_URI"
      approval_mode: "never_require"
      request_timeout: 300
```

初回 OAuth ログインにはブラウザが必要です。サーバーや Docker など headless 環境では、事前に `xurl auth oauth2 --headless` で認証してください。Docker 実行時は `xurl-cache` volume を `/root/.xurl` に mount し、認証済み token cache を永続化します。

X Developer Portal では、使用する redirect URI を OAuth 2.0 設定に登録してください。既定値は X 公式 docs と同じ `http://localhost:8080/callback` です。

OAuth bridge は `npx` を使うため、Docker build 時に Node.js/npm が必要です。このルートを使う場合だけ `.env` で `INSTALL_NODE=true` にしてください。

Client ID / Secret がなく App-only Bearer token だけを使う場合は、OAuth bridge ではなく hosted HTTP MCP server へ直接接続します。この方式は読み取り中心で、ユーザー本人としての操作や書き込み系 tool は使えません。

```yaml
mcp:
  enabled: true
  servers:
    - name: "xapi"
      transport: "http"
      url: "https://api.x.com/mcp"
      headers:
        Authorization: "X_BEARER_TOKEN"
      approval_mode: "never_require"
      request_timeout: 300
```

他の MCP server も `mcp.servers` に追加できます。

```yaml
mcp:
  enabled: true
  servers:
    - name: "xapi"
      transport: "http"
      url: "https://api.x.com/mcp"
      headers:
        Authorization: "X_BEARER_TOKEN"
    - name: "filesystem"
      transport: "stdio"
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
```

## Discord コマンド

| コマンド | 内容 |
| --- | --- |
| `/history` | 現在 Guild の直近履歴を表示 |
| `/history_reset` | 現在 Guild の履歴を削除 |
| `/chara <text>` | 現在 Guild の system prompt を変更 |
| `/chara_reset` | system prompt をデフォルトへ戻す |
| `/config` | 現在 Guild の有効設定を表示 |
| `/config_set_model <provider> <model>` | 現在 Guild のモデル設定を変更。provider は `openai` のみ |
| `/config_reset` | 現在 Guild の設定をデフォルトへ戻す |
| `/help` | コマンド一覧を表示 |

## ローカル CLI

Discord を起動せずに `ChatService` を確認できます。コンテナ内、または依存関係を入れたローカル環境で実行します。

```bash
cd bot
python -m tools.chat_cli --guild-id 123456789 --text "こんにちは" --fake-agent
```

履歴表示:

```bash
cd bot
python -m tools.chat_cli --guild-id 123456789 --show-history
```

履歴削除:

```bash
cd bot
python -m tools.chat_cli --guild-id 123456789 --reset-history
```

## テスト

依存関係をインストールした環境で実行します。

```bash
python -m pytest -q
```

## 設計書

- [ソフトウェア全体設計書](docs/software_overall_design.md)
- [モジュール詳細設計書](docs/module_detail_design.md)
- [テスト計画](docs/test_plan.md)

## 注意事項

- `DISCORD_BOT_TOKEN` と `OPENAI_API_KEY` はリポジトリにコミットしないでください。
- セッション履歴にはユーザー入力が保存されます。運用環境では `bot/data/sessions/` の取り扱いに注意してください。
- 現在は `cogs.chat` のみを読み込む構成です。
