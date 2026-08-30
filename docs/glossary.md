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
6. [周辺・派生手法の整理（2026-08-29調査分）](#6-周辺派生手法の整理2026-08-29調査分)

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

### 16種類のRAG分類との対応

ユーザーが調査した「16種類のRAG」（Medium記事ベース、近い出典: [Gaurav Nigam, "A Complete Guide to Retrieval-Augmented Generation (RAG): 16 Different Types"](https://medium.com/aingineer/a-complete-guide-to-retrieval-augmented-generation-rag-16-different-types-their-implementation-10d48248517b)。原文全体は未取得のため、ユーザー提供の各項目の説明文をそのまま引用元とする）に、本プロジェクトが該当するかどうかを1つずつ照らし合わせる。

| # | 種類 | 概要（原文要約） | 本プロジェクトでの該当状況 |
|---|---|---|---|
| 1 | **Standard RAG** | 検索＋生成の基本形 | ✅ 該当（全システムの土台） |
| 2 | **Agentic RAG** | AIエージェントが自律的に検索・行動する | 🟡 部分的に該当（チュートリアル自動生成でMCP経由のHoudini操作は該当するが、チャットのRAG検索自体は自律計画をしない単発の検索・生成） |
| 3 | **Graph RAG** | ナレッジグラフによる関係推論 | ❌ 非該当（グラフタブは文書間の類似度を可視化するUIであり、LLMの推論にグラフ構造を使ってはいない。§6.1参照） |
| 4 | **Modular RAG** | 検索・推論・生成を独立モジュール化 | ✅ 該当（§5の分類結論そのもの） |
| 5 | **Memory-Augmented RAG** | 永続的な外部メモリで文脈を保持 | 🟡 一部該当（GAS版はRAG_Memoryシートに知識をQ&A形式で蓄積・検索する仕組みがある。Cloudflare版はチャット履歴をRAG検索に還元する機能は意図的に未実装のまま保留中） |
| 6 | **Multi-Modal RAG** | テキスト・画像・音声を横断処理 | ✅ 該当（画像添付質問機能＝実質MAG、Drive同期時のPDF/音声/動画の文字起こし取り込み） |
| 7 | **Federated RAG** | 分散データソースからのプライバシー保護型検索 | ❌ 非該当（単一のD1/Vectorize・Sheetsに集約する構成で、分散ソース間の連合検索は行っていない） |
| 8 | **Streaming RAG** | リアルタイムの検索・生成 | ❌ 非該当（同期はバッチ処理・手動/cronトリガーで、ライブフィード的なリアルタイム性は無い） |
| 9 | **ODQA RAG（Open-Domain QA）** | 大規模・多様なデータセットへの対応 | 🟡 部分的に該当（namespace横断の全DB検索はあるが、自社ナレッジベース内に閉じたクローズドドメインであり、Web全体を対象とするオープンドメインではない） |
| 10 | **Contextual Retrieval RAG** | セッション単位の文脈維持 | ✅ 該当（会話履歴historyを検索・回答生成に渡すマルチターン対応） |
| 11 | **Knowledge-Enhanced RAG** | 構造化ドメインデータの統合 | 🟡 限定的に該当（namespace・difficulty等の構造化メタデータは扱うが、専門分野向けの構造化データベースそのものとの統合ではない） |
| 12 | **Domain-Specific RAG** | 特定業界向けにカスタマイズ | ✅ 該当（Houdini/ゲーム開発ドメインに特化。HyDEのプロンプトもドメインごとに調整済み） |
| 13 | **Hybrid RAG** | 複数の検索方式を組み合わせる | ✅ 該当（ベクトル検索＋BM25/FTS5をRRFで統合。§5で既出） |
| 14 | **Self-RAG** | 自己反省で回答を自ら改善・ファクトチェックする | ❌ 非該当（情報抽出度は表示のみでモデルの自己修正には使っていない。§6.6でCRAGとして優先度高と評価した部分がここに相当） |
| 15 | **HyDE RAG** | 仮説文書生成による検索強化 | ✅ 該当（実装済み。§2で既出） |
| 16 | **Recursive / Multi-Step RAG** | 検索・生成のループを複数回行う | ❌ 非該当（現状は1回の検索→1回の生成のみで、多段の検索ループは無い） |

**まとめ**: 16種類中、明確に該当するのは7種類（Standard, Modular, Multi-Modal, Contextual Retrieval, Domain-Specific, Hybrid, HyDE）。部分的に該当するのが4種類（Agentic, Memory-Augmented, ODQA, Knowledge-Enhanced）。非該当が5種類（Graph, Federated, Streaming, Self-RAG, Recursive/Multi-Step）。

この16分類は§5で既に整理した「Naive→Advanced→Modular」（学術的な発展段階）や「Hybrid／Agentic／Graph RAG」（名称ベース）と重複する項目が多い（Modular・Hybrid・Agentic・Graph・HyDEはいずれも同じものを指している）。したがって「16種類」は**§5の分類と対立するものではなく、実務でよく挙げられる個別パターンをより細かく列挙したもの**と位置づけられる。非該当5種類のうち、Self-RAGは§6.6で優先度「高」としたCRAG（Corrective RAG）と重なる領域であり、次に着手する候補として引き続き有力。

---

## 6. 周辺・派生手法の整理（2026-08-29調査分）

§5でRAGを「Naive→Advanced→Modular」という発展段階と、「Hybrid RAG」「Agentic RAG」「Graph RAG」等の名称ベースの分類の2軸で整理した。今回、ユーザーが追加で調査した手法群をこの2つの分類に照らし合わせて整理する。

### 6.0 まず結論：名称が違うだけのものと、本当に新しいものの見分け

| 今回見つかった名称 | §5・§2との関係 | 補足 |
|---|---|---|
| **GraphRAG / KAG** | §5の「Graph RAG」（名称ベース分類・未実装）と**ほぼ同一** | KAGはGraphRAGの発展形で、グラフ上の**論理推論**（多段の関係を辿る）を特に強調する点がやや異なる。別物というより親戚関係 |
| **CRAG（Corrective RAG）** | §5に**そのままの名称で既出**（未実装として明記済み） | 概念・名称ともに完全に同一 |
| **Agentic RAG** | §5に既出（MCP経由でHoudiniを操作する点が該当すると明記済み） | 同一 |
| **HyDE** | §2に独立項目として既出（本システムで実装済み） | 同一 |
| **Adaptive RAG** | 紛らわしいが§5の「適応的生成」とは**別物** | 本システムの「適応的生成」は理解度スコアに応じて**回答の難易度**（basic/applied/advanced）を変える仕組み。Adaptive RAGは質問ごとに**検索方式そのもの**（無検索／通常RAG／高度な検索）を切り替える仕組みで、対象がまったく違う。名前が似ているだけの別概念 |
| **MAG（Multimodal-Augmented Generation）** | 分類名としては初出だが、**実装自体は既にある** | 2026-08-27に追加した画像添付質問機能（`query.ts`のマルチモーダル対応）が実質MAGに該当する |
| **CAG（Cache-Augmented Generation）** | §5には無い。前回のチャットで別途比較済み | 新規（詳細は6.1） |
| **DAG / TAG / Web-Augmented Generation / Code-Augmented Generation** | §5には無い | 完全に新規 |
| **CoT / ToT / GoT / ReAct** | §5には無い（そもそも別カテゴリ） | 検索拡張（〇〇-Augmented Generation）ではなく、**プロンプト・推論時の工夫**というまったく別の軸の技術。ReActは「思考→行動（ツール呼び出し）→思考」を繰り返す枠組みで、概念的にはAgentic RAGのツール呼び出しループとほぼ同じ動作をしている |
| **Fine-Tuning / LoRA・QLoRA / Doc-to-LoRA / Prompt Tuning** | §5には無い（そもそも別パラダイム） | RAGのように「都度検索して読ませる」のではなく、**モデル本体（またはその一部）を書き換える**アプローチ。6.4で詳述 |

**まとめると**: GraphRAG・CRAG・Agentic RAG・HyDEの4つは名称が違うだけで§5の分類に既に含まれている。Adaptive RAGは名前が似ているが別物。MAGは実装済みだが分類名を付けていなかっただけ。CAG・DAG・TAG・Web/Code-Augmented Generation・CoT系・Fine-Tuning系は本当に新規の観点。

### 6.1 ①外部データの持たせ方・連携（〇〇-Augmented Generation系）

| 手法 | 特徴 | 利点 | デメリット |
|---|---|---|---|
| **GraphRAG / KAG** | 情報を単語・概念間の「関係性」としてグラフ化してから参照する | 複雑な相関関係の要約や、複数ホップ（AとBの関係にあるCが…）の質問に強い | ナレッジグラフの構築・保守が別途必要（エンティティ抽出・関係抽出）。本プロジェクトのようなチュートリアル/ノート中心のテキストは元々グラフ構造との相性がよくない |
| **CAG（Cache-Augmented Generation）** | 知識全体を事前にLLMのコンテキストへ詰め込み、KVキャッシュとして再利用する。検索ステップ自体を無くす | 検索ミスが原理的に起きない、レイテンシが下がる、ベクトルDBが不要で構成がシンプル | コンテキストウィンドウに収まる規模の**小さく安定した**知識にしか使えない（houdini21のような数千ファイル規模には不可）。更新のたびにキャッシュ再構築が必要 |
| **DAG（Data-Augmented Generation）** | PDFなどの文書ではなく、SQL/JSON/CSVのような構造化された数値データを直接処理して文章化する | 売上データ等から財務レポート初稿を自動生成するような、数値ベースの正確な文章化に強い | ※このプロジェクト内で既に別の意味で使っている「DAG」（PDG＝Procedural Dependency Graph、有向非巡回グラフ）と略称が衝突するので注意。本プロジェクトの知識ベースは文書中心で構造化データはほぼ無いため、直接の適用先が乏しい |
| **TAG（Table-Augmented Generation）** | DAGに似るが、特にExcel/SQLのような**表形式データ**のセル間集計・分析に特化 | 表の縦横関係を保ったまま処理できる | 同上。適用先が乏しい |
| **MAG（Multimodal-Augmented Generation）** | テキストだけでなく画像・動画・音声・図表を検索/参照対象にする | スクリーンショットや図解を含む質問に対応できる | 画像埋め込み・ストレージのコストが増える |
| **Web-Augmented Generation** | 社内DBではなくGoogle等のWeb検索エンジンをリアルタイムに叩いて最新情報を取り込む | SideFXのリリースノート更新など、社内DBの更新が追いつかない鮮度の高い情報に対応できる | Worker側から外部Web検索を呼ぶ実装・コストが増える。検索結果の信頼性担保が別課題になる |
| **Code-Augmented Generation** | AIが直接答えを生成するのではなく、裏でPython等のコードを自動生成・実行し、その実行結果を回答に組み込む | 計算問題や、VEX/Pythonスニペットの動作検証など「実際に動かして確認する」質問に強い | サンドボックス実行環境の構築・セキュリティ対策が別途必要。本プロジェクトは既にHoudini操作をMCP経由のツール呼び出しで行っており、部分的に近い性質を持つ |

### 6.2 ②検索・処理プロセスの自動最適化（Advanced RAG・Agentic系）

| 手法 | 特徴 | 利点 | デメリット |
|---|---|---|---|
| **Agentic RAG** | AI自身が「どのnamespaceを、どう検索すべきか」を自律的に計画する | 複数ステップにまたがる複雑な要求に対応できる | 判断ミス時の挙動が読みにくい、レイテンシ・コストが増える |
| **CRAG（Corrective RAG）** | 検索結果が質問に本当に合っているかを自動評価し、不十分ならWeb検索等に切り替える | 検索ミスを自動で補正できる | 評価ステップ自体にLLM呼び出しが1回追加でかかる |
| **Adaptive RAG** | 質問の難易度に応じて「無検索／通常RAG／高度な検索」を自動使い分け | 簡単な質問への無駄な検索コストを削減できる | 難易度判定自体の精度に依存する |
| **Speculative RAG** | ユーザーが送信ボタンを押す前、入力中に先読みして検索を始めておく | 体感レイテンシを大きく下げられる | 無駄な検索（結局送信されない入力）が発生しコストが増える |
| **HyDE** | 質問文の代わりに仮の回答を生成し、その埋め込みで検索する | 語彙ミスマッチを解消できる | 仮回答生成の1LLM呼び出し分のコストが増える（本プロジェクトは実装済み。§2参照） |

### 6.3 ③プロンプト・推論時の拡張（Inference-Time Scaling）

検索拡張（〇〇-Augmented Generation）ではなく、「どう考えさせるか」でLLMの回答の質を上げる手法群。

| 手法 | 特徴 | 利点 | デメリット |
|---|---|---|---|
| **CoT（Chain of Thought）** | 「順を追って考えて」と指示し、思考過程を書き出させる | 論理的・数学的なミスを減らせる、実装コストがほぼゼロ（プロンプト変更のみ） | 出力トークン数が増える分コスト・レイテンシが増える |
| **ToT（Tree of Thoughts）** | 複数の思考の枝を同時にシミュレーションし、成功確率の高いルートを選ぶ | 単一の思考プロセスより難問に強い | 複数ルートを試す分コストが数倍に増える |
| **GoT（Graph of Thoughts）** | ToTをさらに発展させ、思考同士を網目状に組み合わせたり後戻りしたりする | ToTよりさらに複雑な問題に対応できる | 実装・制御が複雑、コストも高い |
| **ReAct（Reason and Act）** | 「思考」と「行動（ツール使用）」を交互に繰り返す | 外部ツールと組み合わせた段階的な問題解決に強い | 本プロジェクトのMCP経由Houdini操作は概念的にほぼReActと同じ動作を既に行っている |

### 6.4 ④モデルの学習・チューニング（RAGとは別パラダイム）

RAGが「都度カンニングペーパーを持ち込む」方式なのに対し、こちらは「事前に頭に叩き込む」方式。検索拡張生成とは根本的にアプローチが異なる。

| 手法 | 特徴 | 利点 | デメリット |
|---|---|---|---|
| **Full Fine-Tuning** | モデル全体のパラメータを新しいデータで再学習する | AIの振る舞い・専門性そのものを根本から最適化できる | 膨大な計算コスト・時間がかかる。知識を更新するたびに再学習が必要（RAGの「ファイルを置くだけ」更新とは対照的） |
| **LoRA / QLoRA** | モデル本体は固定し、小さな差分（アダプター）だけを追加学習する | Full Fine-Tuningよりはるかに軽量 | それでも学習データの準備・学習プロセスが必要 |
| **Doc-to-LoRA**（Sakana AI等、2026年注目） | ドキュメントのテキストから、学習プロセスを経ずに差分パラメータ（LoRA）を自動生成する | 「学習なしでほぼ瞬時に文書の内容をモデルに反映」というRAGとFine-Tuningの中間を狙う | まだ新しい技術で実運用実績が少ない。生成された差分の精度・安定性の検証が必要 |
| **Prompt Tuning / Prefix Tuning** | モデルパラメータはいじらず、入力の先頭に特殊な仮想プロンプトを学習させて付与する | LoRAよりさらに軽量 | 効果がLoRAより限定的なことが多い |

### 6.5 「カンニングペーパー」の例えで整理する（ユーザー提供）

| 手法 | イメージ |
|---|---|
| RAG | カンニングペーパーを**その都度探して**解く |
| CAG | 教科書を丸ごと**机に広げっぱなしにして**解く |
| GraphRAG / KAG | 相関図や家系図などの**まとめノートを見て**解く |
| Fine-Tuning系 | 事前に猛勉強して**頭に叩き込んで**解く |

### 6.6 このプロジェクトへの当てはめ・組み込み優先度

| 手法 | 優先度 | 理由 |
|---|---|---|
| **CRAG（Corrective RAG）** | 高 | 情報抽出度（extractionRate）という「検索結果が質問に合っているか」の指標を既に持っているため、これをトリガーに再検索/Web検索へ切り替えるロジックは比較的低コストで追加できる |
| **CAG** | 中 | `tool_docs`のような小さく安定したnamespace限定でGeminiのコンテキストキャッシュ機能を使って試す価値がある（前回チャット参照） |
| **Adaptive RAG** | 中 | 挨拶や雑談的な質問への無駄な検索を省略できれば、コスト削減に直結する |
| **Speculative RAG** | 低〜中 | UXの改善効果はあるが、無駄な検索コストとのトレードオフを要検証 |
| **GraphRAG / KAG** | 低 | 現状「複数ホップの関係を辿れず答えが出ない」という具体的な失敗事例が出ていない。ナレッジグラフ構築コストに見合わない |
| **DAG / TAG / Web-Augmented / Code-Augmented Generation** | 低 | 知識ベースが文書中心で構造化データがほぼ無い、または実装コストに対して現状の需要が低い |
| **Fine-Tuning系（LoRA含む）** | 非推奨（現時点） | 「ファイルを置くだけで知識が更新される」というRAGの運用しやすさを手放すことになる。Houdini21DBのような継続的に追加・更新されるコンテンツとは相性が悪い |

---

*関連ドキュメント: [docs/model-strategy-report.md](model-strategy-report.md) / [docs/cloud-local-unification-plan.md](cloud-local-unification-plan.md) / [MCPdemo/gas-mcp-demo-report.md](../MCPdemo/gas-mcp-demo-report.md)*
