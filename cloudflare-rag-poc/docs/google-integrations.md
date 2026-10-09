# Google連携（Drive・Gmail・カレンダー・マップ）

2026-10-09追加。管理画面の「ナレッジ登録」タブ →「＋ 連携するシステムを追加」から、Google の4つのサービスをつなげます。

| サービス          | 方式                                                            | 取り込むもの                                 | 同期                                        |
| ----------------- | --------------------------------------------------------------- | -------------------------------------------- | ------------------------------------------- |
| Google Drive      | OAuth（`drive.readonly`）。従来のサービスアカウント方式も併用可 | 指定フォルダ内のファイル                     | 手動実行（フォルダIDは「Drive同期」で設定） |
| Gmail             | OAuth（`gmail.readonly`）                                       | 検索式に合うメールの件名・差出人・日時・本文 | 手動実行のみ（cronなし）                    |
| Google カレンダー | OAuth（`calendar.readonly`）                                    | 予定（過去7日〜未来90日）                    | 毎日自動＋手動                              |
| Google マップ     | APIキー（secret `GOOGLE_MAPS_API_KEY`）                         | 場所の住所・電話番号・営業時間               | 単発の登録                                  |

すべて**読み取り専用**です。メールやファイルの書き込み・削除はできません。

## 一度だけ必要な準備（Google Cloud）

OAuthクライアントは、Gmail送信用に登録済みのもの（`GMAIL_OAUTH_CLIENT_ID` / `GMAIL_OAUTH_CLIENT_SECRET`）を共用します。新しいsecretは要りません。

1. 「APIとサービス」→「ライブラリ」で **Google Drive API** と **Gmail API**（カレンダーは **Google Calendar API**）を有効にする。
2. 「OAuth同意画面」のスコープに `drive.readonly`・`gmail.readonly`（・`calendar.readonly`）を加える。公開状態が「テスト」の間は、テストユーザーに自分のアカウントを追加する。
   - `gmail.readonly` は Google が「制限付き」とするスコープです。公開（本番）にはGoogleの審査が要るため、自分たちだけで使う間は「テスト」のままにします。テスト状態ではリフレッシュトークンが7日で失効するため、定期的に「再認証する」が必要です。
3. 「認証情報」→ OAuthクライアントの「承認済みのリダイレクトURI」に、次を追加する（`<worker>` はデプロイ先のドメイン）。
   - `https://<worker>/admin/oauth/google_drive/callback`
   - `https://<worker>/admin/oauth/gmail/callback`
   - （カレンダーは既存: `https://<worker>/admin/oauth/google_calendar/callback`）
4. マップは Google Cloud の **Places API** を有効にしたAPIキーを、`wrangler secret put GOOGLE_MAPS_API_KEY` で設定する。

## 使い方

1. 「＋ 連携するシステムを追加」でサービスを選び、「Googleで認証する」。Googleの同意画面で許可すると、管理画面へ戻る。
2. 同期する対象を設定する（ナレッジ登録タブの下部「同期・通知の設定」）。
   - **Drive**: 「Drive同期」のフォルダIDを入れて「Drive同期を実行」。
   - **Gmail**: namespace と検索式（例: `label:project-x newer_than:30d`）を入れ「同期元を設定」→「接続テスト」→「Gmail同期を実行」。「ラベルを取得」でラベルから検索式を作れる。
3. 失敗したメールは「失敗メールだけ再同期」で、その分だけやり直せる。

## Gmailの扱い（注意）

- **検索式が空のnamespaceは同期されません**（全メールの取り込みを防ぐため）。
- 取り込むのは件名・差出人・日時・本文のテキストだけ。**添付ファイルは取り込みません**。HTMLだけのメールはタグを除いたテキストにします。
- 登録したメールは、**そのnamespaceにアクセスできる全員が検索で見られます**。共有してよいラベルだけに絞るか、個人用namespaceへ入れてください。
- 1回の同期は最大500通。ナレッジ上のファイル名は「件名 (日付) #メッセージID」です（同じ件名でも区別でき、再試行で対象を復元できる）。
- 同じメールを再同期すると、同じファイル名で上書きされます。ナレッジから消す場合は、登録済みナレッジ一覧の「削除」を使います。

## 仕組み

- `src/googleOAuth.ts`: Drive・Gmail共通のOAuth（開始・コールバック・解除・トークン更新）。接続したアカウントのメールアドレスを表示用に保存。
- `src/gmailSync.ts`: Gmail同期（一覧→1通ずつ取得→本文抽出→登録）、失敗分の再試行、ラベル一覧、接続テスト。
- `src/driveSync.ts`: OAuth接続があればそれを使い、無ければサービスアカウントにフォールバック。
- `migrations/0020_gmail_source.sql`: `kb_sources.gmail_query`。
- テスト: 偽のGoogle/Gemini と SQLite で、OAuth接続・トークン更新・本文抽出・失敗と再試行・検索式なしの拒否・解除後の拒否を確認した（実際のGoogleアカウントでの通しは未確認）。
