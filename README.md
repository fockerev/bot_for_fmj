## 動作環境

dockerがインストール済みなこと

## ファイル構成
``` 
.
├── README.md
├── bot
│   ├── cogs
│   │   └── gpt.py
│   ├── logging_config.json     ロギング設定
│   ├── main.py                 main
│   ├── requirements.txt        依存ライブラリ
│   └── setting.yaml            Botの設定
├── docker-compose.yaml
└── dockerfile
```

## 使い方
1. dev portalでBotのintentsをすべて許可する
2. docker-compose.yamlに以下の環境変数の設定を行う

    |key|値|
    |---|---|
    |DISCORD_BOT_TOKEN|botのトークン|
    |OPENAI_API_KEY|OpenAIのAPIキー|
    |GUILD_ID|動作させるサーバーのID<br> カンマで区切って設定可能<br>ex)"12345, 6789"|
    |BOT_PREFIX|BotのPrefix|

3. 下記コマンドを実行

    ```bash
    cd [クローンしたフォルダ]
    docker compose up -d
    ```

    上記を実行したあとに設定など変更する場合は以下でイメージを再ビルドすること
    
    ```bash
    docker compose up --build -d
    ```

## その他

cogsファイル内にcogを定義したファイルを追加することで動作を追加できる
