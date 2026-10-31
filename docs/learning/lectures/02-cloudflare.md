# 第2回 Cloudflare の基礎（Workers・D1・Vectorize・R2・Secrets・Cron・wrangler）

**到達目標:** [図11](../../images/11-request-life.svg) の **4（Worker を起動）** と、Worker が使う「置き場」（D1・Vectorize・R2・Secrets）を区別して説明できる。`wrangler.jsonc` を読み、**ローカルと本番を間違えずに**コマンドを打てる。
**前提:** 第1回。 **目安:** 3時間

---

## 1. 全体像

このシステムのサーバー側は、**自分で借りたサーバー（VPS など）が1台もありません**。すべて Cloudflare のサービスの組み合わせです。

| 部品 | 何か | このプロジェクトでの役割 |
|---|---|---|
| **Workers** | 小さなプログラム（JavaScript/TypeScript）を、世界中の拠点で動かす | API の本体（`src/index.ts`） |
| **D1** | SQLite 互換のデータベース | 利用者・履歴・予算・実証実験の記録・全文検索 |
| **Vectorize** | ベクトル（意味）検索の索引 | 意味で探す（`VEC_SHARED`・`VEC_PERSONAL`） |
| **R2** | ファイルの置き場（S3 互換） | 動画・サムネイル（`ragreel-gallery` の Worker） |
| **Secrets** | 秘密の値の金庫 | Gemini・Claude・Google TTS の鍵など |
| **Cron Triggers** | 決まった時刻に Worker を動かす | 古い履歴の削除・ヘルスチェック・自動同期 |

## 2. 基礎

### 2.1 Workers（サーバーが無いサーバー）

普通のサーバーは、1台のコンピューターで、プログラムが**ずっと動いて**います。Workers は違います。

- リクエストが来た**その瞬間**に、近くの拠点で、プログラムが（ほぼ）一瞬で起動し、返事をして、終わります。
- 管理するサーバー・OS・セキュリティパッチは、ありません。**使った分だけ**課金されます。
- 代わりに、**制限**があります（2026-10時点。数字は公式ページで確認）。
  - 1回の処理に使える **CPU 時間** と、**サブリクエスト数**（外へ出す通信の回数）に上限がある。超えると `Error 1102` などで止まる。長い処理（大量の同期）は、**小さなバッチに分けて、繰り返し呼ぶ**（[03 §5](../03-specialized.md#5-cloudflare特有の制約と回避策)）。
  - プログラムは、**状態を持ち越せない**。変数に覚えさせても、次のリクエストには残りません。覚えたいことは、D1 などに書く。
  - ファイルシステム（`fs`）は、普通には使えない。

### 2.2 bindings（Worker と置き場のつなぎ方）

Worker のコードは、D1 や Vectorize を、**名前のついた変数**として受け取ります。この結びつけを **binding** と呼び、`wrangler.jsonc` に書きます。

```jsonc
{
  "name": "rag-poc",                  // Worker の名前 → URL の rag-poc.…workers.dev
  "main": "src/index.ts",             // 入口
  "compatibility_date": "2026-08-01", // この日付の挙動で動かす（勝手に変わらない）
  "d1_databases":   [{ "binding": "DB", "database_name": "rag-poc-db", "database_id": "…" }],
  "vectorize":      [{ "binding": "VEC_SHARED", "index_name": "rag-poc-shared" },
                     { "binding": "VEC_PERSONAL", "index_name": "rag-poc-personal" }],
  "vars":           { "EMBEDDING_MODEL": "gemini-embedding-001", "GENERATION_MODEL": "gemini-flash-latest" },
  "triggers":       { "crons": ["0 3 * * *", "*/30 * * * *", "0 4 * * *"] }
}
```

コードでは、`env.DB`・`env.VEC_SHARED` として使います（型は `src/types.ts` の `Env`）。

```ts
export interface Env {
  DB: D1Database;
  VEC_SHARED: VectorizeIndex;
  VEC_PERSONAL: VectorizeIndex;
  GEMINI_API_KEY: string;   // ← これは vars ではなく Secret
  …
}
```

### 2.3 D1（データベース）

- SQLite という、1つのファイルで動く軽いデータベースを、クラウドで使えるようにしたものです。SQL で読み書きします（第3回）。
- **無料枠・料金は「読み取った行数」と「書いた行数」で決まります**。全件を数える SQL を頻繁に打つと、大量に読んだことになります。**2026-10-16** に、これで1日の枠を使い切り、全 API が 500 を返した事故がありました（[06 障害記録 A](../06-maintenance-runbook.md)）。
- 2026-10-21 から **Workers Paid** プラン（月 $5〜）です。枠は広がりましたが、**読む行数に気をつける**考え方は同じです。
- **ローカルの D1** と **本番の D1** は、別のデータです（次の 2.7）。

### 2.4 Vectorize（意味で探す索引）

文章を「意味の方向」を表す数の列（**ベクトル**。このプロジェクトでは 768 次元）に直しておき、質問のベクトルと近いものを探す索引です（第4回）。

- 索引を作るときに**次元数が固定**されます。後で変えるなら、新しい索引を作って、全部入れ直します。
- **メタデータ索引**（絞り込みに使う項目の索引）は、**データを入れる前に**作らないと、絞り込みが効かず、検索が**常に 0 件**になります（[cloudflare-rag-poc/README.md](../../../cloudflare-rag-poc/README.md) の手順 3.5）。

### 2.5 R2（ファイルの置き場）

動画・画像などの**大きなファイル**を置く場所です。D1 には、ファイルそのものではなく、**どこにあるかの目次**を入れます。動画のギャラリー（`ragreel-gallery`）が使います。

### 2.6 Secrets と vars（秘密の値）

| | 例 | どこに書く | 見えるか |
|---|---|---|---|
| **vars** | `EMBEDDING_MODEL`（モデル名） | `wrangler.jsonc` | 見える（コミットしてよい） |
| **Secret** | `GEMINI_API_KEY`・`ANTHROPIC_API_KEY` | `npx wrangler secret put <名前>`（値は、画面に出ない） | **見えない**。コミットしてはいけない |

> 鍵を `wrangler.jsonc` や `.ts` に書いて、うっかりコミットしたら、**その鍵は漏れたものとして、失効して作り直す**。履歴から消しても、遅い。

### 2.7 wrangler（操作の道具）と、ローカル／本番

`wrangler` は、Cloudflare を操作するコマンドです。**同じコマンドでも、`--remote` が付くかどうかで、対象が変わります。**

| コマンド | 対象 | 影響 |
|---|---|---|
| `npx wrangler d1 execute rag-poc-db --local --command "SELECT …"` | **ローカル**の開発用 DB | 本番に影響なし |
| `npx wrangler d1 execute rag-poc-db --remote --command "SELECT …"` | **本番**の D1 | 読むだけなら安全。**UPDATE/DELETE は本番を変える** |
| `npx wrangler d1 migrations list rag-poc-db --remote` | 本番の、保留中のマイグレーション | 一覧だけ（変えない） |
| `npx wrangler d1 migrations apply rag-poc-db --remote` | 本番に、マイグレーションを適用 | **本番を変える。戻せない** |
| `npx wrangler deploy` | 本番に、Worker をデプロイ | **本番を変える**（`rollback` で戻せる） |
| `npx wrangler rollback` | 本番の Worker を、1つ前の版に戻す | 本番を変える |
| `npx wrangler secret put <名前>` | 本番の Secret を登録 | 本番を変える |
| `npx wrangler whoami` | ログイン中のアカウントと権限 | 確認だけ |

**ルール**: 本番を変えるコマンドは、**意図して**打つ。「一覧 → 中身を読む → 適用 → もう一度一覧」の順（[運営者手順書 §6](../../pilot/operator-runbook.md)）。

### 2.8 Cron（決まった時刻に動く）

`triggers.crons` に書いた時刻に、`index.ts` の `scheduled()` が呼ばれます。

| 式 | 意味 | 何をするか |
|---|---|---|
| `0 3 * * *` | 毎日 3:00（UTC） | 期限切れのチャット履歴を削除 |
| `*/30 * * * *` | 30分ごと | ヘルスチェック（異常ならアラート通知） |
| `0 4 * * *` | 毎日 4:00（UTC） | Jira・Backlog・カレンダーの差分同期 |

時刻は **UTC**（日本時間は +9 時間）。`0 3` は日本時間の12時です。

## 3. このプロジェクトでは

- Worker は **2つ**あります。`rag-poc`（検索・回答・管理・実証実験）と、`ragreel-gallery`（動画の置き場）。[図01](../../images/01-system-overview.svg) の、2つの「Cloudflare」の枠です。
- すべての D1 の変更は、`cloudflare-rag-poc/migrations/` の連番の SQL です（現在 0036 まで）。**既存のファイルは直さず、足す**。
- Worker の外から直接見える部品は、`/health`（GET）と `/`（画面）だけ。ほかは、鍵が要ります。

## 4. 演習

**演習 2.1（読む）** `cloudflare-rag-poc/wrangler.jsonc` を開き、(a) D1 の `binding` 名、(b) Vectorize の索引の数と名前、(c) Cron の式を、書き出してください。それぞれ、`src/` のどのファイルで使われているか、`Grep` で探してください（例: `env.DB`・`VEC_SHARED`）。

**演習 2.2（ローカルで試す）** ローカルの D1 に、マイグレーションを適用して、表の一覧を見ます（**`--remote` を付けない**）。

```bash
cd cloudflare-rag-poc
npx wrangler d1 migrations apply rag-poc-db --local
npx wrangler d1 execute rag-poc-db --local --command "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
```

表に `pilot_profile` と `pilot_sessions` が出ることを確認してください。

**演習 2.3（読み取りだけ・本番）** 本番の、保留中のマイグレーションを**一覧するだけ**で確認します。適用はしません。

```bash
npx wrangler d1 migrations list rag-poc-db --remote
```

**演習 2.4（考える）** 次のうち、**本番を変える**コマンドはどれですか。(a) `wrangler deploy` (b) `wrangler d1 execute … --local --command "DELETE FROM memory"` (c) `wrangler d1 migrations list … --remote` (d) `wrangler secret put X` (e) `npm test`

**演習 2.5（考える）** Worker の変数に「最後に質問した人」を覚えさせる実装は、なぜ動かないか。

## 5. つまずきやすい点

- **`--remote` の付け忘れ・付け間違い。** ローカルで試したつもりが本番、または逆。コマンドを打つ前に、`--remote` の有無を、声に出して確認する。
- **ローカルの D1 に、データが無い。** ローカルは空の別データです。本番のデータは、入っていません。
- **Cron の時刻が、日本時間だと思い込む。** UTC です。
- **`wrangler` が `7403` で失敗する。** 一時的な API エラーのことが多い。`npx wrangler whoami` で、ログインと権限（d1・workers）を確認して、再実行（[運用手順書 8-3](../../operations/cloudflare-rag-operations-manual.md)）。

## 6. 確認問題

1. Workers と、普通のサーバーの違いを、3つ挙げよ。
2. `vars` と Secret の違いは？ 鍵はどちらに入れるか。
3. `--local` と `--remote` の違いを説明せよ。
4. D1 の「読み取った行数」を減らすには、SQL をどう書くか（第3回の先取り）。
5. Cron `*/30 * * * *` は、いつ動くか。

## 解答の方針

- 2.1: `grep -rn "env.DB" src | head`。Cron は `src/index.ts` の `scheduled`。
- 2.4: (a)(d) は本番を変える。(b) は `--local` なので、ローカルだけ。(c)(e) は変えない。
- 2.5: Worker は、リクエストごとに起動し、終わると状態が消える。覚えるなら D1 に書く。
- 確認問題 4: 全件を数えない。`WHERE` で絞る。索引が効く条件にする。必要な列だけ選ぶ。`LIMIT` を付ける。
- 確認問題 5: 毎時 0 分と 30 分（UTC）。
