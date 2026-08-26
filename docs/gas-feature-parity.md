# GAS Cloud RAG → Cloudflare POC 機能パリティ一覧

**作成日:** 2026-08-23
**位置づけ:** [scripts/gas_cloud_rag.js](../scripts/gas_cloud_rag.js)（約3,450行・100関数超）が持つ全機能を棚卸しし、[cloudflare-rag-poc/](../cloudflare-rag-poc/)側の実装状況を追跡する。「どんどん機能を入れて最終的にGASと同等以上にする」という方針の進捗管理表。

**運用ルール:** 機能を追加したら都度このファイルのチェックを更新する。まだ着手していない項目に架空の実装状況を書かない。

---

## 1. コア検索・回答生成

| 機能 | GAS側 | POC状況 |
|---|---|---|
| ハイブリッド検索（ベクトル＋BM25をRRFで統合） | `_bm25SearchCandidates_` / `searchByEmbedding_` / `_rrfMerge_` | ✅ 実装済み（D1 FTS5 trigram + Vectorize、`src/hybrid.ts`） |
| HyDE（仮回答を先に生成してから検索） | `hydeExpand_` | ✅ 実装済み（`src/embeddings.ts` `hydeExpand`） |
| 最終回答生成（LLMによるチャット応答） | `ragQueryInternal_` | ✅ 実装済み（`/query`、Gemini生成） |
| 引用率算出（ハルシネーション対策） | `parseExtractionRate_` | ✅ 実装済み（`/query`の`extractionRate`） |
| namespace単位のアクセス制御 | `getNamespacesForKey` 等 | ✅ 実装済み（`src/auth.ts`） |
| 個別DBに絞った検索（検索精度向上） | GAS版チャットUIのDB選択ドロップダウン相当 | ✅ 実装済み（2026-08-26、`POST /query`に`namespaces`パラメータ追加、`POST /me/namespaces`で一般ユーザーも自分の許可namespace一覧を取得可能に）。チャットUIに「🌐全DB横断検索」＋個別DBのドロップダウンを追加。実データで動作確認済み（`shared:cedecnotes`に絞ると他DBの結果が混ざらないことを確認） |
| レベルフィルタ（Phase1レベリング basic/applied/advanced） | `_filter_groups_by_level`相当 | ✅ 実装済み |
| ベクトル圧縮・近似候補選定（`_packSignature_`/ハミング距離） | `_vectorCandidatesFor_` | 対象外（Vectorizeが同等の役割を代替するため移植不要） |

## 2. セキュリティ・利用管理

| 機能 | GAS側 | POC状況 |
|---|---|---|
| APIキー認証（ハッシュ化） | `validateApiKey_` / `_hashApiKey_` | ✅ 実装済み（SHA-256、`src/auth.ts`） |
| トークン予算管理（RAG用） | `_hasQuotaRemaining_` / `_consumeKeyBudget_` | ✅ 実装済み（`src/budget.ts`、`/search`・`/query`双方で強制） |
| トークン予算管理（Claude用） | `_hasClaudeQuotaRemaining_` / `_consumeClaudeBudget_` | ⚠️ テーブル(`token_budgets`)はあるが、Claude呼び出し自体が未実装のため未使用 |
| レート制限 | `isRateLimited_` | ✅ 実装済み（2026-08-26、`src/rateLimit.ts`）。専用テーブルは追加せず、既存`audit_log`の直近件数を数える固定ウィンドウ方式（60秒間に30回まで）。`/search`・`/query`双方に適用、超過時は429を返す |
| 監査ログ（クエリのSHA-256ハッシュ化記録） | `RAGAuditLogger`相当 | ✅ 実装済み（D1 `audit_log`テーブル） |
| ヘルスチェック・アラート | `checkHealthAndAlert_` / `sendHealthAlert_` | ✅ 実装済み・**Slack/Gmail両方とも実際に通知の送受信まで確認済み**（2026-08-26、`src/healthCheck.ts`）。D1接続・直近1時間のKB同期エラー・トークン予算枯渇間近を検知し、Slack（Incoming Webhook）・Gmail（個人アカウントのOAuthリフレッシュトークン方式、`src/gmailOAuth.ts`）へアラート送信。30分ごとのCron Triggerで自動実行、手動実行用の`POST /admin/health/check`とテスト通知用の`POST /admin/health/test-alert`も用意。**当初はサービスアカウント＋Domain-Wide Delegation方式で実装したが、これはGoogle Workspace限定の機能で個人のgmail.comアカウントでは設定できないと判明し、OAuthリフレッシュトークン方式に切り替えた**（GCPプロジェクトでGmail APIの有効化も別途必要だった） |

## 3. 知識ベース管理（ingestion pipeline）

| 機能 | GAS側 | POC状況 |
|---|---|---|
| Notion同期 | `syncNotionToSheets` | ✅ 実装済み・**複数の実データベースで動作確認済み**（2026-08-25）。Houdini21（80ページ・133チャンク）、CEDECNOTES（40ページ・385チャンク）、tool_docs（1ページ・11チャンク）を完全同期。GAME_INFO/HOUDINI22/RESEARCH/TEAM_NOTESは接続確認済みだが中身が空（0ページ）。バッチ処理（`startIndex`/`batchSize`/`opId`）対応、VectorizeベクトルIDのハッシュ化対応、大きいページが混在する場合は`batchSize`を下げて再実行する運用を確立（下記トラブルシューティング参照） |
| Google Drive同期 | `syncDriveToSheets` / `extractDriveFileText_` | ✅ 実装済み・**実データで動作確認済み**（2026-08-26）。サービスアカウント認証（GCPの`iam.disableServiceAccountKeyCreation`組織ポリシーに一度阻まれたが、正しいプロジェクト・大文字小文字を修正して解決）で実際のDriveフォルダを同期し、houdini22で8ドキュメント・67チャンクを登録。Googleドキュメント（ネイティブ）・プレーンテキスト/Markdown・PDF・DOCX・PPTX・音声/動画に対応（PDF/DOCX/PPTX変換の追加は同日）。cedecnotesフォルダの実データでPDF/PPTX変換まで動作確認済み。同期中に1件だけ原因不明の`VECTOR_UPSERT_ERROR`に遭遇し、該当チャンクだけスキップして続行する耐性を追加した |
| チャンク分割 | `chunkText_` | ✅ 実装済み（`src/chunking.ts`、スライディングウィンドウ方式） |
| URL手動登録 | `adminKbImportUrl` | ✅ 実装済み（2026-08-26、`POST /admin/kb/import-url`、`src/urlImport.ts`）。Workers組み込みのHTMLRewriterでscript/style除去＋テキスト抽出。実際にCloudflare Docsのページで45チャンク登録・ロールバックまで動作確認済み |
| QA CSV一括登録 | `adminKbImportQaCsv` / `kbBulkImportQaPairs_` | ✅ 実装済み（2026-08-26、`POST /admin/kb/import-qa-csv`、`src/qaImport.ts`）。RFC4180簡易パーサ＋Notion/Drive同期と同じバッチ処理方式。動作確認済み |
| YouTube文字起こし登録 | `adminKbImportYoutube` | ✅ 実装済み（2026-08-26、`POST /admin/kb/import-youtube`、`src/mediaTranscribe.ts`）。GeminiがYouTube URLを直接fileDataとして受け付けるため、ダウンロード不要 |
| ドキュメントアップロード（音声/動画の文字起こし含む） | `adminKbUploadDoc` / `_transcribeAudioVideoBlob_` | ✅ 実装済み（2026-08-26、`POST /admin/kb/upload-doc`、`src/geminiFile.ts`）。Gemini File APIへアップロード→ACTIVE待ち→文字起こし→削除、の流れ |
| PDF/Word/PowerPoint変換 | `_convertBinaryBlobToText_` | ✅ 実装済み（2026-08-26、`src/docExtract.ts`）。PDFはGeminiのネイティブ文書理解（小さければインライン、大きければFile API）、DOCX/PPTXは自前の最小限ZIPパーサ＋XMLタグ除去。実際のCEDEC発表資料（PDF/PPTX）で検証済み。20MB超のPPTXなど一部大きいファイルはWorkers側のメモリ上限でスキップされることがある（下記トラブルシューティング参照） |
| KB操作履歴 | `adminKbHistory` | ✅ 実装済み（`POST /admin/kb/history`、`kb_log`テーブル）。管理タブでopId列も表示するようにした |
| KBロールバック | `adminKbRollback` | ✅ 実装済み（2026-08-26、`POST /admin/kb/rollback`、`src/kbRollback.ts`）。opId単位でchunks_fts・Vectorize双方から削除。実データで動作確認済み |
| namespaceごとの同期元設定 | `adminSetNotionDbId` / `adminSetDriveFolder` | ✅ 実装済み（`POST /admin/kb/set-source`、`kb_sources`テーブル） |

## 4. API・モデル連携

| 機能 | GAS側 | POC状況 |
|---|---|---|
| Gemini embedding | `embed_` | ✅ 実装済み（`gemini-embedding-001`、768次元） |
| Gemini生成 | `callGemini_` | ✅ 実装済み（`gemini-flash-latest`） |
| Claude APIプロキシ（Houdiniチュートリアル生成用） | `callClaudeProxy_` | ✅ 実装済み（2026-08-26、`POST /claude/messages`、`src/claude.ts`、`@anthropic-ai/sdk`使用）。**2026-08-24時点では「RAGには不要」として対象外にしていたが、実際には`houdini/python_panels/tutorial_agent.py`（Houdiniチュートリアル生成エージェント）がGAS経由でClaude Messages APIを呼んでいたことが判明し、その移行先として追加した**（RAG自体は引き続きGemini/`/query`・`/search`のみで、Claude統合はこのHoudiniエージェント専用）。GAS版と同じ「生のAPIキーをクライアントに持たせず、サーバー側がトークン予算を強制する」設計を踏襲（`token_budgets`の`budget_type='claude'`を使用）。`tutorial_agent.py`側に`claude_backend`（"gas"｜"cloudflare"）・`rag_mode`への"cloudflare"追加で両対応、既定値は既存動作を変えない"gas"のまま。**RAG検索・Claude呼び出し（ツール実行含む）ともに実際にエンドツーエンドで動作確認済み**（2026-08-26。基本応答・ツール呼び出し・トークン予算記録すべて確認）。Houdini実機での`tutorial_agent.py`統合自体は未検証（Houdiniが無い環境での作業のため。Python構文チェックのみ通過済み） |
| 画像/音声/動画のGemini File API連携 | `_uploadBytesToGeminiFile_` / `_transcribeAudioVideoBlob_` | ✅ 実装済み（2026-08-26、`src/geminiFile.ts`）。音声/動画の文字起こし・大きいPDFの変換に使用。画像自体の説明生成は未実装（用途が無いため） |

## 5. 管理機能（Admin API）

| 機能 | GAS側 | POC状況 |
|---|---|---|
| APIキー発行・削除・更新 | `adminCreateKey` / `adminDeleteKey` / `adminUpdateKey` | ✅ 実装済み（`src/keyAdmin.ts`。発行時のみ生キーを返し、以後はハッシュのみ保持） |
| APIキー容量設定・チャージ | `adminSetKeyCapacity` / `adminChargeKeyBalance` | ✅ 実装済み（自動リセット間隔の指定にも対応。Cron Triggerを使わない遅延評価方式） |
| namespace管理（作成・一覧・削除） | `adminListNamespaces` / `adminCreateNamespace` | ✅ 実装済み（`src/namespaceAdmin.ts`。更新は未実装、作成・一覧・削除のみ） |
| キーごとのnamespaceアクセス制御 | `allowed_namespaces`（キー単位の許可リスト） | ✅ 実装済み（`key_namespace_grants`テーブル。旧実装は「全ユーザーが全shared namespace閲覧可」という簡略版だったため、GAS本来の設計に合わせて厳格化した） |
| 利用統計（トークン使用量ダッシュボード用） | `adminTokenUsageStats` / `adminClaudeUsageStats` | ✅ 実装済み（2026-08-25、`POST /admin/usage/stats`＋管理タブの棒グラフ・ユーザー別テーブル・キーごとの使用率ドーナツ表示）。日次集計のため`audit_log`に`tokens_used`列を追加（`migrations/0006_usage_tracking.sql`） |
| 評価統計（ユーザー評価の集計） | `adminRatingStats` | ✅ 実装済み（2026-08-26、`POST /admin/rating-stats`）。既存`memory`テーブルの`rating`列を集計するだけなので追加スキーマ不要 |
| バックアップ | `backupCriticalData_` / `adminBackupNow` | ✅ 実装済み（2026-08-26、`POST /admin/backup/export`、`src/backup.ts`）。users/namespaces/kb_sources/token_budgets/key_namespace_grantsをJSONスナップショットとしてエクスポート（管理タブからダウンロード可能）。チャット履歴本文・ベクトルデータ等の実データはD1の自動バックアップに任せ対象外としている |

## 6. メモリ・チャット履歴

| 機能 | GAS側 | POC状況 |
|---|---|---|
| チャット履歴保存 | `saveMemory_` | ✅ 実装済み（`src/memory.ts`、`/query`成功時に自動保存） |
| チャット履歴一覧 | `getUserMemory` | ✅ 実装済み（`POST /memory/list`） |
| 履歴の評価（役に立った/立たなかった） | `rateMemoryEntry` | ✅ 実装済み（`POST /memory/rate`） |
| チャット履歴検索（RAG検索への統合） | `searchMemory_` | ❌ 未実装（過去の会話を検索コンテキストとして再利用する機能。現状は保存・一覧・評価のみ） |
| 期限切れ履歴の自動削除 | `purgeExpiredMemory_` | ✅ 実装済み（2026-08-26、`wrangler.jsonc`のCron Trigger、毎日UTC 3時に90日以上前の`memory`行を削除。`src/index.ts`の`scheduled`ハンドラ） |

## 7. UI

| 機能 | GAS側 | POC状況 |
|---|---|---|
| Webチャット画面（チャットタブ） | `getChatHtml_`（約1,700行の内蔵HTML） | ✅ 実装済み（`GET /`、`src/chatUi.ts`）。APIキー入力・レベル選択・出典引用率表示・評価ボタン・履歴読み込みに対応 |
| タブ構成（チャット／グラフ／履歴／管理） | GAS版UIの画面構成 | ✅ 実装済み（2026-08-25、`src/chatUi.ts`全面刷新）。4タブ切り替えのSPA構成に |
| グラフ表示（namespace横断の知識関係の可視化） | `buildGraphData_` / `getGraphDataWithKey` | ✅ 実装済み（`POST /graph`、`src/graph.ts`）。各ファイルの先頭チャンクのベクトルを1回のバッチ`getByIds`で取得しWorker内でコサイン類似度計算→エッジ生成。クライアント側はThree.js（CDN読み込み）による3D力学レイアウト＋OrbitControls（回転/ズーム）＋ノードクリックでType/Size/適用日時/接続数/隣接ノード一覧を表示する詳細パネル。Obsidian Graph View相当の操作性（反発力/結集力スライダーによるライブ調整、再生/停止トグル、namespace＝DBごとの表示切替チェックボックス、固定パレットによる色分け凡例）を追加（2026-08-25）。実データ（Houdini21・CEDECNOTES・tool_docs）で動作確認済み |
| ブラウザ内Admin画面（APIキー発行・namespace設定等をUIから操作） | GAS版UIの「管理」タブ | ✅ 実装済み（`src/chatUi.ts`「管理」タブ）。キー発行/一覧/削除、namespace作成/一覧/削除、KB同期元設定、Notion/Drive同期実行（バッチループをクライアントJSで自動継続）、同期履歴表示に対応 |

---

## 現在の優先順位

1. **完了：コア検索・回答生成一式**（ハイブリッド検索・HyDE・`/query`・引用率算出・トークン予算強制）
2. **完了：メモリ・UI一式**（チャット履歴保存/一覧/評価、Webチャット画面）
3. **完了：知識ベース管理の中核（Notion）**— 実際の`cloud-rag-bot`インテグレーション・Houdini21データベース（80ページ）で完全同期・回答生成まで実データ確認済み（2026-08-25）。この過程でVectorizeベクトルID長の上限超過・Cloudflareサブリクエスト数上限超過という2つの実バグを発見・修正した（cloudflare-rag-poc/README.mdのトラブルシューティング参照）
4. **完了：Admin API**（APIキー発行/一覧/削除/namespace許可変更/予算上限設定/残高補充、namespace作成/一覧/削除）— 実データで動作確認済み。副産物として、キーごとのnamespaceアクセス制御（RBAC）を厳格化した
5. **完了：UIの作り込み**（タブ構成／グラフ表示／ブラウザ内Admin画面、2026-08-25）— 実際のGAS版UIとの比較で見えた差分を解消。`src/chatUi.ts`を4タブ構成に全面刷新し、新規`src/graph.ts`（`POST /graph`）でnamespace横断のグラフ可視化、既存Admin API群をブラウザ上のフォーム/一覧/削除ボタンから直接操作できるようにした。実データ（Houdini21）で動作確認済み（81ノード/239エッジ）
6. **完了：Google Drive実同期の検証**（2026-08-26、サービスアカウント認証で実際のDriveフォルダ3件を同期。houdini22で8ドキュメント登録まで確認）
7. **完了：知識ベース管理の周辺機能**（2026-08-26）— URL手動登録（HTMLRewriterでテキスト抽出）、QA CSV一括登録、KBロールバック（opId単位でVectorize/D1から削除）を実装。いずれも実データで動作確認済み
8. **完了：利用統計・評価統計・レート制限・期限切れ履歴の自動削除**（2026-08-25〜26）— トークン使用量ダッシュボード、評価集計、固定ウィンドウ方式のレート制限（60秒30回）、Cron Triggerによる90日超の履歴自動削除
9. **完了：PDF/Word/PowerPoint変換・音声/動画文字起こし・YouTube登録**（2026-08-26）— PDFはGeminiのネイティブ文書理解（小さければインライン、大きければFile API）、DOCX/PPTXは自前の最小限ZIPパーサ、音声/動画とYouTubeはGemini File API/fileDataで文字起こし。実際のCEDEC発表資料（PDF/PPTX）で検証済み。20MB超の一部大きいPPTXはWorkers側のメモリ上限でスキップされることがある
10. **完了：ヘルスチェック・アラート**（2026-08-26）— D1接続・KB同期エラー・トークン予算枯渇間近を検知しSlack/Gmailへ通知。30分ごとのCron Triggerで自動実行。**Slack・Gmailともに実際にテスト通知の送受信まで確認済み。** Gmailは当初サービスアカウント方式（Google Workspace限定と判明）→個人アカウントのOAuthリフレッシュトークン方式に切り替え、GCPプロジェクトでのGmail API有効化も実施して稼働確認した
11. **完了：バックアップ機能**（2026-08-26）— 設定系テーブル（users/namespaces/kb_sources/token_budgets/key_namespace_grants）のJSONエクスポート。実データ（チャット履歴本文・ベクトル）はD1の自動バックアップに任せる方針
12. **保留：チャット履歴検索のRAG統合**（`searchMemory_`相当）— ユーザー指示により一旦保留（2026-08-26）
13. **対象外：Claude APIプロキシ**（Houdiniチュートリアル生成）— ユーザー確認済み（2026-08-24）。RAGには不要なため実装しない

---

**現時点のまとめ（2026-08-26）：** 上記1〜11がすべて完了し、`docs/gas-feature-parity.md`で追跡していたGAS機能のうち実装可能な項目はほぼ実装・実データ検証済みとなった。Claude APIプロキシは当初「RAGには不要」として対象外にしていたが、後にHoudiniチュートリアル生成（`tutorial_agent.py`）のGAS依存移行という別の目的で実装済みに変わっている。残るのは保留中の「チャット履歴検索のRAG統合」のみ。設計・アーキテクチャの詳細は[docs/cloudflare-rag-technical-report.md](cloudflare-rag-technical-report.md)、運用手順は[docs/cloudflare-rag-operations-manual.md](cloudflare-rag-operations-manual.md)を参照。

---

*関連ドキュメント: [docs/cloud-local-unification-plan.md](cloud-local-unification-plan.md) / [cloudflare-rag-poc/README.md](../cloudflare-rag-poc/README.md) / [docs/cloudflare-rag-technical-report.md](cloudflare-rag-technical-report.md)（HTML版: [.html](cloudflare-rag-technical-report.html)）/ [docs/cloudflare-rag-operations-manual.md](cloudflare-rag-operations-manual.md) / [docs/cloudflare-vs-firebase-comparison.md](cloudflare-vs-firebase-comparison.md)*
