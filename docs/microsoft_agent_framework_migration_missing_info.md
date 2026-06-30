# Microsoft Agent Framework 移行実装前の不足情報リスト

## 1. 目的

`docs/microsoft_agent_framework_migration_design.md`、`docs/module_function_design.md`、`docs/test_plan.md` を確認し、Microsoft Agent Framework への初期移行を実装する前に追加で決める必要がある情報を整理する。

初期移行の対象は次の範囲とする。

- Discord の mention チャット応答
- テキスト / 画像入力
- 設定・ログ永続化
- Guild 毎の session 分離
- 最小コマンド

## 2. 最優先で確認が必要な情報

| 優先度 | 不足情報 | 必要な理由 | 決める内容 |
| --- | --- | --- | --- |
| high | Microsoft Agent Framework の具体 API | 設計書では adapter 境界は定義されているが、実際の import、Agent 作成、message 変換、画像入力形式が未確定 | 使用する Python パッケージ名、バージョン、Agent 作成方法、OpenAI 接続方法、multimodal 入力形式 |
| high | 依存パッケージの最終リスト | `requirements.txt` にはまだ `semantic-kernel`、`google-generativeai`、`riotwatcher` が残っており、Agent Framework 追加パッケージが未記載 | 追加する Agent Framework 関連パッケージ、削除する旧依存、Docker build に必要な OS 依存 |
| high | API key / 環境変数名 | 既存コードは Discord token 以外の環境変数仕様が設計書に明記されていない | `OPENAI_API_KEY` などの必須 env、任意 env、未設定時のエラーメッセージ |
| high | `setting.yaml` の移行方法 | 現行設定は `gpt.*`、新設計は `agent.*`。互換キーの扱いが一部だけ決まっている | 旧 `gpt.openai_model` などを読む互換 loader を作るか、設定ファイルを一括更新するか |
| high | 既存 `guild_configs.json` の互換 | 現行 JSON は `ai_provider`、`openai_model`、`gemini_model`。新設計は `provider`、`model` | 旧形式を自動変換するか、初期移行で破棄可能にするか |
| high | Discord Cog の読み込み方式 | 現行 `main.py` は `cogs/*.py` を全読み込みするため、移行対象外の `riot_api.py` も読まれる | 読み込む Cog を allowlist 化する方法、旧 `gpt.py` を残すか新 `chat.py` に置換するか |
| high | Agent error 時の履歴保存方針 | 詳細設計では「設定で選べる。初期値は保存」とあるが設定キーが未定義 | `bot.save_failed_user_message` などの設定名、デフォルト値、保存失敗時の挙動 |

## 3. 実装仕様として追加したい決定事項

### 3.1 AgentService

- Agent instance を request ごとに作るか、`provider + model` 単位で cache するか。
- system prompt を Agent Framework の system instruction として渡すか、通常 message として渡すか。
- `max_tokens`、`temperature` が Agent Framework のどの引数に対応するか。
- Agent Framework からの response が複数 part の場合、Discord 返信用 text をどう抽出するか。
- 画像 URL が外部 URL のまま渡せるか。渡せない場合、download して byte input に変換するか。
- Discord CDN の期限付き URL や query string 付き URL をそのまま扱えるか。
- provider は初期実装で `openai` のみに固定するか、設定上は `gemini` を残すか。

### 3.2 Config

- 新しい `AppConfig` dataclass の最終形。
- `bot.default_system_promt` の typo 互換をいつまで維持するか。
- 現行 `bot.save_api_response` と `bot.save_image_input` を廃止するか、新仕様へ対応させるか。
- `mcp.enabled` の初期値を現行 `true` から新設計どおり `false` へ変更するか。
- `logging.file` の path は repository root 基準か、`bot/` 基準か、Docker container 内の絶対 path か。
- `image_detail` は文字列 `low/high` に統一するか、現行 `image_resolution: 0/1` も読むか。

### 3.3 SessionStore

- session JSON の timezone はローカル時刻、UTC、timezone aware ISO のどれに統一するか。
- atomic save の一時ファイル名と、rename 失敗時の fallback。
- 破損 JSON を検出した場合に `.bak` へ退避するか、ログだけ出して上書きするか。
- `history_size` は message 件数か、user / assistant の往復数か。
- `history_size` を超えたときに user message と assistant message のペアを維持するか。
- 既存 Semantic Kernel 履歴がある場合に移行するか、初期移行では無視するか。

### 3.4 MessageParser

- `http` 画像 URL を許可するか、`https` のみ許可するか。
- `http` から `https` への変換を実装する場合、どの条件で変換するか。
- Discord attachment の判定は拡張子、`content_type`、両方のどれを優先するか。
- 画像 URL の最大件数。
- 画像 URL の重複排除を行うか。
- 返信先 message に画像添付がある場合、それも入力画像に含めるか。
- unsupported attachment が混ざっている場合、画像だけ処理して警告するか、request 全体を validation error にするか。

### 3.5 ChatService

- `reference_text` を user text に埋め込む際の固定フォーマット。
- text なし画像のみ request の prompt 文を自動追加するか。
- Agent response が Discord の文字数上限を超えた場合、分割送信するか、切り詰めるか。
- Agent response が空の場合の fallback message。
- save 失敗時に Discord へ成功応答を返すか、保存失敗をユーザーに知らせるか。

### 3.6 Discord コマンド

- slash command だけにするか、prefix command も維持するか。
- `/help` を自作するか、discord.py の標準 help を使うか。
- `/search` は未登録にするか、未対応メッセージを返す stub として残すか。
- `/config_set_model` の provider 引数を `openai` 固定にするか、将来 provider 名を受け付ける形にするか。
- command sync 対象の Guild ID が未設定の場合、global sync に fallback するか起動エラーにするか。

### 3.7 Logging

- 既存 `bot/logging_config.json` を使い続けるか、新しい `logging_service.py` へ寄せるか。
- ログファイル directory が存在しない場合に自動作成するか。
- message preview の最大文字数。
- 画像 URL は host のみ出すか、path まで出すか。
- request ID や guild ID を log context として付与するか。

### 3.8 CLI / Test

- `chat_cli` の real Agent 実行時に必要な env と終了コード。
- `--fake-agent` の応答内容を固定文字列にするか、入力を echo して検証しやすくするか。
- `pytest` / `pytest-asyncio` を依存に追加するか。
- smoke test を通常 CI から外す marker 設定を `pytest.ini` に置くか。
- Docker 内で CLI smoke test を実行する手順を用意するか。

## 4. 既存コードから見える移行時の注意点

| 項目 | 現状 | 実装時に必要な対応 |
| --- | --- | --- |
| Cog 読み込み | `bot/main.py` が `cogs` 配下の `.py` を全読み込み | `riot_api.py` を読まない allowlist に変更する |
| 設定名 | `gpt.max_token`、`gpt.image_resolution`、`bot.default_system_promt` | 新設定名への移行または互換 loader を実装する |
| Guild 設定 | `ai_provider` enum と provider 別 model を保持 | 新設計の `provider` / `model` へ変換する |
| 依存関係 | `semantic-kernel`、`riotwatcher` が残っている | 初期移行完了時に不要依存を削除する |
| MCP | 現行 `setting.yaml` では `enabled: True` | 初期移行では無効化する |
| ログ | `logging_config.json` 依存 | 新 `logging_service.py` とどちらを正にするか決める |
| token 読み込み | `GUILD_ID` が未設定だと import 時に失敗する | 起動時 validation に移し、明確な error を出す |

## 5. 実装前に決めると手戻りが少ないチェックリスト

- [ ] Microsoft Agent Framework の公式 Python API と対応バージョンを確定する。
- [ ] `requirements.txt` の追加 / 削除対象を確定する。
- [ ] `.env` / Docker に必要な環境変数一覧を確定する。
- [ ] `setting.yaml` を新形式へ書き換えるか、旧形式互換で読むか決める。
- [ ] `guild_configs.json` の旧形式互換を実装するか決める。
- [ ] 起動時に読み込む Cog の allowlist を決める。
- [ ] 画像 URL の許可条件と最大件数を決める。
- [ ] Agent error 時に user message を履歴保存するか決める。
- [ ] Discord 返信が長すぎる場合の分割 / 切り詰め方針を決める。
- [ ] CLI と pytest の依存追加方針を決める。

## 6. 推奨する次アクション

1. Microsoft Agent Framework の最新 Python ドキュメントを確認し、`MicrosoftAgentService` の最小実装方針を確定する。
2. `setting.yaml` と `guild_configs.json` の互換方針を先に決める。
3. Cog allowlist 化と Riot API 非読み込みを最初の実装に含める。
4. Fake AgentService で `ChatService` / `SessionStore` / `MessageParser` を先に実装し、real Agent は adapter 単体で差し替える。
