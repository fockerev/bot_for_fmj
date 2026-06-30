# Microsoft Agent Framework 移行設計 再確認結果

## 1. 確認結果サマリ

前回不足として挙げた項目の多くは、設計書へ反映済み。

解消済みの主な項目:

- `agent.*` への設定移行と旧 `gpt.*` fallback
- `bot.default_system_promt` の typo 互換
- 既存 `guild_configs.json` の旧形式から新形式への変換方針
- `cogs.chat` の allowlist 読み込み
- `bot.save_failed_user_message`
- 画像 URL の `https` 限定、最大4件、重複除去、unsupported attachment の扱い
- SessionStore の UTC timestamp、破損 JSON `.bak` 退避、履歴件数定義
- `logging_service.py` を正とする方針
- CLI / pytest / smoke marker 方針

今回の実装で、設計書間の小さな整合修正とアプリ層の実装は反映済み。現時点で残る不足は、主に Microsoft Agent Framework の実 API binding 確定。

## 2. 実装前に残る高優先度の確認事項

| 優先度 | 項目 | 現状 | 必要な対応 |
| --- | --- | --- | --- |
| high | Microsoft Agent Framework Python API | 実装直前に公式ドキュメント確認と明記されている | 使用パッケージ名、バージョン、Agent 作成、OpenAI 接続、system instruction、text / image URL 形式、`max_tokens` / `temperature` 指定方法を確定する |
| resolved | 依存パッケージ最終形 | `requirements.txt` を初期移行用に更新済み | Agent Framework 公式パッケージ確定後に追加する |
| resolved | Discord 返信分割の責務 | `ChatCog` に `split_discord_message()` を実装済み | `ChatResponse.text` は完全な応答本文のまま保持する |
| resolved | Agent error 時の保存フロー | `ChatService.handle_chat()` に `save_failed_user_message` 分岐を実装済み | fallback assistant message は保存しない |

## 3. 設計書間で整合したい点

| 対象 | 不整合 / あいまいさ | 推奨修正 |
| --- | --- | --- |
| `GuildSession` | 移行設計の dataclass 例には `updated_at` がなく、詳細設計には必須項目としてある | 修正済み |
| `AgentResult` | 移行設計の例は `text` のみ、詳細設計は `raw: Any | None` あり | 修正済み |
| `/history` | 詳細設計の処理で `SessionStore.get_session(guild_id)` と書かれているが、定義は `get_session(guild_id, system_prompt)` | 修正済み |
| `/chara_reset` | default system prompt を session に反映するとあるが、取得元の手順が省略されている | 修正済み |
| Config fallback | 旧 `gpt.image_resolution` を `agent.image_detail` に fallback するとあるが、`0/1` から `low/high` への変換規則が本文では暗黙 | 修正済み |
| TestPlan | SessionStore の `.bak` 退避、UTC timestamp、画像最大4件、https 限定、Discord返信分割のテスト観点が薄い | 修正済み |

## 4. 実装時に注意する点

- `MicrosoftAgentService` は `agent-framework` の `OpenAIChatClient.as_agent()` / `Agent.run()` を使用する。
- `OPENAI_API_KEY` は Discord Bot 起動時必須。CLI の `--fake-agent` は API key 不要。
- 既存 `logging_config.json` は使用しない。新しい `logging_service.py` を正とする。

## 5. 推奨する次アクション

1. `OPENAI_API_KEY` ありで real CLI smoke test を実行する。
2. Discord 実機で mention text / mention image / slash command を確認する。
3. `image_detail` 相当の指定方法が Agent Framework / OpenAI provider option にあるか継続確認する。
