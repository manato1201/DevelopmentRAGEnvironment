# 座学資料: AIなしでも保守・拡張できるようになるために

**作成日:** 2026-10-17
**目的:** このプロジェクト（RAG環境・Cloudflare Worker・Houdini/Unity連携）を、AIに頼らなくても**動かし続け、直し、機能を足せる**ようにする。
**対象:** 開発者本人、およびこのプロジェクトを引き継ぐ人。
**位置づけ:** 設計資料（`docs/`の他のファイル）は「何がどうなっているか」。この資料は「それを自分で読み書きするために、何を知っている必要があるか」。

> **2026-10-30 追加: [講義シリーズ（全16回）](lectures/README.md)。** 基礎（URL・DNS・HTTP）から順に、図を使って、このシステムを理解し、保守・拡張するまでを、演習つきで進める（第1〜10回）。さらに **Part 2（第11〜16回）で、アルゴリズム（検索・予算・グラフ・実験設計）とスクリプトを、数を入れて検算しながら**読む。**初めて読む人は、こちらから**。下の01〜06は、必要な知識を引く**辞書**として使う。

---

## 1. 構成（4段階 ＋ 手順）

| 段階 | 資料 | 中身 | 目安 |
|------|------|------|------|
| 常識 | [01-common-knowledge.md](01-common-knowledge.md) | OS・ネットワーク・データ形式・セキュリティ・Git・仕事の進め方・費用と上限 | 半日 |
| 基礎 | [02-fundamentals.md](02-fundamentals.md) | TypeScript・SQL/SQLite・Python・C#の読み方、開発環境、Cloudflareの基本 | 2〜3日 |
| 専門 | [03-specialized.md](03-specialized.md) | RAG、LLMのAPIとtool use、認証・OAuth、MCP、Cloudflare特有の制約、Houdini、Unity | 1〜2週間 |
| 応用 | [04-applied.md](04-applied.md) | このプロジェクトの設計パターン、機能を足す手順（レシピ）、テスト、デバッグ、リリース | 1週間 |
| Script | [05-scripts.md](05-scripts.md) | PowerShell/Bash/Pythonのスクリプト、`wrangler`、プロジェクトの`scripts/`の地図、安全な自動化 | 2〜3日 |
| 保守 | [06-maintenance-runbook.md](06-maintenance-runbook.md) | 日次・週次・月次の点検、症状別の切り分け、実際に起きた障害の復旧記録 | 随時参照 |

関連: 用語は[glossary.md](../reference/glossary.md)・[terminology.md](../reference/terminology.md)、構造は[architecture-layering-plan.md](../design/architecture-layering-plan.md)、使い方は[user-manual.md](../guides/user-manual.md)、運用は[cloudflare-rag-operations-manual.md](../operations/cloudflare-rag-operations-manual.md)。

### 講義シリーズとの対応

| 講義 | 深掘り先（辞書） |
|---|---|
| [第1回 インターネットの基礎](lectures/01-internet.md) | [01 常識](01-common-knowledge.md) |
| [第2回 Cloudflare の基礎](lectures/02-cloudflare.md) | [02 基礎](02-fundamentals.md)・[03 専門 §5](03-specialized.md) |
| [第3回 データベースと SQL](lectures/03-database.md) | [02 基礎（SQL）](02-fundamentals.md) |
| [第4回 RAG と AI の API](lectures/04-rag-and-ai.md) | [03 専門](03-specialized.md) |
| [第5回 Worker のコードを読む](lectures/05-worker-code.md) | [04 応用](04-applied.md) |
| [第6回 Houdini パネルのコードを読む](lectures/06-houdini-panel.md) | [03 専門 §7](03-specialized.md)・[04 応用](04-applied.md) |
| [第7回 Web 画面の仕組み](lectures/07-web-ui.md) | [04 応用 レシピE](04-applied.md#レシピe-管理画面にカードを足す) |
| [第8回 機能を足す通し演習](lectures/08-add-a-feature.md) | [04 応用](04-applied.md) |
| [第9回 テスト・デプロイ・運用](lectures/09-test-deploy-operate.md) | [05 Script](05-scripts.md)・[06 保守](06-maintenance-runbook.md) |
| [第10回 トラブルシュートと総合演習](lectures/10-troubleshooting.md) | [06 保守](06-maintenance-runbook.md) |
| [第11回 アルゴリズムの読み方・書き方](lectures/11-algorithm-basics.md) | [02 基礎](02-fundamentals.md) |
| [第12回 検索のアルゴリズム](lectures/12-search-algorithms.md) | [03 専門（RAG）](03-specialized.md) |
| [第13回 制御のアルゴリズム](lectures/13-control-algorithms.md) | [01 常識（費用と上限）](01-common-knowledge.md)・[03 専門](03-specialized.md) |
| [第14回 グラフのアルゴリズム](lectures/14-graph-algorithms.md) | [03 専門 §7（Houdini）](03-specialized.md) |
| [第15回 実験設計と習熟度の数式](lectures/15-experiment-and-growth.md) | [04 応用](04-applied.md) |
| [第16回 スクリプトを読み・書く](lectures/16-scripts.md) | [05 Script](05-scripts.md) |

## 2. 目的別の学習パス

| やりたいこと | 読む順番 | ここまで読めば |
|---|---|---|
| **止まったときに、直せる**（運用のみ） | 01 → 06 → 05（wranglerの節） → 02（SQLの節） | 症状から原因を切り分け、D1の中身を確認し、復旧できる |
| **機能を足せる**（保守開発） | 01 → 02 → 04 → 03（必要な章） → 05 | 新しいAPI・連携・画面を、レシピに沿って追加できる |
| **設計を変えられる**（アーキテクト） | すべて ＋ [architecture-layering-plan.md](../design/architecture-layering-plan.md) | 層の分け方・契約・移行の順序を、自分で判断できる |
| **Houdini側だけ触る** | 01 → 02（Python） → 03（Houdini・LLM） → 04（Houdiniツール追加） | チュートリアル生成のツールを足し、挙動を調整できる |

## 3. 学び方のルール

1. **読むだけで終わらせない。** 各章の「練習」は、実際にこのリポジトリのファイルを開いて答える形になっている。答えは章末の「ヒント」で確認する（答えそのものは書かない。コードに書いてある）。
2. **本番に触れない。** 練習は、ローカルの開発用DB（`--remote`を付けない）と、読み取り専用のコマンドだけで行う。`--remote`を付けるのは、本番を見たいと決めたときだけ。
3. **分からなくなったら、コードより先にエラーメッセージを読む。** このプロジェクトのエラーは、日本語で原因と対処を出すように作ってある。
4. **変更は小さく、1つずつ。** 1回の変更で複数の問題を直そうとしない。
5. **「なぜそうなっているか」を探す。** コード内のコメントには、実際に起きた問題と、その対策の経緯が書いてある。設計を変える前に、そのコメントを読む。

## 4. 到達度チェックリスト

自己採点用。✔が付けば、その段階は終わり。

**常識**
- [ ] HTTPのステータスコード（200/401/403/404/429/500/503）の意味を説明できる
- [ ] `Unexpected token '<'` というエラーが、なぜ出るのかを説明できる
- [ ] APIキーを、どこに置いてはいけないか言える
- [ ] 無料枠の上限に達したとき、何が起きるかを説明できる

**基礎**
- [ ] `src/http.ts` と `src/chunking.ts` を読んで、何をしているか説明できる
- [ ] `migrations/` の任意のSQLを読んで、表の構造を説明できる
- [ ] `async/await` と `Promise` の違いを説明できる
- [ ] `wrangler d1 execute`で、本番とローカルを間違えずに使い分けられる

**専門**
- [ ] 検索の流れ（質問 → 埋め込み → ベクトル検索＋FTS → 統合 → 回答）を、図に描ける
- [ ] OAuthのAuthorization Code＋PKCEの流れを説明できる
- [ ] tool useのループ（`tutorial_agent.py`）を、擬似コードで書ける
- [ ] D1の「読み取り行数」が増える原因を、3つ挙げられる

**応用**
- [ ] 新しいAPIルート（権限つき）を、レシピに沿って追加できる
- [ ] 新しいマイグレーションを書き、ローカルで適用して確かめられる
- [ ] リリースの手順（型チェック → マイグレーション → デプロイ → 動作確認）を、順序の理由つきで説明できる

**Script**
- [ ] PowerShellとBashの違い（変数・クォート・パス）を3つ挙げられる
- [ ] 「確認なしで本番を変更するコマンド」を、なぜ避けるのか説明できる

**保守**
- [ ] 「全APIが500を返す」ときの切り分けを、手順どおりに行える
- [ ] 本番のD1の状態を、書き換えずに確認できる

## 5. この資料の保守

- コードを変えたら、関連する章の「このプロジェクトでは」の節を更新する。更新日を各章の先頭に書く。
- 新しい障害が起きたら、[06-maintenance-runbook.md](06-maintenance-runbook.md)の「障害記録」に1件足す（原因・症状・復旧手順・再発防止）。**一番価値が高いのは、この記録。**
- 事実が変わりやすいもの（無料枠の数字、各サービスの画面・仕様）は、本文では「2026-10時点」と書き、公式ページへのリンクを添える。数字は古くなる前提で読む。
