# 02. 基礎編

**更新日:** 2026-10-17　**目安:** 2〜3日　**前提:** [01. 常識編](01-common-knowledge.md)
**ゴール:** このプロジェクトのコードを**読んで、何をしているか説明できる**。書くのは次の応用編から。

読み方のコツ: 全部を覚えない。**この章の表を手元に置いて、コードを読みながら引く**。

---

## 1. TypeScriptを読む（Worker本体）

Worker（`cloudflare-rag-poc/src/`）はTypeScript。JavaScriptに「型」を足した言語。

### 1.1 最低限の文法

```ts
// 変数: const は再代入しない、let は再代入する
const limit = 5;
let count = 0;

// 関数（型つき）。引数と戻り値の型を書く
export function jsonResponse(status: number, body: unknown): Response { ... }

// アロー関数: 短い関数を、その場で書く
const names = users.map((u) => u.name);

// オブジェクトと分割代入
const { userId, role } = user;

// 型の定義
interface AuthedUser { userId: string; role: "admin" | "member" | "guest"; }

// 省略可能(?)・null許容
function f(a?: string, b: string | null) { ... }

// テンプレート文字列（バッククォート）
const msg = `namespace(${ns})への書き込み権限がありません`;

// 配列・Map・Set
const ids = rows.map((r) => r.id);
const byId = new Map(rows.map((r) => [r.id, r]));

// モジュール: 別ファイルの関数を読む
import { jsonResponse } from "./http";
```

| 見かけたもの | 意味 |
|---|---|
| `x ?? y` | `x`が`null`/`undefined`のときだけ`y` |
| `x?.y` | `x`が`null`でなければ`x.y`、そうでなければ`undefined` |
| `a \|\| b` | `a`が偽（空文字・0・nullなど）なら`b` |
| `as T` | 「この値は`T`型だ」と、コンパイラに伝える（実行時の確認はしない） |
| `unknown` | 何が入っているか分からない値。使う前に確認が必要 |
| `Promise<T>` | 後で`T`になる、非同期の結果 |

### 1.2 非同期（async/await）

ネットワークやDBの呼び出しは、結果が返るまで待つ。`await`で待つ。`await`は`async`関数の中でだけ使える。

```ts
async function load(env: Env, userId: string) {
  const row = await env.DB.prepare("SELECT role FROM users WHERE user_id = ?")
    .bind(userId)
    .first();            // ← 結果が返るまで、ここで待つ
  return row;
}

// 複数を同時に待つ（互いに依存しないときだけ）
const [a, b] = await Promise.all([loadA(), loadB()]);
```

**よくある間違い:** `await`を付け忘れる。型は`Promise<...>`のまま進み、中身が取れない。「書き込んだのに反映されない」ときは、`await`の付け忘れを疑う。

### 1.3 エラー処理

```ts
try {
  await doWork();
} catch (err) {
  const message = err instanceof Error ? err.message : String(err);
  return jsonResponse(500, { error: message });
}
```

このプロジェクトの規約: **画面に出すエラーは、日本語で、原因と対処が分かる文にする**。

### 1.4 Workerの基本形

```ts
export default {
  async fetch(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    // 1) URLのパスで処理を振り分け  2) 認証  3) 処理  4) jsonResponse で返す
  },
  async scheduled(event, env, ctx) { /* Cronで呼ばれる */ },
};
```

- `env`: Cloudflareが渡す、DB・ベクトルDB・秘密の値（`env.DB`, `env.VEC_SHARED`, `env.GEMINI_API_KEY`）。**どれが入るかは `wrangler.jsonc` の設定で決まる。**
- `ctx.waitUntil(promise)`: レスポンスを返した後も、その処理を続けさせる（Slackの遅延応答で使用）。

### 練習
1. [`src/http.ts`](../../cloudflare-rag-poc/src/http.ts) の`clampInt`に、`("abc", 10, 1, 100)`と`(500, 10, 1, 100)`を渡すと、それぞれ何が返るか。なぜか。
2. [`src/chunking.ts`](../../cloudflare-rag-poc/src/chunking.ts) の`chunkText`に、2,300文字の文章を渡す（`size`・`overlap`は既定値）。チャンクはいくつできて、2番目の開始位置は何文字目か。
3. [`src/index.ts`](../../cloudflare-rag-poc/src/index.ts)の`fetch`を読み、「認証が必要なルート」と「不要なルート」を、それぞれ2つ挙げる。
4. `async`でない関数の中で`await`を書くと、何が起きるか。

**ヒント:** 1は、`Number("abc")`が`NaN`になる点。2は、`start = end - overlap`の計算。3は、`/health`・`/admin/bootstrap`・`/slack/command`と、`authenticate`を呼ぶ位置を見比べる。

## 2. SQLとSQLiteを読む（D1）

D1はSQLite（小さなデータベース）をクラウドで使えるようにしたもの。**このプロジェクトのデータの形は、`migrations/*.sql`を順に読めば全部分かる。**

### 2.1 基本の命令

```sql
-- 読む
SELECT user_id, role FROM users WHERE role = 'admin' ORDER BY created_at DESC LIMIT 10;

-- 件数・集計
SELECT namespace, COUNT(*) AS n FROM kb_documents GROUP BY namespace;

-- 書く
INSERT INTO users (user_id, role, created_at) VALUES ('u1', 'member', 1760000000);
UPDATE token_budgets SET used_tokens = used_tokens + 100 WHERE user_id = 'u1';
DELETE FROM threads WHERE user_id = 'u1';

-- 結合（2つの表を、共通の値でつなぐ）
SELECT d.file, l.status
FROM kb_documents d JOIN kb_log l ON l.namespace_id = d.namespace AND l.file = d.file;
```

| 用語 | 意味 |
|---|---|
| 主キー（PRIMARY KEY） | 行を一意に決める列。重複できない |
| 索引（INDEX） | 検索を速くする目次。**索引の無い列で探すと、全行を読む** |
| `NULL` | 値が無い。`= NULL`では比較できず、`IS NULL`を使う |
| `?`と`bind` | 値の差し込み。**文字列を直接つなげて書かない**（SQLインジェクション） |
| トランザクション・`batch` | 複数の命令をまとめて、全部成功か全部失敗にする |
| `INSERT OR REPLACE` | 同じ主キーがあれば置き換える |
| `ON CONFLICT ... DO UPDATE` | 同じ主キーがあれば、指定の列だけ更新する |

### 2.2 「速い・遅い」ではなく「何行読むか」で考える

D1は**読んだ行数**で、無料枠が決まる（[01 §7](01-common-knowledge.md#7-費用と上限の常識)）。命令が「何行読むか」は、次で調べられる。

```sql
EXPLAIN QUERY PLAN SELECT * FROM kb_documents WHERE namespace = 'shared:docs';
-- SEARCH ... USING INDEX idx_kb_documents_namespace  ← 索引で絞れている（良い）
-- SCAN ...                                           ← 全行を読んでいる（要注意）
```

- 条件の列に索引がある → `SEARCH`（少ない行だけ読む）
- 索引が無い、または`LIKE '%…'`（先頭が不定の部分一致）→ `SCAN`（全部読む）
- **FTS5の`UNINDEXED`列**（`chunks_fts`の`chunk_id`・`namespace`・`file`）で探すと、必ず全部読む。そのため、このプロジェクトでは**対応表`chunk_rows`**（[migrations/0030](../../cloudflare-rag-poc/migrations/0030_chunk_rows.sql)）と`kb_documents`（[migrations/0008](../../cloudflare-rag-poc/migrations/0008_kb_documents.sql)）を作って、全部読まずに済ませている。**どちらのファイルの冒頭コメントにも、実際に起きた問題の経緯が書いてある。** 必ず読むこと。

### 2.3 マイグレーション

- 表の構造の変更は、**番号つきのSQLファイルを追加**して行う（`migrations/0031_…sql`）。**適用済みのファイルは、書き換えない。**
- 適用は、`wrangler d1 migrations apply`。**適用の記録が残るので、同じファイルは二度流れない。**
- 順序の鉄則: **マイグレーションを先に適用 → 新しいコードをデプロイ**。逆にすると、新しいコードが存在しない表を読んで、全部が500になる。
- 既存の行を埋める処理（バックフィル）は、そのマイグレーションの中に書く。

### 練習
1. `migrations/0004_kb_sources.sql`を読み、`kb_log`にはどんな列があるか、表にまとめる。
2. 「`kb_log`から、状態が`error`のものを、新しい順に20件」を取るSQLを書く。
3. 次の2つは、どちらが何行読むか。理由も。`SELECT * FROM kb_documents WHERE namespace = 'x'`／`SELECT * FROM chunks_fts WHERE namespace = 'x'`
4. `migrations/`のうち、**索引を作っているもの**を、すべて探す。（ヒント: `grep -n "CREATE INDEX" migrations/*.sql`）

## 3. Pythonを読む（Houdiniパネル・ローカルRAG）

```python
from __future__ import annotations      # 型ヒントの書き方を新しい形にする（先頭に書く）
import json
from pathlib import Path

class HoudiniToolExecutor:               # クラス: データと処理をまとめたもの
    def __init__(self, sandbox_path: str) -> None:   # 作るときに呼ばれる
        self.sandbox_path = sandbox_path             # self.〜 は、そのオブジェクトの持ち物

    def execute(self, tool_name: str, tool_input: dict) -> tuple[str, bool]:
        handler = getattr(self, f"_tool_{tool_name}", None)   # 名前から関数を取り出す
        if handler is None:
            return f"未知のツールです: {tool_name}", True
        try:
            return handler(tool_input), False
        except Exception as exc:                  # 例外を捕まえて、結果として返す
            return f"エラー: {exc}", True
```

| 見かけたもの | 意味 |
|---|---|
| インデント | Pythonでは**インデントが構文**。タブとスペースを混ぜない |
| `def f(x: int) -> str:` | 関数。`->`は戻り値の型 |
| `_name`（先頭に`_`） | 「内部用」の約束。外から呼ばない |
| `f"…{x}…"` | 文字列に変数を埋め込む |
| `with open(p) as f:` | ファイルを開き、終わったら必ず閉じる |
| `try / except` | 例外の処理（TypeScriptの`try / catch`） |
| `dict` / `list` | `{"a": 1}` / `[1, 2]` |
| `uv run python x.py` | このプロジェクトのPython実行。依存は`pyproject.toml` |

Houdini内のPythonは、**Houdini同梱のPython**で動く。追加のパッケージを入れにくいため、`tutorial_agent.py`は`urllib`（標準ライブラリ）だけでHTTPを呼ぶ。

### 練習
1. [`houdini_tools.py`](../../houdini/python_panels/houdini_tools.py)の`execute`（550行付近）を読み、「未知のツール名」「例外」「サンドボックス違反」のとき、それぞれ何を返すか。
2. `_run_in_main_thread`（351行付近）は、何のために、何をしているか。（→ [03 専門編 §7](03-specialized.md#7-houdini)）

## 4. C#を読む（Unity）

Unity側（`Assets/Editor/RAGChatbot/`）の読み方の最低限。

- `interface IRAGClient` は「できること」の約束。`CloudRAGClient`・`LocalRAGClient`が、それぞれ実装する。**接続先を切り替えても、画面側のコードは変わらない。**（Workerの層の考え方と同じ。→ [architecture-layering-plan.md](../architecture-layering-plan.md)）
- `EditorWindow`を継承したクラスが、Unityのエディタ内のウィンドウになる（`RAGChatbotWindow.cs`）。
- 通信は非同期。画面の更新は、Unityのメインスレッドで行う。

練習: `IRAGClient.cs`を開き、メソッドを書き出す。`CloudRAGClient.cs`と`LocalRAGClient.cs`で、同じメソッドの中身の違い（接続先・認証）を、1行ずつ書く。

## 5. 開発環境

| 道具 | 用途 | 確認 |
|---|---|---|
| Node.js / npm | Workerの開発（TypeScript） | `node -v` / `npm -v` |
| `wrangler` | Cloudflareの操作（開発・デプロイ・D1） | `npx wrangler --version` |
| `uv` | Pythonの実行・依存管理 | `uv --version` |
| Git | 履歴管理 | `git --version` |
| PowerShell / Bash | コマンド操作（→ [05 Script編](05-scripts.md)） | |

- Worker: `cd cloudflare-rag-poc` → `npm install`（初回のみ）→ `npm run typecheck`（型の確認）→ `npm run dev`（ローカルで起動）
- **ローカル起動のDB（`--remote`無し）は、本番と別物。** 空のことが多い。

## 6. Cloudflareの基本

| 部品 | 一言で | このプロジェクトでの使い方 |
|---|---|---|
| **Workers** | サーバーを持たずにコードを動かす。世界中の拠点で、必要なときだけ動く | `src/index.ts`がAPIとチャット画面を返す |
| **D1** | SQLite互換のDB | 利用者・履歴・予算・全文検索（FTS5） |
| **Vectorize** | ベクトル検索のDB | 意味検索（共有用`rag-poc-shared`、個人用`rag-poc-personal`） |
| **Cron Triggers** | 決まった時刻にコードを呼ぶ | ヘルスチェック（30分ごと）、日次の差分同期、定期の再クロール |
| **Secrets** | 秘密の値の保管 | `wrangler secret put GEMINI_API_KEY` |
| **wrangler.jsonc** | 上記の設定ファイル | `cloudflare-rag-poc/wrangler.jsonc` |

- `binding`は「コードの中での名前」。`"binding": "DB"`と書けば、コードでは`env.DB`で使える。
- **Workersの制約**（1回のCPU時間、外部呼び出し数、メモリ128MB）が、このプロジェクトの設計（バッチ処理＋再開）の理由。→ [03 専門編 §5](03-specialized.md#5-cloudflare特有の制約と回避策)

### 練習
1. [`wrangler.jsonc`](../../cloudflare-rag-poc/wrangler.jsonc)を読み、D1・Vectorize・Cronの設定を、それぞれ1行で説明する。
2. `env.VEC_SHARED`は、`wrangler.jsonc`のどの記述から来るか。
3. `wrangler secret put`で登録した値は、`wrangler.jsonc`に書かれていない。なぜ書かないのか。

## 確認

- [README.md](README.md)の「基礎」のチェック4項目に答えられる。
- 任意のファイル1つ（おすすめ: `src/budget.ts`）を、行ごとに「何をしているか」を日本語で書き出せる。
