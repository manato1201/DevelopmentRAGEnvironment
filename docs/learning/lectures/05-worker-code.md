# 第5回 Worker のコードを読む（`index.ts` からハンドラまで・テストの書き方）

**到達目標:** `cloudflare-rag-poc/src/index.ts` から、任意の API（例: `/pilot/plan`）の**ハンドラまで、ファイルと関数を順にたどれる**。ハンドラの型・エラーの返し方・テストの書き方を、真似て書ける。
**前提:** 第1〜4回、TypeScript を少し（変数・関数・`async/await`・`interface`）。 **目安:** 4時間

---

## 1. 全体像

[図11](../../images/11-request-life.svg) の **4（Worker を起動）〜7** が、この回のコードです。

```
リクエスト ──▶ index.ts fetch()
                ├─ GET /health, GET /（画面）, OAuth のコールバック …（鍵なし）
                ├─ POST 以外は 405
                ├─ （初回セットアップ・Slack など、鍵以外で確かめるもの）
                ├─ authenticate()           … 鍵 → ハッシュ → users → AuthedUser（無ければ 401）
                └─ switch (url.pathname)    … 道筋で、ハンドラへ
                      case "/pilot/plan":  return await handlePilotPlan(req, env, user);
                      …
                      default:             404「未定義のエンドポイントです」
              └─ catch: BudgetExceededError/RateLimitedError → 429、ForbiddenError → 403、その他 → 500
```

## 2. 基礎（TypeScript の読み方）

### 2.1 型

```ts
interface ProfileRow { user_id: string; pid: number | null; slot: number }   // 形を宣言
async function loadProfile(env: Env, userId: string): Promise<ProfileRow | null> { … }
```

- `number | null` は「数か、null」。`?` は「無くてもよい」。
- `Promise<T>` は「あとで T が届く」。`await` で待つ。**`await` を忘れると、まだ届いていない Promise を使ってしまう**（バグの定番）。
- 型は、**実行時には消えます**。外から来る値（リクエストの JSON）は、型を信用せず、**中身を確かめる**（`likert()`・`clampInt()`）。

### 2.2 ハンドラの形

すべての API は、同じ形の関数です。

```ts
export async function handlePilotSessionReset(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  const body = await readBody(req);                         // 手紙（JSON）を読む。壊れていても空のオブジェクト
  const id = typeof body.sessionId === "string" ? body.sessionId : "";   // 型を確かめる
  const row = id ? await env.DB.prepare("SELECT …").bind(id).first<…>() : null;
  if (!row || row.user_id !== user.userId || row.discarded_at != null)
    return jsonResponse(404, { error: "課題の記録が見つかりません" });   // 他人の記録は「無い」と答える
  …
  await env.DB.prepare("UPDATE pilot_sessions SET discarded_at = ? WHERE id = ?").bind(now, id).run();
  return planResponse(env, user.userId);                    // 更新後の状態を返す
}
```

読むときの観点:

1. **誰が呼べるか**（`requireAdmin(user)` があるか。なければ、鍵を持つ全員）
2. **入力を、どう確かめているか**（型・範囲・長さ）
3. **他人のデータに触れないか**（`user.userId` で絞っているか。他人の ID は「無い」と答えて、存在を教えない）
4. **失敗を、どの番号で返しているか**（400・404・409）
5. **書き込みは、原子的か**（複数の更新が、途中で止まっても壊れないか）

### 2.3 エラーの返し方

| 返したいもの | 書き方 |
|---|---|
| 入力が悪い | `return jsonResponse(400, { error: "…" })` |
| 無い・他人のもの | `return jsonResponse(404, { error: "…" })` |
| 今の状態ではできない | `return jsonResponse(409, { error: "…" })` |
| 権限が無い | `requireAdmin(user)`（`ForbiddenError` を投げ、`index.ts` の `catch` が 403 にする） |
| 予算・回数 | `BudgetExceededError`・`RateLimitedError`（429） |
| 想定外 | 何もしない（`catch` が 500 にする） |

エラーの文は、**日本語で、原因と対処**を書きます（パネルが、そのまま利用者に見せる場合があるため）。

### 2.4 純関数とハンドラを分ける

`src/pilotTasks.ts` の**上半分**は、**純関数**（同じ入力なら同じ出力。D1 も、時計も使わない）です。

```ts
export function slotForPid(pid: number): number { return ((pid - 1) % 3) + 1; }
export function mistakeScore(cook, self) { … }           // 操作ミスの合成
export function buildPlan(slot, sessions): TaskPlan { … } // 次の課題
export function buildHistory(sessions): HistoryItem[] { … } // やり直せる記録
export function summarizeTasks(rows) { … }               // 集計
```

**下半分**が、D1 を読み書きするハンドラです。

> なぜ分けるか: 純関数は、**D1 も、HTTP も要らず、一瞬でテストできる**。ハンドラは、純関数を呼ぶだけの**薄い層**にして、テストの量を、純関数に寄せる。**判断（ビジネスのルール）は、純関数に置く**。

### 2.5 ファイルの地図（`src/`）

| 役割 | ファイル |
|---|---|
| 入口・ルーティング | `index.ts` |
| 認証・権限 | `auth.ts`（`authenticate`・`requireAdmin`・`ForbiddenError`） |
| 共通 | `http.ts`（`jsonResponse`・`clampInt`）・`types.ts`（`Env`・`AuthedUser`） |
| 検索・回答 | `query.ts`・`search.ts`・`retrieve.ts`・`hybrid.ts`・`embeddings.ts`・`chunking.ts` |
| 予算・制限 | `budget.ts`・`rateLimit.ts`・`auditLog.ts` |
| 履歴・成長 | `memory.ts`・`threads.ts`・`growth.ts`・`glossary.ts` |
| ナレッジ登録・同期 | `kbIngest.ts`・`urlImport.ts`・`notionSync.ts`・`driveSync.ts`・`jiraSync.ts` … |
| 評価・実験 | `tutorialFeedback.ts`・`pilotTasks.ts`・`pilotStats.ts` |
| 外部の中継 | `claude.ts`・`tts.ts`・`mcp/` |
| 画面 | `chatUi.ts`・`asciiArt.ts`・`listSort.ts` |
| 運用 | `healthCheck.ts`・`alerts.ts`・`backup.ts` |

## 3. テストの書き方

### 3.1 実行

```bash
cd cloudflare-rag-poc
npm run typecheck          # 型の検査（tsc --noEmit）
npm test                   # 全テスト（tsx --test test/*.test.mjs）
npx tsx --test test/pilot_tasks.test.mjs   # 1ファイルだけ
```

### 3.2 偽の D1（本物のスキーマで）

テストは、本番に**つながりません**。`node:sqlite`（Node 標準の SQLite）に、`migrations/` を**番号順に**適用して、**本物と同じ表**を作り、D1 と同じ形（`prepare().bind().first/all/run`）の**偽物**で包みます（`test/pilot_tasks.test.mjs` の冒頭）。

```js
const db = new DatabaseSync(":memory:");
for (const f of readdirSync(MIG).filter((n) => n.endsWith(".sql")).sort()) db.exec(readFileSync(MIG + f, "utf8"));
const D1 = { prepare(sql) { return { a: [], bind(...x) { this.a = x; return this; },
  async run() { … }, async first() { … }, async all() { … } }; } };
const env = { DB: D1 };
```

> **マイグレーションを、テストで適用する意味**: SQL の構文の間違い・列の不足・部分一意索引の効き方が、**デプロイの前に**分かる。`0036` の「破棄した行を残しつつ、有効な行は1つ」も、このテストで確かめている。

### 3.3 ハンドラを呼ぶ

```js
const post = (body) => new Request("https://x/", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const call = async (handler, user, body = {}) => { const res = await handler(post(body), env, user); return { status: res.status, body: await res.json() }; };

const r = await call(pt.handlePilotSessionReset, u3, { sessionId: run1 });
assert.equal(r.status, 200);
assert.equal((await call(pt.handlePilotSessionReset, u3, { sessionId: run1 })).status, 404, "discard once only");
```

### 3.4 良いテストの条件

- **正常系だけでなく、境界と失敗を書く**: 他人の ID（404）・二重の操作（409/404）・範囲外の値（null になる）・次の回を始めたあと（409）。
- **理由を、メッセージに書く**（`assert.equal(…, 404, "discard once only")`）。落ちたとき、何が壊れたか分かる。
- **時間に依存しない**: 時間が絡むなら、DB の値を直接書き換えて（`UPDATE … SET started_at = …`）、結果を**範囲**で確かめる（±3秒）。
- **本物のスキーマ**で動かす（上の 3.2）。

## 4. このプロジェクトでは（たどってみる）

`POST /pilot/plan` を、行番号を確かめながら、たどります。

1. `src/index.ts` の `async fetch(` … POST か確認 → `authenticate(req, env)` → `switch` の `case "/pilot/plan"`
2. `src/pilotTasks.ts` の `handlePilotPlan` → `planResponse(env, userId)`
3. `planResponse` → `loadProfile`（`pilot_profile`）→ `loadSessions`（`pilot_sessions`。`discarded_at IS NULL`）→ `buildPlan`（純関数）・`buildHistory`（純関数）
4. `jsonResponse(200, { status: "ok", profile: true, pid, …plan, history })`

## 5. 演習

**演習 5.1（たどる）** 上の 1〜4 を、実際にファイルを開いて、**関数名と行番号**を書き出してください。

**演習 5.2（読む）** `handlePilotSessionEnd` を読み、(a) 他人の `sessionId` を送ると何が返るか、(b) `surveySec` が 99999 のとき `endedAt` はどうなるか、(c) `docs_only` の回に `sourceUseful` を送ると、どう保存されるか、を答えてください。テスト `pilot_tasks.test.mjs` の該当部分で確かめてください。

**演習 5.3（書く・小）** `pilotTasks.ts` の純関数 `median` に、**偶数個の入力**と**null を含む入力**の、テストの行を足してください（`test/pilot_tasks.test.mjs` の「集計の部品」の節）。実行して、通ることを確認してください。

**演習 5.4（書く・中）** 管理者向けに、`POST /admin/pilot/ping`（`{ status: "ok", registered: <参加者数> }` を返す）を足してください。手順: ①ハンドラ（`requireAdmin`）②`index.ts` の import と `case` ③テスト（管理者は 200、一般ユーザーは `rejects`）④型検査・テスト。**終わったら、元に戻してください**（演習なので、コミットしない）。

**演習 5.5（考える）** 次のコードの問題を、2つ挙げてください。

```ts
const row = await env.DB.prepare(`SELECT * FROM pilot_sessions WHERE id = '${body.sessionId}'`).first();
return jsonResponse(200, row);
```

## 6. つまずきやすい点

- **`await` の付け忘れ。** `const row = env.DB.prepare(…).first()` は、Promise。`row.user_id` が undefined になる。
- **`catch` で握りつぶす。** 失敗が見えなくなる。握りつぶすなら、**理由を、コメントに**（例: 習熟度の読み込みに失敗しても、質問そのものは続ける）。
- **`switch` に `case` を足し忘れる。** ハンドラを作っても、`index.ts` に無ければ、**404**（「未定義のエンドポイントです」）。
- **管理者だけの API に `requireAdmin` を忘れる。** 全員に見えてしまう。**テストで、一般ユーザーが拒否されることを、必ず確かめる**。

## 7. 確認問題

1. `authenticate` が null を返すと、どの番号か。権限の無い呼び出しは、どの番号か。
2. 純関数とハンドラを分ける利点は？
3. 他人の記録に触れたとき、403 でなく 404 を返す理由は？
4. テストで、本物の `migrations/` を適用する理由は？
5. ハンドラを作ったのに 404 が返る。最初に確かめることは？

## 解答の方針

- 5.2: (a) 404（他人の記録は「無い」と答える）。(b) `surveySec` は上限 86400 に丸められ、`now - 86400` が `started_at` より小さいので、`Math.max(row.started_at, …)` で `started_at`。所要時間は 0。(c) `null`（出典の有用性は、本システムを使わない回に無い）。
- 5.5: ① SQL インジェクション（値を、文字につなげている。`bind` を使う）。② 他人の `id` でも読める（`user_id` で絞っていない）。③ `SELECT *` で、返したくない列まで返す。
- 確認問題 3: 存在すること自体を、他人に教えないため。
- 確認問題 5: `index.ts` の `switch` に、`case` と import があるか。次に、**デプロイされた版が、そのコードを含むか**（第9回）。
