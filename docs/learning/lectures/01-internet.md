# 第1回 インターネットの基礎（URL・DNS・HTTPS・HTTP・JSON・API キー）

**到達目標:** [図11](../../images/11-request-life.svg) の **1・2（DNS）・3（HTTPS で送る）・11（JSON で返す）** を、自分の言葉で説明できる。エラーの番号（401・404・429…）から、「どこで止まったか」を言える。
**前提:** なし。 **目安:** 2時間

---

## 1. 全体像

あなたが Houdini のパネルで質問を送ると、パネルは**インターネット越しに**、運営の Worker（Cloudflare 上のプログラム）へ**手紙を出し**、**返事**を受け取ります。手紙と返事の書き方の決まりが **HTTP**、その手紙を盗み見られないようにする封筒が **HTTPS**、宛先の名前から住所を調べる電話帳が **DNS** です。

[![リクエストの一生](../../images/11-request-life.svg)](../../images/11-request-life.svg)

この回で扱うのは、図の左の部分（利用者 → DNS → 拠点）と、最後の「JSON で返す」です。

## 2. 基礎

### 2.1 URL（宛先の書き方）

```
https://rag-poc.manato1201m.workers.dev/query
└─┬─┘   └──────────────┬───────────────┘└─┬─┘
 方式（scheme）     ホスト名（host）     道筋（path）
```

- **方式**: `https` は「暗号化して送る」。`http` は暗号化しない（このプロジェクトでは使わない）。
- **ホスト名**: どのコンピューター（のグループ）に送るか。`workers.dev` は Cloudflare が貸している名前の領域で、`rag-poc.manato1201m` が、運営の Worker の名前。
- **道筋（path）**: そのコンピューターの中の、どの窓口か。`/query`（質問）、`/search`（検索）、`/pilot/plan`（実証実験の次の課題）…。Worker は、道筋で処理を振り分けます（第5回）。

### 2.2 DNS（名前を住所に直す）

コンピューターは、名前（`rag-poc.manato1201m.workers.dev`）では通信できません。**住所**（IP アドレス。例: `104.18.x.x`）が必要です。**DNS** は、名前から住所を調べる、インターネットの電話帳です。

1. パネルが「この名前の住所は？」と聞く（図の **1**）
2. 住所が返る（図の **2**）。結果は、しばらく手元に覚えておく（**キャッシュ**）ので、毎回は聞かない

> つまずき: 「サーバーに接続できません」の原因の多くは、(a) ネットワークが切れている、(b) URL の綴りが違って DNS が引けない、(c) サーバーが落ちている、のどれかです。パネルは、この種のエラーを「サーバーに接続できません。ネットワークと、「接続」タブの URL を確認してください。」と言い換えます（`houdini/python_panels/panel_info.py` の `friendly_error`）。

### 2.3 HTTPS（暗号化した封筒）

HTTP の手紙は、そのままだと、途中の誰かが**読める**ことがあります。**HTTPS** は、手紙を暗号化する封筒です（TLS という仕組み）。さらに、**相手が本物か**を、証明書で確かめます。

- 暗号化されるのは、手紙の中身（**キー**を含む）。**どのホストに送ったか**は、見えます。
- Cloudflare は、利用者に一番近い拠点（エッジ）で、HTTPS を受け止めます（図の **3** の先）。

### 2.4 HTTP（手紙と返事の書き方）

**リクエスト（手紙）**:

```
POST /query HTTP/1.1                          ← 方法（method）と道筋
Host: rag-poc.manato1201m.workers.dev         ← 宛先
Authorization: Bearer <あなたのAPIキー>        ← 誰が出したか（ヘッダー）
Content-Type: application/json                ← 本文の形
                                              ← 空行で、ヘッダーと本文を分ける
{"query": "Pyroとは？", "namespaces": ["houdini22"]}   ← 本文（body）
```

**レスポンス（返事）**:

```
HTTP/1.1 200 OK                               ← ステータスコード
content-type: application/json; charset=utf-8
                                              
{"status":"ok","answer":"…","sources":[…]}    ← 本文
```

**方法（method）** は、`GET`（取ってくる）と `POST`（送って処理させる）が主です。このプロジェクトの Worker は、**`/`（画面）と `/health` などを除き、POST だけ**を受け付けます（それ以外は 405）。

### 2.5 ステータスコード（返事の第一声）

番号の最初の数字で、おおまかな意味が決まります。**2xx = 成功、4xx = 手紙の側が悪い、5xx = サーバーの側が悪い**。

| 番号 | 意味 | このプロジェクトでの典型 |
|---|---|---|
| 200 | 成功 | 普通の応答 |
| 400 | 手紙の書き方が悪い | `kind は fixed か free を指定してください`（`pilotTasks.ts`） |
| 401 | 誰か分からない（認証に失敗） | キーが無い・違う・期限切れ。`index.ts` の `authenticate` が null を返したとき |
| 403 | 誰かは分かるが、権限が無い | admin 専用の API を、一般ユーザーが呼んだ（`ForbiddenError`） |
| 404 | その窓口は無い | **未定義のエンドポイントです: /pilot/plan** ＝ Worker が古い、または綴りの間違い |
| 405 | その方法は受け付けない | GET で API を呼んだ |
| 409 | 今の状態では、できない | 完了済みの課題を、もう一度終える・次の回を始めたあとに前の回をやり直す |
| 429 | 回数・予算が上限 | 60秒に30回を超えた（`rateLimit.ts`）・トークン予算が尽きた（`budget.ts`） |
| 500 | サーバーの中で例外 | コードのバグ・D1 の枠の超過（[06 障害記録 A](../06-maintenance-runbook.md)） |
| 503 | サーバーが一時的に使えない | |

> **覚え方**: 401 は「あなたは誰？」、403 は「あなたには、させない」。404 は「そんな窓口は無い」、409 は「今は、それはできない」。

### 2.6 JSON（データの書き方）

手紙の本文も、返事の本文も、**JSON** という形式で書きます。

```json
{
  "round": 1,
  "fixed": { "taskId": "pyro", "condition": "docs_only", "done": false },
  "history": []
}
```

- `{ }` は、名前と値の組（オブジェクト）。`[ ]` は、並び（配列）。
- 値は、文字列 `"…"`・数 `12`・真偽 `true/false`・`null`・入れ子。
- 末尾のカンマや、シングルクォートは、**間違い**です。

**「Unexpected token '<'」の正体**: 画面は JSON が返ってくると思って読もうとしたのに、実際は `<html>…` で始まる**エラーページ**だった、という意味です（サーバーが落ちた・Cloudflare のエラーページ）。コードのバグではなく、**サーバーから JSON が返らなかった**ことを疑います。

### 2.7 API キー（誰が出した手紙か）

- キーは、**利用者を識別する合言葉**です。`Authorization: Bearer <キー>` として送ります。
- Worker は、キーそのものを**保存しません**。キーの **SHA-256 ハッシュ**（元に戻せない要約）だけを、D1 の `users.user_id` に持ちます。手紙のキーをハッシュして、一致する行を探します（`src/auth.ts` の `authenticate`）。
- したがって、D1 が漏れても、キーは分かりません。
- **キーを置いてはいけない場所**: チャット・メール・コミット・スクリーンショット・URL（`?key=…`）。URL は、履歴やログに残ります。
- Worker 自身が使う外部の鍵（Gemini など）は、コードに書かず、**Secrets**（`wrangler secret put`）に入れます（第2回）。

## 3. このプロジェクトでは

| 学んだこと | 実際のコード |
|---|---|
| JSON の返事の作り方 | `cloudflare-rag-poc/src/http.ts` の `jsonResponse(status, body)` |
| 手紙（JSON）の読み方 | `src/pilotTasks.ts` の `readBody(req)`（読めなければ空のオブジェクト） |
| 数のクランプ（不正な値を丸める） | `src/http.ts` の `clampInt(raw, def, min, max)` |
| 認証 | `src/auth.ts` の `authenticate`（`Bearer` を取り出し、`sha256Hex`、`users` を引く） |
| 401/405/404 | `src/index.ts` の `fetch`（認証 → POST の確認 → `switch (url.pathname)` → 未定義は 404） |
| パネル側の送信 | `houdini/python_panels/rag_client.py` の `post_json`（`Authorization: Bearer` を付けて POST） |
| エラーの言い換え | `houdini/python_panels/panel_info.py` の `friendly_error` |

## 4. 演習

**演習 1.1（読む）** `cloudflare-rag-poc/src/index.ts` の `async fetch(` を開き、**リクエストが、401 になる条件**と、**405 になる条件**を、行番号つきで書いてください。

**演習 1.2（読む）** `houdini/python_panels/panel_info.py` の `friendly_error` を読み、次の入力がどのメッセージになるか、予想してから、`houdini/tests/test_panel_debug.py` で確かめてください。
1. `HTTP Error 404: Not Found`　2. `処理に 15000ms かかりました`　3. `<urlopen error [Errno 11001] getaddrinfo failed>`

**演習 1.3（送る）** 本番に**読み取りだけ**の確認を送ります（キーは使いません）。下の PowerShell を実行し、結果を説明してください。

```powershell
# 鍵なしで /pilot/plan を呼ぶ → 401 になるはず（404 なら、Worker が古い）
try { Invoke-RestMethod -Method Post -Uri "https://rag-poc.manato1201m.workers.dev/pilot/plan" -ContentType "application/json" -Body "{}" }
catch { $_.Exception.Response.StatusCode.value__ }
```

**演習 1.4（考える）** 次の症状は、HTTP のどの段階の問題ですか。(a) 画面に「応答がJSONではありません」と出る。(b) 「APIキーが無効か、期限が切れています」と出る。(c) 「サーバーに接続できません」と出る。

## 5. つまずきやすい点

- **401 と 403 を混同する。** 401 は「誰か分からない」、403 は「権限が無い」。
- **404 を「バグ」だと決めつける。** このプロジェクトでは、**新しい機能だけ 404** は、ほぼ「Worker が、まだデプロイされていない」です（第9回）。
- **curl が Windows で動かない。** PowerShell の `Invoke-RestMethod`、または Node の `fetch` を使うと、確実です。
- **キーをコピーして、うっかり貼る。** 貼ってしまったら、**そのキーを失効して、作り直す**（運営の管理画面）。

## 6. 確認問題

1. URL `https://a.example/b/c` の、方式・ホスト名・道筋は？
2. DNS が引けないと、どうなるか？ キャッシュは、何のためにあるか？
3. HTTPS で、暗号化されるものと、されないものは？
4. 403 と 409 の違いを、このプロジェクトの例で説明せよ。
5. キーを D1 に保存しないのは、なぜか？

## 解答の方針

- 1.1: `index.ts` の `authenticate` の直後（`if (!user)`）と、`req.method !== "POST"` を探す。
- 1.2: 1 → 「まだ対応していません」、2 → 「うまくいきませんでした」（桁の途中の数字を、ステータスと取り違えない。`has_status` の正規表現）、3 → 「サーバーに接続できません」。
- 1.3: 401。レスポンスが 404 なら、`index.ts` の `case "/pilot/plan"` を含むバージョンが、デプロイされていない。
- 1.4: (a) 応答の本文が JSON でない（サーバー側）、(b) 認証（401）、(c) 通信の前の段階（DNS・ネットワーク）。
- 確認問題 5: D1 が漏れても、キーが復元できないようにするため（ハッシュは一方向）。
