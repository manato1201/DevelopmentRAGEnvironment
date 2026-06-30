# ライセンス・利用規約 コンプライアンスガイド

> 対象: DevelopmentRAGEnvironment / 商用導入時の確認資料  
> 更新日: 2026-06-25  
> ※ 本資料は参考情報です。最終的な法的判断は弁護士にご確認ください。

---

## 判定サマリー

| ツール | ライセンス種別 | 商用利用 | 改造 | ソース開示 | ユーザー上限 | リスク |
|--------|--------------|---------|------|-----------|------------|--------|
| ベンダー統合コード（旧 mcp-rag-server 由来） | MIT | ○ | ○ | なし | なし | **低** |
| MCP SDK (Anthropic) | MIT | ○ | ○ | なし | なし | **低** |
| ChromaDB | Apache 2.0 | ○ | ○ | なし | なし | **低** |
| multilingual-e5-large | MIT | ○ | ○ | なし | なし | **低** |
| sentence-transformers | Apache 2.0 | ○ | ○ | なし | なし | **低** |
| sudachipy / sudachidict | Apache 2.0 | ○ | ○ | なし | なし | **低** |
| markitdown (Microsoft) | MIT | ○ | ○ | なし | なし | **低** |
| D3.js | ISC | ○ | ○ | なし | なし | **低** |
| uv | MIT / Apache 2.0 | ○ | ○ | なし | なし | **低** |
| numpy | BSD 3-Clause | ○ | ○ | なし | なし | **低** |
| PySide6 | LGPL v3 | ○ | △ | 改変部のみ | なし | **中** |
| Houdini (SideFX) | 独自（有償） | 要確認 | ✗ | — | — | **高** |
| Unity | 独自（有償） | 要確認 | ✗ | — | — | **中** |
| Claude API (Anthropic) | 利用規約 | ○ | — | — | なし | **低** |
| Gemini API (Google) | 利用規約 | ○ | — | — | なし | **中** |
| Notion API | 利用規約 | ○ | — | — | レート制限あり | **低** |

---

## 1. ベンダー統合コード（旧 mcp-rag-server 由来）

**ライセンス: MIT（原作者: karaage, 2025）**

```
MIT License
Copyright (c) 2025 karaage
```

[karaage0703/mcp-rag-server](https://github.com/karaage0703/mcp-rag-server) の検索エンジンコードをこのリポジトリに直接取り込み（ベンダー統合）、`scripts/document_processor.py` / `scripts/embedding_generator.py` / `scripts/rag_service.py` / `scripts/mcp_server.py` などとして同梱しています（2026-06-30、外部リポジトリへの依存を解消）。MIT ライセンスは改造・再配布・組み込みを許可しているため、ソースコードを直接コピーして本リポジトリの一部にすることに問題はありません。**「外部ツールへの依存」ではなく「自社コードに組み込んだサードパーティ由来のコード」という扱いになります。**

### 許可されること
- 商用製品への組み込み・販売
- ソースコードの改造・カスタマイズ
- 再配布・サブライセンス

### 義務
- **配布時にのみ**: 取り込んだコードの著作権表示（上記 MIT License テキスト）を `LICENSE` または `NOTICE` ファイル等に同梱すること
- 内部ツールとして使うだけなら配布不要 → 義務なし
- ベンダー統合（コードをコピーして改変）しても、MIT ライセンスである限りソース開示義務は発生しない

### 依存パッケージのライセンス

ベンダー統合コードが利用するパッケージ（`pyproject.toml` で直接宣言）はすべて許容的ライセンス:

| パッケージ | ライセンス |
|-----------|-----------|
| sentence-transformers | Apache 2.0 |
| chromadb | Apache 2.0 |
| markitdown (Microsoft) | MIT |
| sudachipy / sudachidict-core | Apache 2.0 |
| rank-bm25 | Apache 2.0 |
| numpy | BSD 3-Clause |
| mcp (Anthropic MCP SDK) | MIT |
| pydantic | MIT |
| watchdog | Apache 2.0 |

コピーレフト（GPL/AGPL）を含むパッケージは**ゼロ**。ソース開示義務は発生しない。

> 注: 本プロジェクトは `.env` / `load_dotenv()` を使用しない方針のため、`python-dotenv` は依存に含まれません。

---

## 2. MCP SDK（Anthropic）

**ライセンス: MIT（Copyright (c) 2024 Anthropic, PBC）**

`scripts/mcp_server.py` / `scripts/rag_mcp_server.py` が内部で使う `mcp[cli]` ライブラリ。MIT なので商用利用・改造ともに問題なし。配布時は著作権表示を維持するだけでよい。

---

## 3. PySide6（Houdini パネルで使用）

**ライセンス: LGPL v3（または商用ライセンス）**

### 条件
- **動的リンク（通常の import）**: 自社コードのソース開示不要。Houdini の Python パネルは import 形式なので**これに該当**
- **PySide6 本体を改変した場合**: その差分のみ LGPL 準拠で公開が必要
- **外部配布しない社内ツール**: 開示義務なし

### ライセンス表示義務
外部にソフトウェアを配布する場合は、製品のドキュメントやライセンス画面に以下を記載:
```
This software uses PySide6, licensed under LGPL v3.
https://www.qt.io/licensing/
```

### 商用ライセンスへの切り替え
Qt 商用ライセンス（有料）に切り替えると LGPL 義務から完全に解放される。大規模商用製品で義務回避を重視する場合は検討。

---

## 4. Houdini（SideFX）

**ライセンス: 独自商用ライセンス（要別途契約）**

### ライセンス種別と商用可否

| ライセンス | 月額/年額 | 商用利用 | 売上上限 |
|-----------|---------|---------|---------|
| Apprentice | 無料 | **不可** | — |
| Indie | 約 $269/年 | 可 | **$100,000 USD/年未満** |
| Core | 約 $1,995/年 | 可 | 制限なし |
| FX | 約 $4,495/年 | 可 | 制限なし |

### 対処方針
- 現在 Apprentice を使用している場合 → **商用化前に必ず有償ライセンスへ移行**
- プロジェクト年間売上が $10万 USD を超える見込みなら Core 以上を選択
- SideFX の営業担当に直接相談するとスタジオ向け割引が得られる場合あり

---

## 5. Unity

**ライセンス: 独自商用ライセンス（売上規模依存）**

### ライセンス種別

| ライセンス | 料金 | 対象条件 |
|-----------|------|---------|
| Personal | 無料 | 年収・調達額 $10万 USD 未満 |
| Pro | 約 $2,040/年/席 | 上記以外の法人 |

### 今回の用途について
今回実装した RAG Chatbot（`RAGChatbotWindow.cs`）は Unity **Editor** 上で動く開発ツール。  
エンドユーザーに配布するランタイムではないため、**Unity Runtime Fee（2023年問題）の対象外**。  
ただし組織の収益規模によって Pro ライセンスが必要になる点は変わらない。

---

## 6. Claude API（Anthropic）

**利用規約ベース。従量課金。**

### 商用利用
- API 経由での商用利用は許可されている
- 利用規約の禁止事項（有害コンテンツ生成等）を遵守する必要あり

### データ取り扱い（重要）
- **API 経由のデータはモデル学習に使用されない**（claude.ai Consumer 製品とは異なる）
- エンタープライズ向けに DPA（データ処理契約）の締結が可能
- 機密情報・個人情報を扱う場合は DPA 締結を推奨

### 料金・上限
- トークン従量課金（ユーザー数上限なし）
- レート制限あり（Tier に応じて上限が変化）
- 大量利用の場合は Enterprise プランで専用レート制限を設定可能

---

## 7. Gemini API（Google）

**利用規約ベース。商用利用可だが環境選択が重要。**

### 利用環境の違い

| 環境 | 料金 | データ学習 | SLA | 推奨 |
|------|------|-----------|-----|------|
| Google AI Studio（無料枠） | 無料 | **使われる可能性あり** | なし | 開発・検証のみ |
| Vertex AI（有料） | 従量課金 | **使われない** | あり | **商用推奨** |

### 商用化時の対処
現在 GAS 側で使用している Gemini は Google AI Studio 系の API。  
本格商用化では **Vertex AI 経由の Gemini に切り替え**、Google Cloud DPA を締結することを強く推奨。

---

## 8. Notion API

**利用規約ベース。商用利用可。**

### プラン別の制限

| プラン | API レート制限 | DPA | SSO |
|--------|--------------|-----|-----|
| Free | 1,000 req/min | なし | なし |
| Plus | 1,000 req/min | なし | なし |
| Business | 1,000 req/min | 可 | 可 |
| Enterprise | カスタム | 可 | 可 |

### 商用化時の対処
- 機密情報を扱う場合は **Business 以上**で DPA 締結
- API を高頻度で使う場合はレート制限に注意（現行同期処理で問題が出た場合は Enterprise を検討）

---

## 9. 商用化チェックリスト（優先度順）

### 必須対応（リリース前に完了）

- [ ] **Houdini ライセンス確認**: Apprentice → Indie/Core へ移行
- [ ] **Gemini を Vertex AI 経由に移行**: データ保護のため
- [ ] **Unity ライセンス確認**: 組織収益が $10万超なら Pro へ

### 推奨対応（規模拡大時）

- [ ] **Anthropic と DPA 締結**: 個人情報・機密情報を扱う場合
- [ ] **Google Cloud DPA 締結**: Vertex AI 利用時
- [ ] **Notion Business/Enterprise 移行**: 機密データを Notion に置く場合
- [ ] **Qt 商用ライセンス検討**: 外部配布製品で PySide6 義務を回避したい場合

### 配布時に必要な著作権表示（ベンダー統合コードを含めて配布する場合）

ソフトウェアを外部に配布・販売する際は以下の著作権表示を同梱:

```
ベンダー統合コード（旧 mcp-rag-server 由来、scripts/document_processor.py 等）
MIT License - Copyright (c) 2025 karaage

MCP SDK
MIT License - Copyright (c) 2024 Anthropic, PBC

ChromaDB
Apache License 2.0 - Copyright (c) 2022 Chroma

PySide6
LGPL v3 - The Qt Company
```

---

## 10. 「ソース開示が必要になる」ケースの整理

商用化で最も怖い「コードを開示しなければならない」状況が発生する条件:

| 条件 | 発生するか |
|------|-----------|
| GPL ライセンスのパッケージを使う | **発生しない**（本システムに GPL なし）|
| AGPL ライセンスのパッケージを使う | **発生しない**（AGPL なし）|
| PySide6 を改変して配布する | **改変部のみ**開示が必要 |
| PySide6 を改変せず使う | 開示不要 |
| MIT/Apache 2.0 のコードを改変する | 開示不要 |

**結論: 現在の構成でソースコードの全面開示が義務になるケースはない。**  
PySide6 を改造しない限り、自社コードは完全にクローズドにできる。
