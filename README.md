# ゲーム開発 RAG 環境

**更新日:** 2026-10-31（README を入口に絞り、資料を目的別のフォルダに整理）

ゲーム開発チーム向けの **RAG 環境**。自分たちのドキュメントを検索して、出典つきで AI に答えさせる仕組みを、**クラウド（Cloudflare）とローカル**の 2 層で作り、**Houdini・Unity** のパネルから使えるようにしました。

> **RAG（Retrieval-Augmented Generation）** … AI に質問するとき、先にドキュメントを検索して関連情報を見つけ、それを添えて答えさせる仕組み。「AI が自分のチームの資料を見ながら答える」と考えれば OK。

---

## 資料の探し方

| こうしたい | ここから |
|---|---|
| **資料を探す**（全部の一覧） | **[docs/README.md（索引）](docs/README.md)** |
| 全体を知りたい | [プロジェクト概要](docs/design/project-overview.md)・[システムガイド](docs/system-guide.html) |
| 使い方を知りたい | [ツール取扱説明書](docs/guides/user-manual.md)・[Houdini チュートリアル生成](docs/guides/manual-houdini-tutorial.md) |
| 実証実験を運営する | [運営者向け手順書](docs/pilot/operator-runbook.md) |
| 動かし続ける・障害対応 | [運用手順書](docs/operations/cloudflare-rag-operations-manual.md)・[保守の手順](docs/learning/06-maintenance-runbook.md) |
| **仕組みを理解して、直す・足す人になる** | **[講義シリーズ（全16回）](docs/learning/lectures/README.md)**（基礎 → 運用 → アルゴリズム・スクリプト） |
| 言葉が分からない | [用語集](docs/reference/glossary.md) |

---

## 何ができるか

| 機能 | 概要 |
|---|---|
| **クラウド RAG** | Cloudflare Workers + D1 + Vectorize。出典つきの回答、権限・予算・回数の制御、管理画面（旧 GAS 版は 2026-10-22 に廃止） |
| **ローカル RAG** | 個人メモ・チャット履歴など、外に出せない情報を手元で管理（ChromaDB + HTTP ブリッジ） |
| **Houdini 連携** | パネルに、チャット・グラフ・チュートリアル生成・動画・実証実験の「課題」タブ |
| **Unity 連携** | エディタ内のチャット UI・グラフビュー |
| **チュートリアル自動生成** | 自然言語の依頼から、Houdini のノードグラフを実際に組み、cook エラーなしのチュートリアルと解説動画を作る |
| **説明レベルと習熟度** | 質問で使った専門用語から習熟度を推定し、説明の深さを自動で選ぶ |
| **実証実験の仕組み** | 3 回 ×（固定課題＋自由課題）の計測、やり直し、中断からの再開、氏名なしの集計 |
| **外部サービス連携（MCP）** | Notion・GitHub・Slack・Google などへ、確認つきで接続 |
| **安全の仕組み** | 監査ログ、権限（最小権限）、トークン予算、回数制限 |

> 機能の全部の一覧と、それぞれの狙い → **[プロジェクト概要](docs/design/project-overview.md#機能一覧)**

---

## システム全体の構成

[![システム全体の構成](docs/images/01-system-overview.svg)](docs/images/01-system-overview.svg)

*図: 手元の Houdini とパネル、Cloudflare の Worker、外部の AI・サービスの関係。*

### 図で見る（番号の順に読む）

| 知りたいこと | 図 |
|---|---|
| 質問が届いて、答えが返るまで | [11 リクエストの一生](docs/images/11-request-life.svg) |
| データはどこに、どう置かれているか | [14 データの置き場](docs/images/14-data-model.svg) |
| Houdini パネルは、どう分かれているか | [15 パネルの内部構成](docs/images/15-houdini-panel.svg) |
| 実証実験は、どう進むか | [12 実証実験の流れ](docs/images/12-pilot-flow.svg) |
| 課題 1 回は、どう状態が変わるか | [13 課題の状態](docs/images/13-task-states.svg) |
| 変更してから本番に出すまで | [16 変更から本番まで](docs/images/16-change-flow.svg) |

---

## クイックスタート

詳しい手順は、各リンク先と [プロジェクト概要（クイックスタート詳細）](docs/design/project-overview.md#クイックスタート詳細) に。

### クラウド RAG

1. Cloudflare Worker（[cloudflare-rag-poc/](cloudflare-rag-poc/README.md)）をデプロイする
2. 管理画面で API キーを発行する
3. Houdini / Unity の Settings タブで、Worker の URL と API キーを設定する

→ [docs/design/cloud-rag.md](docs/design/cloud-rag.md)

### ローカル RAG

```powershell
uv sync                                              # 依存パッケージ
uv run python scripts\rag_cli.py index               # ドキュメントをインデックス化
$env:ANTHROPIC_API_KEY = "sk-ant-..."
uv run python scripts\rag_local_bridge.py            # ローカル HTTP ブリッジ（localhost:8766）
```

→ [docs/design/local-rag.md](docs/design/local-rag.md)

### Houdini

```powershell
# パネルを Houdini の設定フォルダへ配置（上書き前に自動で退避。--check で差分だけ見る）
uv run python houdini\deploy_panels.py 22.0 --pypanel
```

配置後に Houdini を**再起動**し、Python Panel から RAGChatBot を追加します。**Settings タブで、Worker の URL と API キーを設定**します（チュートリアル生成の Claude 呼び出しは、常に Cloudflare 経由。手元に `ANTHROPIC_API_KEY` は要りません）。**Tutorial** タブでトピックを入力するか、Chat タブで `/tutorial <トピック>` と入力します。

→ [取扱説明書（Houdini）](docs/guides/manual-houdini-tutorial.md)・[設計](docs/design/content-generation.md)

### Unity

`Assets/Editor/RAGChatbot/` をプロジェクトにコピーし、メニュー **RAG → RAG Chatbot** を開いて、Settings タブで接続先（Cloud / Local）を設定します。

---

## ディレクトリ構成

```
DevelopmentRAGEnvironment/
├── README.md
├── docs/              ドキュメント（入口: docs/README.md）
│   ├── guides/        使い方          ├── pilot/       実証実験
│   ├── operations/    運用・安全・規約  ├── design/      設計・仕様（project-overview.md ほか）
│   ├── reports/       調査・検証・報告  ├── reference/   用語
│   ├── learning/      学習資料（講義シリーズ全16回・座学資料）
│   └── images/        図（SVG）
├── cloudflare-rag-poc/  クラウド RAG の実装（Worker・D1 マイグレーション・テスト）
├── houdini/           Houdini パネル（python_panels/）・配置スクリプト・テスト
├── Assets/            Unity のエディタ拡張
├── scripts/           ローカル RAG・図/資料の生成・点検・バックアップのスクリプト
├── lecture/           講義資料（HTML）
└── localRAG/          Obsidian vault（インデックス対象のドキュメント置き場）
```

> 各フォルダの中身の詳細 → [プロジェクト概要（ディレクトリ構成の詳細）](docs/design/project-overview.md#ディレクトリ構成詳細)

---

## 開発

```bash
cd cloudflare-rag-poc && npm run typecheck && npm test      # Worker: 型検査とテスト
uv run python -m unittest discover -s houdini/tests          # Houdini 側の単体テスト
uv run python scripts/build_diagrams.py                      # 図を作り直す
uv run --with markdown python scripts/build_docs_html.py     # 資料の HTML を作り直す
```

CI（`ruff`・`mypy`・namespace 検査）と、設計判断 → [プロジェクト概要（開発）](docs/design/project-overview.md#開発ci-と静的解析)。変更から本番に出すまでの標準の流れ → [図16](docs/images/16-change-flow.svg)・[講義 第9回](docs/learning/lectures/09-test-deploy-operate.md)。

> **本番を変える操作**（D1 のマイグレーション・Worker のデプロイ・シークレット）は、**人が操作の名前を挙げて許可してから**行います。

---

## 参考リンク

| リソース | URL |
|---|---|
| karaage0703/mcp-rag-server（検索エンジンのベンダリング元、MIT） | https://github.com/karaage0703/mcp-rag-server |
| Notion API リファレンス | https://developers.notion.com/ |
| Google AI Studio（Gemini API キー発行） | https://aistudio.google.com/ |
| uv — Python パッケージマネージャー | https://docs.astral.sh/uv/ |
