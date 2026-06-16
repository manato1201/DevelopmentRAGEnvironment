# RAG環境設計ドキュメント

**作成者:** 松浦真聖  
**作成日:** 2026-06-10  
**バージョン:** 1.0

---

## 目次

1. [システム概要](#1-システム概要)
2. [設計思想・分割方針](#2-設計思想・分割方針)
3. [クラウドRAG構成](#3-クラウドrag構成)
4. [ローカルRAG構成](#4-ローカルrag構成)
5. [クラウド↔ローカル連携](#5-クラウドローカル連携)
6. [実装ロードマップ](#6-実装ロードマップ)
7. [参考リンク](#7-参考リンク)

---

## 1. システム概要

本ドキュメントは、個人の技術情報管理・AI活用を目的としたRAG（Retrieval-Augmented Generation）環境の設計をまとめたものです。

### 全体方針

| 種別 | 管理場所 | 理由 |
|------|----------|------|
| ツール仕様・ゲーム情報・共有すべき技術情報 | **クラウド（Notion）** | チームで共有・参照できる必要がある |
| チャット履歴・チュートリアル生成結果・個人メモ・共有NG情報 | **ローカル（pgvector）** | プライバシー保護・外部流出リスクの排除 |

### 参考プロジェクト

- **ローカルRAG参考:** [mcp-rag-server（karaage0703）](https://github.com/karaage0703/mcp-rag-server) / [解説記事](https://zenn.dev/mkj/articles/30eeb69bf84b3f)
- **クラウドRAG参考:** [Research Collector](https://manato1201.github.io/Research-Collector/) / [GitHub](https://github.com/manato1201/Research-Collector)

---

## 2. 設計思想・分割方針

### なぜ分けるのか

単一のRAG環境にすべての情報を入れると以下の問題が生じる：

- 個人情報がクラウドに漏洩するリスク
- 共有資料と個人メモが混在し検索精度が低下する
- チームメンバーへの展開時にプライベート情報が混入する

### 分割基準

```
クラウドに入れるもの（共有すべき情報）
├── Unity / Houdini / DirectX12 などツール仕様
├── ゲーム情報・共有設計書
├── 技術記事（手動で精査したもの）
└── 研究論文・ゼミ資料

ローカルに入れるもの（個人情報）
├── Claude / LLMとのチャット履歴
├── Houdiniチュートリアル生成結果
├── Obsidianノート・個人進捗メモ
└── 共有NG文書・草稿
```

---

## 3. クラウドRAG構成

### 3.1 アーキテクチャ

```
[追加ソース]              [知識ベース]           [チャット層]
手動（Notion UI）    →                       →
Web Clipper         →   Notion Workspace    →   GAS WebApp
ローカルスクリプト   →   （DB分離）          →   + Gemini API
GASフォーム（補助）  →                       →
```

### 3.2 Notion DB設計

Notionのworkspace内でDBを用途別に**完全分離**する。

| DB名 | 内容 | 追加方法 |
|------|------|----------|
| `Tool Docs DB` | Unity・Houdini・DX12・環境設定 | 手動 / スクリプト |
| `Game Info DB` | ゲーム仕様・共有ゲーム情報 | 手動 |
| `Research DB` | 論文・技術記事（手動精査済み） | 手動 / スクリプト |
| `Team Notes DB` | ゼミ資料・議事録・方針 | 手動 |

#### 共通メタデータスキーマ

各DBページに以下のプロパティを統一する：

```
title        : ページタイトル（テキスト）
source_url   : 元URL（URL型）
tags         : タグ（マルチセレクト）例: Unity, Houdini, RAG
summary      : AI生成の100字要約（テキスト）
collected_at : 追加日（日付）
category     : DBカテゴリ（セレクト）
```

`summary` は追加時点でGemini APIに生成させておくことで、チャット時のcontext量を削減しAPIコストを抑える。

### 3.3 混合防止の仕組み

Notion APIは `database_id` を指定して検索できるため、DB単位で物理的に分離される。

```javascript
// GAS内の定数定義例
const NOTION_DBS = {
  tool_docs:  "xxxx-aaaa-...",
  game_info:  "xxxx-bbbb-...",
  research:   "xxxx-cccc-...",
  team_notes: "xxxx-dddd-..."
};

// チャット時は対象DBを明示指定
function searchNotion(query, dbKey) {
  const dbId = NOTION_DBS[dbKey];
  // Notion Search API に database_id + query を渡す
}
```

### 3.4 GAS WebApp（チャットボット）

#### RAGの流れ

```
① ユーザーが質問 + 対象DBを選択
       ↓
② GAS: Notion API で指定DB内をキーワード検索
       ↓
③ 上位N件のページ本文を取得してcontextを構築
       ↓
④ "以下のドキュメントを参考に答えよ\n{context}\n\n質問:{query}"
   → Gemini API (gemini-2.0-flash) に送信
       ↓
⑤ 回答をWebAppのチャットUIに返す
```

#### なぜGemini UIから直接呼べないのか

`gemini.google.com` はGASエンドポイントをツールとして登録する機能を持たないため、Gemini UIから直接GASを呼び出すことはできない。GAS上でWebAppを立て、そこでGemini APIを呼ぶ構成（**A方式**）が実装量最小かつ保守性が高い。

#### GAS実装の骨格

```javascript
// GAS: doPost エントリポイント
function doPost(e) {
  const { query, dbKey } = JSON.parse(e.postData.contents);
  
  // 1. Notion検索
  const context = searchNotion(query, dbKey);
  
  // 2. Gemini API呼び出し
  const prompt = buildPrompt(query, context);
  const answer = callGemini(prompt);
  
  return ContentService
    .createTextOutput(JSON.stringify({ answer }))
    .setMimeType(ContentService.MimeType.JSON);
}

function callGemini(prompt) {
  const url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent";
  const payload = {
    contents: [{ parts: [{ text: prompt }] }]
  };
  const res = UrlFetchApp.fetch(`${url}?key=${GEMINI_API_KEY}`, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload)
  });
  return JSON.parse(res.getContentText())
    .candidates[0].content.parts[0].text;
}
```

### 3.5 ドキュメント追加の3パターン

| 方法 | 用途 | 工数 |
|------|------|------|
| Notion UI / Web Clipper | 日常的な1件追加 | ★☆☆ 最小 |
| Pythonスクリプト → Notion API | まとめて追加・既存データ移行 | ★★☆ 中程度 |
| GASフォーム（URL貼り付け） | URLから自動整形して追加 | ★★☆ 中程度（初期実装が必要） |

Research Collectorのコレクター部分（RSS収集・重複除去）はそのまま流用可能。NotebookLM連携部分をNotion API書き込みに差し替えるだけで動作する。

---

## 4. ローカルRAG構成

### 4.1 ベース構成

[mcp-rag-server](https://github.com/karaage0703/mcp-rag-server) を基盤として使用する。

**主な特徴（原構成）:**
- PostgreSQL + pgvector によるベクトル検索
- `intfloat/multilingual-e5-large` で日本語対応
- LangChain等の外部依存なし（バージョン安定性が高い）
- CLI（インデックス化）とMCP（検索）の役割分担
- 差分インデックス機能（新規・変更ファイルのみ処理）

### 4.2 namespace設計

pgvectorのテーブルに `namespace` カラムを持たせて用途別に分離する。

| namespace | 内容 | ソース |
|-----------|------|--------|
| `chat_logs` | Claude等との会話ログ | 自動エクスポート |
| `tutorials` | Houdiniチュートリアル生成結果 | 生成時に自動保存 |
| `personal_notes` | Obsidianノート・個人進捗 | Obsidian vault |
| `private_docs` | 共有NG文書・草稿 | 手動追加 |

```sql
-- namespace付きの検索例
SELECT content, metadata
FROM documents
WHERE namespace = 'personal_notes'
ORDER BY embedding <-> query_embedding
LIMIT 5;
```

### 4.3 自動インデックス化（watchdog）

現状のCLI手動実行を、`watchdog` ライブラリによるディレクトリ監視で自動化する。

```python
# auto_index.py（常駐プロセス）
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import subprocess, time

class IndexHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(('.md', '.txt', '.pdf')):
            print(f"変更検知: {event.src_path}")
            subprocess.run(["uv", "run", "python", "-m", "src.main", "index"])

if __name__ == "__main__":
    observer = Observer()
    observer.schedule(IndexHandler(), path="./data/source", recursive=True)
    observer.start()
    print("監視開始...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
```

**Obsidianとの連携:** `SOURCE_DIR` をObsidianのvaultパスに向けるだけで、ノートの保存と同時にインデックスが更新される。

### 4.4 他MCPホストへの接続設定

mcp-rag-serverは特定のLLMに依存しないため、設定ファイルにエントリを追加するだけで複数のホストから利用できる。

#### Claude Code（既存）

```bash
claude mcp add mcp-rag-server \
  -- uv run --directory /path/to/mcp-rag-server python -m src.main
```

#### Cursor

`~/.cursor/mcp.json` に追記：

```json
{
  "mcpServers": {
    "mcp-rag-server": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-rag-server", "python", "-m", "src.main"]
    }
  }
}
```

#### Cline（VS Code）

`cline_mcp_settings.json` に同様のエントリを追加する。

#### 将来（claude.ai Remote MCP対応後）

Remote MCP対応後はclaude.aiのWeb UIからも同じサーバーに接続可能になる。

---

## 5. クラウド↔ローカル連携

### 5.1 参照方向

```
ローカル → クラウド（Notion）: 読み取り専用
クラウド → ローカル         : なし（意図的）
```

クラウドDBへの書き込みはローカルからは行わない。汚染リスクを排除するため。

### 5.2 Notion MCP による統合

Notion MCPはclaude.aiにすでに接続済みのため、Claude CodeからNotionのDBを追加実装なしで直接参照できる。

**Claude Codeでの利用例:**

```
「Houdini SOPのVEXについて調べて、過去のチュートリアル生成結果（ローカル）
と公式ドキュメント（Notion）を両方参照して回答して」
```

→ mcp-rag-server（`tutorials` namespace）とNotion MCPを組み合わせてコンテキストを構築する。

### 5.3 将来的な拡張（Supabase Vector）

チームへの展開が必要になった場合、ローカルのDocker pgvectorをSupabase Vectorに移行することで：

- ローカル・クラウドで同じVectorDBを参照できる
- namespaceによる分離は維持したまま共有可能
- MCPサーバーの設定変更のみで移行できる（コード変更不要）

---

## 6. 実装ロードマップ

### Phase 1: クラウドRAG（Notion + GAS）

- [ ] Notionワークスペース・DB4本の作成（スキーマ統一）
- [ ] GAS WebApp基本実装（Notion検索 + Gemini呼び出し）
- [ ] チャットUI実装（DBドロップダウン付き）
- [ ] ローカルスクリプト整備（まとめて追加用）

### Phase 2: ローカルRAG改良

- [ ] namespace設計をpgvectorに実装
- [ ] watchdog自動インデックス化スクリプト作成
- [ ] ObsidianをSOURCE_DIRに設定
- [ ] Cursor / Cline への接続設定追加

### Phase 3: 統合・拡張

- [ ] Claude CodeでNotion MCP + ローカルRAGの併用確認
- [ ] チャット履歴の自動取り込みパイプライン
- [ ] Supabase Vector移行検討（チーム展開時）

---

## 7. 参考リンク

| リソース | URL |
|----------|-----|
| mcp-rag-server（GitHub） | https://github.com/karaage0703/mcp-rag-server |
| mcp-rag-server（解説記事） | https://zenn.dev/mkj/articles/30eeb69bf84b3f |
| Research Collector（ポートフォリオ） | https://manato1201.github.io/Research-Collector/ |
| Research Collector（GitHub） | https://github.com/manato1201/Research-Collector |
| Notion API リファレンス | https://developers.notion.com/ |
| Gemini API ドキュメント | https://ai.google.dev/gemini-api/docs |
| pgvector | https://github.com/pgvector/pgvector |
| watchdog（Python） | https://github.com/gorakhargosh/watchdog |
