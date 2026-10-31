# 04. 応用編

**更新日:** 2026-10-17　**目安:** 1週間　**前提:** [02. 基礎編](02-fundamentals.md)、必要に応じて[03. 専門編](03-specialized.md)
**ゴール:** このプロジェクトに、**自分の手で機能を足し、壊さずにリリースできる**。

---

## 1. このプロジェクトの設計パターン

コードを読むときも、足すときも、**次のパターンのどれに当てはまるか**を先に考える。

| パターン | 内容 | 実例 |
|---|---|---|
| **バッチ＋再開** | 1回で少しだけ処理し、位置を保存して続きを呼び直す。1件の失敗で止めない | `urlImport.ts`、各`*Sync.ts` |
| **冪等な書き込み** | 何度やっても同じ結果。決まったIDで「置き換える」 | チャンクID＝`ハッシュ:番号`、`INSERT OR REPLACE` |
| **変更の検出** | ハッシュを保存し、変わったものだけ処理 | `crawl_page_hashes` |
| **許可リスト（デフォルト拒否）** | 明示的に許可したものだけ通す | `sync_allowed_namespaces`、`key_namespace_grants` |
| **オプトイン** | 自動の動作は、明示的にオンにしたものだけ | `auto_jira`などの自動同期 |
| **プレビュー→実行** | 副作用のある操作の前に、結果を見せる | 各連携の「プレビュー」 |
| **索引を経由する** | 全件走査を避け、対応表・要約表を持つ | `kb_documents`、`chunk_rows`、`stats_cache` |
| **エラーを結果として返す** | 例外で止めず、LLMや利用者が直せる文にする | `HoudiniToolExecutor.execute` |
| **サーバー側で強制する** | 予算・権限は、クライアントを信じず、サーバーで止める | `budget.ts`、`auth.ts` |
| **追加のみのマイグレーション** | 表は足すだけ。適用済みのファイルを書き換えない | `migrations/` |

## 2. レシピ（機能の足し方）

どのレシピも、**最後に「§4 リリース」を行う**。

### レシピA: 新しいAPIルートを足す

**例:** `POST /admin/hello` が、管理者にだけ`{"status":"ok","message":"hello"}`を返す。

1. **ハンドラを書く。** `cloudflare-rag-poc/src/hello.ts`を作る。
    ```ts
    import type { AuthedUser, Env } from "./types";
    import { jsonResponse } from "./http";
    import { requireAdmin } from "./auth";

    export async function handleHello(req: Request, env: Env, user: AuthedUser): Promise<Response> {
      requireAdmin(user);                       // 権限は、必ず最初に確認する（403を投げる）
      const body = (await req.json().catch(() => ({}))) as { name?: string };
      return jsonResponse(200, { status: "ok", message: `hello ${body.name ?? ""}`.trim() });
    }
    ```
2. **入口に登録する。** `src/index.ts`の先頭にimportを足し、`switch (url.pathname)`に`case "/admin/hello": return await handleHello(req, env, user);`を足す。
3. **確認する。** `npm run typecheck` → `npm run dev` → `curl`で呼ぶ。
4. 権限の確認: ①キー無し→401、②memberのキー→403、③adminのキー→200、の3つを必ず試す。

**落とし穴**
- 権限確認の**付け忘れ**が、最も危険。ハンドラの先頭に必ず書く（`requireAdmin` / `requireKnowledgeEditor`）。
- 入力は信用しない。数値は`clampInt`、文字は長さを確認。
- 認証不要のルート（`/health`など）は、`authenticate`より前にある。新しいルートは、**後ろ（`switch`の中）**に置く。

### レシピB: 新しいテーブル（マイグレーション）を足す

**例:** 「お知らせ」を保存する`notices`表。

1. **番号を決める。** `ls migrations/`で、最後の番号を確認し、+1（例: `0031_notices.sql`）。
2. **SQLを書く。** 冒頭に、**なぜ必要か**をコメントで書く（後で自分が助かる）。
    ```sql
    -- お知らせ（2026-10-xx追加）。管理者が書き、全員が読む。
    CREATE TABLE IF NOT EXISTS notices (
        notice_id TEXT PRIMARY KEY,
        body TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_notices_created ON notices(created_at);
    ```
3. **ローカルで適用して確かめる。** `npm run db:migrate:local` → `npx wrangler d1 execute rag-poc-db --command "SELECT name FROM sqlite_master WHERE name='notices'"`
4. **本番へは、デプロイの前に適用する。**（→ §4）

**落とし穴**
- **適用済みのファイルを書き換えない。** 直したいときは、**新しい番号**で、`ALTER TABLE`や新しい表を足す。
- **検索・並べ替えに使う列には、索引を足す**（足さないと、全行を読む。→ [03 §5.2](03-specialized.md#52-d1の読み取り行数を増やす原因3つ)）。
- ユーザーを消す処理（`keyAdmin.ts`の`handleDeleteKey`）に、**そのユーザーの行を消す1行を足す**。忘れると、消したはずの個人データが残る。
- 既存の行を埋める処理は、同じファイルに書く。**大きな表を全件読む処理は、1回きり**にする（D1の読み取り枠）。

### レシピC: 新しい連携（外部サービスとの同期）を足す

今は、既存の連携（`backlogSync.ts`など）を**写して作る**。将来は共通の骨格になる予定（[architecture-layering-plan.md §4.2](../design/architecture-layering-plan.md#42-コネクタの契約プラグインの形)）。

1. 写す元を決める。**認証がAPIキー方式ならBacklog**、**OAuthならJira**が近い。
2. 作るもの: `xxxOAuth.ts`（接続）、`xxxSync.ts`（同期・プレビュー・失敗分の再同期）。
3. **必ず守る安全策**（既存の連携と同じにする）
   - 同期先は`authorizeSync`（`syncTargets.ts`）で認可する（許可リスト、個人用は本人のみ）。
   - プレビュー（登録せず、内容だけ返す）を作る。
   - 自動同期は、`kb_sources`に`auto_xxx`列を足し、**既定はオフ**にする。
   - 失敗は、1件ごとにcatchして、`kb_log`に記録。全体は止めない。
   - 履歴は`recordOp`で、実行者を残す。
4. `index.ts`にルートを足し（`/admin/sync/xxx`、`/preview`、`/retry-failed`）、`types.ts`に環境変数を足し、画面（`chatUi.ts`）にカードを足す。
5. ドキュメント: `cloudflare-rag-poc/docs/`に、使い方・必要なsecretを書く。

### レシピD: Houdiniの道具を足す

**例:** ノードを複製する`copy_node`。変更する場所は**3か所**。

1. **定義を足す。** `houdini_tools.py`の`HOUDINI_TOOLS`（リスト）に、名前・説明・`input_schema`（JSON Schema）を足す。**説明文は、LLMが読む**ので、いつ使うか・使ってはいけないときを書く。
2. **実行を足す。** `HoudiniToolExecutor`に`_tool_copy_node(self, args: dict) -> str`を足す。
   - ノードのパスは、必ず`self._resolve(path)`を通す（サンドボックスの外を拒否する。通さないと、外のノードを触れてしまう）。
   - 結果は、**LLMが次の判断に使える文**で返す（作ったノードのパス、見つからなかった理由など）。
   - 失敗は、`raise`でよい（`execute`が、エラー結果に変換する）。
3. **システムプロンプトに、使い方を足す**（`tutorial_agent.py`）。道具だけ増やしても、使い方が伝わらないと使われない。
4. 実機で、3つ以上の依頼で試す。**実機に反映するには、`Documents/houdini21.0/python_panels`へのコピーが必要**（リポジトリを直しても、実機は変わらない。→ 配置先の注意）。

**落とし穴:** `hou`を触る処理は、`execute`が`_run_in_main_thread`で包むので、`_tool_*`の中では**意識しなくてよい**。ただし、`_tool_*`の外（別スレッド）で`hou`を直接呼ばない。

### レシピE: 管理画面にカードを足す

`chatUi.ts`は、画面全体が**1つのテンプレート文字列**。

- HTMLは、`<div class="admin-subpanel" data-subtab="…">`の中にカード（`<div class="card">`）を足す。
- 処理は、同じファイルのスクリプト部分に書く。サーバーとは、`api("/admin/xxx", {…})`で通信する（失敗の再試行・非JSON応答の判定を含む共通関数）。
- **テンプレート文字列の制約:** 文字列中の`` ` ``と`${…}`は、そのまま書けない。バックスラッシュも、1つの`\`が消える（`\\`と書く）。**表示が壊れたら、まず、ここを疑う。**
- 画面の部品・色・文言の規約は、[ui-rules.md](../design/ui-rules.md)。
- 管理者専用のものは、`class="admin-only-section"`を付ける（非管理者には、表示されない）。ただし、**見えないだけで、サーバー側の権限確認は別に必要**（レシピA）。

## 3. テストと確認

### 3.1 現状

| 確認 | あるか | 方法 |
|---|---|---|
| 型チェック（Worker） | ○（CIで自動） | `cd cloudflare-rag-poc && npm run typecheck` |
| Python静的解析 | ○（CIで自動） | `.github/workflows/ci.yml`（ruff・mypy） |
| Workerの自動テスト | ○（CIで自動。`cloudflare-rag-poc/test/`の9ファイル） | `cd cloudflare-rag-poc && npm test` |
| Houdini・Unityの自動テスト | ×（実機で確認） | — |

**Workerのテストは、2026-10-17にリポジトリへ入れた**（それまでは、リポジトリの外に置かれていた）。`npm test`は、TypeScriptの元のファイルを直接動かす（`tsx`。ビルド不要）。偽のD1（`node:sqlite`）と偽の外部APIだけを使うので、**Cloudflareにも外部サービスにも、接続しない**。Node.js 22以上が必要。

| テスト | 見ているもの |
|---|---|
| `chunk_rows.test.mjs` | チャンクの登録・再登録・短縮・削除と、FTSとの対応表のずれ |
| `crawl_graph.test.mjs` | クロールの再開・変更なしのスキップ、グラフの500件の比例配分 |
| `features2.test.mjs` | ステージング、答えられなかった質問、定期クロール、同期の許可リスト |
| `features3.test.mjs` | スレッド、プリセット、Slack（署名・連携コード）、ユーザー削除 |
| `gmail.test.mjs` | Google連携（Gmail・Drive）のOAuthと同期 |
| `gov.test.mjs` | 連携のガバナンス（許可リスト・個人用・プレビュー・自動同期のオプトイン） |
| `mcp.test.mjs`・`mcp_ext.test.mjs` | 公式MCPクライアント（接続・ツール・権限・監査） |
| `stream.test.mjs` | 回答のストリーミング（SSEの分割・失敗時の返金） |

**未確認のもの:** 実際のGemini・Slack・各OAuthサービスとの通し（偽のものでしか試していない）。画面（`chatUi.ts`）、Houdini、Unity。

### 3.2 当面の確認手順（手動）

1. `npm run typecheck`（0で終わる）と、`npm test`（全部passする）
2. `npm run dev`で起動し、`curl`で、変更したルートを、**正常系と異常系**（キー無し・権限不足・不正な入力）で呼ぶ。
3. 画面を変えたときは、ブラウザで操作し、**開発者ツールのConsoleにエラーが出ていない**ことを確認する。
4. DBの確認は、**ローカル**で（`--remote`なし）。
5. **本番で確認するなら、読み取りのコマンドだけ**。書き込みは、手順を決めてから。

### 3.3 テストの考え方（書くときの型）

- **偽のDB**（メモリ上のSQLite）と**偽の外部API**（`fetch`を差し替え）で、実際のネットワークを使わずに動かす。
- 見るのは、「**何が返るか**」と「**DBに何が残るか**」。
- **失敗のケースを必ず書く**（権限なし、不正な入力、外部APIの失敗、上限超過）。
- **書いたテストが、本当に失敗を検出できるか**を、一度、確かめる（コードをわざと壊して、失敗することを見る。確かめたら、必ず元に戻す）。
- 新しいテストは、`cloudflare-rag-poc/test/名前.test.mjs`に置く。既存の1本を写すのが早い（偽のD1の作り方が、そのまま使える）。

## 4. リリース手順（チェックリスト）

**順序には理由がある。** 順番を変えない。

```
□ 1. 変更の中身を読む        git status / git diff
□ 2. 型チェックとテスト      cd cloudflare-rag-poc && npm run typecheck && npm test   （どちらも成功）
□ 3. 未適用のマイグレーションを確認    npx wrangler d1 migrations list rag-poc-db --remote
□ 4. 適用前に、中身を読む    migrations/ の対象ファイル。大きな表を全件読む処理が無いか
□ 5. マイグレーションを適用  npm run db:migrate:remote      ← 確認プロンプトに、自分で答える
□ 6. 適用を確認              対象の表・列があるか（SELECT name FROM sqlite_master …）
□ 7. デプロイ                npm run deploy
□ 8. 動作確認                /health、画面の読み込み、変更した機能の正常系・異常系
□ 9. 記録                    git commit（メッセージは、既存の書き方に合わせる）、必要ならドキュメント
```

**なぜ、マイグレーションが先か:** 新しいコードは、新しい表・列を読む。**先にコードを出すと、表が無いので、全部が500になる。**
**なぜ、確認プロンプトに自分で答えるか:** 本番のDBを変更する操作は、**何が適用されるかを見てから**行う（自動で「はい」にしない）。
**D1の読み取り枠に余裕があるときに行う:** 枠を使い切っている間は、マイグレーションも失敗する。→ [06 §3](06-maintenance-runbook.md#3-障害記録)

**デプロイを戻したいとき:** `npx wrangler rollback`（直前の版に戻す）。**DBのマイグレーションは戻らない**（追加のみにしておけば、古いコードでも動く。だから、削除・名前変更はしない）。

## 5. おすすめの改善（AI無しで続けられるようにするために）

優先度の高い順。**（Workerのテストの追加と、CIでの自動実行は、2026-10-17に完了した。）**

| # | 改善 | 理由 |
|---|---|---|
| 1 | **`chatUi.ts`を分解する**（[architecture-layering-plan.md §4.4](../design/architecture-layering-plan.md#44-chatuits-の分解)） | 6,000行超の1つの文字列は、人間が直すのも難しい。画面のテストも作れない |
| 2 | **API仕様書（OpenAPI）を作る** | クライアント（Unity・Houdini）と、サーバーの食い違いを防ぐ |
| 3 | **本番を触らずに試せる環境（ステージングのWorker）を作る** | D1の上限や、マイグレーションの失敗を、本番で踏まずに済む |
| 4 | **テストを増やす**（認証・権限、検索、各連携の同期の、異常系） | いまのテストは、新しい機能（2026-10）に偏っている |

## 練習

1. レシピAに沿って、`GET`ではなく`POST`で`/admin/hello`を作り、3つの権限のケースを試す。**終わったら、変更を元に戻す**（`git restore`）。
2. 現在の最新のマイグレーションの番号を調べ、次の番号で、空のマイグレーション（コメントだけ）を作る。ローカルに適用する。**終わったら、ファイルを削除する。**
3. 「`chunk_rows`を足したマイグレーションが、デプロイの前に必要だった理由」を、§4の言葉で説明する。
4. §4のチェックリストの各項目を、「飛ばすと何が起きるか」で書き直す。

## 確認

- [README.md](README.md)の「応用」のチェック3項目に答えられる。
