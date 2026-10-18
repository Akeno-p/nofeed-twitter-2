# nofeed-twitter

フィードを見せず、「自分のツイートの投稿」と「自分のツイートへのリプライの確認・返信」だけができる、自分専用のX(Twitter)クライアントです。

- フロント: HTML / CSS (Tailwind) / jQuery
- サーバー: Django
- 認証: ユーザー名 + パスワード + 2段階認証 (TOTP)
- X連携: OAuth 2.0 (PKCE)

## 初回セットアップ

```sh
cd nofeed-twitter-2
python3 -m venv .venv                      # 作成済みなら不要
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser # ログイン用のユーザー名とパスワードを決める
```

## X Developer Console での準備

1. Developer Console でアプリを作成し、**OAuth 2.0** を有効にする
2. アプリの種類は **Web App (Confidential client)**、権限は **Read and write**
3. **Callback URL** に `http://127.0.0.1:8000/x/callback/` を登録 (`localhost` ではなく `127.0.0.1`)
4. Client ID と Client Secret を `.env` に書く (`.env.example` を参考に)

```
X_CLIENT_ID=...
X_CLIENT_SECRET=...
```

## 起動

```sh
.venv/bin/python manage.py runserver
```

`http://127.0.0.1:8000/` を開く。初回ログイン時に2段階認証のQRコードが出るので、認証アプリで読み取ります。
ログイン後、歯車 → 「Xアカウントを追加」でXと連携します。

## テスト

```sh
.venv/bin/python manage.py test
```

## CSSを変更したとき

Tailwind を使っています。`static/css/app.css` はビルド済みなので、そのまま動かすだけなら Node は不要です。
テンプレートのクラス名を変えたら再ビルドしてください。

```sh
npm install
npm run css
```

## 費用についての注意

X API は従量課金です。このアプリは API 呼び出しを減らすため、取得したツイートを `db.sqlite3` に保存し、
「ツイート取得」「リプライ取得」を押したときだけ、前回より新しい分を取りに行きます。
リプライは検索ではなく、料金の安い「自分へのメンション一覧」(Owned Reads) から取ります。
Owned Reads の安い料金は、Developer Console でアプリを作ったアカウント本人だけが対象です。
リンク (URL) を含む投稿は料金が高いので、投稿前に確認ダイアログが出ます (`example.com` のような書き方も対象)。

使いすぎを防ぐため、Developer Console で支払いの上限 (Spending limit) を設定しておくことをおすすめします。

## 保存される情報

`db.sqlite3` に、Xのアクセストークン・更新トークン、2段階認証の秘密鍵、取得したツイートが入ります。
`.env` と `db.sqlite3` は他人に渡さず、Git などにも入れないでください (`.gitignore` 済み)。
