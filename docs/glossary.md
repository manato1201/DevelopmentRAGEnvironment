# 用語集

**作成日:** 2026-08-22
**対象読者:** 実証実験参加者・勉強会/中間発表の聴講者（ITの専門知識が無い方も対象）
**方針:** 専門用語を専門用語で説明しない。日常的な言い換え・具体例を優先する。

---

## 目次

1. [AI・生成AIの基本用語](#1-ai生成aiの基本用語)
2. [RAG（検索拡張生成）の仕組み](#2-rag検索拡張生成の仕組み)
3. [このプロジェクト固有の用語](#3-このプロジェクト固有の用語)
4. [インフラ・技術基盤の用語](#4-インフラ技術基盤の用語)
5. [このプロジェクトのRAG分類](#5-このプロジェクトのrag分類)

---

## 1. AI・生成AIの基本用語

| 用語 | 説明 |
|---|---|
| **AI / 生成AI** | 質問文を入力すると、文章で回答を作ってくれる技術。ChatGPTやGeminiなどが代表例 |
| **LLM（大規模言語モデル）** | 生成AIの中身にあたる、文章を理解・生成する仕組みそのもの。Claude・Geminiなどは全てLLM |
| **Claude** | Anthropic社が開発するLLM。本プロジェクトではチュートリアル自動生成やチャット応答に使用 |
| **Gemini** | Google社が開発するLLM。本プロジェクトでは主に埋め込み生成・回答生成に使用 |
| **プロンプト** | AIに与える指示・質問文のこと |
| **トークン** | AIが文章を処理する際の最小単位（単語の一部程度の大きさ）。AIの利用料金は「何トークン使ったか」で決まることが多い |
| **API / APIキー** | APIはソフトウェア同士がやり取りするための「窓口」。APIキーはその窓口を使うための鍵（パスワードのようなもの） |
| **function calling（ツール呼び出し）** | AIが「この処理を実行してほしい」と要求を出し、こちら側のプログラムがそれを実行して結果を返す仕組み。AIが直接何かを操作するのではなく、あくまで「お願い」をするだけ |
| **tool call（ツールコール）** | function callingの中で、AIが実際に「この関数をこの引数で呼んで」と要求した1回分のやり取りのこと。function callingが仕組み全体の名前だとすれば、tool callはその仕組みが1回発火した単位 |
| **MCP（Model Context Protocol）** | function callingを異なるAIサービス・異なるツール間でも共通に使えるようにした、業界標準の通信規格。「AIツールの共通コンセント」のようなもの。MCP経由の呼び出しも、実体はtool callの1つ |

**3語の関係:**

<div style="--d-bg:#ffffff; --d-panel-2:#eef1f4; --d-border:#dfe3e8; --d-text:#14171c; --d-muted:#68707c; --d-c-chat:#e07b1f; --d-c-cloud:#0e8f8a; --d-c-local:#7350d6; --d-line:#aab1bb; background:var(--d-bg); border:1px solid var(--d-border); border-radius:12px; padding:1rem; overflow-x:auto;">
<svg viewBox="0 0 900 420" xmlns="http://www.w3.org/2000/svg" style="display:block;min-width:700px;">
  <defs><marker id="fc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--d-line)"/></marker></defs>
  <rect x="330" y="20" width="240" height="60" rx="12" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="450" y="55" font-size="14" font-weight="700" fill="var(--d-text)" text-anchor="middle">AIによる外部操作全般</text>
  <line x1="380" y1="80" x2="180" y2="140" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#fc-arrow)"/>
  <line x1="520" y1="80" x2="650" y2="140" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#fc-arrow)"/>
  <rect x="30" y="140" width="300" height="100" rx="12" fill="var(--d-panel-2)" stroke="var(--d-c-chat)" stroke-width="2"/>
  <circle cx="65" cy="172" r="16" fill="var(--d-c-chat)"/>
  <text x="65" y="177" font-size="13" fill="#fff" text-anchor="middle" font-weight="700">F</text>
  <text x="95" y="177" font-size="14" font-weight="700" fill="var(--d-text)">Function Calling</text>
  <text x="50" y="205" font-size="11.5" fill="var(--d-muted)">AIが関数呼び出しを要求する</text>
  <text x="50" y="222" font-size="11.5" fill="var(--d-muted)">『仕組み』</text>
  <line x1="180" y1="240" x2="180" y2="290" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#fc-arrow)"/>
  <rect x="30" y="290" width="300" height="100" rx="12" fill="var(--d-panel-2)" stroke="var(--d-c-cloud)" stroke-width="2"/>
  <circle cx="65" cy="322" r="16" fill="var(--d-c-cloud)"/>
  <text x="65" y="327" font-size="13" fill="#fff" text-anchor="middle" font-weight="700">T</text>
  <text x="95" y="327" font-size="14" font-weight="700" fill="var(--d-text)">Tool Call</text>
  <text x="50" y="355" font-size="11.5" fill="var(--d-muted)">その仕組みが実際に1回</text>
  <text x="50" y="372" font-size="11.5" fill="var(--d-muted)">発火した『単位』</text>
  <rect x="570" y="140" width="300" height="120" rx="12" fill="var(--d-panel-2)" stroke="var(--d-c-local)" stroke-width="2"/>
  <circle cx="605" cy="172" r="16" fill="var(--d-c-local)"/>
  <text x="605" y="177" font-size="13" fill="#fff" text-anchor="middle" font-weight="700">M</text>
  <text x="635" y="177" font-size="14" font-weight="700" fill="var(--d-text)">MCP</text>
  <text x="590" y="205" font-size="11.5" fill="var(--d-muted)">Function Callingを異なる</text>
  <text x="590" y="222" font-size="11.5" fill="var(--d-muted)">サービス間で共通化する</text>
  <text x="590" y="239" font-size="11.5" fill="var(--d-muted)">『標準規格』</text>
  <line x1="570" y1="230" x2="335" y2="330" stroke="var(--d-c-local)" stroke-width="1.5" stroke-dasharray="5,4" marker-end="url(#fc-arrow)"/>
  <text x="360" y="290" font-size="10.5" fill="var(--d-muted)">MCP経由の呼び出しも実体はTool Call</text>
</svg>
</div>

出典：[Anthropic Tool Use（Function Calling）公式ドキュメント](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview) ／ [Model Context Protocol 公式仕様](https://modelcontextprotocol.io/specification/2025-11-25) ／ [Anthropic MCP発表（2024年11月）](https://www.anthropic.com/news/model-context-protocol)

---

## 2. RAG（検索拡張生成）の仕組み

| 用語 | 説明 |
|---|---|
| **RAG（検索拡張生成）** | AIに質問する前に、関連する社内資料・過去の記録などを検索して読み込ませ、その内容を踏まえて回答させる仕組み。AIが知らないはずの専門情報にも正確に答えられるようになる |
| **埋め込み（エンベディング）** | 文章の「意味」を数値の列（ベクトル）に変換したもの。意味が近い文章ほど、この数値も近くなる |
| **ベクトル検索** | 埋め込み同士の近さを計算して、質問文と意味が近い文章を探し出す検索方法。キーワードが一致しなくても、意味が近ければ見つけられるのが特徴 |
| **チャンク / チャンキング** | 長い文書を検索しやすい大きさ（数百文字程度）に分割すること。分割した1つ1つの断片を「チャンク」と呼ぶ |
| **ハイブリッド検索** | ベクトル検索（意味の近さ）とキーワード検索（単語の一致）を組み合わせた検索方式。片方だけでは拾いきれない情報を補い合う |
| **HyDE（ハイド）** | 質問文をそのまま検索するのではなく、AIに「こんな回答になりそうだ」という仮の文章を一度作らせてから検索する手法。専門用語の言い回しの違いを埋める効果がある |
| **namespace（ネームスペース）** | 検索対象の情報を、種類ごとに区切ったグループのこと。本プロジェクトでは「チーム共有情報」と「個人情報」を別のnamespaceとして管理し、混ざらないようにしている |

---

## 3. このプロジェクト固有の用語

| 用語 | 説明 |
|---|---|
| **Cloud RAG** | チームで共有してよい情報（ツール仕様・設計書・ゼミ資料等）を検索対象とする仕組み。インターネット経由でアクセスする |
| **Local RAG** | 個人情報（チャット履歴・個人メモ等）を検索対象とする仕組み。自分のパソコン内で完結する |
| **チュートリアル自動生成** | トピック（学びたい内容）を入力すると、AIがHoudini上で実際にノードグラフを組み立てながら、手順書（チュートリアル）を自動で作成する機能 |
| **ノードグラフ** | Houdiniで、部品（ノード）同士をつなげて処理の流れを作る仕組み。プログラミングを、線でつなぐ図として表現したようなもの |
| **サンドボックス** | チュートリアル自動生成が作業する専用の隔離エリア。ここでの操作は他の作業中データに影響しない |
| **トークン予算** | 1人・1組織あたりが使えるAI利用量の上限。使いすぎを防ぐための仕組み |

---

## 4. インフラ・技術基盤の用語

| 用語 | 説明 |
|---|---|
| **GAS（Google Apps Script）** | Googleが提供する、ブラウザ上でプログラムを書いて動かせる仕組み。現在のCloud RAGはこの上で動いている |
| **サーバーレス** | 自分でサーバー（コンピューター）を用意・管理しなくても、プログラムを動かせる仕組み。使った分だけ課金され、管理の手間が少ないのが特徴 |
| **Cloudflare** | サーバーレスの実行環境を提供する会社・サービス。今後、Cloud RAGの移行先として検討している |
| **Vectorize** | Cloudflareが提供する、ベクトル検索専用のデータベース。現在Google Sheetsで代用している検索の仕組みを、これに置き換える計画 |
| **OAuth（オーオース）** | 「このアプリに、あなたのGoogleアカウントのここまでの範囲を使う許可を与える」という、安全な許可の仕組み。パスワードそのものを渡さずに済む |
| **スコープ** | OAuthで許可する範囲のこと。「カレンダーの閲覧だけ許可する」「メール送信も許可する」など、細かく分けられている |

---

## 5. このプロジェクトのRAG分類

RAG（検索拡張生成）は、実装の高度さによって大きく3段階に分類される（Gao et al., *Retrieval-Augmented Generation for Large Language Models: A Survey*, arXiv:2312.10997, 2023–2024）。

| 段階 | 内容 |
|---|---|
| **Naive RAG** | 質問文をそのままベクトル検索し、見つかった文書をAIに渡すだけの最もシンプルな形 |
| **Advanced RAG** | 検索前にクエリを工夫する（HyDE等）・複数の検索方式を組み合わせる（ハイブリッド検索）等、検索の精度を上げる工夫を加えた形 |
| **Modular RAG** | 上記に加えて、状況に応じて検索先を出し分ける「ルーティング」、利用者に応じて出力を調整する「適応的生成」、AIが外部ツールを操作する「ツール統合」などの部品（モジュール）を組み合わせた、最も発展した形 |

**分類結果：本プロジェクトは「Modular RAG」に該当する。**

| 分類の根拠 | 本システムでの実装 |
|---|---|
| ルーティング | namespace単位でChromaDBコレクションを自動分割し、共有情報／個人情報を論理的に分離して検索先を出し分けている |
| ハイブリッド検索（Advanced RAGの要素） | ベクトル検索（ChromaDB）＋BM25（キーワード検索）をRRFで統合 |
| クエリ変換（Advanced RAGの要素） | HyDEによる仮回答生成で、検索クエリの言い回しギャップを補正 |
| 適応的生成 | 理解度スコアに応じてbasic→applied→advancedの難易度で出力を自動調整 |
| ツール統合 | MCP経由でAIがHoudiniを直接操作し、生成物を検証する |
| 監査・防御 | クエリのSHA-256ハッシュ化・監査ログ記録・トークン予算の二重管理 |

単にハイブリッド検索やHyDEを備えるだけならAdvanced RAGの範囲だが、本システムはそれに加えて「ルーティング」「適応的生成」「ツール統合」という複数のモジュールを組み合わせているため、一段階上のModular RAGに位置づけられる。

**補足（実務でよく使われる名称ベースの分類との関係）：** 「Naive→Advanced→Modular」はRAGの発展段階に基づく学術的な分類（Gao et al.）だが、実務では「Hybrid RAG」「Agentic RAG」「Graph RAG」等、手法ごとに名前を付ける分類も広く使われる（例：Level Up Coding「Top 8 RAG Architectures」）。この名称ベースの分類に当てはめると、本システムは検索方式の面で**Hybrid RAG**（ベクトル検索＋キーワード検索の統合）に明確に該当し、MCP経由でHoudiniを複数手順にわたって操作する面では**Agentic RAG**的な特性も併せ持つ。一方、Reranked／Multi-Query／Hierarchical／Graph／Corrective RAGに該当する仕組みは現状実装していない。これらは学術的な発展段階の分類とは別軸（技法ごとの命名）であるため、**Modular RAGという結論自体に変化はない**——Hybrid検索やAgentic的なツール統合は、いずれもModular RAGを構成するモジュールの一部として位置づけられる。

---

*関連ドキュメント: [docs/model-strategy-report.md](model-strategy-report.md) / [docs/cloud-local-unification-plan.md](cloud-local-unification-plan.md) / [MCPdemo/gas-mcp-demo-report.md](../MCPdemo/gas-mcp-demo-report.md)*
