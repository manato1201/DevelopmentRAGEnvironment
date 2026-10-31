# ドキュメントの索引

**更新日:** 2026-10-31（資料を、目的別のフォルダに整理）
**使い方:** まず「目的別の入口」で、読む資料を選ぶ。全部の一覧は、下の「フォルダ別の一覧」。

> **フォルダの考え方:** 「**誰が、何のために読むか**」で分けています。**使う人**は `guides/`、**実証実験を運営する人**は `pilot/`、**動かし続ける人**は `operations/`、**作り・直す人**は `design/` と `learning/`、**経緯を知りたい人**は `reports/`、**言葉を引く人**は `reference/`。

---

## 目的別の入口

| こうしたい | 読む資料 |
|---|---|
| **初めて、全体を知りたい** | [ルートの README](../README.md) → [プロジェクト概要](design/project-overview.md) → [システムガイド](system-guide.html)（図で見る） |
| **使い方を知りたい**（Houdini パネル・チャット・管理画面） | [ツール取扱説明書](guides/user-manual.md)、チュートリアル生成は [取扱説明書（Houdini）](guides/manual-houdini-tutorial.md) |
| **Houdini が初めて** | [Houdini 初心者ガイド](guides/houdini-beginner-guide.md) |
| **動画生成を使いたい** | [RAGReel 取扱説明書](guides/manual-ragreel.md) |
| **Slack から質問したい** | [RAGボットの使い方](guides/slack-canvas-guide.md) |
| **実証実験を運営する** | [運営者向け手順書](pilot/operator-runbook.md) → [告知](pilot/pilot-announcement.md)・[分析設計](pilot/pilot-analysis-design.md) |
| **障害が起きた・日々の点検をする** | [運用手順書](operations/cloudflare-rag-operations-manual.md)、症状別は [保守の手順（障害記録つき）](learning/06-maintenance-runbook.md) |
| **費用・上限を知りたい** | [費用と利用枠](operations/cost-and-quota.md) |
| **仕組みを理解して、直す・足す人になりたい** | [講義シリーズ（全16回）](learning/lectures/README.md) → [座学資料](learning/README.md) |
| **設計の詳細を知りたい**（Cloudflare） | [Cloudflare RAG 技術解説書](design/cloudflare-rag-technical-report.md) |
| **言葉が分からない** | [用語集](reference/glossary.md)・[用語・技術解説](reference/terminology.md) |
| **セキュリティ・規約を確かめる** | [Worker の点検](operations/security-audit-2026-10-22.md)・[ライセンス](operations/license-compliance.md)・[隔離方針](operations/sandbox-policy.md) |

---

## フォルダ別の一覧

### `guides/` — 使い方

| 資料 | 内容 |
|---|---|
| [user-manual.md](guides/user-manual.md) | ツール取扱説明書（チャット・グラフ・管理画面・課題タブ・背景など。2026-10-17） |
| [manual-houdini-tutorial.md](guides/manual-houdini-tutorial.md) | Houdini チュートリアル生成パネルの取扱説明書 |
| [manual-ragreel.md](guides/manual-ragreel.md) | RAGReel（動画生成）の取扱説明書 |
| [houdini-beginner-guide.md](guides/houdini-beginner-guide.md) | Houdini の基礎知識とショートカットキー一覧 |
| [slack-canvas-guide.md](guides/slack-canvas-guide.md) | Slack の RAG ボットの使い方 |

### `pilot/` — 実証実験

| 資料 | 内容 |
|---|---|
| [operator-runbook.md](pilot/operator-runbook.md) | 運営者向け手順書（配布・課題の運営・デプロイ順序） |
| [pilot-announcement.md](pilot/pilot-announcement.md) | 参加者への告知（たたき台。データの扱い・FAQ） |
| [pilot-analysis-design.md](pilot/pilot-analysis-design.md) | 分析設計（ラテン方格・指標・集計・変更履歴） |
| [pilot-test-proposal.md](pilot/pilot-test-proposal.md) | ベータテスト・本格実証実験の実施提案書（2026-08-22） |
| [houdini21-learning-effect-study.md](pilot/houdini21-learning-effect-study.md) | 学習効果検証 A/B テストの実験設計（2026-08-06） |

### `operations/` — 運用・安全・規約

| 資料 | 内容 |
|---|---|
| [cloudflare-rag-operations-manual.md](operations/cloudflare-rag-operations-manual.md) | Cloudflare RAG の日常運用（同期・D1 の確認・障害対応） |
| [cost-and-quota.md](operations/cost-and-quota.md) | トークン・費用の見積もりと、配る量の決め方 |
| [security-audit-2026-10-22.md](operations/security-audit-2026-10-22.md) | Worker のセキュリティ点検 |
| [claude-token-security-report.md](operations/claude-token-security-report.md) | Claude API トークンのセキュリティ強化（予算制・自動回復） |
| [license-compliance.md](operations/license-compliance.md) | ライセンス・利用規約のコンプライアンス |
| [sandbox-policy.md](operations/sandbox-policy.md) | 実行環境の隔離方針（R4） |
| [AUTOMATION_RULES.md](operations/AUTOMATION_RULES.md) | 自動化の運用ルール（R8） |

### `design/` — 設計・仕様

| 資料 | 内容 |
|---|---|
| [project-overview.md](design/project-overview.md) | **プロジェクト概要**: 機能一覧・設計思想・ディレクトリ構成の詳細・CI |
| [cloud-rag.md](design/cloud-rag.md) | クラウド RAG 環境ガイド（設計・セットアップ） |
| [local-rag.md](design/local-rag.md) | ローカル RAG の統合ガイド |
| [cloudflare-rag-technical-report.md](design/cloudflare-rag-technical-report.md) | Cloudflare RAG の技術解説書（データフロー・修正したバグ） |
| [cloud-local-unification-plan.md](design/cloud-local-unification-plan.md) | Cloud/Local RAG の統合方針と移行設計 |
| [architecture-layering-plan.md](design/architecture-layering-plan.md) | 共通層・固有層の整理と、ライブラリ化・プラグイン化の設計案 |
| [content-generation.md](design/content-generation.md) | コンテンツ動的生成の設計（houdini21） |
| [content-generation-braintq.md](design/content-generation-braintq.md) | コンテンツ動的生成の設計（BrainTQ） |
| [houdini-tutorial-technical-report.md](design/houdini-tutorial-technical-report.md) | Houdini チュートリアル生成と動画生成の技術解説書 |
| [houdini-lesson-design.md](design/houdini-lesson-design.md) | チュートリアル生成を「レッスン」にする設計 |
| [houdini-video-script.md](design/houdini-video-script.md) | チュートリアル動画の台本と音声の改善 |
| [houdini-distribution-plan.md](design/houdini-distribution-plan.md) | チュートリアル・動画生成の配布計画 |
| [distribution-strategy.md](design/distribution-strategy.md) | 配布戦略の調査・提案書 |
| [mcp-integration-guide.md](design/mcp-integration-guide.md) | 外部サービス連携（公式 MCP）の選定と使い方 |
| [tidb-tikv-migration-design.md](design/tidb-tikv-migration-design.md) | TiDB Cloud / TiKV 移行設計書 |
| [ui-rules.md](design/ui-rules.md) | UI の決めごと表（`chatUi.ts`） |

### `reports/` — 調査・検証・報告

| 資料 | 内容 |
|---|---|
| [houdini21-tutorial-gen-report.md](reports/houdini21-tutorial-gen-report.md) | houdini21 チュートリアル自動生成の実機検証レポート |
| [model-strategy-report.md](reports/model-strategy-report.md) | モデル運用戦略と Google MCP 調査 |
| [improvement-report-2026-10.md](reports/improvement-report-2026-10.md) | 2026-10 の改善の実施報告 |
| [project-status-2026-08.md](reports/project-status-2026-08.md) | プロジェクトの現状整理（2026-08 時点） |
| [gas-feature-parity.md](reports/gas-feature-parity.md) | GAS 版から Cloudflare への移行の記録（GAS 版は廃止済み） |
| [cloudflare-vs-firebase-comparison.md](reports/cloudflare-vs-firebase-comparison.md) | Cloudflare と Firebase で作った場合の違い |
| [comparison-houdini-mcp.md](reports/comparison-houdini-mcp.md) | 他の Houdini × AI の道具との比較 |
| [new-project-ideas-borrowed-tech-2026-10.md](reports/new-project-ideas-borrowed-tech-2026-10.md) | 新規プロジェクト案と「他アプリから借りる技術」の調査 |
| [other-project-rag-integration-plan.md](reports/other-project-rag-integration-plan.md) | 別プロジェクトへの RAG 環境の統合計画 |
| [other-project-knowledge-features-backport.md](reports/other-project-knowledge-features-backport.md) | 別プロジェクトのナレッジ登録機能の逆輸入ガイド |
| [graduation-research-novelty-and-insights.md](reports/graduation-research-novelty-and-insights.md) | 卒業研究・論文執筆用メモ（比較・新規性） |

### `reference/` — 用語

| 資料 | 内容 |
|---|---|
| [glossary.md](reference/glossary.md) | 用語集（この資料群で使う言葉） |
| [terminology.md](reference/terminology.md) | 技術・用語の解説 |

### `learning/` — 学習資料

| 資料 | 内容 |
|---|---|
| [講義シリーズ（全16回）](learning/lectures/README.md) | 基礎から順に、図と演習で。第1〜10回＝仕組みと運用、第11〜16回＝アルゴリズムとスクリプト |
| [座学資料（01〜06）](learning/README.md) | 必要な知識を引く辞書（常識・基礎・専門・応用・Script・保守） |

### その他

| 場所 | 内容 |
|---|---|
| [images/](images/) | 構成図・流れ図（SVG）。`scripts/build_diagrams.py` で生成 |
| [system-guide.html](system-guide.html) | システムガイド（図でまとめたもの。`scripts/build_system_guide.py` で生成） |
| [../cloudflare-rag-poc/docs/](../cloudflare-rag-poc/docs/) | Worker 側の個別資料（MCP クライアント・使いやすさ・同期の統制・Google 連携） |
| `../IMPROVEMENT_*.md` | 改善の計画・設計（ルートに置いたまま。コードのコメントが、この名前で参照している） |
| `../lecture/` | 講義資料（HTML。クラウド RAG・ローカル RAG など） |

---

## この索引の保守

- **資料を足したら、この表に1行足す。** どのフォルダに置くかは、冒頭の「フォルダの考え方」で決める（迷ったら、**読む人**で選ぶ）。
- **`.md` が元です。** `.html` は `scripts/build_docs_html.py` が作る（直接直さない）。新しい資料を HTML にするときは、そのスクリプトの `DEFAULT_TARGETS` に足す。
- **ファイルを移したら、リンクが切れていないか確かめる**（第16回の点検スクリプトの見本が使えます）。
