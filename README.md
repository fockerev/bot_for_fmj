# Readme
## 動作環境

__下記環境以外での動作は保証しない__

|名称|Version|
|---|---|
|Python|3.11.6|
|Discord.py|2.3.2|
|OpenAI API|1.10.0|

## ファイル構成
``` 
./
│  .env                 Token等環境変数を記入するファイル
│  main.py              Botのmain処理
│  README.md            readme
│  requirements.txt     必要パッケージリスト
│  setting.yaml         設定ファイル
│ 
└─cogs
    └─ gtp.py           OpenAIを利用したBotモジュール
```

## 使い方
0. dev portalでBotのintentsをすべて許可する
1. .envファイルを作成
2. 下記キーを記入する

|key名|値|
|---|---|
|DISCORD_BOT_TOKEN|botのトークン|
|OPENAI_API_KEY|OpenAIのAPIキー|
|GUILD_ID|動作させるサーバーのID<br> カンマで区切って設定可能<br>ex)"12345, 6789"|
|BOT_PREFIX|BotのPrefix|

```
DISCORD_BOT_TOKEN="YOUR_BOT_TOKEN"
OPENAI_API_KEY="YOUR_API_KEY"
GUILD_ID="YOUR_SERVER_ID"
BOT_PREFIX="/"
```
3. 下記コマンドを実行
```bash
cd [クローンしたフォルダ]
pip install -r requirements.txt
```

4. Botを起動する
```bash
python main.py
```

## その他

cogsファイル内にcogを定義したファイルを追加することで動作を追加できる

## 更新履歴
#### 2024/02/05
- 入力する対話履歴の数を5に制限
- 複数のサーバーID入力に対応
#### 2024/02/08
- AIの返答にToken数上限付与
- Token使用量ランキングコマンド追加
#### 2024/06/02
- 入力する対話履歴の数を8に変更
- 画像ファイルの入力に対応
#### 2024/06/02
- 入出力の合計で使用量ランキングを作成するように変更
- 入力ファイル形式をpng/jpg/gifに制限し、非対応ファイルが入力されると非対応と応答するよう変更
#### 2024/09/18
- 設定ファイルに対応
- コマンドを追加
#### 2024/12/14
- ちょっとしたアップデート