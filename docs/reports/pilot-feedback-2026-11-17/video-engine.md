# video-engine（前と後の差）

対象: `C:\Users\matuu\Desktop\GameDevelopment\RAGReel`（動画エンジン C++ とギャラリー Worker）。コミット・デプロイ（`wrangler deploy`）はしていない。

## 項目ごとの差

### 15 fps・1280x720 で荒い／VEX など文字が多い所がつぶれる（フル HD・30 fps へ）
- **前**:
  - `engine/src/main_cloudrag.cpp`: `constexpr int kFrameWidth = 1280; constexpr int kFrameHeight = 720; constexpr int kFps = 15;`（2026-09-26 に 30→15 に下げた経緯のコメントつき）。
  - `engine/src/encode/video_encoder.cpp`: VP9 `crf=32` 固定、`deadline=realtime`・`cpu-used=6`・`row-mt=1`・`tile-columns=2`。
  - `engine/qml/CloudRagScene.qml`: ルートが `width: 1280; height: 720` の固定。左パネル 420px、図の余白 56px（右の面は約 748x452）、文字は 要点 14px・コード 16px・参考カード 15/11px・下の帯 12px。`SceneAssembler` は QML のルートの大きさを設定せず、QML の値のまま。
  - 「参考」スライドは 1 列のカード。11 件だと、下にはみ出す（今回の画面の字の大きさで試すと、12 件で最後の行が切れた）。同じ資料（例: Shelf tools）が重複して並ぶ。
- **後**:
  - 新規 `engine/src/encode/video_profile.h`: プロファイル `1080p30`（既定）/ `1080p15` / `720p30` / `720p15`。`--video-profile <名前>`（優先）または環境変数 `RAGREEL_VIDEO_PROFILE` で選ぶ。`720p15` は前の既定と同じ。知らない名前は既定にして警告。ログに `Video profile: 1080p30 (1920x1080, 30 fps)`。
  - `main_cloudrag.cpp`: 大きさ・fps をプロファイルから決める（メタ行・チャプター・マニフェストにも反映）。
  - `video_encoder.cpp`: crf は画素数で決める（1080p は 30、720p は 32）。
  - `SceneAssembler::initialize`: QML ルートに書き出しの大きさを設定。`scene_assembler.cpp` の `renderFrame`: 全画素を変換していた `convertToFormat(RGBA8888)` をやめた（画面は不透明で、バイト列は同じ）。
  - `CloudRagScene.qml`: 1280 幅を基準に、全体（`stage`）を実際の幅へ拡大して描く（文字は拡大後の大きさで描き直される）。右の面を広げた（左 380px・図の余白 20px・下の帯 96px → 約 860x584）。縮小のときは `mipmap`。文字を大きく（要点 17px・コード 19px・参考 14〜19px・下の帯 14px）。「参考」はカードを 1/2/3 列にして件数で字と余白を変え、はみ出さない。同じ資料は 1 件にまとめる（`dedupeReferenceItems`）。「参考」スライドの左の本文行（「⬜ 未引用 …」の重複。絵文字が豆腐になる）は出さない。
  - 見た目の確認: 1080p30 でフレームを取り出して目視（コード・図解・「参考」12 件の 2 列）。
  - **実測**（同じ入力・同じ PC、短い動画）:

    | | 720p15（前） | 1080p30（後） |
    |---|---|---|
    | 描画+エンコード（Render 段） | 19.7 秒（`--mock`・114.8 秒の動画）／15.6 秒（Houdini 形式・119.1 秒の動画） | 57.8 秒（114.0 秒）／58.0 秒（119.1 秒） → 約 3〜3.7 倍 |
    | 1 フレームあたり（シーン / エンコード） | 4.7 / 6.5 ms ／ 3.5 / 4.4 ms | 6.9 / 9.7 ms ／ 6.7 / 9.1 ms |
    | ファイルの大きさ | 5.09 MB ／ 5.98 MB | 9.15 MB ／ 9.39 MB（約 1.6〜1.8 倍） |
    | 最大のメモリ（working set） | 352 MB | 508 MB |

    実機の長い動画（500〜1000 秒）は、描画だけで数分〜十数分になる見込み（静止の多いスライドでの実測から。動きの多い視点クリップが多いと、エンコードはさらに重い）。`convertToFormat` をやめた分は、1080p30 の Render 段 64.4 秒 → 57.8 秒。フレームの差は平均 0.004/255（エンコードのゆらぎ）。
- **状態**: **完了**（ただし、下の「未対応・要確認」の 2 点: Houdini が撮る画像の解像度、Mermaid の `-s 2`）

### RAG 出典が「出典なし」
- **前**（突き合わせの結果）:
  - ギャラリー（`web/public/app.js` の `sourcesHTML`）が読むのは、`metadata.json` の `rag_sources[]` の `file` と `similarity`。空なら「出典なし」。
  - エンジン（`manifest_writer.cpp`）が `rag_sources` に書くのは `detail.ragSources` = Cloud RAG の応答の `sources`（`file` / `namespace` / `similarity` / `excerpt`）。
  - **途切れていた所**: Houdini のチュートリアル動画（`--houdini-md`）は、Cloud RAG に直接聞かず `response.sources` が空。`rag_sources: []` のまま公開されていた。Houdini 側の `gallery_upload.py` は、エンジンが書いた `metadata.json` をそのまま送るだけで、出典のキーは足していない（読んだだけで、変更なし）。
  - もう 1 つの原因: 打ち切りで終わったチュートリアルの「## 参考」は、バッジ無しの行（`- [1] 題名（houdini22）`。`tutorial_agent.py` の `source_lines`）。スライド用の解析（`parseHoudiniReferenceItems`）は、バッジ（✅/⬜）を必須にしているので、これでは読めない。
- **後**:
  - `manifest_writer.{h,cpp}`: `parseTutorialSources(markdown)` を追加（バッジ有り 2 種と、バッジ無しの 3 通りを読む。重複は 1 件に）。`ManifestVideoDetail::tutorialSources` を `rag_sources` に書く。Cloud RAG の出典と同じ資料は重ねない。
  - `main_cloudrag.cpp`: Houdini モードで、チュートリアルの本文（`response.answer`）から `detail.tutorialSources` を作る。
  - ギャラリー `app.js` の `sourcesHTML`: `similarity` が無いのに `0.00` と出さない。`namespace` を題名の横に、`cited` を「活用 / 検索のみ」で出す。`styles.css` に `.source-ns`。
  - **既存のキー名をそのまま使った**（Houdini 側が合わせるべき名前）:

    | キー | 内容 |
    |---|---|
    | `file` | 出典の題名（必須） |
    | `namespace` | 知識ベース名（`houdini22` など） |
    | `similarity` | 類似度 0〜1。Cloud RAG に直接聞いた動画にだけ。Houdini の動画では**キーごと無い** |
    | `cited` | true=チュートリアルで使った / false=検索のみ。**打ち切りの動画は未評価なので、キーごと無い** |
    | `excerpt` | 空文字 |

    **Houdini 側が `gallery_upload.py` から出典を別に送る必要は無い**（エンジンの `metadata.json` に入っているものを送るので）。変えるとすれば、上のキー名を壊さないことだけ。
  - テスト: `manifest_writer_tests` に、Houdini 形式の出典の書き出し・Cloud RAG との重複排除・出典なしは空配列・バッジ有り/無し/重複/無し の解析・重複除去（7 件追加）。`web.test.js` の `sourcesHTML`（0.00 を出さない）。実機相当: 手順つき Houdini 形式の動画を書き出し、`metadata.json` の `rag_sources` に 12 件（重複 1 件を除く）が入ることを確認。
- **状態**: **完了**（実際の Houdini で作った動画をギャラリーで見る確認は、していない）

### 動画サイトで、まとめて消せる機能
- **前**: 1 本ずつ（`DELETE /api/videos/:id`。動画ページの管理ドロワー）だけ。一覧に選択も一括削除も無い。
- **後**:
  - Worker `cloudflare/ragreel-gallery/src/index.js`: `DELETE /api/videos`、本文 `{"ids": [...]}`。認証は 1 本ずつと同じ `Authorization: Bearer <UPLOAD_TOKEN>`（未設定なら 401）。1 つでも不正な id・空・101 本以上は 400（何も消さない）。重複は 1 本として数える。manifest の書き換えは 1 回だけ。
  - 画面 `web/public/gallery.html` / `app.js` / `styles.css`（共有ギャラリーのみ。`file://` では出さない）: 上のバーの「選択」→ カードを押して選ぶ（チェック・Space でも）→ 「表示中をすべて選択」「選択を解除」「選択を削除（N 本）」「終了」。絞り込みで見えない動画は選択から外れる。確認の画面に「全 M 本のうち N 本」と題名（8 本まで）。**全部を消すときは、本数の入力が合わないと消さない**。続けて、管理トークン（保存済みならそのまま。`vf_upload_token`）。削除後は再読み込みで最新にする。
  - 鍵なしで消せる経路は無い（鍵の確認は Worker）。
  - テスト: 新規 `cloudflare/ragreel-gallery/test/index.test.js`（9 件。鍵なし・誤り・未設定は 401 で何も消えない、不正 id は全体を拒否、上限、重複、1 本の削除は従来どおり、GET では消えない）と `test/web.test.js`（9 件。`planBulkDelete`・確認画面・全部のときの入力・Bearer と本文・401・分割・`sourcesHTML`）。`package.json`（`type: module`、`npm test` = `node --test test/*.test.js`）を新規に足した。
- **状態**: **完了**（ブラウザでの実際の操作の確認は、していない。構文は `node --check`、関数は単体テストで確認）。デプロイ前なので、本番の Worker にはまだ無い。

### 動画の品質差（エンジンの書き出しの検査）
- **前**: `tools/video_spec.json` の基準は 1280x720・15fps（30fps だけ旧版の警告）。`verify_export.py` は `video.mp4` しか探さず、エンジンの書き出し（`video.webm`）のフォルダを読めなかった。字幕の有無は、ファイルが無いと一律 skip。
- **後**: 基準を 1920x1080・30fps に。`legacyProfiles`（720p15・720p30・1080p15）は不合格にせず警告。`video.webm` のフォルダも読む（`--all` も）。`metadata.json` に字幕があると書いてあるのにファイルが無いときは不合格。テストは 1080p を基準に更新（`python -m unittest discover -s tools/tests`: 26 件）。エンジンが書いた実際の 1080p30 の動画・720p15 の動画で、それぞれ合格・警告になることを確認。
- **状態**: **完了**（Houdini 側の品質チェッカーは別の担当）

## 変更したファイル（RAGReel）
- `engine/src/encode/video_profile.h`（新規）: 大きさ・fps・crf の選び方
- `engine/src/encode/video_encoder.cpp`: crf を画素数で決める
- `engine/src/main_cloudrag.cpp`: プロファイル、出典、参考の重複除去
- `engine/src/scene/scene_assembler.cpp`: QML に大きさを渡す、不要な画素変換をやめる
- `engine/qml/CloudRagScene.qml`: 拡大して描く構造、レイアウト・文字サイズ、参考カードのグリッド（担当リストに明記は無いが、描画の本体なので変更）
- `engine/src/manifest/manifest_writer.{h,cpp}`: 出典の解析・書き出し・重複除去
- `engine/tests/manifest_writer_test.cpp`, `engine/tests/video_profile_test.cpp`（新規）, `engine/CMakeLists.txt`（`video_profile_tests` の追加）
- `cloudflare/ragreel-gallery/src/index.js`, `package.json`（新規）, `test/index.test.js`（新規）, `test/web.test.js`（新規）
- `web/public/app.js`, `web/public/gallery.html`, `web/public/styles.css`
- `tools/verify_export.py`, `tools/video_spec.json`, `tools/tests/test_verify_export.py`
- `docs/technical-reference.md`: §27 を追加（実測値・キー名・一括削除）、§7・§24.1 の追記

## テスト
- ビルド: `/tmp/build_ragreel.cmd` 相当（vcvars64 + `cmake --build build`）。エラー無し。
- `build/engine/video_profile_tests.exe`: 7 件 通過
- `build/engine/manifest_writer_tests.exe`: 16 件 通過（出典関連の 7 件を含む）
- `build/engine/script_composer_tests.exe`: 33 件 通過
- `build/engine/narration_tests.exe`: 52 件 通過
- `build/engine/cloud_rag_client_tests.exe`: 4 件 通過、`resource_budget_manager_test.exe`: PASS
- `cd cloudflare/ragreel-gallery && npm test`: 18 件 通過
- `python -m unittest discover -s tools/tests`: 26 件 通過
- `node tools/check_gallery_layout.js`・`node tools/check_contrast.js`: 通過
- 実機相当の書き出し: `--mock`（1080p30・720p15）、手順・参考 12 件つきの Houdini 形式（1080p30・720p15）。`verify_export.py` を実際の書き出しに実行

## 未対応・要確認（ユーザーの判断・実機確認が要るもの）
1. **書き出し時間が約 3〜4 倍になる**（既定を 1080p30 にしたため）。許容できなければ、既定を戻す（`video_profile.h` の `kProfiles[0]` の順番）か、Houdini 側から `RAGREEL_VIDEO_PROFILE=1080p15`（約 2 倍）/ `720p15`（前と同じ）を渡す。実機の長い動画での時間は未測定（短い動画の実測からの見積もり）。
2. **文字のつぶれは、撮る画像の大きさにも依存する**。Houdini が撮るパラメータ画像・ネットワーク画像が小さいと、画面を大きくしても拡大するだけで鮮明にならない。撮影の解像度（`video-capture` 担当）を、1.5 倍以上にすると効果が大きい。
3. **図解（Mermaid）の PNG を 2 倍にする `-s 2`**: `engine/src/ingest/script_composer.cpp` の `renderMermaidToPng` に足したいが、担当のファイルの外で、編集が許可されなかったので、していない。1 行（`QStringLiteral("-s"), QStringLiteral("2")` を引数に追加）。
4. 一括削除の画面は、実際のブラウザでの操作確認が未実施（デプロイ前）。デプロイ後に、(a) 鍵なしの `DELETE /api/videos` が 401、(b) 一部の選択、(c) 全部の選択で本数の入力が出る、を確認してほしい。
5. `build/engine/output`（gitignore 済みのビルド出力）に、動作確認で書き出した動画を一時的に足したが、manifest と一緒に削除して元に戻した。
