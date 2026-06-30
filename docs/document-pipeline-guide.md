# ドキュメント化・インデックス化ガイド（Claude 不要版）

> Claude API を使わずに、任意のファイルを RAG 検索可能な状態にする手順書。  
> 更新日: 2026-06-25

---

## 全体フロー

```
【入力】
  PDF / Word / PowerPoint / Markdown / テキスト
        ↓
【変換】markitdown（ローカル実行・外部API不要）
        ↓
【チャンキング】見出しベース（文字数ベースより高精度）
        ↓
【出力】localRAG/namespace/xxx.md
        ↓
【自動インデックス化】auto_index.py が検知 → ChromaDB + multilingual-e5-large
        ↓
【検索可能】Unity / Houdini / ブラウザから RAG クエリ
```

**外部 API を一切使わない。インターネット不要で完結する。**

---

## 1. 使い方

### 1-1. ファイルを追加

```bash
# PDF を tool_docs namespace に追加
python scripts/document_pipeline.py add path/to/design.pdf --namespace tool_docs

# Word ファイルを research namespace に追加
python scripts/document_pipeline.py add path/to/report.docx --namespace research

# ディレクトリごと追加
python scripts/document_pipeline.py add path/to/docs_folder/ --namespace team_notes

# 追加と同時にインデックス化
python scripts/document_pipeline.py add path/to/file.pdf --namespace tool_docs --index

# 書き込まずに確認だけ（dry-run）
python scripts/document_pipeline.py add path/to/file.pdf --dry-run
```

### 1-2. インデックス化だけ実行

```bash
python scripts/document_pipeline.py index
```

### 1-3. テンプレートを生成

```bash
# ミーティングメモのテンプレートを生成
python scripts/document_pipeline.py template meeting --output localRAG/team_notes/

# 種類: meeting / research / tool / knowledge
```

---

## 2. Namespace の選び方

| Namespace | 用途 | 例 |
|-----------|------|-----|
| `tool_docs` | ツール・ライブラリのドキュメント | Unity マニュアル、API リファレンス |
| `game_info` | ゲーム・プロジェクト情報 | 仕様書、デザインドキュメント |
| `research` | 調査・研究メモ | 論文要約、技術調査 |
| `team_notes` | チームの議事録・共有メモ | ミーティングメモ、決定事項 |
| `personal_notes` | 個人メモ | 学習メモ、アイデア |

---

## 3. 手書きで Document 化する（テンプレート活用）

Claude が使えない状況でも、**テンプレートに沿って書くだけで高品質なドキュメント**になる。

### テンプレートの場所
```
localRAG/_templates/
  meeting.md      ← ミーティングメモ
  research.md     ← 調査メモ
  tool_doc.md     ← ツールドキュメント
  knowledge.md    ← 知識メモ
```

### 書き方のコツ（Claude なしでも検索精度が上がる）

1. **見出しを必ず使う**（`#`, `##`, `###`）  
   見出しベースで分割されるため、見出しがあると検索精度が大幅に向上する

2. **1 ファイル = 1 トピック**にする  
   「Unity の物理演算」「Houdini のプロシージャル」など、話題を混ぜない

3. **frontmatter を書く**  
   `namespace`, `tags`, `status` を正確に記入すると管理が楽になる

4. **具体的なキーワードを本文に含める**  
   「〇〇とは」ではなく、実際に検索しそうな言葉で書く

---

## 4. 対応ファイル形式

| 形式 | 変換方法 | 備考 |
|------|---------|------|
| `.md` / `.txt` | そのまま読み込み | 最も高品質 |
| `.pdf` | markitdown で Markdown 変換 | テキストベース PDF は良好、スキャン PDF は注意 |
| `.pptx` / `.ppt` | markitdown でスライドテキスト抽出 | 図・画像の内容は取れない |
| `.docx` / `.doc` | markitdown で Markdown 変換 | 表・箇条書きも対応 |
| `.xlsx` / `.xls` | markitdown でテーブル変換 | データ量が多いと分割数が増える |
| `.html` | markitdown で本文抽出 | ナビ・広告は除去される |

---

## 5. チャンキング戦略

### heading ベース（デフォルト・推奨）

```
# 見出し1
  → チャンク 1: "見出し1 > ..." という heading path 付きで保存

## 見出し2
  → チャンク 2: "見出し1 > 見出し2" という heading path 付きで保存
```

メリット:
- 意味的にまとまったチャンクになる
- 検索時に「どのセクションの話か」が分かる
- 長すぎるセクションは自動的に段落で再分割

### チャンクサイズの調整

```bash
# チャンクを小さくする（より細かく検索したい場合）
python scripts/document_pipeline.py add file.pdf --max-chunk 400 --overlap 60

# チャンクを大きくする（文脈を広く持たせたい場合）
python scripts/document_pipeline.py add file.pdf --max-chunk 1200 --overlap 100
```

**推奨値:**
- 技術ドキュメント: `--max-chunk 600`
- ミーティングメモ: `--max-chunk 400`
- 長文レポート: `--max-chunk 1000`

---

## 6. 自動化（watchdog）

`auto_index.py` が起動していれば、`localRAG/` にファイルを置くだけで自動インデックス化される。

```bash
# 監視開始（バックグラウンドで動かしておく）
cd C:\Users\matuu\Desktop\GameDevelopment\DevelopmentRAGEnvironment
python scripts/auto_index.py

# または PowerShell でバックグラウンド実行
Start-Process python -ArgumentList "scripts/auto_index.py" -WindowStyle Hidden
```

監視が動いていれば、`document_pipeline.py add` した後に自動でインデックス化される。

---

## 7. Claude を使う場面・使わない場面

| 作業 | Claude 使う | Claude なし |
|------|------------|------------|
| ファイル変換（PDF→MD等） | 不要 | markitdown で自動 |
| チャンキング | 不要 | heading ベース自動分割 |
| 埋め込み生成 | 不要 | multilingual-e5-large（ローカル） |
| ChromaDB への保存 | 不要 | 直接保存 |
| **ドキュメントの整理・要約** | あると便利 | テンプレートで代替 |
| **非構造データの構造化** | あると便利 | 手動でテンプレートに沿って書く |
| 検索結果の回答生成 | 使用（rag_local_bridge）| ローカルLLM(Ollama)で代替可 |

---

## 8. ローカル LLM による完全オフライン化（オプション）

Claude API なしで回答生成もしたい場合は Ollama を使う。

```bash
# Ollama インストール（Windows）
winget install Ollama.Ollama

# 日本語対応モデルをダウンロード
ollama pull llama3.2
ollama pull phi4  # 軽量・高速

# rag_local_bridge.py の CLAUDE_MODEL を変更する代わりに
# Ollama の OpenAI 互換 API を使う（port 11434）
```

Ollama の API は OpenAI 互換のため、`rag_local_bridge.py` の `_call_claude()` を  
`http://localhost:11434/v1/chat/completions` に向ければ完全オフライン化できる。

---

## 9. トラブルシューティング

**markitdown のインポートエラー**
```bash
# このリポジトリの依存（pyproject.toml に markitdown[all] を含む）が
# uv sync されているか確認する
cd C:\Users\matuu\Desktop\GameDevelopment\DevelopmentRAGEnvironment
uv sync
uv run python scripts\document_pipeline.py add ...
```

**チャンクが多すぎる（PDF が長い）**
```bash
# チャンクサイズを大きくする
python scripts/document_pipeline.py add file.pdf --max-chunk 1200
```

**日本語のチャンクが途中で切れる**  
heading ベース分割なので、ファイル内に `##` などの見出しを追加すると改善する。
