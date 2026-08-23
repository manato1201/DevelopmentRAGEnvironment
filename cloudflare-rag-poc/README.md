# Cloudflare RAG 検証環境（POC）

**位置づけ:** [docs/cloud-local-unification-plan.md](../docs/cloud-local-unification-plan.md) の統合方針を、実際に動かして検証・チューニングするための別環境。

**このフォルダは本番の `scripts/gas_cloud_rag.js`（Cloud RAG）・`scripts/rag_service.py`（Local RAG）には一切影響しません。** 実証実験（9月〜）が終わるまで、この検証環境の結果に関わらず本番は現行構成のまま動き続けます。

## 実装済みの内容

- `POST /search` — 既存の `rag_local_bridge.py` の `/search` と同一のリクエスト/レスポンス契約（`docs/cloud-local-unification-plan.md` §8.3）
- `POST /ingest` — 検証用の投入エンドポイント（本番のNotion/ChromaDB連携は行わない。テキストを直接渡してGeminiで埋め込み、Vectorizeへ登録するだけ）
- D1（`migrations/0001_init.sql`）— users / namespaces / token_budgets / audit_log の4テーブル（設計書§8.1のまま）
- Vectorize 2インデックス（`VEC_SHARED` / `VEC_PERSONAL`）による共有・個人スコープの分離
- APIキー（SHA-256ハッシュ）によるユーザー認証、namespaceのアクセス制御

**動作確認済み（2026-08-23）：** `https://rag-poc.manato1201m.workers.dev` に実際にデプロイし、`/ingest`→`/search`が実データで正しく通ることを確認済み（下記トラブルシューティングに記載の3件を修正した後）。

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

### 日本語テキストが`/search`のレスポンスで文字化けする

Worker側のバグではなく、**動作確認時にコマンドラインへ直接日本語を含むJSONを埋め込んだこと自体が原因**になりうる（Windows上のシェルは、多バイト文字を含むコマンドライン引数をネイティブexe（`curl.exe`等）へ渡す際にロケール依存のエンコーディング変換を挟むことがある）。対処：`-d '...'`で直接埋め込まず、UTF-8で保存したJSONファイルを`--data-binary @path\to\file.json`で渡す。動作確認でも、直接埋め込んだリクエストのみ文字化けし、ファイル経由のリクエストは正常だった。

## 今後チューニングすべき点（動かしながら見えてきたら随時追記）

- [ ] `text-embedding-004` 以外の埋め込みモデル（`gemini-embedding-001`等）への切り替え検証（次元数変更が必要になる点に注意）
- [ ] トークン予算（`token_budgets`テーブル）を実際に`/search`実行時に消費・チェックする処理の実装（現状はテーブルのみ用意、消費ロジック未実装）
- [ ] 既存`houdini21DB`（Notion・約7,810ファイル相当）からの実データ移行スクリプト（§6-3: 全件Gemini再埋め込み）
- [ ] レイテンシ・コストの実測（設計書§8.4は見積もりのみ）
