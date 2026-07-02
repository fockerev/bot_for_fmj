# bot_for_fmj

Discord で動作する Python 製チャットボットです。Bot がメンションされたメッセージを受け取り、Microsoft Agent Framework 経由で OpenAI モデルを呼び出して応答します。

## 主な機能

| 機能 | 内容 |
| --- | --- |
| メンション応答 | Discord 上で Bot がメンションされたメッセージへ返信 |
| テキスト / 画像入力 | 本文、Discord 添付画像、本文中の HTTPS 画像 URL に対応 |
| Guild 別履歴 | `bot/data/sessions/guild_<guild_id>.json` に会話履歴を保存 |
| Guild 別設定 | `bot/data/guild_configs.json` にモデル設定や system prompt を保存 |
| Slash / hybrid command | 履歴表示、履歴削除、キャラクター設定、設定確認など |
| ローカル CLI | Discord を起動せずチャット処理を確認可能 |

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
│   └── module_detail_design.md
├── docker-compose.yaml
├── dockerfile
└── tests
```

## セットアップ

1. Discord Developer Portal で Bot の intents を許可する。
2. `docker-compose.yaml` または実行環境に以下の環境変数を設定する。

| key | 必須 | 値 |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | yes | Discord Bot の token |
| `OPENAI_API_KEY` | yes | OpenAI API key |
| `GUILD_ID` | yes | 動作させる Guild ID。カンマ区切りで複数指定可能 |
| `BOT_PREFIX` | no | prefix command 用。未指定時は `/` |
| `TZ` | no | timezone。例: `Asia/Tokyo` |

3. コンテナを起動する。

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
| `mcp` | `enabled`, `command`, `args`, `search_result_limit` | 現状は読み込みのみ |

現状の Agent 実行 provider は `openai` のみ対応しています。

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

## 注意事項

- `DISCORD_BOT_TOKEN` と `OPENAI_API_KEY` はリポジトリにコミットしないでください。
- セッション履歴にはユーザー入力が保存されます。運用環境では `bot/data/sessions/` の取り扱いに注意してください。
- 初期移行後は `cogs.chat` のみを読み込む構成です。
