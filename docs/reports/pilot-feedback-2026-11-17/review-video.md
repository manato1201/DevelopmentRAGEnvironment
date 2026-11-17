# レビュー: video（動画の素材・エンジン・ギャラリー）2026-11-17

## 1. 確認した範囲

- RAGReel: `cloudflare/ragreel-gallery/src/index.js`（まとめて削除・認証・入力検証）、`web/public/app.js`・`gallery.html`・`styles.css`（選択モード・出典表示）、`engine/src/encode/video_profile.h`・`video_encoder.cpp`、`engine/src/main_cloudrag.cpp`（プロファイル選択）、`engine/src/scene/scene_assembler.cpp`、`engine/qml/CloudRagScene.qml`、`engine/src/manifest/manifest_writer.*`（出典の読み書き）、`tools/verify_export.py`・`video_spec.json`、`docs/technical-reference.md` §24・§27。
- DevelopmentRAGEnvironment: `screen_capture.py`、`video_script.py`、`video_factory_bridge.py`、`gallery_upload.py`、対応するテスト。

問題なしと確認したもの:
- 認証: `UPLOAD_TOKEN` 未設定なら誰でも 401。比較は SHA-256 にしてから全バイトを比べる定数時間。まとめて削除・1 本の削除とも、認証が最初。
- 公開の画面から鍵なしで消せる経路は無い（画面は鍵を送るだけで、確かめるのは Worker。CORS ヘッダが無いので、他のサイトからも呼べない）。
- 出典・動画のタイトルの HTML は、`escapeHTML`（`& < > " '`）を通る。
- `--video-profile`・`RAGREEL_VIDEO_PROFILE` が不正な値のときは、1080p30 に戻り、ログに WARNING が出る（`video_profile_tests` 7 件）。値なしの `--video-profile` は空として扱われ、既定になる。
- 720p15 を選ぶと、サイズ・fps・crf 32 は前と同じ。ただし QML の配置（左パネル 420→380、下の帯 108→96、文字サイズ）は、全プロファイル共通で変わっている（設計どおり。§27.1 に記載）。
- エンジンが書く出典のキー（`file` / `namespace` / `cited` / `excerpt`）は、ギャラリー（`sourcesHTML`）と Houdini 側（`video_script.dedupe_sources`・`gallery_upload.merge_rag_sources`）のキー名と一致。エンジンの `metadata.json` に出典があるときは、Houdini 側は触らない（二重にならない）。

## 2. 見つけた不備と、直したこと

| # | 場所 | 不備 | 直し方・テスト |
|---|---|---|---|
| 1 | `cloudflare/ragreel-gallery/src/index.js` `handleDelete` / `handleBulkDelete` | R2 のファイルを先に消し、あとで manifest を更新していた。manifest の更新が失敗すると、「一覧にあるのにファイルが無い」壊れた項目が残る | manifest を先に更新し、そのあとファイルを消す順にした（失敗しても、残るのは一覧に出ない余分なファイルだけ。同じ要求のやり直しで消える）。テスト 3 件を追加（先に失敗を確認） |
| 2 | 同 `isValidId` | 長さの上限が無く（R2 のキーは 1024 バイトまで）、`\` も通っていた。長い id で delete が毎回 500 になる | 200 文字まで、`\` を拒否。まとめて削除は、重複込みの生の本数が 1000 を超えたら、1 本ずつ調べる前に 400 |
| 3 | `web/public/app.js` `sourcesHTML` | `rag_sources` が配列でない・要素が null や文字列だと例外で画面が落ちる | 配列かつオブジェクトの要素だけを使う。`<script>` を含む名前・壊れたデータのテストを追加 |
| 4 | `engine/src/manifest/manifest_writer.cpp` `parseTutorialSources` | ①バッジの後ろを `\S*` で読み飛ばしていたため、「✅」の後ろに「引用済み」が無い行で、題名の最初の語が消える（Python 側 `_SOURCE_LINE_RE` は `引用済み\|未引用` で、食い違い）。②`\s*` が改行をまたぎ、「- [1]」だけの行の次の行を題名に読む。③入力の大きさ・件数に上限が無い | Python と同じ形の正規表現にし、空白は `[ \t]` だけにした。読む範囲 100,000 文字・200 件の上限。C++ のテスト 3 件を追加（ラベル無しバッジ・CRLF・巨大/壊れた入力） |
| 5 | `video_script.py` `check_video_quality` / `check_step_quality` | 補足情報（`.meta.json`）の `name_pt: null`・`lines_hidden: "x"`、台本の `steps`/`images` が想定外の型、手順の `step` が文字列と数値の混在、で例外になる。`build_script` から呼ばれるので、台本の生成が止まる | `_number()` で数値を安全に読み、型の違う入力を読み飛ばす。ソートのキーも整数だけにした。テスト 2 件 |
| 6 | `screen_capture.py` `plan_focus_bounds` | ペインの縦横比が極端（1e-9 や inf）だと、範囲が ±3.5e9 になる | 縦横比を 0.25〜4 に収める。テスト追加 |
| 7 | `screen_capture.py` `render_network_diagram` | 全体図用の読み込み上限（`_MAX_DIAGRAM_NODES` = 60）を、注目ノードの図にも使っていた。61 個目以降のノードに注目する手順で、注目ノードが図に出ない（全体図になり、名前が読めない） | 注目ノードの図は 500 個まで読んでから、注目ノードの前後を選ぶ（`_MAX_FOCUS_MODEL_NODES`）。100 ノードで 81 個目に注目するテストを追加 |
| 8 | `screen_capture.py` `wrap_code_lines` | 5MB の 1 行で約 54 秒かかった（折り返しのたびに残りを複製） | 200,000 文字で切る（`MAX_CODE_CHARS`。表示できるのは 4 枚まで）。テスト追加 |
| 9 | `screen_capture.find_extra_pages`・`video_factory_bridge._extra_pages` | ファイル名に `[` `]` があると、glob の記号として扱われ、2 枚目以降の画像が見つからない | `glob.escape` を使う。テスト追加 |
| 10 | `gallery_upload.find_script_sources` | `source_tutorial`（manifest.json の値）に `../` があると、フォルダの外の `*_video_script.json` を読めた | `/`・`\`・`..` を含む名前は読まない。テスト追加 |
| 11 | `video_script._NODE_HELP` からの目的 | 「、」の手前だけを取っていたため、目的が「スキャッターは」になっていた | `_help_purpose()`: 「〇〇は、」の後ろを取る（「球の形を作るノードです」） |
| 12 | `video_script.assemble_script`（generation 担当の指摘） | `houdini_tools` が記録する `entry["purpose"]` を読んでいない | ノードを作る手順で、記録された `purpose`（文字列のみ。空白・コードのような文は無視、60 文字まで）を第 1 候補にし、無ければモデルの出力、定型文の順。`recorded_purpose()`。テスト 2 件（先に失敗を確認） |

## 3. リファクタリング

- `handleDelete` / `handleBulkDelete` の削除の順序を同じ形に揃えた（コメントで理由を残した）。大きな書き換えはしていない。

## 4. 直していないもの

- `tutorial_view.py`（担当外）が `gallery_upload.upload_missing()` に `tutorial_dirs` を渡していないため、Houdini 側の出典の補い（台本から入れる処理）は、いまは動かない。エンジンが `rag_sources` を書くので、新しい動画では不要。ただし、**エンジンを更新する前に作った動画**を後から上げる場合は、出典が空のまま。必要なら、`tutorial_view.py` の担当が `tutorial_dirs`（チュートリアルの保存先）を渡す。
- `DELETE /api/videos` は、manifest の読み・書きが比較・交換なしの読んで書き換え（既知の制限。§24 に記載済み）。同時に 2 人が上げる・消すと、一方の変更が失われうる。管理者 1 人の運用の前提。
- QML の配置の変更は、720p15 でも見た目が変わる（意図した変更。「動き」＝サイズ・fps・crf は前と同じ）。
- 1080p30 の描画時間は、約 3〜4 倍（§27.1 に実測。長い動画で数分〜十数分）。メモリは +156MB。極端には増えない。
- Mermaid の PNG が 1 倍のまま（`script_composer.cpp`。担当外。§27.1 に記載済み）。
- 実機で未確認: Houdini 実機のネットワークエディタの座標（`MIN_VIEW_WIDTH` などは推測値）、`Parm.containingFolderSetParmTuples` の動き。

## 5. テストの結果

- Worker・画面: `cd cloudflare/ragreel-gallery && npm test` → 23 件 OK（以前 18 件）。
- C++: `/tmp/build_ragreel.cmd` のビルド成功。`manifest_writer_tests` 19 件、`video_profile_tests` 7 件、`cloud_rag_client_tests` 4 件、`narration_tests` 52 件、`script_composer_tests` 33 件、`resource_budget_manager_test` OK。
- `python -m unittest discover -s tools/tests` → 26 件 OK。
- Houdini: `uv run --with PySide6 python -m unittest discover -s houdini/tests` → 806 件 OK（以前 759 件。他の担当の追加分を含む）。
- 注: C++ の新しい 3 件のテストは、直す前の失敗を確認していない（ビルド 1 回で、修正と同時に実行した）。`wrangler deploy` は実行していない。
