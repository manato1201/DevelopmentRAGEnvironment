# 旧 IMPROVEMENT_PLAN.md(2026-07/08)の棚卸し

**調べた日:** 2026-11-18 / **対象:** origin/main(9a25eaa)の `IMPROVEMENT_PLAN.md` の `- [ ]` 31 項目(Phase 1〜5 と Final Phase)
**目的:** Cloudflare 移行(GAS 廃止 2026-10-22)より前に書かれた計画の完了基準を、今のコード・テスト・履歴で仕分け、今後の作業リストにする。`IMPROVEMENT_PLAN.md` 自体は変更していない。

## 集計

| 区分 | 件数 | 意味 |
|---|---|---|
| 完了 | 19 | すでに満たされている |
| 不要 | 5 | 前提が変わって意味を失った |
| 未完了 | 4 | 満たされておらず、今も意味がある(実質は 2 件の問題。後述) |
| 確認不能 | 3 | 実機・本番・実測が要る |
| 合計 | 31 | |

Phase ごと: P1 = 完了 4・不要 1 / P2 = 完了 4・確認不能 1 / P3 = 完了 1・不要 4 / P4 = 完了 5 / P5 = 完了 2・未完了 3 / Final = 完了 3・未完了 1・確認不能 2

## 確認のために実行したもの

| 実行 | 結果 |
|---|---|
| `houdini/tests` の unittest(Python 3.13、既存の .venv を利用) | 750 件・error 3・skipped 51。error 3 は環境要因(下記) |
| 同 `test_namespace_isolation`・`test_prompt_guard`(空の `data/` を一時作成) | 11 件・3 件とも OK(`data/` が無いと import で失敗) |
| `test_panel_actions` | `PySide6` が無く import 失敗(`pyproject.toml`・`uv.lock` に PySide6 が無い)。Qt 依存の 51 件は skip |
| `cloudflare-rag-poc`: `npm run typecheck` / `npm test` | どちらも成功(テスト 34 件 pass、fail 0) |
| `ruff check scripts/ houdini/` | **10 件の指摘**(F401×2・E702・F841×4・E741×2・E402)。CI と同じ |
| `mypy --strict`(CI の 3 モジュール) | 成功(エラー 0) |
| `scripts/ci_check_namespaces.py` | 空の `localRAG/` では「スキップ」で exit 0。`localRAG/bogus_ns` を一時作成すると検知して exit 1 |
| レベルチェーン(`build_level_chain`)をスタブで実行 | basic は前段の要約なし、applied・advanced は前段の要約がシステムプロンプトに入る |
| ローカルブリッジを別ポートで起動(`--no-auth`、空の ChromaDB) | `/health` が 200。`/search` は `level` あり・なしで同じ形式 |
| Worker の `/query` に画像あり・なしを送る(偽の Gemini・D1 で実行) | 画像ありのときだけ Gemini の `inlineData` が付く。レスポンスのキー・`extractionRate` は同じ |
| `gh run list`(GitHub Actions) | main の CI は 2026-10-21 以降すべて失敗(`lint` ジョブの ruff 段で停止)。`worker` ジョブは成功 |

一時ファイル(`data/`・`logs/`・`localRAG/`)は確認後に削除済み。

---

## Phase 0: 現状分析(チェック項目なし)

**状態: 調査のみ。前提の多くが古い。** Cloud RAG は GAS(`gas_cloud_rag.js`)ではなく Cloudflare Worker + D1 + Vectorize に置き換わった(db68fd4、2026-10-22)。ローカル RAG(ChromaDB + HTTP ブリッジ)は残っている。`houdini/python_panels/` は 3,624 行から大きく増え、構成も変わった。

## Phase 1: RAG レベリング

**状態: 実装済み**(ce4c5ec、2026-08-12)。ただし 2026-10-20 に、3 段階を「難しさ」ではなく学習の道すじ(レッスン 1→2→3)に定義し直した(`_LEVEL_INSTRUCTIONS` は `lesson_design.LESSON_PATH` 由来)。Worker 側にも `level` のフィルタ(`retrieve.ts`)がある。

| 項目 | 区分 | 根拠 / 足りないもの |
|---|---|---|
| 同一トピックで 3 レベルを生成し、`prior_level_summary` が次段に含まれる | 完了 | `tutorial_agent.py` の `build_level_chain`・`_summarize_for_next_level`・`_build_initial_prompt`。スタブ実行で applied・advanced のプロンプトに入ることを確認。進捗ログ「前段の要約をプロンプトに引き継ぎました」もある。専用の単体テストは無い |
| `level` 未指定の `/search`・`/query` が従来どおり | 完了 | `rag_local_bridge.py` は `if level:` のときだけ絞る。`level` あり・なしで `/search` が同じ形式で 200(実起動)。Worker も `level ? filter : ranked`(`retrieve.ts`)。件数の回帰テストは無い |
| `_safe_meta()` が `difficulty` を通す | 完了 | `VectorDatabase._safe_meta({"difficulty":"basic","tags":[…]})` → `difficulty` は残り、list は落ちる(実行確認) |
| 客観指標で basic→advanced 後の理解度スコア変化を計測 | 不要 | 0〜1 の理解度スコア(`score_engine.py`)の代わりに、Worker の「説明レベルの成長」(`growth.ts`、用語の蓄積)が使われている。実験設計も `pilot-analysis-design.md`(3 回の回間比較、説明レベルの推移)に差し替わり、`pilotStats.ts` が成長レベルを集計する。計画の「変化率」という専用指標は作られていない |
| `extractionRate`/`extractionDetail` の算出式が変わらない | 完了 | Phase 1 のコミットはこの部分に触れていない。Worker は `query.ts` の `cited / sources.length`、ブリッジは `_parse_extraction`。`stream.test.mjs` が `extractionRate == 100` を検証し pass |

## Phase 2: VLM 対応

**状態: 実装済み(一部は置換)**(4fb7824、2026-08-12)。Cloud 側は GAS から Worker の `/query`(`image: {mimeType, data}`)へ移植済み。Houdini の Chat タブに「画面を添付」。ローカルは CLIP を別コレクション `{namespace}_images` に入れ、`/index-images`・`/image-search` を追加。ローカルの `/query` は画像を受け取らない(設計書に明記)。

| 項目 | 区分 | 根拠 / 足りないもの |
|---|---|---|
| Cloud RAG に画像付きクエリを送り、同じ形式で応答 | 完了 | `query.ts`・`embeddings.ts`(`inlineData`)。偽の Gemini で画像あり・なしを比較し、レスポンスのキーが同じことを確認。画像の経路の自動テストは無い |
| CLIP 追加後もテキスト検索のスコア・順位が変わらない | 完了 | 別コレクション・別メソッドで、`search()`(BM25+ベクトル RRF)に触れていない(4fb7824 の差分)。`get_document_count` は `_images` を除外。順位を比べる実測テストは無い |
| `capture_viewport()` の画像が Cloud RAG 経由で VLM に解釈される | 確認不能 | コード上は `rag_chatbot.py` の `_capture_viewport_b64()` → Worker → Gemini。実際に解釈されるかは、Houdini 実機 + 本番 Worker + 本物の Gemini の通しが必要 |
| VLMAutoReplayTool 設計書とのキャプチャ関数の共通化を判断できる | 完了 | `screen_capture.py` の docstring に 2 関数を共通インターフェース候補として明記。VLMAutoReplayTool 側の設計書にも参照がある |
| HyDE・情報抽出度・閾値フィルタが画像の有無で同じ | 完了 | 画像は最終回答の生成にだけ渡る(検索・HyDE は画像を使わない)。`extractionRate` も同じ値。**ただし閾値フィルタ(コサイン 0.58)は Worker に見当たらない**(`cloud-rag.md` §4.3 は GAS 時代の記述のまま) |

## Phase 3: TiDB/TiKV 移行設計

**状態: 設計のみ(計画どおり)**(7126992)。実装なし。`migrate_auth_to_tidb.py` は参考の独立スクリプトで、本番の経路から呼ばれない。認証・メタデータは Cloudflare D1(`migrations/` 37 本)に移ったため、**事実上凍結**。設計書(`tidb-tikv-migration-design.md`)に D1 の言及は無い。

| 項目 | 区分 | 根拠 / 足りないもの |
|---|---|---|
| `auth.db` の 3 テーブルを TiDB へ欠損なく移行(件数突合) | 不要 | 移行先が D1 になり、TiDB へ移す動機が消えた。TiDB のインスタンスも無い |
| `pep.py` の `authorize()`/`filter_namespaces()` が移行後も無変更で動く | 不要 | 同上。TiDB 移行をしないので検証する対象が無い |
| `score_engine.py` の `update_score()`/`get_score()` が TiDB でも同じ戻り値 | 不要 | 同上。理解度スコアは Worker 側では `growth.ts`(D1)に置き換わっている |
| ChromaDB(ベクトル本体)が移行対象に含まれない | 完了 | 設計書 §1・§3 と、移行スクリプトが `users`/`access_logs`/`understanding_scores` の 3 表だけを扱うこと |
| 配布方式 A〜E と TiDB 接続設定が独立に両立 | 不要 | TiDB 接続を実装しない。配布は Houdini パネルの配置と Worker のデプロイに変わった |

## Phase 4: 軽量サービスレジストリ

**状態: 実装済み**(7126992)。`rag_service.py` に `register_embedder`/`get_embedder`/`register_vector_backend`/`get_vector_backend`。`create_rag_service_from_env()` と CLIP の遅延ロードがレジストリ経由。ECS・DI コンテナは無い。

| 項目 | 区分 | 根拠 / 足りないもの |
|---|---|---|
| `rag_cli.py index` がレジストリ経由になっても出力が変わらない | 完了 | `rag_cli.py` は `create_rag_service_from_env()`(レジストリ経由)を使い、構築ロジックは従来と同じ。コミット記録に実 ChromaDB での確認あり。今回は再実行していない(出力を比べるテストは無い) |
| 未登録キーで即エラー(暗黙フォールバックなし) | 完了 | `get_embedder("nope")`・`get_vector_backend({}, "nope")` が `KeyError`(実行確認) |
| `document_processor.py`/`embedding_generator.py` の公開 API 差分なし | 完了 | 7126992 以降、この 2 ファイルへの変更コミットは無い(`git log`・`git diff` が空) |
| ECS/DI 相当のクラス階層が無い | 完了 | レジストリはモジュール内の辞書 2 つと関数だけ。`project-overview.md` にも不採用の記載 |
| 導入後も `/health` が 200 | 完了 | ブリッジを実起動(空の ChromaDB)して `/health` が 200 |

## Phase 5: 静的解析の軽量強化

**状態: 一部**。`.github/workflows/ci.yml`・`pyproject.toml` の ruff 設定・`ci_check_namespaces.py` は在る(7126992、Worker ジョブは 44652a6 で追加)。しかし **main の CI は 2026-10-21 以降ずっと赤**。

| 項目 | 区分 | 根拠 / 足りないもの |
|---|---|---|
| `ci.yml` が push 時に緑になる | 未完了 | 直近の main はすべて失敗(ruff 段で停止し、後続の mypy・namespace・unittest が実行されていない)。`worker` ジョブは緑。**最小の埋め方:** ruff の 10 件を直す。そのあと unittest 段で赤くなる見込み(下記「実質の問題」) |
| ruff が警告ゼロ、または `# noqa`+理由で許容 | 未完了 | 10 件: `pilot_panel.py` F401、`rag_local_bridge.py:88` E402、テスト 8 件(`test_generation_20261117.py` E702・F841×2、`test_node_links.py` E741×2、`test_panel_nav.py` F401、`test_report.py` F841×2)。**最小の埋め方:** `ruff check --fix` で 1 件、残りは未使用変数の削除・`l`→`line` に改名・E402 に理由つき `# noqa` |
| `pep.py` ベースの CI チェックが不正な namespace で実際に失敗する | 未完了 | ローカルでは `localRAG/bogus_ns` を置くと exit 1 で検知する。しかし `localRAG/` は `.gitignore` 対象で CI の checkout には無く、スクリプトは「スキップ」で exit 0 になる。つまり CI では検出力が働かない。**最小の埋め方:** 一時の `localRAG/<未知のフォルダ>` を作って exit 1 を確かめる単体テストを足す |
| `mypy --strict` が 1 モジュール以上でエラーゼロ | 完了 | `pep.py`・`score_engine.py`・`audit_logger.py` で成功(実行確認) |
| 監査ログ(JSONL)が既存フォーマットのまま | 完了 | `audit_logger.py` の CI 導入時の変更は型注釈のみ(`str(event.get("query",""))` を含む)。以降の変更コミットは無い |

## Final Phase: 統合検証

| 項目 | 区分 | 根拠 / 足りないもの |
|---|---|---|
| `:8766` の HTTP 契約が無変更(Unity・Houdini) | 完了 | `level`/`difficulty` は任意の追加のみ。`/search` が `level` なしで従来形式のまま(実起動)。Phase 1 のコミットは `Assets/` に触れていない。Unity エディタ実機は未確認 |
| VLM 追加後もテキストのみクエリの品質・レイテンシが劣化しない | 確認不能 | 画像なしの経路は変わらない(確認済み)。レイテンシの実測は、本番 Worker の `audit_log.latency_ms` など画像追加前後の数字が要る |
| `pep.py` ベースの CI が namespace 違反を実際に検出する | 未完了 | Phase 5 の同項目と同じ(CI では `localRAG/` が無くスキップ) |
| TiDB/TiKV は設計のみで、着手は基準超過のときだけ | 完了 | 実装なし・本番経路から未接続。着手条件は設計書 §3 に明記 |
| ECS/ジョブシステム不採用の根拠を README または本書に明記 | 完了 | `docs/design/project-overview.md`「アーキテクチャ判断: ECS・重量 DI コンテナを採用しない理由」。README は索引に絞られたため、README 直下ではなくここに移っている |
| Phase 0 の既存機能(HyDE・抽出度・👍/👎・理解度スコア)が全 Phase 後も動く(最終回帰) | 確認不能 | Worker 側は自動テスト pass(`retrieve_context`・`stream`・`growth` ほか)。ローカル側の `score_engine`・ブリッジには単体テストが無く、本番・Houdini 実機・ブリッジを通した確認が要る |

---

## 実質の問題(未完了 4 件は 2 つにまとまる)

1. **CI が赤い(5.1・5.2)。** ruff の 10 件が原因。直しても、次の unittest 段で 3 モジュールが赤くなる見込み(**未確認**。ローカルで再現した要因による推測):
   - `test_namespace_isolation`・`test_prompt_guard`: `data/` が無いと `score_engine` の `sqlite3.connect` が失敗する(CI のクリーンな checkout には `data/` が無い)。`data/` を作れば 2 つとも通る(確認済み)。
   - `test_panel_actions`: `PySide6` を無条件に import している(依存に無い)。他の Qt テストは `skipUnless` で skip される。
2. **namespace 検査が CI では何も検査しない(5.3・Final 3)。** `localRAG/` が CI に無いため。

## 未完了と確認不能だけの一覧(今後の作業リスト)

| # | 項目 | 区分 | 最小の作業 / 確認に要るもの |
|---|---|---|---|
| 1 | P5-1 CI が緑にならない | 未完了 | ruff 10 件を直す → unittest 段の 3 モジュール(`data/` の作成、PySide6 の skip 化または依存追加)を直す |
| 2 | P5-2 ruff の警告 10 件 | 未完了 | 上記の表のとおり(自動修正 1 件 + 手修正) |
| 3 | P5-3 / Final-3 namespace 検査が CI で検出しない | 未完了 | 一時の `localRAG/<未知>` を作って exit 1 を確かめる単体テストを足す |
| 4 | P2-3 ビューポート画像が VLM に解釈される | 確認不能 | Houdini 実機 + 本番 Worker + Gemini で「画面を添付」して質問する |
| 5 | Final-2 画像追加後のレイテンシ | 確認不能 | 本番 `audit_log.latency_ms` の画像追加前後の比較 |
| 6 | Final-6 既存機能の最終回帰 | 確認不能 | ローカルブリッジ・`score_engine` の通し確認(単体テストが無い)、本番・Houdini 実機の通し |

## 気づいた点(チェック項目の外)

- 閾値フィルタ(コサイン 0.58)は Worker に実装が見当たらない。意図して外したのか、GAS 廃止で落ちたのかは未確認。
- `tidb-tikv-migration-design.md` は Cloudflare D1 への移行に触れておらず、状態が古い(冒頭に「凍結」と一行足すだけで足りる)。
- `IMPROVEMENT_PLAN.md` の Phase 0 は GAS・ChromaDB 前提のまま。本書へのリンクを冒頭に置くと、読み違いを防げる(本人の編集と衝突するため、今回は触れていない)。

## 追記(2026-11-18)

P5-1(CI が緑にならない)と P5-2(ruff の 10 件)は、同日の CI 修復で解消した(ruff・mypy・名前空間の検査・houdini の単体テストを、PySide6 と `data/` の無い環境で通した)。P5-3・Final-3(名前空間の検査が CI で何も検出しない)は、未対応のまま残っている。
