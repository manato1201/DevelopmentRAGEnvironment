# プロジェクト現状整理（2026年8月時点）

**作成日:** 2026-08-22（更新: 2026-08-22 構成図・スケジュール修正、統合版プレゼン資料の反映）
**位置づけ:** 勉強会・中間発表資料のベースとなる、プロジェクト全体の現状サマリー。

---

## 目次

1. [プロジェクトの目的](#1-プロジェクトの目的)
2. [RAGとしての分類](#2-ragとしての分類)
3. [全体アーキテクチャ（実際の4リポジトリ構成）](#3-全体アーキテクチャ実際の4リポジトリ構成)
4. [実装済み機能](#4-実装済み機能)
5. [直近の取り組み（セキュリティ・コスト・MCP検証）](#5-直近の取り組みセキュリティコストmcp検証)
6. [現在検討中の課題](#6-現在検討中の課題)
7. [今後のスケジュール（2026-08-22時点・計画より遅延中）](#7-今後のスケジュール2026-08-22時点計画より遅延中)
8. [発表・共有資料](#8-発表共有資料)

---

## 1. プロジェクトの目的

ゲーム開発（Unity/Houdini）を支援するRAG（検索拡張生成）環境を構築する。

- **個人情報とチーム共有情報を物理的に分離**しつつ、両方をツール内から直接検索・質問できるようにする
- Houdiniについては、検索だけでなく**チュートリアルの自動生成**まで踏み込む
- 最終的には、ITリテラシーが高くない利用者でも扱える水準まで仕上げ、実証実験で効果を検証する

## 2. RAGとしての分類

**Modular RAG**（Gao et al., *Retrieval-Augmented Generation for Large Language Models: A Survey*, arXiv:2312.10997）に該当する。

| 分類軸 | 本システムの実装 |
|---|---|
| ルーティング | namespace単位でChromaDBコレクションを自動分割し、共有情報／個人情報を論理的に分離 |
| ハイブリッド検索（フュージョン） | ベクトル検索（ChromaDB）＋ BM25（Sudachi形態素解析）をRRFで統合 |
| クエリ変換 | HyDEによる仮回答生成 → 検索クエリの言い回しギャップを補正 |
| 適応的生成 | 理解度スコアに応じてbasic→applied→advancedの難易度で出力を調整 |
| ツール統合 | MCP経由でHoudiniを直接操作（create_node / cook 等）し、生成物を検証 |
| 監査・防御 | クエリのSHA-256ハッシュ化・JSONL監査ログ・トークン予算の二重管理 |

ハイブリッド検索・HyDEといったAdvanced RAGの要素に加え、上記のルーティング／適応的生成／ツール統合モジュールを備えるため、Naive→Advanced→Modularの発展段階のうち**Modular RAG**に位置づけられる。

補足：Hybrid RAG／Agentic RAG等の名称ベースの実務分類に当てはめても、本システムはハイブリッド検索の面でHybrid RAG、MCP経由の複数手順操作の面でAgentic RAG的特性に該当するのみであり、いずれもModular RAGを構成する要素の一部のため分類結果は変わらない（詳細は[docs/glossary.md](glossary.md)5章）。

## 3. 全体アーキテクチャ（実際の4リポジトリ構成）

システムに実際に関わるのは以下の4リポジトリ。**ServerLauncherという起動管理コンポーネントは実在しない**（過去の資料で誤って記載していたため削除済み）。

<div style="--d-bg:#ffffff; --d-panel-2:#eef1f4; --d-border:#dfe3e8; --d-border-strong:#c7cdd6; --d-text:#14171c; --d-muted:#68707c; --d-highlight-bg:#e7f0fe; --d-highlight-border:#3d7de8; --d-c-cloud:#0e8f8a; --d-c-local:#7350d6; --d-c-chat:#e07b1f; --d-c-mcp:#c94141; --d-c-sec:#1f7a4d; --d-c-video:#2f4b9e; --d-c-llm:#33404f; --d-c-future:#8a6d1e; --d-line:#aab1bb; background:var(--d-bg); border:1px solid var(--d-border); border-radius:12px; padding:1rem; overflow-x:auto;">
<svg viewBox="0 0 1680 880" xmlns="http://www.w3.org/2000/svg" style="display:block;min-width:900px;">
  <defs>
    <marker id="ps-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--d-line)"/></marker>
    <marker id="ps-arrowUser" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--d-c-chat)"/></marker>
    <marker id="ps-arrowFuture" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--d-c-future)"/></marker>
  </defs>
  <rect x="20" y="140" width="200" height="170" rx="12" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="120" y="166" font-size="13" fill="var(--d-muted)" text-anchor="middle">クライアント</text>
  <rect x="45" y="180" width="150" height="40" rx="8" fill="#2b2b2b"/>
  <text x="120" y="205" font-size="13" fill="#fff" text-anchor="middle" font-weight="600">Unity</text>
  <rect x="45" y="228" width="150" height="40" rx="8" fill="#2b2b2b"/>
  <text x="120" y="253" font-size="13" fill="#fff" text-anchor="middle" font-weight="600">Houdini</text>
  <line x1="220" y1="200" x2="350" y2="200" stroke="var(--d-line)" stroke-width="2" marker-end="url(#ps-arrow)"/>
  <line x1="220" y1="248" x2="350" y2="248" stroke="var(--d-c-chat)" stroke-width="2.5" marker-end="url(#ps-arrowUser)"/>
  <text x="225" y="233" font-size="11" fill="var(--d-c-chat)" font-weight="600">質問・トピック入力（直接）</text>
  <rect x="350" y="40" width="820" height="580" rx="18" fill="none" stroke="var(--d-border-strong)" stroke-width="2"/>
  <text x="378" y="78" font-size="19" font-weight="700" fill="var(--d-text)">DevelopmentRAGEnvironment（メインリポジトリ）</text>
  <text x="378" y="100" font-size="12.5" fill="var(--d-muted)">Cloud RAG + Local RAG + MCP（このリポジトリ内で完結）</text>
  <rect x="400" y="140" width="340" height="170" rx="12" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="424" y="168" font-size="14" font-weight="700" fill="var(--d-text)">対話・操作</text>
  <text x="424" y="186" font-size="11" fill="var(--d-muted)">Chatbot / MCP Server</text>
  <rect x="424" y="198" width="30" height="30" rx="7" fill="var(--d-c-chat)"/>
  <text x="439" y="218" font-size="14" fill="#fff" text-anchor="middle" font-weight="700">C</text>
  <text x="464" y="212" font-size="12.5" font-weight="600" fill="var(--d-text)">チャットボット</text>
  <text x="464" y="227" font-size="10.5" fill="var(--d-muted)">LLM切替（Claude/Gemini）で応答</text>
  <line x1="439" y1="228" x2="439" y2="250" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#ps-arrow)"/>
  <rect x="424" y="252" width="30" height="30" rx="7" fill="var(--d-c-mcp)"/>
  <text x="439" y="272" font-size="14" fill="#fff" text-anchor="middle" font-weight="700">M</text>
  <text x="464" y="266" font-size="12.5" font-weight="600" fill="var(--d-text)">MCP Server</text>
  <text x="464" y="281" font-size="10.5" fill="var(--d-muted)">Houdiniを直接操作・記録</text>
  <rect x="400" y="330" width="340" height="250" rx="12" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="424" y="358" font-size="14" font-weight="700" fill="var(--d-text)">RAGデータ基盤</text>
  <text x="424" y="376" font-size="11" fill="var(--d-muted)">Cloud RAG / Local RAG（namespaceで論理分離）</text>
  <rect x="424" y="388" width="30" height="30" rx="7" fill="var(--d-c-cloud)"/>
  <text x="439" y="408" font-size="14" fill="#fff" text-anchor="middle" font-weight="700">Cl</text>
  <text x="464" y="402" font-size="12.5" font-weight="600" fill="var(--d-text)">Cloud RAG</text>
  <text x="464" y="417" font-size="10.5" fill="var(--d-muted)">チーム共有情報（Notion + GAS）</text>
  <line x1="439" y1="418" x2="439" y2="440" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#ps-arrow)"/>
  <rect x="424" y="442" width="30" height="30" rx="7" fill="var(--d-c-local)"/>
  <text x="439" y="462" font-size="14" fill="#fff" text-anchor="middle" font-weight="700">Lo</text>
  <text x="464" y="456" font-size="12.5" font-weight="600" fill="var(--d-text)">Local RAG</text>
  <text x="464" y="471" font-size="10.5" fill="var(--d-muted)">個人情報（ChromaDB + BM25 + HyDE）</text>
  <rect x="424" y="490" width="296" height="60" rx="8" fill="var(--d-highlight-bg)" stroke="var(--d-highlight-border)" stroke-width="1.3"/>
  <text x="440" y="512" font-size="11" font-weight="600" fill="var(--d-highlight-border)">ハイブリッド検索</text>
  <text x="440" y="530" font-size="10" fill="var(--d-muted)">ベクトル(e5-large) ＋ BM25 を RRF で統合</text>
  <line x1="740" y1="213" x2="760" y2="213" stroke="var(--d-line)" stroke-width="1.5"/>
  <line x1="760" y1="213" x2="760" y2="457" stroke="var(--d-line)" stroke-width="1.5"/>
  <line x1="760" y1="457" x2="742" y2="457" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#ps-arrow)"/>
  <rect x="800" y="140" width="340" height="230" rx="14" fill="var(--d-panel-2)" stroke="var(--d-c-sec)" stroke-width="2"/>
  <text x="824" y="168" font-size="14" font-weight="700" fill="var(--d-c-sec)">セキュリティ・品質制御</text>
  <rect x="824" y="188" width="30" height="30" rx="7" fill="var(--d-c-sec)"/>
  <text x="839" y="208" font-size="13" fill="#fff" text-anchor="middle" font-weight="700">A</text>
  <text x="864" y="202" font-size="12.5" font-weight="600" fill="var(--d-text)">監査ログ</text>
  <text x="864" y="217" font-size="10.5" fill="var(--d-muted)">クエリをSHA-256でハッシュ化・JSONL記録</text>
  <line x1="839" y1="218" x2="839" y2="240" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#ps-arrow)"/>
  <rect x="824" y="242" width="30" height="30" rx="7" fill="var(--d-c-sec)"/>
  <text x="839" y="262" font-size="13" fill="#fff" text-anchor="middle" font-weight="700">T</text>
  <text x="864" y="256" font-size="12.5" font-weight="600" fill="var(--d-text)">トークン予算</text>
  <text x="864" y="271" font-size="10.5" fill="var(--d-muted)">RAG/Claude双方をサーバー側で二重管理</text>
  <line x1="839" y1="272" x2="839" y2="294" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#ps-arrow)"/>
  <rect x="824" y="296" width="30" height="30" rx="7" fill="var(--d-c-sec)"/>
  <text x="839" y="316" font-size="13" fill="#fff" text-anchor="middle" font-weight="700">S</text>
  <text x="864" y="310" font-size="12.5" font-weight="600" fill="var(--d-text)">理解度スコア</text>
  <text x="864" y="325" font-size="10.5" fill="var(--d-muted)">basic→applied→advancedを自動調整</text>
  <line x1="1170" y1="225" x2="1220" y2="225" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#ps-arrow)"/>
  <text x="1173" y="215" font-size="10" fill="var(--d-muted)">生成・埋め込みAPI呼び出し</text>
  <rect x="1220" y="140" width="280" height="170" rx="12" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="1244" y="168" font-size="14" font-weight="700" fill="var(--d-text)">外部LLM API</text>
  <rect x="1244" y="192" width="232" height="38" rx="8" fill="var(--d-c-llm)"/>
  <text x="1360" y="216" font-size="13" fill="#fff" text-anchor="middle" font-weight="600">Claude API</text>
  <rect x="1244" y="240" width="232" height="38" rx="8" fill="var(--d-c-llm)"/>
  <text x="1360" y="264" font-size="13" fill="#fff" text-anchor="middle" font-weight="600">Gemini API</text>
  <line x1="1170" y1="455" x2="1220" y2="455" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#ps-arrow)"/>
  <text x="1173" y="445" font-size="10" fill="var(--d-muted)">回答・チュートリアルをHTTP POST</text>
  <rect x="1220" y="340" width="380" height="250" rx="12" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="1244" y="368" font-size="14" font-weight="700" fill="var(--d-text)">LearningQt（別リポジトリ）</text>
  <text x="1244" y="386" font-size="11" fill="var(--d-muted)">GameDevelopment/LearningQt（Qt/C++）</text>
  <rect x="1244" y="398" width="30" height="30" rx="7" fill="var(--d-c-video)"/>
  <text x="1259" y="418" font-size="13" fill="#fff" text-anchor="middle" font-weight="700">Q</text>
  <text x="1284" y="412" font-size="12.5" font-weight="600" fill="var(--d-text)">ナレーション動画生成</text>
  <text x="1284" y="427" font-size="10.5" fill="var(--d-muted)">SAPI5音声合成 ＋ Mermaid図解 ＋ FFmpeg</text>
  <line x1="1259" y1="428" x2="1259" y2="455" stroke="var(--d-line)" stroke-width="1.5" marker-end="url(#ps-arrow)"/>
  <rect x="1244" y="457" width="326" height="60" rx="8" fill="var(--d-highlight-bg)" stroke="var(--d-highlight-border)" stroke-width="1.3"/>
  <text x="1260" y="479" font-size="11" font-weight="600" fill="var(--d-highlight-border)">Web公開（動画ギャラリー）</text>
  <text x="1260" y="497" font-size="10" fill="var(--d-muted)">manifest.json方式で31本を自動公開中</text>
  <text x="350" y="660" font-size="11" fill="var(--d-c-future)" font-weight="600">連携検討中（将来・未確定）</text>
  <line x1="545" y1="620" x2="545" y2="676" stroke="var(--d-c-future)" stroke-width="1.5" stroke-dasharray="5,4" marker-end="url(#ps-arrowFuture)"/>
  <line x1="965" y1="620" x2="965" y2="676" stroke="var(--d-c-future)" stroke-width="1.5" stroke-dasharray="5,4" marker-end="url(#ps-arrowFuture)"/>
  <rect x="350" y="676" width="390" height="140" rx="12" fill="none" stroke="var(--d-c-future)" stroke-width="1.5" stroke-dasharray="6,5"/>
  <text x="374" y="704" font-size="13" font-weight="700" fill="var(--d-c-future)">VisualRegressionQATool（別リポジトリ）</text>
  <text x="374" y="722" font-size="10.5" fill="var(--d-muted)">ピクセル差分によるビジュアル回帰QA</text>
  <text x="374" y="740" font-size="10.5" fill="var(--d-muted)">生成チュートリアル・描画結果の検証への活用を検討中</text>
  <rect x="770" y="676" width="390" height="140" rx="12" fill="none" stroke="var(--d-c-future)" stroke-width="1.5" stroke-dasharray="6,5"/>
  <text x="794" y="704" font-size="13" font-weight="700" fill="var(--d-c-future)">VLMAutoReplayTool（別リポジトリ）</text>
  <text x="794" y="722" font-size="10.5" fill="var(--d-muted)">基盤モデル計画＋専用スキル実行のゲーム自動プレイエージェント</text>
  <text x="794" y="740" font-size="10.5" fill="var(--d-muted)">ローカルRAGブリッジ(:8766)を共用し連携を検討中</text>
</svg>
</div>

現状はCloud/Localが別インフラ・別実装。統合方針は[docs/cloud-local-unification-plan.md](cloud-local-unification-plan.md)を参照。LearningQtは`GameDevelopment/LearningQt`として別リポジトリで運用され、HTTP経由でCloud RAGの回答・チュートリアルを取得して動画化する（実在・連携確定）。VisualRegressionQATool（`GameDevelopment/VisualRegressionQATool`）とVLMAutoReplayTool（`GameDevelopment/VLMAutoReplayTool`）は、性能向上・デバッグ効率化の観点で将来連携する可能性があるが、現時点では未確定。

## 4. 実装済み機能

| 機能 | 概要 |
|---|---|
| Cloud RAGチャット | チーム共有ドキュメント（Notion経由）に対するハイブリッド検索（ベクトル+キーワード）+ HyDE |
| Local RAGチャット | ChromaDBベースの個人情報検索 |
| Houdiniチュートリアル自動生成 | トピックからノードグラフを自動組み立て、手順書を生成（basic→applied→advancedの3段階生成に対応） |
| トークン予算管理 | APIキーごとにRAG用・Claude用を独立管理し、GAS側で強制。自動回復にも対応 |
| モデル選択機能 | チュートリアル生成モデルをclaude-sonnet-5（高品質）/claude-haiku-4-5（低コスト）から選択可能 |
| 監査ログ・アクセス制御 | 全クエリの監査ログ記録、ロールベースのnamespace権限制御 |
| チュートリアル自動動画化 | LearningQt（別リポジトリ）がRAG回答・チュートリアルをナレーション付き動画に変換し、Web公開（31本自動公開中） |

## 5. 直近の取り組み（セキュリティ・コスト・MCP検証）

- **セキュリティ強化**：クライアント側でトークン上限を改ざんできる構成を廃止し、GASを唯一の判定者にする設計へ移行（[docs/claude-token-security-report.md](claude-token-security-report.md)）
- **コスト最適化**：チュートリアル生成モデルの選択制対応。Houdini自動操作は実際にはMCPではなくAnthropicツールユースであることを確認・整理（[docs/model-strategy-report.md](model-strategy-report.md)）
- **MCP実機検証**：Gemini経由でGoogle純正MCP（Calendar）・サードパーティMCP（DeepWiki）・複数サーバー横断を検証。Calendar MCPは複数の壁に直面し、代替としてGASネイティブサービス（Calendar/Gmail/Maps）での実装に切り替えた（[MCPdemo/gas-mcp-demo-report.md](../MCPdemo/gas-mcp-demo-report.md)）
- **性能改善**：ナレッジ一括登録がGASの実行時間上限（6分）に達する問題を、埋め込みAPI呼び出しのバッチ化で緩和
- **発表資料の整備**：勉強会・中間発表を1つのデッキに統合（本編は結論ベース、Appendixに技術詳細）し、ABテストの評価指標を独立変数/従属変数で厳格に定義（詳細は8章）

## 6. 現在検討中の課題

| # | 課題 | 対応方針 |
|---|---|---|
| 1 | Cloud RAGのDB管理・性能に限界（Sheetsへの力技実装） | Cloudflare（Workers + Vectorize）への移行を検討中。ただし実証実験期間中は着手しない（[docs/cloud-local-unification-plan.md](cloud-local-unification-plan.md)） |
| 2 | Cloud/Localの二重実装 | バックエンドを1つに統合し、「共有スコープ」「個人スコープ」という論理的な区分けとして再設計する方針 |
| 3 | ITリテラシーが高くない利用者への対応 | エラーメッセージの平易化、セットアップ手順書・用語集の整備を実証実験前に完了させる（[docs/pilot-test-proposal.md](pilot-test-proposal.md)） |
| 4 | スケジュールの遅延 | 当初計画（7月時点で完了予定だった項目）が8月時点でも進行中。現在地を8月に再設定し、以降のフェーズを後ろ倒しで再計画（7章） |

## 7. 今後のスケジュール（2026-08-22時点・計画より遅延中）

<div style="--d-bg:#ffffff; --d-panel-2:#eef1f4; --d-border:#dfe3e8; --d-text:#14171c; --d-muted:#68707c; --d-highlight-bg:#e7f0fe; --d-highlight-border:#3d7de8; --d-line:#aab1bb; background:var(--d-bg); border:1px solid var(--d-border); border-radius:12px; padding:1rem; overflow-x:auto;">
<svg viewBox="0 0 1560 380" xmlns="http://www.w3.org/2000/svg" style="display:block;min-width:900px;">
  <defs><marker id="ps-sc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--d-line)"/></marker></defs>
  <text x="20" y="30" font-size="11" fill="var(--d-highlight-border)" font-weight="700">8月　★現在地</text>
  <rect x="20" y="44" width="200" height="110" rx="10" fill="var(--d-highlight-bg)" stroke="var(--d-highlight-border)" stroke-width="2"/>
  <text x="36" y="72" font-size="13" font-weight="700" fill="var(--d-text)">①システム改善・</text>
  <text x="36" y="90" font-size="13" font-weight="700" fill="var(--d-text)">強化</text>
  <text x="36" y="112" font-size="10.5" fill="var(--d-highlight-border)">進行中（計画より遅延）</text>
  <line x1="220" y1="99" x2="240" y2="99" stroke="var(--d-line)" stroke-width="2" marker-end="url(#ps-sc-arrow)"/>
  <text x="240" y="30" font-size="11" fill="var(--d-muted)">9月上旬</text>
  <rect x="240" y="44" width="200" height="110" rx="10" fill="var(--d-highlight-bg)" stroke="var(--d-highlight-border)" stroke-width="2"/>
  <text x="256" y="72" font-size="13" font-weight="700" fill="var(--d-text)">②ベータテスト・</text>
  <text x="256" y="90" font-size="13" font-weight="700" fill="var(--d-text)">中間発表</text>
  <text x="256" y="112" font-size="10.5" fill="var(--d-highlight-border)">マイルストーン</text>
  <line x1="440" y1="99" x2="460" y2="99" stroke="var(--d-line)" stroke-width="2" marker-end="url(#ps-sc-arrow)"/>
  <text x="460" y="30" font-size="11" fill="var(--d-muted)">9月中旬〜下旬</text>
  <rect x="460" y="44" width="200" height="110" rx="10" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="476" y="72" font-size="13" font-weight="700" fill="var(--d-text)">③実証実験</text>
  <text x="476" y="90" font-size="13" font-weight="700" fill="var(--d-text)">対象者選定＆実験</text>
  <text x="476" y="112" font-size="10.5" fill="var(--d-muted)">予定</text>
  <line x1="660" y1="99" x2="680" y2="99" stroke="var(--d-line)" stroke-width="2" marker-end="url(#ps-sc-arrow)"/>
  <text x="680" y="30" font-size="11" fill="var(--d-muted)">10月</text>
  <rect x="680" y="44" width="200" height="110" rx="10" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="696" y="72" font-size="13" font-weight="700" fill="var(--d-text)">④実証実験</text>
  <text x="696" y="90" font-size="13" font-weight="700" fill="var(--d-text)">継続</text>
  <text x="696" y="112" font-size="10.5" fill="var(--d-muted)">予定</text>
  <line x1="880" y1="99" x2="900" y2="99" stroke="var(--d-line)" stroke-width="2" marker-end="url(#ps-sc-arrow)"/>
  <text x="900" y="30" font-size="11" fill="var(--d-muted)">11月</text>
  <rect x="900" y="44" width="200" height="110" rx="10" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="916" y="72" font-size="13" font-weight="700" fill="var(--d-text)">⑤実証実験継続／</text>
  <text x="916" y="90" font-size="13" font-weight="700" fill="var(--d-text)">考察・論文執筆</text>
  <text x="916" y="112" font-size="10.5" fill="var(--d-muted)">中旬〜並行開始</text>
  <line x1="1100" y1="99" x2="1120" y2="99" stroke="var(--d-line)" stroke-width="2" marker-end="url(#ps-sc-arrow)"/>
  <text x="1120" y="30" font-size="11" fill="var(--d-muted)">12月</text>
  <rect x="1120" y="44" width="200" height="110" rx="10" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="1136" y="72" font-size="13" font-weight="700" fill="var(--d-text)">⑥まとめ</text>
  <text x="1136" y="112" font-size="10.5" fill="var(--d-muted)">予定</text>
  <line x1="1320" y1="99" x2="1340" y2="99" stroke="var(--d-line)" stroke-width="2" marker-end="url(#ps-sc-arrow)"/>
  <text x="1340" y="30" font-size="11" fill="var(--d-muted)">12月下旬</text>
  <rect x="1340" y="44" width="200" height="110" rx="10" fill="var(--d-highlight-bg)" stroke="var(--d-highlight-border)" stroke-width="2"/>
  <text x="1356" y="72" font-size="13" font-weight="700" fill="var(--d-text)">⑦最終発表</text>
  <text x="1356" y="112" font-size="10.5" fill="var(--d-highlight-border)">マイルストーン</text>
  <line x1="20" y1="200" x2="1540" y2="200" stroke="var(--d-border)" stroke-width="1"/>
  <text x="20" y="230" font-size="10.5" fill="var(--d-muted)" letter-spacing="0.05em">LEGEND</text>
  <rect x="20" y="244" width="26" height="26" rx="6" fill="var(--d-panel-2)" stroke="var(--d-border)" stroke-width="1.5"/>
  <text x="56" y="262" font-size="12" fill="var(--d-muted)">通常フェーズ（予定）</text>
  <rect x="260" y="244" width="26" height="26" rx="6" fill="var(--d-highlight-bg)" stroke="var(--d-highlight-border)" stroke-width="2"/>
  <text x="296" y="262" font-size="12" fill="var(--d-muted)">現在地・マイルストーン</text>
</svg>
</div>

バックエンド統合（Cloudflare移行）は、上図⑦最終発表・実証実験の完全終了後に着手する方針を継続する。

## 8. 発表・共有資料

| 資料 | 内容 |
|---|---|
| [docs/pilot-test-proposal.md](pilot-test-proposal.md) | ベータテスト・本格実証実験の実施提案書（構成図・スケジュール図・ABテストの厳格な評価指標定義を含む） |
| [docs/glossary.md](glossary.md) | 用語集（Function Calling / Tool Call / MCPの関係図を含む） |
| 統合版プレゼン資料（`presentation.pptx`） | 勉強会・中間発表を1つに統合したスライド資料。本編14枚＋Appendix8枚。黒背景＋パネル色＋オレンジアクセントのデザイン |

---

*関連ドキュメント: [docs/model-strategy-report.md](model-strategy-report.md) / [docs/cloud-local-unification-plan.md](cloud-local-unification-plan.md) / [docs/pilot-test-proposal.md](pilot-test-proposal.md) / [docs/glossary.md](glossary.md) / [MCPdemo/gas-mcp-demo-report.md](../MCPdemo/gas-mcp-demo-report.md)*
