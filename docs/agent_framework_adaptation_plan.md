# agent-framework 対応変更計画

## 1. 目的

現状の実装では `bot/modules/agent_service.py` に `MicrosoftAgentService` の境界を作り、公式 API が未確定だったため暫定的に OpenAI SDK 互換経路を閉じ込めている。

Microsoft Agent Framework は `pip install agent-framework` で導入でき、Python API ドキュメントは以下で確認できる。

- https://learn.microsoft.com/ja-jp/python/api/agent-framework-core/agent_framework?view=agent-framework-python-latest
- https://learn.microsoft.com/ja-jp/python/api/agent-framework-core/agent_framework.openai?view=agent-framework-python-latest

このドキュメントでは、現状実装から `agent-framework` へ対応させるために必要な変更と、実装反映状況を整理する。

## 1.1 実装反映状況

反映済み:

- `requirements.txt` に `agent-framework` を追加。
- `agent_service.py` から暫定 OpenAI SDK 直呼び経路を削除。
- `OpenAIChatClient.as_agent()` と `Agent.run()` を使用。
- app 独自 `ChatMessage` から Agent Framework `Message` / `Content` へ変換。
- Agent Framework `AgentResponse.text` から応答本文を抽出。
- `convert_messages()` の unit test を追加。

## 2. 確認した API

`.venv` に `agent-framework==1.9.0` を入れて確認した範囲では、主要 API は次の通り。

```python
from agent_framework import Agent, AgentResponse, Content, Message
from agent_framework.openai import OpenAIChatClient, OpenAIChatOptions
```

確認できたシグネチャ概要:

```python
OpenAIChatClient(
    model: str | None = None,
    *,
    api_key: str | Callable | None = None,
    ...
)

OpenAIChatClient.as_agent(
    *,
    instructions: str | None = None,
    default_options: Mapping[str, Any] | None = None,
    ...
) -> Agent

Agent.run(
    messages=None,
    *,
    options=None,
    session=None,
    stream=False,
    ...
) -> Awaitable[AgentResponse]

Message(
    role: str,
    contents: Sequence[Content | str | Mapping[str, Any]] | None = None,
    ...
)

Content.from_text(text: str)
Content.from_uri(uri: str, *, media_type: str | None = None)
```

`AgentResponse` と `ChatResponse` には `text` property があるため、Discord 返信用の本文抽出は `response.text` を優先してよい。

## 3. 依存関係の変更

### 3.1 `requirements.txt`

変更前:

```text
openai
```

変更後:

```text
agent-framework
```

ただし、`agent-framework` はメタパッケージで多数の provider / tool 拡張を引き込む。Docker image size と install time を抑えたい場合は、実装検証後に次の最小依存へ寄せられるか確認する。

```text
agent-framework-core
agent-framework-openai
```

ユーザー指定は `pip install agent-framework` のため、まずは `agent-framework` を採用する。

### 3.2 `openai` 依存

`agent-framework-openai` が内部で OpenAI SDK を使うため、アプリ側の直接依存としての `openai` は削除候補。

`MicrosoftAgentService` から `_generate_with_openai_sdk()` は削除済み。アプリコードから直接 `openai` import は行わない。

## 4. `agent_service.py` の変更

### 4.1 削除する処理

以下は削除済み。

- `_import_agent_framework()`
- `_generate_with_openai_sdk()`
- `openai.AsyncOpenAI` を使う暫定経路
- `agent_framework` が見つかったら `AgentConfigurationError` にする処理

### 4.2 追加した import

```python
from agent_framework import Content, Message
from agent_framework.openai import OpenAIChatClient
```

### 4.3 client / agent 作成

初期実装では app 側の `SessionStore` が履歴を管理するため、Agent Framework の `AgentSession` は使わない。毎回 app 履歴を `Message` に変換し、stateless に `agent.run()` する。

`system_prompt` は app 側の `ChatMessage(role="system")` として渡しているが、Agent Framework では `OpenAIChatClient.as_agent(instructions=...)` で system message として入れられる。

推奨方針:

- `build_agent_messages()` は当面そのまま system message を先頭に含めてよい。
- `MicrosoftAgentService.generate()` 側で先頭の system message を取り出して `instructions` に渡す。
- user / assistant の履歴だけを `agent.run(messages=...)` に渡す。

理由:

- Guild ごとの system prompt を Agent Framework の agent instructions として扱える。
- app 独自履歴と Agent Framework session の二重管理を避けられる。

### 4.4 実装方針

```python
class MicrosoftAgentService:
    def __init__(self, api_key_env: str = "OPENAI_API_KEY"):
        self.api_key_env = api_key_env
        self._clients: dict[tuple[str, str], OpenAIChatClient] = {}

    async def generate(self, messages: list[ChatMessage], settings: AgentSettings) -> AgentResult:
        if settings.provider != "openai":
            raise AgentConfigurationError(f"unsupported provider: {settings.provider}")

        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise AgentConfigurationError(f"{self.api_key_env} is required")

        client = self._get_client(settings, api_key)
        instructions, run_messages = self.convert_messages(messages, settings)

        agent = client.as_agent(
            instructions=instructions,
            default_options={
                "model": settings.model,
                "temperature": settings.temperature,
                "max_tokens": settings.max_tokens,
            },
        )
        response = await agent.run(run_messages)
        return AgentResult(text=response.text or "", raw=response)

    def _get_client(self, settings: AgentSettings, api_key: str) -> OpenAIChatClient:
        key = (settings.provider, settings.model)
        if key not in self._clients:
            self._clients[key] = OpenAIChatClient(model=settings.model, api_key=api_key)
        return self._clients[key]
```

`agent` 自体は `instructions` が Guild ごとに変わるため、client を cache し、agent は request ごとに作る方が扱いやすい。

## 5. message 変換の変更

### 5.1 変更前

現在の `convert_messages()` は OpenAI SDK chat completions 互換の dict を返している。

```python
{"role": "user", "content": [{"type": "text", "text": "..."}]}
```

### 5.2 変更後

Agent Framework の `Message` / `Content` へ変換する。

```python
def convert_messages(
    self,
    messages: list[ChatMessage],
    settings: AgentSettings,
) -> tuple[str | None, list[Message]]:
    instructions = None
    converted = []

    for message in messages:
        if message.role == "system":
            instructions = self._message_text(message)
            continue

        contents = []
        for part in message.content:
            if part.type == "text":
                contents.append(Content.from_text(part.text or ""))
            elif part.type == "image_url":
                contents.append(
                    Content.from_uri(
                        part.image_url or "",
                        media_type=self._guess_image_media_type(part.image_url or ""),
                    )
                )

        converted.append(Message(message.role, contents))

    return instructions, converted
```

### 5.3 画像 URL

現在の app model は `image_url` part に `detail` を持つが、Agent Framework の `Content.from_uri()` は `media_type` を受け取る。`detail` はそのまま渡せないため、初期対応では `detail` を Agent Framework 変換では使わない。

必要な追加関数:

```python
def _guess_image_media_type(url: str) -> str | None:
    path = urlparse(url).path.lower()
    if path.endswith(".png"):
        return "image/png"
    if path.endswith(".jpg") or path.endswith(".jpeg"):
        return "image/jpeg"
    if path.endswith(".webp"):
        return "image/webp"
    if path.endswith(".gif"):
        return "image/gif"
    return None
```

`image_detail` は将来、Agent Framework / provider 側に対応する option が確認できた時点で `additional_properties` または provider-specific option として再検討する。

## 6. response 抽出の変更

現状:

```python
text = response.choices[0].message.content or ""
return AgentResult(text=text, raw=response)
```

変更後:

```python
response = await agent.run(run_messages)
return AgentResult(text=response.text or "", raw=response)
```

空応答の fallback は既存どおり `ChatService` 側で行う。

## 7. テスト変更

### 7.1 既存テスト

既存の unit / service test は `FakeAgentService` 中心のため、大きな変更は不要。

継続して通す対象:

```bash
.venv/bin/python -m pytest tests/unit tests/service -m "not smoke"
```

### 7.2 追加した unit test

`MicrosoftAgentService.convert_messages()` のテストを追加済み。

確認観点:

- `system` message が `instructions` に分離される。
- user / assistant message が `agent_framework.Message` に変換される。
- text part が `Content.from_text()` 相当になる。
- image URL part が `Content.from_uri()` 相当になり、`media_type` が拡張子から推定される。
- `detail` は初期変換では捨てても session JSON 側には残る。

### 7.3 smoke test

real Agent Framework 呼び出しは API key が必要なため smoke test に分離する。

```bash
OPENAI_API_KEY=... .venv/bin/python -m bot.tools.chat_cli --guild-id 100 --text "こんにちは"
```

画像入力 smoke:

```bash
OPENAI_API_KEY=... .venv/bin/python -m bot.tools.chat_cli \
  --guild-id 100 \
  --text "この画像を説明して" \
  --image-url https://example.com/a.png
```

## 8. 設定変更

`setting.yaml` の構造は変更不要。

```yaml
agent:
  provider: "openai"
  model: "gpt-4.1"
  max_tokens: 1600
  temperature: 1.0
  image_detail: "low"
```

ただし `image_detail` は Agent Framework 変換では未使用になるため、ドキュメント上は以下の注記を追加する。

- `image_detail` は session JSON には保存する。
- Agent Framework への URL 画像入力では、初期対応では `Content.from_uri()` の `media_type` のみ指定する。
- provider 側で detail 相当の option が確認できたら再接続する。

## 9. Docker 変更

`dockerfile` は追加変更不要。`requirements.txt` に `agent-framework` が入れば build 時に install される。

注意点:

- `agent-framework` メタパッケージは依存が多く、Docker build 時間と image size が増える。
- 初期移行完了後、`agent-framework-core` + `agent-framework-openai` へ縮小できるか検証する。

## 10. 実装順序

1. `requirements.txt` に `agent-framework` を追加する。完了。
2. `agent_service.py` の OpenAI SDK fallback を削除する。完了。
3. `OpenAIChatClient` を使う `_get_client()` を追加する。完了。
4. `convert_messages()` を `Message` / `Content` 返却へ変更する。完了。
5. `generate()` で `client.as_agent(instructions=...)` と `agent.run()` を使う。完了。
6. `convert_messages()` の unit test を追加する。完了。
7. 既存 unit / service test を実行する。完了。
8. `chat_cli --fake-agent` を実行する。必要に応じて実行。
9. `OPENAI_API_KEY` ありで real CLI smoke test を実行する。未実施。

## 11. 残る確認事項

- `Content.from_uri()` で Discord CDN URL が OpenAI 側へそのまま渡るか。
- `gif` 入力が対象モデルで期待どおり処理されるか。
- `image_detail` 相当の指定方法が Agent Framework / OpenAI provider option にあるか。
- `agent-framework` メタパッケージではなく最小依存にできるか。
- `OpenAIChatClient.as_agent()` の `default_options` と `agent.run(options=...)` のどちらに model / temperature / max_tokens を寄せるか。初期実装では request ごとの設定差し替えを考え、`agent.run(options=...)` に寄せてもよい。
