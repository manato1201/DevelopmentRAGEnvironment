# Cloudflare RAG 検証環境（POC）

**位置づけ:** [docs/cloud-local-unification-plan.md](../docs/cloud-local-unification-plan.md) の統合方針を、実際に動かして検証・チューニングするための別環境。

**このフォルダは本番の `scripts/gas_cloud_rag.js`（Cloud RAG）・`scripts/rag_service.py`（Local RAG）には一切影響しません。** 実証実験（9月〜）が終わるまで、この検証環境の結果に関わらず本番は現行構成のまま動き続けます。

## 実装済みの内容

- `POST /search` — 既存の `rag_local_bridge.py` の `/search` と同一のリクエスト/レスポンス契約（`docs/cloud-local-unification-plan.md` §8.3）。**ハイブリッド検索**（Vectorizeのベクトル検索 ＋ D1 FTS5のBM25キーワード検索をRRFで統合）と**HyDE**（質問文の代わりに仮回答を生成してから埋め込む）を実装済み
- `POST /query` — LLMによる最終回答まで生成するチャット用エンドポイント（`/search`は検索結果のみを返す「生」の経路）。回答文中の`[1]`等の出典番号を検知して引用率（`extractionRate`）を算出する、既存GASのハルシネーション対策と同じ仕組みを実装
- `POST /ingest` — 検証用の投入エンドポイント（本番のNotion/ChromaDB連携は行わない）。GeminiでベクトルEmbeddingを作りVectorizeへ、同時にD1 FTS5テーブルにも書き込む
- **トークン予算の実強制** — `token_budgets`テーブルの残量をリクエスト前にチェックし（`assertBudgetAvailable`）、実際に使ったトークン数を都度加算する（`consumeBudget`）。上限到達時は`429`を返す。予算レコードが無いユーザーは無制限（開発用の既定動作）
- **チャット履歴（メモリ）** — `/query`成功のたびに会話を`memory`テーブルへ保存し、`POST /memory/list`で直近履歴を取得、`POST /memory/rate`で回答の役立ち度（👍/👎）を記録できる（既存GAS `saveMemory_`/`getUserMemory`/`rateMemoryEntry`相当）
- **Webチャット画面** — `GET /`（または`/chat`）でブラウザから直接使えるチャットUIを提供。APIキー入力・レベル選択・出典引用率の表示・評価ボタン・履歴読み込みに対応（既存GAS `getChatHtml_`相当、軽量版）
- **知識ベース同期（Notion / Google Drive）** — `POST /admin/sync/notion`・`POST /admin/sync/drive`で、Notionデータベースの各ページ本文、またはDriveフォルダ内のGoogleドキュメント/プレーンテキストを取得し、チャンク分割→Gemini埋め込み→Vectorize+FTS5への登録まで自動で行う（既存GAS `syncNotionToSheets`/`syncDriveToSheets`相当）。管理者ロールのみ実行可能。**PDF/DOCX/音声/動画の変換・文字起こしは未対応**（下記「今後チューニングすべき点」参照）
- **Admin API（APIキー発行・namespace管理）** — `/admin/keys/*`でAPIキーの発行（生成した鍵はその場限りでしか取得できない）・一覧・削除・namespace許可の変更・トークン予算の上限設定＋自動リセット間隔・残量補充。`/admin/namespaces/*`でnamespaceの作成・一覧・削除。いずれも管理者ロールのみ（既存GAS `adminCreateKey`/`adminListKeys`/`adminUpdateKey`/`adminSetKeyCapacity`/`adminChargeKeyBalance`/`adminCreateNamespace`/`adminListNamespaces`相当）
- D1（`migrations/`配下、0001〜0005）— users / namespaces / token_budgets / audit_log / memory / kb_sources / kb_log / key_namespace_grants の各テーブル＋FTS5仮想テーブル`chunks_fts`
- Vectorize 2インデックス（`VEC_SHARED` / `VEC_PERSONAL`）による共有・個人スコープの分離
- APIキー（SHA-256ハッシュ）によるユーザー認証、**キーごとの共有namespaceアクセス制御**（`key_namespace_grants`、adminロールは無条件に全shared namespaceを閲覧可）、adminロールによる管理operationの制限

**⚠️ 挙動の変更（2026-08-24、Admin API実装に伴う）：** これまでは「全ユーザーが全shared namespaceを閲覧できる」という簡略化した挙動だったが、GAS本来の「キーごとに見られるnamespaceを制御する」設計に合わせて厳格化した。**既存ユーザーは移行時に自動で全shared namespaceへの許可を付与済み**（`migrations/0005_key_admin.sql`のバックフィル）なので既存の動作確認には影響しないが、**今後`/admin/keys/create`で新規発行するキーは、`namespaces`を明示的に指定しない限りどのshared namespaceも見えない**点に注意。

**動作確認済み（2026-08-25）：** `https://rag-poc.manato1201m.workers.dev` に実際にデプロイし、`/ingest`→`/search`（ハイブリッド検索+HyDE）→`/query`（Gemini生成回答+引用率算出+メモリ保存）→`/memory/list`→`/memory/rate`→トークン予算の消費記録→`GET /`のチャットUI表示→`/admin/kb/set-source`→`/admin/kb/history`→adminロール強制（非adminは403）→Admin API一式（キー発行・namespace許可・予算上限・カスケード削除）→**実際のNotionデータベース（Houdini21、80ページ、既存`cloud-rag-bot`インテグレーション経由）の完全同期→実内容に基づく正確な引用付き回答の生成**、まで実データで確認済み。**Google Drive実同期**（`/admin/sync/drive`）はまだ未検証（Notionと同じ設計のため恐らく動くはずだが、サービスアカウントでの実行はこれから）。

## 設計書からの変更点（実装してみて分かったこと）

設計書§6-1では「個人スコープはユーザーごとに別インデックス（物理分離）」を推奨していたが、**Cloudflare WorkersのVectorizeバインディングはwrangler設定ファイルに静的に書く必要があり、ユーザー登録のたびに新しいインデックスを動的に作成・バインドすることができない**ことが実装時に判明した（Workers for Platforms等を使えば可能だが、複雑さに見合わない）。

そのため、この検証環境では**個人スコープも1本の共通インデックス（`VEC_PERSONAL`）にし、`owner_user_id`メタデータでの厳格なフィルタ**（`search.ts`・`ingest.ts`で強制）によって論理分離する方式にした。ただし通常の論理分離（アクセス制御層のバグが即座に情報漏洩に直結する）とは異なり、**書き込み時・検索時の両方でowner_user_idの一致を必須にする**ことで、実質的に「物理分離に近い安全性」を確保している。この点は設計書§6-1の推奨案の実装上の妥協点として認識しておくこと。

## セットアップ手順

```bash
cd cloudflare-rag-poc
npm install
```

### 1. Cloudflareにログイン（初回のみ）

```bash
npx wrangler login
```

### 2. D1データベースを作成

```bash
npx wrangler d1 create rag-poc-db
```

出力される `database_id` を `wrangler.jsonc` の `REPLACE_WITH_D1_DATABASE_ID` に貼り付ける。

### 3. Vectorizeインデックスを2つ作成

```bash
npx wrangler vectorize create rag-poc-shared --dimensions=768 --metric=cosine
npx wrangler vectorize create rag-poc-personal --dimensions=768 --metric=cosine
```

### 3.5. メタデータインデックスを作成（★これを飛ばすと`/search`が常に0件になる）

Cloudflare Vectorizeは、metadataでフィルタする（`filter: {namespace: {...}}`のような）クエリを行う前に、**そのプロパティ用のメタデータインデックスを明示的に作成しておく必要がある**。さらに重要な点として、**このインデックスは作成後に投入されたベクトルにしか効かず、既存のベクトルは遡って対象にならない**（動作確認で実際にハマった）。そのため、**必ずこの手順をデータ投入（`/ingest`）より先に実行すること**：

```bash
npx wrangler vectorize create-metadata-index rag-poc-shared --property-name=namespace --type=string
npx wrangler vectorize create-metadata-index rag-poc-personal --property-name=namespace --type=string
npx wrangler vectorize create-metadata-index rag-poc-personal --property-name=owner_user_id --type=string
```

作成状況は `npx wrangler vectorize list-metadata-index rag-poc-shared` で確認できる。

### 4. Gemini APIキーをシークレット登録

```bash
npx wrangler secret put GEMINI_API_KEY
```

### 5. D1マイグレーション適用

```bash
npm run db:migrate:local   # ローカル検証用
npm run db:migrate:remote  # 実際にCloudflareへデプロイして試す場合
```

`migrations/0001_init.sql` には動作確認用のテストユーザー（`display_name: Dev Test User`）が1件入っている。このユーザーのAPIキーは任意の文字列でよいが、**そのSHA-256ハッシュ値が `dev-test-user-hash` という文字列のハッシュと一致するわけではない**（このマイグレーションはプレースホルダとしてハッシュ値をそのまま`user_id`に入れているだけ）。実際に動作確認する際は、以下のいずれかの方法でテストユーザーを作り直すこと：

**PowerShell（このプロジェクトの標準シェル）の場合：**

```powershell
$key = "my-test-key"
$hash = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($key))) -replace '-', ''
$hash.ToLower()
```

得られたハッシュ値で、リモートDBのテストユーザーを更新する（`--local`に変えればローカル検証用DBも同様に更新できる）：

```powershell
npx wrangler d1 execute rag-poc-db --remote --command "UPDATE users SET user_id='<上で得たハッシュ値>' WHERE user_id='dev-test-user-hash'; UPDATE namespaces SET owner_user_id='<上で得たハッシュ値>', namespace_id='personal:<上で得たハッシュ値>' WHERE owner_user_id='dev-test-user-hash'; UPDATE token_budgets SET user_id='<上で得たハッシュ値>' WHERE user_id='dev-test-user-hash';"
```

### 6. ローカルで起動、またはCloudflareへデプロイ

```powershell
npm run dev      # ローカル起動（Vectorizeは動かない、下記注意参照）
npm run deploy   # 実際にCloudflareへデプロイして試す場合
```

**注意：VectorizeにはWranglerのローカルエミュレーションが存在しない**（`wrangler dev`実行時に`Vectorize Index bindings do not support local development`という警告が出る。動作確認済み）。`/health`とD1周りの動作はローカルのみで確認できるが、`/search`・`/ingest`（Vectorizeへの読み書きを伴う）を試すには、`wrangler.jsonc`のVectorizeバインディングに`"remote": true`を追加するか、`npm run deploy`で実際にCloudflareへデプロイしてから試す必要がある。VectorizeはCloudflareの有料プラン（Workers Paid）が必要な点にも留意。

**`npm run deploy`実行時に「workers.dev subdomainを登録してください」というエラーが出た場合：** このCloudflareアカウントでWorkersを初めて使うため、`https://dash.cloudflare.com/<アカウントID>/workers/onboarding`（エラーメッセージ内にリンクが表示される）で一度だけ手動登録が必要（対話プロンプトが必要なため自動化できない）。登録後、再度`npm run deploy`を実行すれば`https://rag-poc.<サブドメイン>.workers.dev`にデプロイされる。

## 動作確認

**PowerShellでは`curl`が`Invoke-WebRequest`のエイリアスになっており、`-X`/`-H`/`-d`等の本来のcurl構文が使えない。** 必ず`curl.exe`と明示するか、`Invoke-RestMethod`を使うこと。以下は`curl.exe`版（`my-test-key`は上記手順5で決めたAPIキー文字列に、URLは`localhost:8787`かデプロイ後のworkers.dev URLに置き換える）：

```powershell
# ヘルスチェック
curl.exe http://localhost:8787/health

# データ投入
curl.exe -X POST http://localhost:8787/ingest -H "Authorization: Bearer my-test-key" -H "Content-Type: application/json" -d '{\"chunks\":[{\"text\":\"HoudiniのScatterノードは、ポイントを面や体積上にランダム配置する。\",\"file\":\"scatter.md\",\"namespace\":\"shared:houdini21\",\"difficulty\":\"basic\"}]}'

# 検索
curl.exe -X POST http://localhost:8787/search -H "Authorization: Bearer my-test-key" -H "Content-Type: application/json" -d '{\"query\":\"ポイントをランダムに配置する方法は？\",\"limit\":3}'
```

PowerShellでは`'...'`の中の`"`はエスケープ不要なはずが、`curl.exe`に渡す際は二重引用符をバックスラッシュでエスケープする必要がある点に注意（上記の`\"`はそのまま貼り付けてよい）。`Invoke-RestMethod`を使う場合はエスケープ不要でより素直に書ける：

```powershell
Invoke-RestMethod -Uri http://localhost:8787/search -Method Post -Headers @{Authorization="Bearer my-test-key"} -ContentType "application/json" -Body (@{query="ポイントをランダムに配置する方法は？"; limit=3} | ConvertTo-Json)
```

`/search` のレスポンスが `docs/cloud-local-unification-plan.md` §8.3の契約通り `{texts, sources, status}` の形で返ってくることを確認する。

**推奨：日本語を含むリクエストはインラインで打たず、UTF-8ファイル経由で送る。** コマンドラインに直接日本語を埋め込むと、シェルの文字コード変換で化けることがある（下記トラブルシューティング参照）。JSONファイルを用意して`--data-binary @path\to\file.json`（`curl.exe`）または`Get-Content -Raw -Encoding UTF8`で読み込んで渡す方が安全。

`/query`（LLM回答生成込み）も試す場合：

```powershell
curl.exe -X POST http://localhost:8787/query -H "Authorization: Bearer my-test-key" -H "Content-Type: application/json" --data-binary "@query.json"
```

`query.json`の中身は`{"query": "...", "limit": 5}`。レスポンスは`{answer, sources, status, namespaces, extractionRate, extractionDetail}`（`extractionRate`は回答が出典番号`[1]`等をどれだけ引用しているかの割合。低い場合は「AIが出典を示さずに答えている」可能性があるサイン）。

## 知識ベース同期のセットアップ（Notion / Google Drive）

`/admin/sync/notion`・`/admin/sync/drive`を使うには、それぞれの認証情報を別途用意する必要がある。**adminロールのユーザーのAPIキーでのみ実行できる**（`src/auth.ts`の`requireAdmin`）。

### Notion側の準備

1. https://www.notion.so/my-integrations で「新しいインテグレーション」を作成し、**Internal Integration Secret**（`ntn_...`のような文字列）を控える
2. 同期したいNotionデータベースを開き、右上の「…」→「コネクト」から、作成したインテグレーションを追加する（これをしないと、そのデータベースにインテグレーションからアクセスできない）
3. データベースのURL（`https://www.notion.so/xxxx?v=yyyy`の`xxxx`部分、ハイフン無し32文字）が`notionDatabaseId`

```bash
npx wrangler secret put NOTION_API_KEY
```

### Google Drive側の準備

1. GCPコンソールでサービスアカウントを作成し、JSON形式のキーをダウンロードする（**Drive APIを有効化**しておくこと）

   **⚠️ 組織ポリシー`iam.disableServiceAccountKeyCreation`によりキー作成がブロックされる場合がある。** Googleが2025年以降の新規プロジェクトに自動適用している「デフォルトで保護」のセキュリティ既定値の一つで、個人のGmailアカウントで作成したプロジェクトでも遭遇する（実際にこのPOCのセットアップ中に発生）。対処は2通り：
   - **(推奨・最短) この制約を自分のプロジェクトに限って無効化する**：GCPコンソール → 「IAMと管理」→「組織のポリシー」→ `iam.disableServiceAccountKeyCreation` を検索 → 「ポリシーを管理」→ このプロジェクトに対するルールを追加し「適用しない」に設定 → 保存。エラー画面に出た`roles/orgpolicy.policyAdmin`ロールが自分に無い場合は、「IAMと管理」→「IAM」で自分自身にそのロールを付与してから再試行する。
   - **(代替) サービスアカウントキーを使わずOAuthのリフレッシュトークン方式にする**：同じGCPプロジェクトでOAuthクライアント（デスクトップアプリ種別）を作成し、一度だけブラウザで認可フローを行ってリフレッシュトークンを取得、それを`client_id`/`client_secret`と共にシークレットとして保存する。Worker側は`https://oauth2.googleapis.com/token`に`grant_type=refresh_token`でPOSTしてアクセストークンを得る（サービスアカウントの秘密鍵署名は不要になる）。OAuthクライアントの作成自体はこの組織ポリシーの対象外のため、上記の権限昇格ができない環境でもこちらなら通る。**このPOCの`src/googleAuth.ts`は現状サービスアカウント方式のみ実装済み。OAuth方式が必要な場合は別途実装が必要。**

2. 同期したいDriveフォルダを、サービスアカウントのメールアドレス（`xxx@yyy.iam.gserviceaccount.com`の形式）と**閲覧者権限で共有**する
3. ダウンロードしたJSONキーファイルの中身をまるごとシークレットに設定する：

```bash
npx wrangler secret put GOOGLE_SERVICE_ACCOUNT_JSON
# プロンプトでJSONファイルの中身（1行にまとめたもの）を貼り付ける
```

4. フォルダのURL（`https://drive.google.com/drive/folders/xxxx`の`xxxx`部分）が`driveFolderId`

### namespaceに同期元を設定してから実行する

```powershell
# 1. namespaceに同期元を紐付ける（先にnamespacesテーブルへnamespace自体が存在している必要あり）
curl.exe -X POST http://localhost:8787/admin/kb/set-source -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"namespace\":\"shared:houdini21\",\"notionDatabaseId\":\"<Notion DB ID>\",\"driveFolderId\":\"<Drive フォルダID>\"}'

# 2. Notion同期を実行
curl.exe -X POST http://localhost:8787/admin/sync/notion -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"namespace\":\"shared:houdini21\"}'

# 3. Drive同期を実行
curl.exe -X POST http://localhost:8787/admin/sync/drive -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"namespace\":\"shared:houdini21\"}'

# 4. 同期結果の履歴を確認
curl.exe -X POST http://localhost:8787/admin/kb/history -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"limit\":20}'
```

`/admin/sync/notion`・`/admin/sync/drive`のレスポンスは`{status, opId, documents, chunks, skipped, totalPages/totalFiles, processedRange, nextIndex}`。`skipped`には「本文が空」「未対応のmimeType」等でスキップされたファイルの一覧が入るので、想定より件数が少ない場合はここを確認する。

**★バッチ処理が必須（実際のHoudini21データベース同期で判明）：** 1リクエストで全ページを処理しようとするとCloudflareの「サブリクエスト数上限」に達して途中で失敗する（80ページ中20ページ弱で発生した）。そのため両エンドポイントとも`startIndex`・`batchSize`（既定5件）を受け取り、レスポンスの`nextIndex`が`null`になるまで**同じ`opId`を渡しながら繰り返し呼び出す**設計にしている：

```python
# 実際に80ページのNotion同期で使用したループの骨子
op_id = None
start_index = 0
while True:
    body = {"namespace": "shared:houdini21", "startIndex": start_index, "batchSize": 5}
    if op_id:
        body["opId"] = op_id
    resp = call_api("/admin/sync/notion", body)
    op_id = resp["opId"]
    if resp["nextIndex"] is None:
        break
    start_index = resp["nextIndex"]
```

**現時点で未対応：** DriveのPDF/Word文書（バイナリ形式）の変換、音声/動画ファイルの文字起こし（既存GAS `_convertBinaryBlobToText_`/`_transcribeAudioVideoBlob_`相当）。Googleドキュメント（ネイティブ形式）とプレーンテキスト/Markdownファイルのみ対応。

**実データでの動作確認済み（2026-08-25）：** 実際のNotionデータベース（Houdini21、80ページ）を`cloud-rag-bot`インテグレーション経由で全件同期し、133チャンクを登録。その後`/query`で実際の内容（PDG/TOPsタスクグラフについて）を尋ねたところ、正しい情報源を引用した正確な回答が生成されることを確認した（引用率100%）。

## ヘルスチェック・アラート通知のセットアップ（Slack / Gmail）

30分ごとのCron Triggerで、D1接続・直近1時間のKB同期エラー・トークン予算枯渇間近を自動チェックする。問題があれば設定済みのチャンネルへ通知する。**どちらも未設定のままでもエラーにはならない**（該当チャンネルへの送信をスキップするだけ）。

### Slack（推奨・数分で設定できる）

1. Slackで対象チャンネルの「連携アプリを追加」→「Incoming Webhook」を有効化し、Webhook URLを発行する
2. シークレットとして登録する：

```bash
npx wrangler secret put SLACK_WEBHOOK_URL
# プロンプトで https://hooks.slack.com/services/... を貼り付ける
```

### Gmail（個人アカウントのOAuthリフレッシュトークン方式）

サービスアカウント＋Domain-Wide Delegation方式は**Google Workspace限定の機能**で、個人のgmail.comアカウントでは設定できないことが判明したため、代わりに「一度だけブラウザでOAuth同意し、得られたリフレッシュトークンを保存しておく」方式にした（`src/gmailOAuth.ts`）。

1. GCPコンソール →「APIとサービス」→「有効なAPIとサービス」から**Gmail APIを有効化**する（未有効だと`accessNotConfigured`エラーになる。実際に一度遭遇した）
2. GCPコンソール → 「APIとサービス」→「認証情報」→「認証情報を作成」→「OAuthクライアントID」→ アプリケーションの種類は**「デスクトップアプリ」**を選択して作成する
3. 発行された「クライアントID」「クライアントシークレット」を控える
4. この2つの値を使って、一度だけ認可コードを取得しリフレッシュトークンに交換する（Claude側で対話的に実施できる：ローカルで一時的にコールバックを受け取るサーバーを立て、認可URLをブラウザで開いて同意するだけ）
5. 得られたリフレッシュトークンをシークレットとして登録する：

```bash
npx wrangler secret put GMAIL_OAUTH_CLIENT_ID
npx wrangler secret put GMAIL_OAUTH_CLIENT_SECRET
npx wrangler secret put GMAIL_OAUTH_REFRESH_TOKEN
npx wrangler secret put GMAIL_ALERT_TO
# プロンプトで、アラートの送信先メールアドレス（同意したアカウント自身のアドレスでよい）を貼り付ける
```

### 動作確認

```bash
curl.exe -X POST http://localhost:8787/admin/health/test-alert -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{}'
# {"results":{"slack":"ok","gmail":"未設定（...)"},"status":"ok"} のように、設定した分だけ ok が返る
```

## Claude APIプロキシのセットアップ（Houdiniチュートリアル生成用）

`houdini/python_panels/tutorial_agent.py`が従来GAS経由で行っていたClaude Messages API呼び出しを、Cloudflare側でも受けられるようにしたもの。RAG自体には使わない（RAGは引き続きGeminiのみ）。

```bash
npx wrangler secret put ANTHROPIC_API_KEY
```

ユーザーごとにClaude専用のトークン予算を設定したい場合（任意。未設定なら無制限）：

```bash
curl.exe -X POST http://localhost:8787/admin/keys/set-capacity -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"userId\":\"<対象のuserId>\",\"budgetType\":\"claude\",\"limitTokens\":500000}'
```

呼び出し例（`tutorial_agent.py`が送るのとほぼ同じ形。`model`省略時は`claude-sonnet-5`）：

```bash
curl.exe -X POST http://localhost:8787/claude/messages -H "Authorization: Bearer <APIキー>" -H "Content-Type: application/json" -d '{\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}],\"max_tokens\":256}'
```

## Admin APIの使用例

すべて管理者ロールのAPIキーが必要（`verify-test-key`のような動作確認用テストユーザーは`role='admin'`で作成している）。

```powershell
# 新しいAPIキーを発行（namespacesを指定しないと、そのキーはどのshared namespaceも見えない）
curl.exe -X POST http://localhost:8787/admin/keys/create -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"displayName\":\"チームメンバーA\",\"role\":\"member\",\"namespaces\":[\"shared:houdini21\"],\"ragCapacity\":100000}'
# レスポンスの apiKey は生成時にしか表示されない。渡す相手に控えてもらうこと

# 発行済みキーの一覧（生のキーは表示されない、userIdで識別する）
curl.exe -X POST http://localhost:8787/admin/keys/list -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{}'

# 見られるnamespaceを変更する（既存の許可を全て置き換える）
curl.exe -X POST http://localhost:8787/admin/keys/update-namespaces -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"userId\":\"<対象のuserId>\",\"namespaces\":[\"shared:houdini21\",\"shared:tool_docs\"]}'

# トークン予算の上限・自動リセット間隔を設定（resetIntervalHoursを省略すると自動リセットなし）
curl.exe -X POST http://localhost:8787/admin/keys/set-capacity -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"userId\":\"<対象のuserId>\",\"limitTokens\":100000,\"resetIntervalHours\":24}'

# 残量を補充する（used_tokensを減算する）
curl.exe -X POST http://localhost:8787/admin/keys/charge -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"userId\":\"<対象のuserId>\",\"amount\":50000}'

# キーを削除する（個人namespace・予算・メモリ・namespace許可も連鎖的に削除される）
curl.exe -X POST http://localhost:8787/admin/keys/delete -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"userId\":\"<対象のuserId>\"}'

# namespaceの作成・一覧・削除
curl.exe -X POST http://localhost:8787/admin/namespaces/create -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"namespaceId\":\"shared:new_topic\",\"scope\":\"shared\"}'
curl.exe -X POST http://localhost:8787/admin/namespaces/list -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{}'
curl.exe -X POST http://localhost:8787/admin/namespaces/delete -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"namespaceId\":\"shared:new_topic\"}'

# namespaceごとの参考資料数上限を設定（resultLimitにnullを渡すと解除）
curl.exe -X POST http://localhost:8787/admin/namespaces/set-limit -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"namespaceId\":\"shared:cedecnotes\",\"resultLimit\":2}'

# URLの本文を取得してnamespaceへ登録
curl.exe -X POST http://localhost:8787/admin/kb/import-url -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"namespace\":\"shared:tool_docs\",\"url\":\"https://example.com/docs\"}'

# QA CSVの一括登録（バッチ処理。nextIndexがnullになるまでstartIndex/opIdを更新して呼び続ける）
curl.exe -X POST http://localhost:8787/admin/kb/import-qa-csv -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" --data-binary @qa.json

# opId単位でロールバック（同期履歴の一覧から対象のopIdを確認する）
curl.exe -X POST http://localhost:8787/admin/kb/rollback -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"opId\":\"op_1234567890_ab12cd\"}'

# 利用統計・評価統計
curl.exe -X POST http://localhost:8787/admin/usage/stats -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"days\":14}'
curl.exe -X POST http://localhost:8787/admin/rating-stats -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{}'

# YouTube動画を文字起こし登録
curl.exe -X POST http://localhost:8787/admin/kb/import-youtube -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{\"namespace\":\"shared:tool_docs\",\"youtubeUrl\":\"https://www.youtube.com/watch?v=xxxx\"}'

# PDF/DOCX/PPTX/音声/動画ファイルを直接アップロードして登録（fileBase64はbase64エンコード済みのファイル内容）
curl.exe -X POST http://localhost:8787/admin/kb/upload-doc -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" --data-binary @upload.json

# ヘルスチェック（手動実行）・テスト通知
curl.exe -X POST http://localhost:8787/admin/health/check -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{}'
curl.exe -X POST http://localhost:8787/admin/health/test-alert -H "Authorization: Bearer <adminのAPIキー>" -H "Content-Type: application/json" -d '{}'
```

## 型チェック

```bash
npm run typecheck
```

## トラブルシューティング（実際に遭遇したエラーと対処）

### `Invalid property: databaseId => Invalid uuid [code: 7400]`

`wrangler d1 create` を実行すると、wranglerが`wrangler.jsonc`に**新しいd1_databasesエントリを自動追記する**ことがある（`binding: "DB"`のプレースホルダとは別に、`binding: "rag_poc_db"`のような名前で実IDのエントリが増える）。同じ`database_name`のエントリが2つになり、`--remote`マイグレーション実行時にどちらを使うか曖昧になってエラーになる。**対処：自動追記されたエントリは削除し、もとの`binding: "DB"`エントリの`database_id`を実際のIDに書き換える**（このファイルは既に修正済み）。`wrangler vectorize create`でも同様に`binding: "VECTORIZE"`という重複エントリが自動追記されることがあるので、同様に整理すること。

### `table users already exists at offset 13: SQLITE_ERROR`（ローカルのみ）

`wrangler d1 execute --local --file=...`で直接SQLを実行した後に、`wrangler d1 migrations apply --local`（`npm run db:migrate:local`）を実行すると、マイグレーション管理テーブルが「まだ未適用」と認識したまま同じSQLを再実行しようとして失敗する。**対処：`npm run dev`を止めてから`.wrangler`フォルダを削除し（`Remove-Item -Recurse -Force .wrangler`）、`npm run db:migrate:local`をやり直す。** `--remote`側（実際のCloudflare上のD1）はこの問題と無関係で、正常に動作することを確認済み。

### PowerShellで`curl -X ...`が動かない

上記「動作確認」参照。`curl`は`Invoke-WebRequest`のエイリアスなので`curl.exe`と明示すること。

### `/search`がヒットするはずなのに常に`検索結果（0 件）`になる

ほぼ確実に**メタデータインデックス未作成**（上記3.5）が原因。`wrangler vectorize list-metadata-index <index名>`で確認し、無ければ作成する。**既にデータを投入済みの場合、そのベクトルは遡ってフィルタ対象にならない**ため、メタデータインデックス作成後に該当ベクトルを`wrangler vectorize delete-vectors`で削除し、`/ingest`から再投入すること。動作確認でも実際にこの手順で解決した。

### Gemini embedding APIが`404 NOT_FOUND`を返す

`text-embedding-004`はGoogle側で廃止されている（2026-08-23確認）。`wrangler.jsonc`の`EMBEDDING_MODEL`は`gemini-embedding-001`に変更済み。このモデルは次元数を指定しないと3072次元で返るため、`src/embeddings.ts`で`outputDimensionality: 768`を明示している（Vectorizeインデックスの次元数と一致させる必要がある）。

### 日本語テキストが`/search`・`/query`のレスポンスで文字化けする、またはFTS5が`syntax error near "@"`を返す

Worker側のバグではなく、**動作確認時にコマンドラインへ直接日本語を含むJSONを埋め込んだこと自体が原因**になりうる（Windows上のシェルは、多バイト文字を含むコマンドライン引数をネイティブexe（`curl.exe`等）へ渡す際にロケール依存のエンコーディング変換を挟むことがある）。文字化けした結果、たまたま`@`等のFTS5クエリ構文上意味を持つ文字が紛れ込むと、`chunks_fts MATCH`が構文エラーになる（動作確認でも実際にこのパターンでエラーを再現した）。対処：`-d '...'`で直接埋め込まず、UTF-8で保存したJSONファイルを`--data-binary @path\to\file.json`で渡す。動作確認でも、直接埋め込んだリクエストのみ文字化け・エラーになり、ファイル経由のリクエストは正常だった。

### Vectorizeが`id too long; max is 64 bytes`を返す（知識ベース同期で発生）

VectorizeのベクトルIDは64バイト上限だが、`${namespace}:${file}:${chunkIndex}`のように**ページタイトルをそのままIDに使っていた**ため、日本語の長いタイトル（UTF-8で1文字3バイト）で簡単に超過した。実際のHoudini21データベース同期（80ページ）で発生し、該当ページがすべて`skipped`扱いになった。対処：`src/kbIngest.ts`・`src/ingest.ts`で、IDを`sha256(namespace + file)の先頭40文字 + ":" + chunkIndex`というハッシュベースの固定長に変更した（人間が読めるファイル名は`metadata.file`にそのまま残す）。**この修正より前に投入したデータは古い形式のIDのまま残るため、再同期する場合は事前に`wrangler vectorize delete-vectors`で削除しておくこと。**

### 知識ベース同期が`Too many subrequests by single Worker invocation`で一部失敗する

Cloudflareの「1リクエストあたりのサブリクエスト数上限」（有料プランで1,000）に、Notion/Driveの1ページあたり複数回のfetch呼び出し（本文取得＋チャンクごとの埋め込み）が積み重なって到達する。実際にHoudini21（80ページ）の同期で、20ページに満たない時点でこのエラーが出た。対処：`/admin/sync/notion`・`/admin/sync/drive`を`startIndex`・`batchSize`・`opId`によるバッチ処理に変更した（上記「知識ベース同期のセットアップ」参照）。1回のリクエストで全件を同期しようとせず、`nextIndex`が`null`になるまでループで呼び出すこと。

### Drive同期の管理タブボタンで`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`エラーになる

実機で`shared:cedecnotes`（PDF/PPTX中心のフォルダ）に対して管理タブの「Drive同期を実行」ボタンを押したところ発生（2026-08-26）。原因はタイムアウト：Drive同期はPDF/PPTX/音声動画の変換（Gemini呼び出し込み）を挟むため1ファイルあたりが大幅に遅く、UIが使っていた`batchSize=5`だと1リクエストが**115秒**もかかることを実際に計測で確認した。ブラウザ・中継プロキシ側のタイムアウトでリクエストが打ち切られ、Cloudflareのエッジ（またはブラウザ自身）がHTMLのタイムアウトページを返し、それを`JSON.parse()`しようとして「Unexpected token '<'」エラーになる。対処：管理タブの「Drive同期を実行」ボタンは`batchSize=1`に固定した（Notionは変換が無く速いので`batchSize=5`のまま）。あわせて、`api()`ヘルパーがJSON以外の応答を受け取った場合に「タイムアウトの可能性、batchSizeを下げて再試行」という分かりやすいエラーメッセージを出すようにした。

### `batchSize=5`でも一部ページだけ`Too many subrequests`で失敗する

`shared:cedecnotes`（40ページ）の同期で、`batchSize=5`のバッチ処理化（上記対策済み）にも関わらず8ページだけ失敗した。原因は**1ページ単体の内容量が大きく**、そのページ1件だけでブロック取得＋チャンク埋め込みの呼び出し回数が嵵み、同じバッチ内の他ページ分と合算してサブリクエスト数上限を超えたため（バッチ全体の合計値の問題であり、個別ページの単純な大きさだけが原因ではない）。対処：失敗したnamespaceだけ`batchSize=1`に落として再実行する（`/admin/kb/set-source`は変更不要、`/admin/sync/notion`の`batchSize`パラメータだけ変えて`startIndex=0`からやり直せば、既存の成功済みチャンクはID一致で上書き＝重複しない）。実際にこの方式で8件の失敗が0件になった。**目安：同期が一部失敗する場合はまず`batchSize`を下げて再実行する。**

### Notion同期で「0ページ」と返るデータベースがある（エラーではない）

複数のNotionデータベースID（`DB_GAME_INFO`/`DB_HOUDINI22`/`DB_RESEARCH`/`DB_TEAM_NOTES`）を同期したところ、いずれもエラー無く`totalPages: 0`で完了した。Notion APIは、インテグレーションがデータベースにアクセスできない場合は`object_not_found`（404）を返すため、**200 OKで0件が返る場合は「インテグレーションはアクセスできているが、データベースの中身が実際に空」であることを意味する**（以前`DB_HOUDINI22`で発生した404エラーとは別の状態）。データベースIDの転記ミスだった`DB_HOUDINI22`（末尾`bf3`→正しくは`bf7`）はこの回で判明・修正できた。

### `VECTOR_QUERY_ERROR (code=40025): max top K is 50`（`limit`を大きくした検索で発生）

`/query`・`/search`の検索候補プール拡大ロジックが、`retrieve()`で`limit*3`した値を`hybridSearch()`内でさらに`*3`していたため（実質`limit*9`）、`limit=8`程度の指定でVectorizeの`returnMetadata:"all"`時のtopK上限（50件）を超えてエラーになっていた。小さい`limit`（5前後）では上限内に収まっていたため見過ごされていた潜在バグ（2026-08-25、`limit=8`で実際に発覚）。対処：`src/hybrid.ts`で`topK = Math.min(limit * 3, 50)`を一箇所で計算し、Vectorize検索・BM25検索の両方で共有するように修正。

### 情報抽出の内訳を可視化・namespaceごとに参考資料数を調整できるようにした（2026-08-25）

複数DBを横断検索すると、無関係なDBのチャンクがスコアの偶然の一致で上位に紛れ込み、回答の質を下げることがある（実際に「SOPとは」という質問でcedecnotes内の無関係な資料が上位に混ざる事例で確認）。対処：
- `namespaces`テーブルに`result_limit`列を追加し、`POST /admin/namespaces/set-limit`でnamespaceごとに検索結果の採用件数上限を設定できるようにした（管理タブの「namespace管理」からも設定可能）。上限が無いnamespaceは従来通り無制限（後方互換）。
- 出典の`score`フィールドが常に`0`固定だったバグを修正し、RRFスコアをその回答内での相対パーセンテージ（最高スコアを100%とする）として実際に算出するようにした。
- チャットUIの出典一覧に、namespace（DB）ごとの固定色分けバッジ・関連度パーセンテージ・引用有無バッジを表示。複数DBにまたがって抽出された場合は、内訳（貢献度の比率）を示す色分けバーと凡例も表示するようにした。色はグラフタブと共通のパレットを使い、画面全体で同じDBは同じ色になるようにしている。

### PDF/DOCX/PPTX変換・音声動画文字起こし・YouTube登録（2026-08-26追加）を実データで検証した際の所見

実際のcedecnotesフォルダ（CEDECの発表資料PDF/PPTXを多数含む）で検証し、以下が判明した：

- **26MBのPDF**：Gemini APIのインラインデータ上限（約18MB）を超えるため、`src/docExtract.ts`の`extractTextFromPdf`はFile API（アップロード→ACTIVE待ち→参照）に自動的に切り替わるようにした。実際にこの方式で34チャンク登録まで成功した。
- **大きいPPTX（埋め込み動画・画像を多数含む発表資料）**：`Memory limit exceeded before EOF`でWorkers isolateのメモリ上限（128MB）に達することがある。ダウンロード前に`Content-Length`で弾く対策を入れたが、それでも発生する場合がある（ダウンロード自体は上限内でも、ZIP解凍・XML展開の過程でメモリを消費するため）。**この失敗は該当ファイルだけがスキップされ、同期処理全体は継続する**（`driveSync.ts`のtry/catchで捕捉済み）ため、実害は該当ファイル1件が登録されないことに限られる。
- **File API経由の変換はバッチ内のサブリクエスト数が増える**：PDF/音声/動画のFile APIアップロードは1ファイルあたり複数回のAPI呼び出し（アップロード開始・データ送信・状態確認・生成・削除）を要するため、`batchSize=5`のままだと`Too many subrequests`に達しやすい。**PDF/PPTX/音声/動画が混在するフォルダを同期する場合は`batchSize=1`〜`2`程度に下げることを推奨する。**

### 特定のドキュメントの特定チャンクだけ`VECTOR_UPSERT_ERROR (code=40023): failed to parse ... json format`で失敗する（原因未特定）

Google Driveの「Houdini 22 Sneak Peek | SideFX」（Webページを丸ごとGoogleドキュメント化したもの、コメント欄のスパムまで含む）の同期で、常に同じチャンク（chunk_index=2）だけがVectorizeの`upsert()`で失敗する事例が発生した。制御文字・孤立サロゲート・U+FFFD（置換文字）の除去を試したが解消せず、原因はチャンク単体でも再現するため個別リクエストの内容起因と考えられるが、具体的にどの文字列がVectorize側のパーサを壊しているかは特定できていない。**実利的な対処として、1チャンクの登録失敗でドキュメント全体を失敗させず、そのチャンクだけスキップして他のチャンクは登録を続行するようにした**（`src/kbIngest.ts`の`ingestDocument`が`{chunks, skippedVectors}`を返すように変更、`kb_log`の詳細に「Nチャンクは登録失敗のためスキップ」と記録される）。同じ症状に再度遭遇した場合は、`skippedVectors`に載る`chunk_index`から該当テキストをたどって原因を絞り込めるようにしてある。

### Vectorizeの`getByIds()`が`too many ids in payload; max id count is 20`を返す（グラフ表示機能で発生）

`/graph`の実装（`src/graph.ts`）で、ノードごとに`query()`を呼ぶ代わりに全ノード分のベクトルを1回の`getByIds()`でまとめて取得する設計にしていたが、実データ（Houdini21、88ノード）で試したところ`VectorizeIndex.getByIds()`自体に**1回あたり最大20件**という上限があることが判明した。対処：IDを20件ずつのチャンクに分割し、`getByIds()`を複数回呼ぶように変更（それでもノードごとに`query()`するよりは遥かに少ない呼び出し回数で済む）。Vectorizeの各APIの上限は個別に把握しておく必要がある（`upsert`は1,000件/回、`getByIds`は20件/回など、メソッドごとに異なる）。

### `/graph`が`id too long; max is 64 bytes`を返す（同上、`getByIds`の上限修正後に発生）

上記を修正してもなお同じ64バイト上限エラーが発生した。原因は、上記「Vectorizeが`id too long`を返す」バグの**修正前に部分的に投入されたデータの残骸**：Vectorizeへの`upsert`自体は失敗していたが、D1側の`chunks_fts`テーブルには古い形式（`shared:houdini21:<日本語ページ名>:0`）のレコードが既に挿入済みで、それが再同期後もオーファン（Vectorize側に実体を持たない孤立行）として残っていた。`/graph`はD1の`chunks_fts`からノード候補を取得するため、この孤立行のIDをそのまま`getByIds()`に渡してエラーになった。対処：`length(CAST(chunk_id AS BLOB)) > 64`で該当行を特定し、`DELETE FROM chunks_fts WHERE chunk_id IN (...)`で7件削除（該当ファイルはハッシュ化されたIDで正しく再登録済みだったため、データの欠落はない）。**教訓：SQLiteの`length()`は文字数を返すため、日本語などマルチバイト文字を含む列のバイト数チェックには`length(CAST(x AS BLOB))`を使うこと。**

### `curl`が`HTTP 000`で全て失敗するのに、対象URLは実際には生きている

動作確認中に一度、`rag-poc.manato1201m.workers.dev`だけでなく`api.github.com`や`example.com`など無関係なホストへの`curl`も軒並み`HTTP 000`（TLSハンドシェイクは成立するが応答が返らない）になったことがあった。WebFetch経由では同じURLが正常に応答したため、**Worker側ではなくこの端末のcurl/ネットワーク経路側の一時的な問題**と判断した。`curl`が原因不明で全滅する場合は、Worker自体を疑う前に無関係な既知サイトへの`curl`も試し、それも失敗するならローカル環境側の問題を疑うこと。代替手段として、Pythonの`urllib.request`（下記）や`Invoke-RestMethod`でも同じリクエストが送れる。

### スクリプトから叩くと`403 Forbidden`が返る（ブラウザ・`curl.exe`では起きない）

`User-Agent`ヘッダが無い、または`Python-urllib/3.x`のようないかにもボットらしい既定値のままだと、workers.dev側の自動ボット対策で弾かれることがある（Worker自身のコードに到達する前に403になる。動作確認で実際に再現した）。対処：リクエストに`User-Agent: Mozilla/5.0 ...`のような通常のブラウザ相当の値を明示的に付ける。Pythonの例：

```python
import json, urllib.request
req = urllib.request.Request(
    "https://rag-poc.<サブドメイン>.workers.dev/query",
    data=json.dumps({"query": "...", "limit": 5}).encode("utf-8"),
    method="POST",
    headers={
        "Authorization": "Bearer <APIキー>",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    },
)
with urllib.request.urlopen(req, timeout=30) as res:
    print(res.read().decode("utf-8"))
```

## 今後チューニングすべき点（動かしながら見えてきたら随時追記）

- [x] ~~`text-embedding-004` 以外の埋め込みモデルへの切り替え~~ → `gemini-embedding-001`に切替済み
- [x] ~~トークン予算の実消費・チェック処理~~ → `src/budget.ts`で実装・動作確認済み（`/search`・`/query`双方）
- [x] ~~ハイブリッド検索（BM25+ベクトル+RRF）~~ → D1 FTS5（trigramトークナイザ）+ Vectorizeで実装・動作確認済み
- [x] ~~HyDE~~ → `src/embeddings.ts`の`hydeExpand`で実装・動作確認済み
- [x] ~~LLMによる最終回答生成（`/query`相当）＋引用率算出~~ → 実装・動作確認済み
- [x] ~~チャット履歴（メモリ）保存・一覧・評価~~ → `src/memory.ts`で実装・動作確認済み
- [x] ~~Webチャット画面~~ → `GET /`（`src/chatUi.ts`）で実装・動作確認済み
- [x] ~~Notion同期~~ → `src/notion.ts`/`src/notionSync.ts`で実装（コード・権限制御は動作確認済み。実際のNotionワークスペースでの同期そのものは認証情報未設定のため未検証）
- [x] ~~Google Drive同期（Googleドキュメント/テキストのみ）~~ → `src/driveSync.ts`で実装（同上、未検証）
- [x] ~~Admin API（APIキー発行/一覧/削除/namespace許可変更/予算上限設定/残高補充）~~ → `src/keyAdmin.ts`で実装・動作確認済み
- [x] ~~namespace管理（作成/一覧/削除）~~ → `src/namespaceAdmin.ts`で実装・動作確認済み
- [x] ~~キーごとのnamespaceアクセス制御（RBAC厳格化）~~ → `key_namespace_grants`テーブル＋`src/auth.ts`で実装・動作確認済み（既存ユーザーへの後方互換バックフィル込み）
- [x] ~~トークン予算の自動リセット（時間間隔指定）~~ → `src/budget.ts`の遅延評価方式で実装済み（Cron Trigger不要）
- [x] ~~実際のNotion認証情報での同期検証~~ → 実際の`cloud-rag-bot`インテグレーション・Houdini21データベース（80ページ）で完全同期に成功、`/query`での回答生成まで確認済み（2026-08-25）
- [x] ~~VectorizeベクトルIDの64バイト上限対策~~ → ハッシュベースの固定長IDに変更済み
- [x] ~~知識ベース同期のサブリクエスト数上限対策~~ → バッチ処理（`startIndex`/`batchSize`/`opId`/`nextIndex`）に変更済み
- [x] ~~Google Drive側の実認証情報での同期検証~~ → サービスアカウント経由で実際のDriveフォルダ（houdini21・houdini22・cedecnotes）を同期。houdini22は8ドキュメント・67チャンク登録、cedecnotesはPDF/PPTX中心で大半スキップ（既知の未対応mimeType）、houdini21は対象フォルダが空だった（2026-08-26）
- [x] ~~Webチャット画面のタブ構成（チャット／グラフ／履歴／管理）・グラフ表示・ブラウザ内Admin画面~~ → `src/chatUi.ts`を4タブ構成に全面刷新、新規`src/graph.ts`（`POST /graph`）でグラフ可視化を追加、既存Admin APIをブラウザから直接操作できるように（2026-08-25、実データで81ノード/239エッジを確認済み）
- [x] ~~グラフ表示の3D化・ノードクリックでの詳細表示~~ → Three.js（CDN）による3D力学レイアウト＋OrbitControls＋クリックで接続数/隣接ノード一覧を表示（2026-08-25）
- [x] ~~トークン利用状況の可視化（グラフ表示）~~ → `POST /admin/usage/stats`＋管理タブに日次棒グラフ・ユーザー別テーブル・キーごとの使用率ドーナツを追加（2026-08-25）
- [x] ~~グラフ詳細パネルにType/Size/適用日時を追加~~ → `ChunkMetadata`に`source`/`size`/`ingested_at`を追加し、Notion/Drive/手動登録それぞれの`ingestDocument()`呼び出し時に記録（2026-08-25）。**この変更より前に投入済みのデータ（houdini21の既存80件）には無いため「不明（旧データ）」と表示される。** 該当namespaceを再同期すれば新しいメタデータで上書きされる
- [x] ~~管理タブの表が横にはみ出しページ全体が横スクロールしてしまう~~ → 各テーブルを`.table-scroll`（`overflow-x:auto`）でラップし、`table-layout:fixed`+`word-break:break-all`で長いID列を折り返すように修正。`html,body`に`overflow-x:hidden`も追加（2026-08-25）
- [x] ~~グラフのObsidian風操作性（反発力/結集力調整・アニメーション再生/停止・DBごとの表示切替・色分け）~~ → スライダーでライブ調整可能な常時力学シミュレーション、再生/停止トグル、namespace（DB）ごとの表示チェックボックス、固定パレットによる色分け凡例を追加（2026-08-25）
- [x] ~~namespaceごとの参考資料数調整・情報抽出の内訳可視化~~ → `result_limit`によるDB別上限設定、出典スコアの実値化、色分けバッジ・内訳バーの表示を追加（2026-08-25）。この過程で`limit`が大きいと`VECTOR_QUERY_ERROR(40025)`になる潜在バグも発見・修正
- [x] ~~URL手動登録・QA CSV一括登録・KBロールバック~~ → `src/urlImport.ts`（HTMLRewriterでテキスト抽出）・`src/qaImport.ts`（RFC4180簡易パーサ＋バッチ処理）・`src/kbRollback.ts`（opId単位でVectorize/D1から削除）を実装、実データで動作確認済み（2026-08-26）
- [x] ~~評価統計・レート制限・期限切れ履歴の自動削除~~ → `POST /admin/rating-stats`（既存`memory`テーブル集計）、`src/rateLimit.ts`（60秒30回の固定ウィンドウ、既存`audit_log`を流用し新規テーブル不要）、Cron Trigger（毎日UTC3時、90日超の`memory`行を削除）を実装（2026-08-26）
- [x] ~~PDF/Word/PowerPoint変換・音声/動画文字起こし・YouTube登録~~ → `src/docExtract.ts`（PDFはGeminiネイティブ理解、DOCX/PPTXは自前ZIPパーサ）、`src/mediaTranscribe.ts`・`src/geminiFile.ts`（音声/動画/YouTube）を実装。実際のCEDEC資料（PDF/PPTX）で検証済み（2026-08-26）
- [x] ~~ヘルスチェック・アラート通知（Slack/Gmail）~~ → `src/healthCheck.ts`＋`src/alerts.ts`。30分ごとのCron TriggerでD1接続・KB同期エラー・予算枯渇を検知しSlack/Gmailへ通知。手動実行・テスト通知用のエンドポイントも追加（2026-08-26）。**Slack・Gmailともに実際に通知の送受信まで確認済み。** Gmailは当初サービスアカウント方式（Google Workspace限定と判明）→個人アカウントのOAuthリフレッシュトークン方式に切り替え済み
- [x] ~~バックアップ機能~~ → `POST /admin/backup/export`（`src/backup.ts`）。設定系テーブルのJSONスナップショットを管理タブからダウンロード可能に（2026-08-26）
- [x] ~~Claude APIプロキシ（Houdiniチュートリアル生成の移行先）~~ → `POST /claude/messages`（`src/claude.ts`、`@anthropic-ai/sdk`）。`houdini/python_panels/tutorial_agent.py`のGAS依存（Claude呼び出し・houdini21 RAG検索の両方）をCloudflare側に切り替えられるようにした（`claude_backend`/`rag_mode="cloudflare"`、既定値は既存動作を変えない"gas"）。**RAG検索・Claude呼び出し（ツール実行含む）ともに実際にエンドツーエンドで動作確認済み**（2026-08-26）
- [ ] Drive上のPDF/Word文書の変換、音声/動画の文字起こし対応（既存GAS `_convertBinaryBlobToText_`/`_transcribeAudioVideoBlob_`相当）
- [ ] 既存`houdini21DB`（Notion・約7,810ファイル相当）を実際に`/admin/sync/notion`で全件投入する（§6-3の再埋め込み移行の実行）
- [ ] レイテンシ・コストの実測（設計書§8.4は見積もりのみ）
- [ ] 他の未実装機能は `docs/gas-feature-parity.md` の一覧を参照
