# RAG Environment

ローカル・クラウド両対応のRAG（Retrieval-Augmented Generation）環境のセットアップドキュメント集です。

## 概要

| 種別 | 構成 | 用途 |
|------|------|------|
| **ローカルRAG** | WSL2 + Docker + pgvector + mcp-rag-server | チャット履歴・個人メモ・チュートリアル生成結果など共有NGな情報 |
| **クラウドRAG** | Notion + GAS + Gemini API | ツール仕様・ゲーム情報・技術記事など共有すべき情報 |

2つはセットで使うことを前提に設計されており、Claude CodeからローカルとNotionの両方を同時に参照できます。

## ディレクトリ構成

```
rag-environment/
├── README.md
├── docs/
│   ├── local-rag-setup.md      # ローカルRAGセットアップ手順
│   ├── cloud-rag-setup.md      # クラウドRAGセットアップ手順
│   └── system-design.md        # システム設計ドキュメント（全体像）
├── lecture/
│   ├── local-rag-lecture.html  # ローカルRAG講義資料
│   └── cloud-rag-lecture.html  # クラウドRAG講義資料
└── scripts/
    ├── extract_zip.py          # Houdini help zip展開スクリプト
    └── delete_non_txt.py       # .txt以外削除スクリプト
```

## クイックスタート

### ローカルRAG（mcp-rag-server）

**→ [docs/local-rag-setup.md](docs/local-rag-setup.md)**

必要なもの: Windows 11 / Claude Desktop / Houdiniインストール済み  
所要時間: セットアップ約30分 + インデックス化4時間以上

```bash
# WSL2 Ubuntu で
git clone https://github.com/karaage0703/mcp-rag-server
cd mcp-rag-server && uv sync
# .env を設定してインデックス化 → Claude Desktop に MCP 登録
```

### クラウドRAG（Notion + GAS + Gemini）

**→ [docs/cloud-rag-setup.md](docs/cloud-rag-setup.md)**

必要なもの: Notionアカウント / Googleアカウント / Gemini APIキー  
所要時間: 約60〜90分

```
1. Notion に DB 4本を作成（Tool Docs / Game Info / Research / Team Notes）
2. GAS プロジェクトを作成してコードをデプロイ
3. WebApp URL でチャットUIにアクセス
```

## 設計思想

```
クラウドに入れるもの（共有すべき情報）
├── ツール仕様: Unity / Houdini / DirectX12 / 環境設定
├── ゲーム情報: 共有設計書・仕様
├── 技術記事:   手動で精査したもの
└── 研究資料:   ゼミ資料・議事録

ローカルに入れるもの（個人情報）
├── チャット履歴: Claude等との会話ログ
├── 生成結果:     Houdiniチュートリアル生成結果
├── 個人メモ:     Obsidianノート・進捗
└── 草稿・NG:     共有できない文書
```

クラウドへの書き込みはローカルからは行いません（読み取り専用）。

## スクリプトの使い方

`scripts/` 内のPythonスクリプトはmcp-rag-serverのディレクトリにコピーして使います：

```bash
cp scripts/extract_zip.py ~/mcp-rag-server/
cp scripts/delete_non_txt.py ~/mcp-rag-server/
cd ~/mcp-rag-server
python3 extract_zip.py
python3 delete_non_txt.py
```

## 参考

- [mcp-rag-server](https://github.com/karaage0703/mcp-rag-server) by karaage0703
- [mcp-rag-server 解説記事](https://zenn.dev/mkj/articles/30eeb69bf84b3f)
- [Notion API リファレンス](https://developers.notion.com/)
- [Gemini API ドキュメント](https://ai.google.dev/gemini-api/docs)
