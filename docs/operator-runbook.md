# 運営者向け手順書（実証実験の運営）

**対象:** サーバー（Cloudflare）と、テスターの鍵・予算を管理する人 ／ **版:** 2026-10-21

テスター向けの説明は [manual-houdini-tutorial.md](manual-houdini-tutorial.md) と [manual-ragreel.md](manual-ragreel.md)、費用の根拠は [cost-and-quota.md](cost-and-quota.md) にあります。

## 1. 全体の構成

[![システム全体の構成](images/01-system-overview.svg)](images/01-system-overview.svg)

*図: システム全体の構成。手元の Houdini とパネル、Cloudflare の Worker、外部の AI・サービスの関係。*

```
テスターのPC                         あなたのCloudflare（Worker）                 外部サービス
Houdini パネル ──(鍵)──▶ /claude/messages ─────────────────────────────▶ Anthropic（Claude）
                 ──(鍵)──▶ /search（検索）──▶ D1（全文検索）+ Vectorize ──▶ Gemini（埋め込み・仮の回答）
RAGReel（動画） ──(鍵)──▶ /tts ───────────────────────────────────────▶ Google Cloud Text-to-Speech
Houdini パネル ──(鍵)──▶ /tutorial-feedback/submit（評価）──▶ D1
```

- **配るもの:** Houdini パネル（zip）と、RAGReel（インストーラー）だけです。Cloudflare は配りません。
- **鍵:** テスターは、**あなたが発行した API キー1つ**だけを持ちます。Anthropic・Google・Gemini の鍵は、**Worker のシークレット**にあり、テスターには渡りません。
- **費用の上限:** Claude は**鍵ごとの予算**、音声は**鍵ごと・全体の1日の文字数**で、サーバー側が止めます（クライアントでは回避できません）。

## 2. 実証実験の前にやること（チェックリスト）

| # | 作業 | 状態の確認方法 |
|---|---|---|
| 1 | **Workers Paid に切り替える**（月 $5）。ダッシュボード → Workers & Pages → Plans | 済 |
| 2 | **Cloudflare の課金アラート**を作る（例: $10） | ダッシュボード → Billing → Notifications |
| 3 | **Google Cloud の音声合成**: API を有効化し、**鍵を作り、「Cloud Text-to-Speech API だけ」に制限**する。割り当て（クォータ）で、1日の文字数を下げる。予算アラートを作る（アラートは通知のみ。**止まりません**） | `npx wrangler secret list` に `GOOGLE_TTS_API_KEY`（済） |
| 4 | **Worker のシークレット**が揃っているか | `npx wrangler secret list`: `ANTHROPIC_API_KEY`、`GEMINI_API_KEY`、`GOOGLE_TTS_API_KEY` ほか |
| 5 | **最新の Worker をデプロイ**し、マイグレーションを適用する | §6 |
| 6 | **Houdini 公式ドキュメントを登録**する（章の見出しつき） | §5 |
| 7 | **自分で1本通しで試す**（生成 → 動画 → 評価）。品質チェックの点数、動画の音声、プログレスバーを確認 | — |
| 8 | **テスターの鍵を発行**（§3） | 管理画面 |
| 9 | **配布物を作る**（§7）と、同意書・質問票の準備（学生は、先生との相談後） | — |

## 3. テスターの鍵を発行する

管理画面 →「ユーザー・権限」→「新しいAPIキーを発行」。

| 項目 | 設定 |
|---|---|
| 名前 | 匿名のID（例: `tester-e01`（企業）、`tester-s01`（学生））。**個人名は入れない**（学生の評価は匿名で扱うため） |
| ロール | `member`（質問・生成・評価を使える最小限）。**admin にしない** |
| アクセスできる namespace | `shared:houdini22`（と、使う版 `shared:houdini21`）。**他の知識（社内資料など）は、含めない** |
| RAG 予算 | 既定のままでよい（検索の回数の上限） |
| **Claude 予算** | **420,000 トークン**（チュートリアル＋動画の台本 10回分に、5割の余裕と、先確保の余裕を足した値。根拠は [cost-and-quota.md](cost-and-quota.md)） |
| 有効期限 | 実験の終了日（例: 8週間後） |

- **生のキーは、発行の画面で一度しか見られません。** コピーして、すぐ本人に渡します。メールで送るときは、**URL と別の経路**で（例: URL はメール、キーは別のチャット）。
- 追加でチャージするとき: 「予算」で上限を上げる（`/admin/keys/charge`）。
- やめてもらうとき: 「失効」または「削除」。**削除すると、その人の個人用の資料・履歴・評価の紐づけも消えます。**
- **音声**は、鍵ごとに1日 50,000 文字（既定）、全体で1日 300,000 文字（既定）が上限です。変えるときは、Worker の変数 `TTS_DAILY_CHARS_PER_KEY`・`TTS_DAILY_CHARS_GLOBAL` を設定してデプロイします。

## 4. 日々の見守り

| 見るもの | 場所 | 目安 |
|---|---|---|
| Claude の使用量・推定費用 | 管理 → 利用状況・コスト | 鍵ごとの使用が、予算の8割に近い人に連絡 |
| 評価（👍👎・タグ・点数） | 管理 → Houdiniチュートリアルの評価（CSV 出力あり） | `lesson_score`（レッスン品質点数）と評価を突き合わせる |
| 音声の使用量 | D1 の `tts_usage` 表（日・鍵ごとの文字数） | 全体の上限の8割で、原因を確認 |
| D1 の読み取り・書き込み | Cloudflare ダッシュボード → D1 → Metrics | 有料では、込み分（読み取り 250億行／月、書き込み 5,000万行／月）に遠く及ばない |
| ヘルスチェック | 管理 → システム | 30分ごとに自動。異常は Slack／Gmail で通知 |

```bash
npx wrangler d1 execute rag-poc-db --remote --command "SELECT day, user_id, chars FROM tts_usage ORDER BY day DESC LIMIT 20"
```

## 5. Houdini 公式ドキュメントの登録（約2,000ページ）

### 5.1 方針（なぜこうするか）

同名のノード（Transform / Merge / Null …）が、SOP・VOP・DOP・LOP・APEX などの章に別々にあります。章の情報が無いと、**後から登録した章が、先のものを上書き**し、検索でも別の章の説明が混ざります。そこで、次のようにしています。

- **namespace は分けません**（切り替え不要）。
- URL から章（SOP / VOP / …）を決め、**本文の先頭に見出し**（`【Houdini 22 / SOP / merge】`）を入れ、**ファイル名にも章**を付けます（`Merge [SOP]`）。
- 検索では、質問に「SOPで」などの指定があるときだけ、その章の結果を先に並べます（除外はしません）。指定が無く、同名ノードが複数の章にあるときは、**既定（SOP）で答え、他の章があることを1行添えます。**

### 5.2 手順

1. **バックアップ:** 管理 → システム →「設定バックアップ」の「エクスポート」。（ナレッジ本文は含まれません。本文は、再クロールで作り直せます。）
2. **最新の Worker をデプロイ**（§6）。マイグレーションがあるときは、先に適用。
3. **少数のページで試す:** ナレッジ登録 → サイトのクロール。
   - 起点: `https://www.sidefx.com/docs/houdini/nodes/sop/index.html`
   - 登録先: `shared:houdini22`、階層 1、最大ページ数 5〜10。
   - 確認: 「登録済みナレッジ」に `Merge [SOP]` のような名前で並ぶこと。チャンクの先頭に `【Houdini 22 / SOP / …】` があること。**本文の先頭に `window.dataLayer`（解析のスクリプト）が無い**こと。
4. **本番の登録:** 章ごとに、起点を変えて実行します（ノードの一覧のページ）。

   | 章 | 起点（例） |
   |---|---|
   | SOP | `https://www.sidefx.com/docs/houdini/nodes/sop/index.html` |
   | VOP | `…/nodes/vop/index.html` |
   | DOP | `…/nodes/dop/index.html` |
   | LOP | `…/nodes/lop/index.html` |
   | COP | `…/nodes/cop/index.html` |
   | APEX | `…/nodes/apex/index.html` |
   | その他（OBJ・TOP・CHOP・out・VEX 関数 `…/vex/functions/`） | 同様 |

   **起点の URL は例です。実際の目次ページの URL を、ブラウザで確認してから使ってください**（ページの作りが変わっていることがあります）。パスの絞り込み（pathPrefix）に、章のパス（例: `/docs/houdini/nodes/sop/`）を入れると、他の章へ流れません。**止まったときは、同じ操作をやり直す**と、続きから再開します。
5. **古い登録は、自動で置き換わります。** 見出しの無い旧形式の登録（`Merge` など）は、章つきの名前で登録し直すときに、1回だけ削除されます。同じページを再実行しても、二重になりません。
6. **確認:** 同名ノードの質問（例:「Transform の使い方」）で、答えに「前提: SOP の場合」が付くこと。「VOP の Transform」と書くと、VOP の説明になること。
7. **定期の再クロール**（任意）: 有効にしたものだけ動きます。見出しの版が変わったときは、次の再クロールで、全ページが登録し直されます。

### 5.3 費用と時間の目安

- 約2,000ページ → 約1.2万チャンク。**Gemini の埋め込みで約 $1 未満**（無料枠なら $0）。
- Cloudflare は、込み分の範囲（書き込み 約24万行）。
- 時間: 1ページあたり数秒。1回の呼び出しは、時間の予算の範囲で少しずつ進みます。**数時間のつもり**で。

### 5.4 注意

- **著作権・利用規約:** 公式ドキュメントを、テスターが使う検索の知識として載せることの可否は、SideFX の利用規約を確認してください（`docs/license-compliance.md`）。回答には、引用の番号と、元のファイル名が出ます。
- 登録済みの旧形式のページ（解析のスクリプトが混ざったもの）は、再クロールで直ります。**直るまでは、検索の質が低め**です。

## 6. Worker の更新（デプロイ）

```bash
cd cloudflare-rag-poc
npm run typecheck && npm test                  # 型と、自動テスト（偽のD1・偽の外部API。本番には繋がらない）
npx wrangler d1 migrations list rag-poc-db --remote     # 保留中のマイグレーションを確認
npm run db:migrate:remote                       # あれば適用
npx wrangler deploy
```

- マイグレーションは、**一覧 → 中身を読む → 適用 → もう一度一覧**の順で。
- 今回の変更（`/tts`、章の見出し・検索の補正）は、**既存のデータを書き換えません**（再クロールするまで、既存の検索は従来どおりです）。
- シークレットの登録: `npx wrangler secret put <名前>`（値は、画面に出ません）。

### 6.1 実証実験の「課題」の機能を出すとき（マイグレーション 0035・0036）

| 手順 | 内容 |
|---|---|
| 1 | `npx wrangler d1 migrations list rag-poc-db --remote` で、**0035（課題の記録）・0036（やり直し）**が保留中か確認する |
| 2 | 中身を読む（0035: `pilot_profile`・`pilot_sessions` を作る ／ 0036: `discarded_at`・`paused_sec` の列と、部分一意索引） |
| 3 | `npm run db:migrate:remote` で適用 → もう一度一覧 → 列の存在を確認する |
| 4 | `npx wrangler deploy`（**表を先、Worker を後**。逆だと、新しい Worker が、まだ無い列を読んで失敗する） |
| 5 | 疎通: 鍵なしで `/pilot/plan`・`/pilot/session/reset`・`/admin/pilot/tasks` を呼び、**401**（認証が効いている）になること。**404 なら、Worker が古い** |
| 6 | Houdini パネルを配る（`deploy_panels.py`）。**Worker より先に配ると、参加者の画面に「サーバーが、この機能にまだ対応していません」と出る** |

- 運営（admin）のテストは、参加者番号を取らず、集計に入りません。**割り当ては、一律で番号 1 の順序**になります（実際の参加者は、登録順に 1・2・3 を繰り返します）。
- 参加者が「やり直す」で破棄した記録は、消えずに残ります（D1 の `pilot_sessions.discarded_at`）。集計には入りません。消去の依頼を受けたときの扱いは、[pilot-announcement.md](pilot-announcement.md) の確認事項を参照。
- 変更の標準の流れは [図16](images/16-change-flow.svg)。

## 7. 配布物を作る

[![配布と、キー・予算の管理](images/06-distribution.svg)](images/06-distribution.svg)

*図: 配布と、キー・予算の管理。運営が配り、鍵と予算は運営の Worker で管理する。*

| 配布物 | 作り方 | 渡し方 |
|---|---|---|
| **Houdini パネル（zip）** | `uv run python scripts/build_houdini_package.py --version <版>` → `dist/RAGReelTutorial-<版>.zip` | zip のまま |
| **RAGReel（インストーラー）** | RAGReel リポジトリで、ビルド後に `installer\ragreel.iss` を Inno Setup でコンパイル → `installer\Output\RAGReel-Setup-<版>.exe` | exe のまま（未署名のため、初回に Windows の警告が出ます。[manual-ragreel.md](manual-ragreel.md) §2） |
| 説明書 | [manual-houdini-tutorial.md](manual-houdini-tutorial.md)、[manual-ragreel.md](manual-ragreel.md) | PDF または HTML（`scripts/build_docs_html.py`） |
| **接続先 URL と API キー** | §3 | **別の経路**で |

**配布前の通しのテスト（必須）:** 自分の別のPC、または新しい Windows ユーザーで、zip → `install.cmd` → Houdini でパネル表示 → 生成 → 動画 まで確認してください。

## 8. 実験の終了・後片付け

1. 鍵を**失効**（または期限切れに）。
2. 評価のデータを、CSV で出力して保存。
3. 学生の評価・利用記録は、同意の範囲で扱い、**匿名のIDのまま**集計。
4. 不要になった鍵を削除。Google・Gemini・Anthropic の鍵は、必要なら**ローテーション**（作り直して、Worker のシークレットを更新）。

## 9. 困ったとき

| 症状 | 原因と対処 |
|---|---|
| テスターが、429（予算の上限）になる | 鍵の予算を確認。**残りが、1回の呼び出しの先確保（約4万）より少ないと、実際は足りていても 429 になります。** 上限を上げる。 |
| 音声が従来の声になる | `GOOGLE_TTS_API_KEY` の設定、Google 側の API の有効化・鍵の制限、1日の上限（`tts_usage`）を確認。 |
| `/tts` が 403（error code: 1010） | クライアントの User-Agent が、Cloudflare に弾かれています（Python 標準の `urllib` など）。動画エンジンと配布スクリプトは、対応済みです。 |
| D1 の「Rows read」が、急に増えた | 無料プランでは、1日 500万行で止まります。有料では、込み分が大きく、通常は起きません。全文検索の全件走査を避ける仕組み（`chunk_rows`、`stats_cache`）は入っています。 |
| 登録したページの先頭に解析のスクリプト | 旧形式の登録です。再クロールで直ります（§5）。 |
