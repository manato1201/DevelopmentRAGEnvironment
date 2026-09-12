# AxChatD ナレッジ登録機能 逆輸入ガイド

作成日: 2026-08-31
対象: `scripts/knowledge_manager.py` / `scripts/rag_local_bridge.py`(Python local RAG)を主対象とし、該当箇所のみ `cloudflare-rag-poc/` と `scripts/gas_cloud_rag.js` にも言及する。

## 背景

`docs/axchatd-rag-integration-plan.md` に基づき、AxChatD(`Enterprises/AXTechCare/AxChatD/RAGEnvironment`、FastAPI + React)側で「ナレッジ登録機能の拡充」(FAQ/QA一括登録・URL/YouTube/ファイル単発登録・音声動画文字起こし・Notion継続同期・操作履歴とロールバック・管理画面UX改善)を実装した。

その過程で、AxChatDの `KnowledgeManager` と本プロジェクトの `scripts/knowledge_manager.py` が**同一の設計に基づく実装**(メソッド名・シグネチャ・ジャーナル方式まで酷似)であることが判明し、AxChatD側で発見・修正したバグの多くが**そのまま同じ形でこちらにも存在する**ことを確認した。

本ドキュメントは、AxChatDでの作業内容と本プロジェクトの現状を突き合わせ、(1) 逆輸入すべきバグ修正、(2) 逆輸入を検討すべき機能ギャップ、(3) 設計上の注意点、を整理したものである。

---

## 1. 優先度高：本プロジェクトに現存するバグ

以下はすべて、別セッションでのコード調査により**実際にこのリポジトリの現行コードで確認済み**。

### 1-1. `add_source` — 初回取得に失敗した登録ソースが永久に残る

**該当箇所**: `scripts/knowledge_manager.py:329-351`

```python
def add_source(self, url: str, namespace: str, interval_hours: int = 24) -> dict:
    ...
    sources.append(src)
    self._save_json(self.sources_path, sources)      # 329行目付近: 先に登録を保存
    # 初回取り込み
    self.crawl_source(src["id"])                      # 350行目: try/exceptなし
    return [s for s in self._sources() if s["id"] == src["id"]][0]
```

**問題**: `crawl_source` が `_convert_url` の失敗で `KnowledgeError` を送出すると、`sources.json` への登録（348行目時点で完了済み）はロールバックされない。`crawl_source` は失敗時に `last_crawled` を更新しないため、`crawl_due()` の期限チェック（`if not force and src.get("last_crawled")`）が常に偽となり、**壊れたソースが以後すべての定期クロールで無限に再試行され続ける**。

**AxChatD側での修正**（`RAGEnvironment/server/app/knowledge/knowledge_manager.py`）:

```python
sources.append(src)
self._save_json(self.sources_path, sources)
# 初回取り込み。失敗した場合は登録自体を取り消し、取得できなかったURLが
# 壊れたまま永久に登録され続け、以後のcrawl_dueで際限なく再試行されるのを防ぐ。
try:
    self.crawl_source(src["id"])
except Exception:
    remaining = [s for s in self._sources() if s["id"] != src["id"]]
    self._save_json(self.sources_path, remaining)
    raise
return [s for s in self._sources() if s["id"] == src["id"]][0]
```

**移植方法**: `scripts/knowledge_manager.py` の同箇所に、上記と同じ try/except を追加するだけで良い（周辺ロジックは同一）。

---

### 1-2. `import_qa_csv` — 列の自動判定で質問と回答が入れ替わる

**該当箇所**: `scripts/knowledge_manager.py:285-297`

```python
header = [c.strip().lower() for c in rows[0]]
q_idx, a_idx, start = 0, 1, 0
for i, col in enumerate(header):
    if col in ("question", "質問", "q"):
        q_idx = i
    if col in ("answer", "回答", "a"):
        a_idx = i
if any(c in ("question", "質問", "q", "answer", "回答", "a") for c in header):
    start = 1
if q_idx == a_idx:
    a_idx = q_idx + 1
```

**問題**: 質問列・回答列をそれぞれ独立にキーワード走査しているため、たとえばヘッダーが `["answer", "notes"]` の場合、`a_idx=0`（"answer"に一致）が設定される一方 `q_idx` は何にも一致せずデフォルトの `0` のまま残る。その結果 `q_idx == a_idx == 0` の衝突が起き、フォールバック（`a_idx = q_idx + 1`）が発動して **`q_idx=0`（実際は回答列）が質問として、`a_idx=1`（"notes"列）が回答として使われてしまう**。エラーは出ず、サイレントに質問と回答が入れ替わって登録される。

**AxChatD側での修正**（`RAGEnvironment/web/src/pages/AdminPage.tsx`、`extractQaPairs`）: キーワード走査による自動判定をやめ、**「1列目=質問、2列目=回答」を固定とし、`["question","answer"]` または `["質問","回答"]` の完全一致ヘッダーのみを自動判定する**方式に簡素化した。

```typescript
function extractQaPairs(text: string): Array<{ question: string; answer: string }> {
  const rows = parseCsvRows(text);
  if (!rows.length) return [];
  const header = rows[0].map((cell) => cell.trim().toLowerCase());
  const isHeaderRow =
    (header[0] === "question" && header[1] === "answer") || (header[0] === "質問" && header[1] === "回答");
  const start = isHeaderRow ? 1 : 0;

  const pairs: Array<{ question: string; answer: string }> = [];
  for (const row of rows.slice(start)) {
    if (row.length < 2) continue;
    const question = (row[0] || "").trim();
    const answer = (row[1] || "").trim();
    if (question && answer) pairs.push({ question, answer });
  }
  return pairs;
}
```

**移植方法**: `scripts/knowledge_manager.py` の `import_qa_csv` 内の列判定ロジックを、上記と同じ「完全一致ヘッダーのみ自動判定・それ以外は1列目=質問/2列目=回答固定」に置き換える。ユーザー向けの案内文言（CSVフォーマット説明）も、この挙動に合わせて更新すること。

---

### 1-3. 継続同期のNotionソースが履歴上で識別できない

**該当箇所**: `scripts/knowledge_manager.py` 内、`crawl_source`/`import_url` は `op_type="url"`（208行目）または `"crawl"`/`"crawl_update"`（391, 398-401行目）を無条件に使用しており、URLがNotionドメインかどうかを判定する分岐が存在しない。

**問題**: 継続同期に登録したソースがNotionページであっても、操作履歴（ジャーナル）上は他の一般URLと同じ `"url"`/`"crawl"` 種別で記録され、区別できない。

**AxChatD側の状況**: これはAxChatD側でも同一のバグとして発見・修正した（`source_type=source_type or "notion"` が実際には決して発火しない dead code だった）。加えてAxChatDでは、**そもそもPython版と同様「Notion URLでも汎用スクレイピングに流れてしまい、実質使い物にならない」問題も併発していた**ため、根本対応として `_convert_notion_url` を新設し、Notion判定時は常に `source_type="notion"` を強制するよう修正した（詳細は次章2-1）。

**移植方法**: 次章「2-1. Notion API連携（Python版）」の対応と合わせて実施するのが効率的（Notion専用変換を追加する際に、種別タグ付けも同時に直せるため）。

---

### 1-4. 参考：今回は問題なしと確認できた箇所

念のため確認したが、以下はPython版がすでに正しく実装されていた。誤って「直さなきゃ」と着手しないよう明記しておく。

- **ファイル名の一意性**（`_new_id()`, `scripts/knowledge_manager.py:102-104`）: `time.strftime(...) + secrets.token_hex(2)` で乱数サフィックスが最初から入っており、AxChatDで見つけた「同一秒内の登録がファイル名衝突で上書きされる」バグは存在しない。
  - 参考: このバグはAxChatD側で**新規に書いたコード**（`import_knowledge_url`/`youtube`/`file` エンドポイント）が、既存の `_new_id()` 相当のヘルパーを使わずタイムスタンプのみでファイル名を生成してしまったために発生したもの。教訓として、新規エンドポイントを書く際は既存の `_new_id()` ヘルパーを必ず再利用すること。
- **ロック範囲**（`crawl_source`, `scripts/knowledge_manager.py:361-409`）: ネットワーク取得（`_convert_url`）は `with self._lock:` の**外側**で行われており、ロック保持中に外部通信をブロッキングする問題はない。
  - 参考: AxChatD側の同種バグは `KnowledgeManager` 自体ではなく、**新設したFastAPIルーター層**（`add_knowledge_source`/`crawl_knowledge_sources` エンドポイント）が、すでに内部で適切にロック範囲を管理している `add_source`/`crawl_due` の呼び出し全体を、さらに外側から独自のHTTPレベルロック（`writer_operation_lock()`）で包んでしまったために発生した。Python版にはこの種の「HTTPハンドラ層の追加ロック」という概念自体がないため、直接該当する修正対象はない。ただし、**将来`rag_local_bridge.py`に何らかの排他制御を追加する際は、`KnowledgeManager`が既に内部で行っている細粒度ロックの外側を、さらに粗いロックで包まないよう注意**という教訓として記録しておく。

---

## 2. 機能ギャップ：本プロジェクトに無い機能

### 2-1. Notion API連携（Python版のみ欠落）

| 実装 | 状態 |
|---|---|
| GAS (`scripts/gas_cloud_rag.js`) | ✅ 実Notion API使用（`kbCreateNotionPage_`, `syncNotionToSheets`） |
| Cloudflare PoC (`cloudflare-rag-poc/src/notion.ts`) | ✅ 実Notion API使用 |
| Python local RAG (`scripts/knowledge_manager.py`) | ❌ `_convert_url` は汎用 `markitdown` 変換のみ。`NOTION_TOKEN`/`NOTION_API_KEY` への参照が一切ない |
| AxChatD（今回） | ✅ 新規追加（後述） |

Python版にも `notion_to_corpus.py`・`notion_bulk_add.py`・`localrag_to_notion.py` という実Notion API利用スクリプトは存在するが、**いずれも独立したCLIパイプラインであり、`rag_local_bridge.py`のHTTP API（＝ローカルRAGの検索インデックス）には接続されていない**。つまり「継続同期やURL単発登録でNotion URLを渡しても、Notion APIは使われず質の低い汎用スクレイピングになる」状態が、GAS・Cloudflareでは起きないのにPython版でだけ起きている。

**AxChatD側の対応**（`RAGEnvironment/server/app/knowledge/knowledge_converter.py`）:

```python
def convert_url(self, url: str, source_type: str = "url") -> CanonicalDocument:
    normalized_url = self._normalize_url(url)
    if not re.match(r"^https?://", normalized_url or ""):
        raise KnowledgeConversionError("URLは http:// または https:// で始まる必要があります")
    if is_notion_url(normalized_url):
        return self._convert_notion_url(normalized_url)
    # ...既存の markitdown / crawler フォールバック...

def _convert_notion_url(self, notion_url: str) -> CanonicalDocument:
    # NotionかどうかはURLの性質であり、呼び出し元の意図に関係ないため、
    # 常に source_type="notion" を強制する（呼び出し元から渡された値は使わない）
    try:
        body = convert_notion_url_to_markdown(notion_url)
    except Exception as exc:
        # 継続同期のバックグラウンドスレッドからも呼ばれるため、想定外の例外も
        # 必ずKnowledgeConversionErrorに正規化する（生の500を漏らさない）
        raise KnowledgeConversionError(f"Notionページの取得に失敗しました: {exc}") from exc
    ...
    return CanonicalDocument(..., source_type="notion", ...)
```

Notion APIクライアント自体（トークン認証・ページ取得・ブロック再帰変換）は `converters/notion.py` として新規実装した。ロジック自体はGAS/Cloudflare版の `notion.ts` と同等（ページ取得→ブロック再帰取得→Markdown変換）なので、**移植というより「Python版の`_convert_url`にNotion分岐を追加し、Notion API呼び出しを新規実装する」作業**になる。

**推奨移植方法**:
1. `scripts/knowledge_manager.py` に `is_notion_url()`/Notion API呼び出しヘルパーを追加（`cloudflare-rag-poc/src/notion.ts` のロジックをPythonに移植するのが早い）。
2. `_convert_url` の先頭でNotion判定→専用変換に分岐。
3. これにより 1-3 の「Notion種別タグ付け」問題も同時に解消する。

---

### 2-2. 継続同期がNotionページに未対応（URLのみ）

現状 `crawl_source`/`add_source` はURLの種類を区別しないため、**技術的にはNotion URLも `add_source` に登録できる**が、2-1の問題により汎用スクレイピングにしかならない。2-1を対応すれば、継続同期は自動的にNotionページにも正しく対応する（コード上の分岐は `_convert_url`/`crawl_source` の共通化された経路を通るため、追加の同期専用対応は不要）。

---

### 2-3. 管理者向け「検索テスト」パネル（GAS/Cloudflare/Python いずれにも無し）

3実装すべてを調査したが、「登録した内容がすぐ検索でヒットするか、管理者がその場で試せる」専用の機能・エンドポイントは**どこにも存在しない**（GAS/Cloudflareのend-userの`/search`,`/query`と同じものしかない）。

**AxChatD側で新規追加**: `POST /api/writer/search-test` — 既存の検索ロジック（`services/query_service.py`の`search_rag`）を、writerサービス自身が今保持しているインデックスに対してそのまま呼び出すだけの薄いエンドポイント。管理画面に検索ボックスを設置し、「chunk変換した内容が実際にヒットするか」をその場で確認できる。

```python
@router.post("/api/writer/search-test")
def writer_search_test(
    body: QueryRequest, request: Request, user: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    require_writer_runtime()
    return search_rag(body, user, request)
```

**移植方法**: `rag_local_bridge.py` の既存 `_handle_search` をそのまま呼ぶ管理者専用エンドポイント（例: `/api/admin/search-test`）を追加し、シンプルなHTML/JSの検索ボックスを管理画面に置くだけで良い。ロジックの新規実装は不要。

---

### 2-4〜2-6. 管理画面UXの改善（フロントエンドが存在する場合のみ該当）

Python版はHTTPベースのAPIのみで、AxChatDのような React 管理画面を持たない（想定では簡易HTML/JSフロントか、GAS版の `getChatHtml_()` 相当のUIが対応箇所と思われる）。UIが存在する範囲で、以下は低コストで移植価値がある:

- **QA CSVプレビュー確認**: アップロード即登録ではなく、パース結果（先頭5件+全件数）を表示してから確定させる。列入れ替わりバグ（1-2）のような事故を視覚的に未然防止できる。
- **QA CSV並列アップロード+進捗表示**: 1行ずつの逐次処理から並列数を上げ、進捗バーを表示（AxChatDでは同時6件）。
- **継続同期の「再試行」ボタン**: 登録済みソースを、期限を待たずその場で1件だけ再クロールする（AxChatDでは `crawl_source(source_id)` を直接呼ぶ専用エンドポイントを追加）。
- **未反映件数バッジ・登録元別内訳表示**: 「登録はしたがindexにまだ反映されていない件数」を常時表示し、ワンクリックで反映できるようにする。

これらはPython版がHTMLベースの管理UIを持つかどうかに依存するため、対応の要否は別途判断すること。

---

## 3. 設計上の注意点

### 3-1. `rag_local_bridge.py` の単一スレッドHTTPServer

`scripts/rag_local_bridge.py:35, 1096` で `http.server.HTTPServer`（`ThreadingHTTPServer`ではない）を使用しており、**1リクエストの処理が終わるまで他のすべてのリクエストがブロックされる**。`_call_claude`/`_call_gemini`（30〜60秒タイムアウトの同期通信）、`_handle_graph`（`subprocess.run(timeout=90)`）、`/api/knowledge/*` の外部通信を伴う登録処理などが、いずれもこの単一スレッド上で直列に実行される。

これはAxChatDで見つけた「`async def` ルートの中で同期処理（Gemini File API文字起こし）を直接呼んでイベントループを止めていた」バグと**同じ系統の問題だが、根本原因も対応方法も異なる**（AxChatDはasyncioの誤用、こちらはサーバー実装の選択そのもの）。修正には `ThreadingHTTPServer` への切り替え、または非同期フレームワークへの移行が必要で、**影響範囲が大きいため今回のバグ修正セットには含めず、別途の設計判断として記録するに留める**。

### 3-2. 「即時index」方式 vs AxChatDの「ステージング→明示的build」方式

Python版の `add_faq`/`import_qa_csv`/`import_url`/`import_youtube`/`import_file_bytes` はいずれも、変換したその場で `_index()` を呼び即座にベクトルDBへ反映する「即時index」方式（GAS/Cloudflareも同様）。

AxChatDでは、FAQ/QA/URL/YouTube/ファイルの新規クイック登録機能を実装する際、あえてこれとは異なる**「まずMarkdownステージング領域に置き、管理者が明示的に『chunk変換』ボタンを押すまではindexしない」**という2段階方式を採用した。理由は、AxChatDの埋め込み処理がCPU駆動（Cloud Run、GPU無し）で1回あたり数分かかることがあり、「クイック登録のたびに気づかぬうちに重い変換が走る」体験を避けるため。

Python版（ローカルGPU/CPU環境に依存するが、一般に同様の重さの懸念がある）にこの設計を持ち込むかどうかは、**単純な移植ではなく設計変更を伴う判断**になるため、対応するかどうかは別途検討すること。ちなみにPython版の継続同期（`crawl_source`/`crawl_due`）は元々「即時index」のままで問題ない設計（バックグラウンドで自動的に反映されることが期待値のため）。

---

## 4. 対応状況サマリ

| 機能 | GAS | Cloudflare PoC | Python local RAG | AxChatD(今回) |
|---|---|---|---|---|
| QA CSV一括登録 | ✅ | ✅ | ✅(列判定バグあり) | ✅(修正+プレビューUI) |
| FAQ単発追加 | ✅ | ✅ | ✅ | ✅ |
| URL/YouTube/ファイル単発登録 | ✅ | ✅ | ✅ | ✅ |
| Notion API連携 | ✅ | ✅ | ❌(汎用scraping止まり) | ✅(新規実装) |
| 継続同期(URL) | ❌(手動実行のみ) | ❌(手動実行のみ) | ✅(バグあり) | ✅(修正+個別再試行UI) |
| 継続同期(Notion) | ❌ | ❌ | ❌(2-1に依存) | ✅ |
| 操作履歴+ロールバック | ✅(削除のみ) | ✅(削除のみ、生データ非保持) | ✅(復元も可能) | ✅(削除+復元) |
| 音声/動画文字起こし | ✅ | ✅ | △(オフライン別CLI、bridge未接続) | ✅(non-blocking化済み) |
| 検索テストパネル | ❌ | ❌ | ❌ | ✅(新規実装) |
| Ingest操作へのレート制限/バジェット | 一部のみ | ❌(ingestには未適用) | ❌ | ❌(今回は未着手) |

---

## 5. 推奨アクション(優先順)

1. **`add_source` の失敗時ロールバック**（1-1） — 低リスク・高価値。数行の変更で永久retry storm を防げる。
2. **QA CSV列判定の簡素化**（1-2） — 低リスク・高価値。サイレントなデータ破損（質問と回答の入れ替わり）を防げる。
3. **Notion API連携の追加**（2-1） — 中規模の新規実装だが、これによりPython版がGAS/Cloudflareと機能的に並ぶ。1-3（種別タグ付け）も同時に解消。
4. **検索テストエンドポイントの追加**（2-3） — 低コスト（既存の`_handle_search`を呼ぶだけ）で、登録直後の動作確認体験が大きく改善する。
5. **（任意・要判断）QA CSVプレビュー等の管理画面UX改善**（2-4〜2-6） — Python版のフロントエンド構成次第。
6. **（任意・大規模）`ThreadingHTTPServer`への切り替え**（3-1） — 影響範囲が大きいため、他の対応が落ち着いてから改めて設計検討。
7. **（任意・要設計判断）ステージング方式への移行**（3-2） — 単純な移植ではなく設計変更。埋め込み処理の重さが実際に問題になっているか次第。

---

## 付録：ファイル対応表

| 内容 | AxChatD側 | 本プロジェクト側(Python) |
|---|---|---|
| KnowledgeManager本体 | `RAGEnvironment/server/app/knowledge/knowledge_manager.py` | `scripts/knowledge_manager.py` |
| URL/Notion変換ロジック | `RAGEnvironment/server/app/knowledge/knowledge_converter.py` | `_convert_url`(`scripts/knowledge_manager.py`内) |
| Notion APIクライアント(新規) | `RAGEnvironment/server/app/converters/notion.py` | 無し(要新規実装、`cloudflare-rag-poc/src/notion.ts`参照) |
| 音声/動画文字起こし | `RAGEnvironment/server/app/converters/media_transcribe.py` | `scripts/youtube_transcribe.py`(bridge未接続) |
| HTTPルーティング | `RAGEnvironment/server/app/routers/writer.py` | `scripts/rag_local_bridge.py` |
| 管理画面UI | `RAGEnvironment/web/src/pages/AdminPage.tsx` | (要確認、無い場合は新規検討) |
