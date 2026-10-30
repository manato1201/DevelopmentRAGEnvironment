# 第3回 データベースと SQL（表・索引・マイグレーション・落とし穴）

**到達目標:** [図14](../../images/14-data-model.svg) の表の関係を読める。`migrations/` の SQL を読み書きできる。**SQL の落とし穴**（NULL・索引・`LIMIT`）を避けられる。D1 のコードの型（`prepare → bind → first/all/run`）を使える。
**前提:** 第2回。 **目安:** 3時間

---

## 1. 全体像

[![データの置き場](../../images/14-data-model.svg)](../../images/14-data-model.svg)

D1 には、「人と権限」「質問と回答」「ナレッジ」「評価」「実証実験」の表が入っています。**どの表も、利用者は `user_id` で `users` とつながります**。

## 2. 基礎

### 2.1 表・行・列・主キー

**表（テーブル）**は、Excel の表です。**列**が項目、**行**が1件のデータ。

`users` の例:

| user_id（主キー） | display_name | role | created_at | expires_at |
|---|---|---|---|---|
| 3a7f…（キーのハッシュ） | 田中 | member | 1760000000 | NULL |

- **主キー（PRIMARY KEY）**: 1行を、1つに決める列。同じ値は、2回入れられない。
- **NULL**: 「値が無い」。0 や空文字とは**違います**（2.5 で詳しく）。
- 日時は、**UNIX 秒**（1970-01-01 からの秒数）の整数で持ちます（`created_at`）。`date(created_at, 'unixepoch')` で、日付にできます。

### 2.2 SQL の基本

```sql
-- 読む
SELECT user_id, role FROM users WHERE role = 'admin';
-- 数える
SELECT COUNT(*) AS n FROM memory WHERE user_id = ?;
-- 足す・直す・消す
INSERT INTO threads (thread_id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?);
UPDATE pilot_sessions SET discarded_at = ? WHERE id = ?;
DELETE FROM threads WHERE thread_id = ?;
```

- **`?`** は、後から値を差し込む場所（**プレースホルダー**）。値を SQL の文字に**直接つなげてはいけません**（SQL インジェクション。第5回）。
- **JOIN**: 2つの表を、つなげて読む。

```sql
SELECT p.pid, s.round, s.kind
FROM pilot_sessions s JOIN pilot_profile p ON p.user_id = s.user_id
WHERE s.ended_at IS NOT NULL;
```

- **GROUP BY**: 同じ値でまとめて、数える・合計する。

```sql
SELECT round, kind, COUNT(*) AS n FROM pilot_sessions GROUP BY round, kind;
```

### 2.3 索引（インデックス）

索引は、本の**巻末の索引**です。無いと、データベースは、**全部の行を端から読んで**探します（全件走査）。D1 は、**読んだ行数**で料金と枠が決まるので、全件走査は、そのままコストです。

```sql
CREATE INDEX idx_memory_user_created ON memory(user_id, created_at DESC);
```

この索引があると、`WHERE user_id = ? AND created_at >= ?` が、該当の行だけを読みます。

**索引が効かない書き方**（Z32 の点検項目）:

| 書き方 | 問題 | 直し方 |
|---|---|---|
| `WHERE date(created_at,'unixepoch') = '2026-10-30'` | 列に**関数**をかけると、索引が使えない | `WHERE created_at >= ? AND created_at < ?`（範囲） |
| `WHERE name LIKE '%abc%'` | 前に `%` が付くと、索引が使えない | 前方一致（`'abc%'`）にする。それが無理なら、件数が少ない表だけで使う |
| `LIMIT` だけで `ORDER BY` が無い | どの行が返るか、**不定** | `ORDER BY` を付ける。同じ値が並ぶときは、2つ目の並び（`, id`）も付ける |

### 2.4 一意性と「部分一意索引」

**UNIQUE**: 同じ値の組を、2行入れられない。

`pilot_sessions` は、「同じ人・同じ回・同じ種類」を、**1つだけ**にしたい。でも、「やり直し」で破棄した記録は、**残したい**（`discarded_at` を入れる）。そこで、**破棄していない行だけ**に、一意性をかけます（`0036_pilot_redo.sql`）。

```sql
CREATE UNIQUE INDEX idx_pilot_sessions_slot
  ON pilot_sessions(user_id, round, kind) WHERE discarded_at IS NULL;
```

> 学び: 「消す」代わりに「印を付ける」（**論理削除**）なら、記録が残る。そのとき、一意性は、**印が付いていない行だけ**に、かける。

### 2.5 NULL の落とし穴

NULL は、「分からない」です。**NULL との比較は、真でも偽でもなく、「不明」**になり、`WHERE` では、行が**落ちます**。

| 書き方 | 結果 |
|---|---|
| `WHERE x != 'admin'` | `x` が NULL の行は、**入らない**（`NULL != 'admin'` は不明） |
| `WHERE x IS NULL` | NULL の行（`= NULL` は書けない） |
| `COUNT(*)` と `COUNT(col)` | `COUNT(*)` は全行。`COUNT(col)` は、**col が NULL の行を数えない** |
| `NOT IN (SELECT col …)` | 副問い合わせの中に NULL が1つでもあると、**全体が空になる** |

**このプロジェクトでの対策**:
- `users.role` は **`NOT NULL`**（だから `u.role != 'admin'` で、行が落ちない）。
- 孤児のスレッドを消す SQL は、副問い合わせに **`WHERE thread_id IS NOT NULL`** を付けて、NULL を除いている（`src/index.ts`）。
- `pilot_sessions` の「到達」「アンケート」の列は、**答えなかった = NULL**（0 と区別）。集計は、NULL を飛ばして計算する（`median` は `null` を除く）。

### 2.6 マイグレーション（表の形の変更を、記録する）

表の形を変えるときは、**SQL ファイルを足します**（`migrations/NNNN_名前.sql`）。番号順に、**1回ずつ**適用されます。適用済みの記録は、D1 自身が持ちます。

```bash
npx wrangler d1 migrations list  rag-poc-db --local   # どれが未適用か
npx wrangler d1 migrations apply rag-poc-db --local   # 未適用のものを、順に適用
```

**決まり**:
1. **既存のファイルは、直さない。** 適用済みの環境に、効かないから。直したいなら、新しいファイルで、直す。
2. **戻す SQL は、自動では無い。** 戻したいなら、打ち消す SQL を、**新しいマイグレーション**として足す。
3. **列を足すとき**: `ALTER TABLE … ADD COLUMN`。`NOT NULL` を付けるなら、**`DEFAULT` が必須**（既存の行に入れる値が要るから）。例: `ALTER TABLE pilot_sessions ADD COLUMN paused_sec INTEGER NOT NULL DEFAULT 0;`
4. **本番に適用する前に、中身を読む。** 本番への適用は、戻せません。

### 2.7 コードからの D1（`prepare → bind → first/all/run`）

```ts
// 1行（無ければ null）
const row = await env.DB.prepare("SELECT user_id, pid, slot FROM pilot_profile WHERE user_id = ?")
  .bind(userId).first<ProfileRow>();
// 複数行
const res = await env.DB.prepare("SELECT … FROM pilot_sessions WHERE user_id = ? AND discarded_at IS NULL")
  .bind(userId).all<SessionRow>();
const rows = res.results ?? [];
// 書き込み
await env.DB.prepare("UPDATE pilot_sessions SET discarded_at = ? WHERE id = ?")
  .bind(Math.floor(Date.now() / 1000), id).run();
```

- **`.bind(...)`** で値を渡す。SQL の文字に、値を**つなげない**。
- 複数の書き込みを1回で行うなら、`env.DB.batch([...])`（`src/growth.ts` の `recordQueryTerms`）。

## 3. このプロジェクトでは

- 表の一覧と関係: [図14](../../images/14-data-model.svg)。作った SQL: `cloudflare-rag-poc/migrations/`（`0001_init.sql` から `0036_pilot_redo.sql`）。
- 全文検索は、`FTS5` という仕組み（`chunks_fts`）。`chunk_rows` が、断片（`chunk_id`）と対応づける。
- SQL の点検の記録（2026-10-30）: [IMPROVEMENT_DESIGN_2026-10.md](../../../IMPROVEMENT_DESIGN_2026-10.md) の「Z32 SQL」。結論は「不具合なし。`LIKE '%…%'` は、管理者向けなので許容」。

## 4. 演習

**演習 3.1（読む）** `migrations/0035_pilot_tasks.sql` と `0036_pilot_redo.sql` を読み、次に答えてください。(a) `pilot_profile.pid` は NULL を許すか。なぜか。(b) `0036` で `DROP INDEX` してから作り直した理由は。(c) `paused_sec` に `DEFAULT 0` が必要な理由は。

**演習 3.2（ローカルで書く）** ローカルの D1 で、次を実行して、結果を予想→確認してください。

```bash
cd cloudflare-rag-poc
npx wrangler d1 migrations apply rag-poc-db --local
npx wrangler d1 execute rag-poc-db --local --command "INSERT INTO users (user_id, display_name, role, created_at) VALUES ('t1','試験','member',1)"
npx wrangler d1 execute rag-poc-db --local --command "SELECT COUNT(*) AS rows_, COUNT(expires_at) AS with_expiry FROM users"
```

`rows_` と `with_expiry` が違う理由を、説明してください。

**演習 3.3（点検する）** `cloudflare-rag-poc/src/usageStats.ts` の `SELECT date(created_at, 'unixepoch') …` を読み、`date()` が **SELECT と GROUP BY** にだけあり、`WHERE` には無いことを確認してください。もし `WHERE date(created_at,'unixepoch') >= …` と書いたら、何が起きるか説明してください。

**演習 3.4（書く）** 「各参加者の、有効な（破棄していない）課題の数」を出す SQL を、`pilot_profile` と `pilot_sessions` を JOIN して書いてください。管理者（`pid IS NULL`）は除くこと。

## 5. つまずきやすい点

- **`= NULL` と書いてしまう。** `IS NULL` と書く。
- **ローカルと本番を取り違えて、本番の表を直す。** 第2回の表を再確認。
- **適用済みのマイグレーションを書き換える。** 本番には効かないのに、ローカルだけ直ったように見えて、事故になる。
- **全件を数える SQL を、画面を開くたびに打つ。** D1 の読み取り枠を使い切る（2026-10-16 の事故）。

## 6. 確認問題

1. 主キーと、UNIQUE 索引の違いは？
2. `WHERE role != 'admin'` で、`role` が NULL の行は、入るか？
3. 論理削除と、物理削除（DELETE）の違いと、使い分けは？
4. マイグレーションに「既存のファイルを直さない」決まりがあるのは、なぜか？
5. `SELECT * FROM kb_log LIMIT 50` の問題を2つ挙げよ。

## 解答の方針

- 3.1: (a) 許す。運営（admin）のテストは、番号を取らないため。(b) `UNIQUE INDEX` の条件（`WHERE discarded_at IS NULL`）は、作り直さないと変えられない。(c) 既存の行に、入れる値が要るため。
- 3.2: `COUNT(*)` は全行、`COUNT(expires_at)` は、`expires_at` が NULL でない行だけを数える。
- 3.3: 全行の `created_at` に関数をかけてから比べるので、索引が使えず、全件走査になる。
- 3.4: `SELECT p.pid, COUNT(*) FROM pilot_profile p JOIN pilot_sessions s ON s.user_id = p.user_id WHERE s.discarded_at IS NULL AND p.pid IS NOT NULL GROUP BY p.pid`。
- 確認問題 5: `ORDER BY` が無く、どの50件か不定。`SELECT *` は、不要な列まで読む。
