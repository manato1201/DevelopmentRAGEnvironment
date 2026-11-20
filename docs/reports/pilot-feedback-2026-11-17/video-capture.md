# video-capture（前と後の差）

動画の素材（画面の取り込み）と台本。Houdini 側。実機（Houdini）は無いので、Houdini 依存の部分は、副作用のない関数に切り出して、偽物で試した。

## 項目ごとの差

### ノード数が増えると、全体を撮る関係で、どんどん見づらい
- **前**: `screen_capture.py::_paint_network_diagram` は、全ノードを 1 枚に収め、拡大率の下限が 0.35 だった。40 ノードの一本道（実測）: 拡大率は 0.35 に張り付き、ノード名は 3.85pt、図の高さは 1436 で、画面の高さ（632）を超えて、画面の外にはみ出した。実画面のネットワークエディタも、`focus_network_on` が「直下の全ノードが入る範囲」に合わせていた。
- **後**:
  - 各手順の図は、注目ノードと、その前後だけを、名前が読める大きさで描く（`select_focus_nodes`）。名前の下限は `MIN_NAME_PT = 12`pt（`DIAGRAM_NAME_PT = 14` に拡大率 0.857 以上）。下限を守れる数だけ入れ、残りは上の帯に「表示 7/40 ノード（ほか 33 個は省略）」と書く。40 ノードの一本道で、注目ノードの前後 7 個、名前 12.6pt（実測）。
  - 全体図（`render_graph_diagram`。台本の `images.node_diagram`＝構造の説明に 1 枚）は、拡大率の下限を外して、画面の中に必ず収める（前のようにはみ出さない）。名前が読めなくなるのは、全体図だけ。
  - 実画面は、撮影の直前に、注目ノードと前後が映る範囲に合わせ直す（`plan_focus_bounds` / `frame_network_on_focus`。幅の上限 14 単位、下限 7 単位、ペインの縦横比に合わせる）。`houdini_tools.py` を直さなくても、`capture_network_editor` が `focus_path` を受け取っているので、そこで合わせる。
  - ペインの幅が 1000px 未満なら、実画面を拡大するとぼやけるので、描き直した図にする（`prefer_diagram`、`PANE_PREFER_DIAGRAM_WIDTH`）。
  - 撮った画像のとなりに `<画像>.meta.json`（ノード数・名前の pt・収まったか）を書く。
  - 根拠: `test_capture_readability.py`（BeforeAfterTest、SelectFocusNodesTest、PlanFocusBoundsTest、RenderTest）。
- **状態**: 一部。「全体図は章の冒頭に 1 枚」は、動画全体の構造のスライドの 1 枚（既存の `node_diagram`）のまま。章ごとの全体図は、手順ごとのグラフの記録が無いので作れていない（未対応・要確認）。実画面の範囲の数値（1 ノードの幅、14 単位）は推測で、実機で要確認。

### VEX など文字が多いところが、つぶれて読めない
- **前**: パラメータ画面の右の列（幅 480）に、等幅 11pt で、1 行ずつ出し、はみ出す部分は「…」で切っていた（`_compose_parameter_screen`）。実測: 1365 の幅の 1 行は、読める部分が 3 分の 1 以下。1080p の動画では、文字は約 12.8px。
- **後**: コードの変更がある手順は、専用のカード（`render_code_cards`）にする。等幅 16pt（前の約 1.45 倍。動画では約 18px 以上）、行番号つき、長い行は折り返し（全角は 2 桁で数える）、1 枚に入らなければ複数枚（1 枚目は変更点の一覧と一緒、2 枚目から `step_NNN_network_p2.png`…。最大 4 枚。超える分は「ほか N 行」）。`capture_parameter_screen` の戻り値に `"code_card"` が増えた。
  - 根拠: `test_capture_readability.py`（CodeLayoutTest、RenderTest.test_code_cards_are_split_and_written）。
- **状態**: 一部。2 枚目以降の画像を動画に出すには、動画エンジン側の対応が要る（下の「未対応・要確認」の `network_pages`）。エンジンが読まなければ、1 枚目（先頭の約 16 行）だけが出る。解像度（15fps、フル HD 化）は、エンジン（C++）の担当なので、触っていない。

### 値を変える対象が見えない／見切れている
- **前**: `capture_parameter_screen` は、ノードを選んでペインを前面にするだけで、変更した項目が入っているタブ（例: Code / Render）を前面にしていなかった。別のタブが映っていると、変更した項目が写らない。
- **後**: 撮影の前に、変更した項目のタブを前面にする（`reveal_parm_tabs`。公式 API の `Parm.containingFolders()` / `containingFolderSetParmTuples()`）。タブ名を「A › B」にして、スライドの「変更したパラメータ」の行にも出す（`with_tab_paths`、`tab` キー）。実画面が撮れないときの描き直したカードにも、タブ名が出る。
  - 根拠: `FolderTabTest`（偽のパラメータで、タブが切り替わる）。
- **状態**: 一部。タブの切り替えは、実機未確認（API は公式ドキュメントのもの）。折りたたみ・スクロールで隠れる項目は、API が分からず、未対応。代わりに、右の一覧と台本の `detail` に、タブと項目名を必ず出す。

### 字幕・ナレーションの「ワードと位置が合っているか」
- **前**: 字幕「4にすると、最大値は約0.998になりました。」は、何を 4 にしたのかが無かった。台本の検証（`clean_narration_pair`）は、長さ・英字・コードしか見ていなかった。
- **後**:
  - `step_facts`: 手順の操作文・ツール結果から、ノード名・パス・パラメータ名・値を取り出す（記録に `changes` があれば、それを優先）。
  - `ensure_target`: 解説・字幕に、対象の名前（ノード名と、パラメータ名のどれか。つなぐ手順は両端のノード）が無ければ、先頭に 1 文を足す（例: 「noise1の「Element Size」を、4にします。」）。読み上げはカタカナ、字幕は元のつづり。長さの上限を超えるときは、末尾の文を落とす。定型の解説にも同じ。
  - プロンプトに、規則 21〜24 を追加（最初の文で対象を言う／数字でなく表示名／消すと言う／ノードを作る目的）。モデルへの入力に、「対象ノード」と「変更」（タブ・前・後）を足した。
  - 検査: `missing_targets`、`dangling_value_sentences`（「4にすると」から始まる文。前の文で対象を言っていれば数えない）、品質チェッカー（下）。
  - 根拠: `test_video_quality.py`（TargetInNarrationTest ほか。実験の字幕そのものを使って、前は対象が無い→後は足される）。
- **状態**: 一部。語と、台本の手順の対応は検査できる。字幕の表示時刻と画面の動きの同期は、動画エンジン側（音声から決まる）なので、検査していない。その他の節（「パラメータを動かして確かめよう」など）の「4にすると」は、自動では直せず、警告（`dangling_value`）にとどめた。

### パラメータ調整の細かいところ・どの部分を作業するかを、動画に出す
- **前**: スライドの短い文は、操作文の 1 行目だけ。ノードの階層・タブ・変更前→後・目的は、出なかった。メニューは数字（「2 → detail」）で出ていた。
- **後**: 台本の手順に、次を足した。
  - `points`（画面に出す 2 行）: 1 行目「geo1/noise1 › Code › Run Over」（長いときは前を「…」にして、項目名を残す）、2 行目「Points → detail」。消す手順は「paper_blast を消す」。
  - `detail`（新しいキー）: `action` / `node` / `node_path` / `location`（タブ › 項目）/ `changes`[{label, name, tab, old, new, code}] / `purpose` / `remove`。
  - `source`（新しいキー）: `claude` / `template`。
  - チェックボックスは「オン／オフ」、メニューは表示名で言う（`display_value`）。ただし、表示名は、記録に `kind` と `menu_labels` がある場合だけ（下の「未対応」）。
  - 根拠: `SlideDetailTest`、`AssembleKeepsTargetsTest`、`DisplayValueTest`。
- **状態**: 一部。変更前の値と、チェックボックス・メニューの種別は、`houdini_tools.py`（担当外）が記録に入れないと、取れない。今は、操作文から取れる範囲（ノード・項目名・新しい値）だけ。

### 動画の品質に差がありすぎる → 品質チェッカー
- **前**: 書き出す前の検査が無かった。
- **後**: `video_script.check_video_quality(script, steps)`（Houdini・Claude に依存しない）。手順ごとに、次を調べ、`{"ok", "errors", "warnings", "infos", "issues": [{"step", "level", "code", "message"}]}` を返す。`build_script` が、台本の `quality` に書き、状態の文に「品質チェック: 要修正N件・注意N件」を足す。`format_quality_report` で、画面に出す行にできる。
  - error: `no_visual`（画面の素材が無い）、`diagram_unreadable`（ノード名 12pt 未満・収まっていない）、`target_not_named`、`dangling_value`、`delete_wording`
  - warn: `no_target_view`、`image_small`（幅 1280px 未満）、`code_hidden`、`code_not_enlarged`、`numeric_choice`、`subtitle_long`（字幕 1 文が 60 文字超）、`sources_empty`、`sources_duplicate`
  - info: `detail_missing`、`template_fallback`、`overview_dense`
  - 根拠: `QualityCheckerTest`（12 件）。
- **状態**: 一部。台本の段階で直せるもの（対象の名前）は、`assemble_script` が先に直す。ほかは、警告として出す。書き出しを止める（ゲート）かは、呼び出し側（`tutorial_view.py`、担当外）で、`script["quality"]["ok"]` を見て決める。

### 参照した情報源（出典）の重複／ギャラリーの「出典なし」
- **前**:
  - 重複: チュートリアル(.md)の「## 参考」は、検索結果の 1 件ずつ（同じ資料の別の断片も別の行）を出す（`tutorial_agent.py` の `source_lines`）。エンジンは、その行をそのままスライドにする（`script_composer.cpp::parseHoudiniReferenceItems`）。
  - 出典なし: 動画エンジン（`RAGReel/engine/src/main_cloudrag.cpp`）は、Houdini のチュートリアルから作るときは、検索の問い合わせをしないので、`response.sources` が空のまま、`detail.ragSources = response.sources` で、metadata.json に `"rag_sources": []` を書く。ギャラリー（`web/public/app.js::sourcesHTML`）は、空なら「出典なし」と出す。つまり、**原因は、アップロードの metadata に出典が入っていないこと（確認済み）**。
- **後**（送る側）:
  - `video_script.parse_md_sources` / `dedupe_sources`: 「## 参考」を読み、（資料名＋ナレッジ名）が同じものを 1 件にする（順番は最初に出た順。1 つでも引用されていれば `cited: true`）。台本（`<slug>_video_script.json`）の `"sources"` に書く。
  - `gallery_upload.merge_rag_sources` / `find_script_sources` / `upload_entry(sources=...)` / `upload_missing(tutorial_dirs=...)`: 送る metadata の `rag_sources` が空のときだけ、台本の `sources` を入れる（エンジンが自分で入れたものは、上書きしない）。
  - 根拠: `SourcesTest`、`GallerySourcesTest`（偽のギャラリーに送って、metadata に出典が入ることを確認。前は `[]`）。
- **状態**: 一部。送る側は完了。ただし、エンジンが自動アップロードするとき（`GALLERY_UPLOAD_URL`）は、エンジンが metadata を作るので、エンジン側が台本の `sources` を読むまでは、「出典なし」のまま。Houdini の「動画」タブの手動アップロードは、`tutorial_dirs` を渡せば、直る（呼び出し側は担当外）。md の「## 参考」自体の重複は、`tutorial_agent.py`（担当外）。

## 変更したファイル
- `houdini/python_panels/screen_capture.py`: 注目ノード中心のノード図・実画面の範囲、読める大きさの下限、長いコードのカード、タブの前面化、画像の補足情報
- `houdini/python_panels/video_script.py`: 対象の事実の取り出し・字幕に対象を入れる・スライドの `points` / `detail`・出典の重複除去・品質チェッカー・プロンプト（規則 21〜24、`purpose`）
- `houdini/python_panels/video_factory_bridge.py`: エンジンへ渡す手順の記録に `network_pages` / `capture` を追加（`manifest_entries`）
- `houdini/python_panels/gallery_upload.py`: 送る metadata に出典を入れる
- `houdini/tests/test_capture_readability.py`（新規）: 28 件
- `houdini/tests/test_video_quality.py`（新規）: 40 件
- `houdini/tests/test_video_script.py`: 解説に対象の名前を入れる fixture（`TARGETS`）に直した（新しい規則で、対象が無い解説は、先頭に足されるため）
- `houdini/tests/test_run_20261106.py`: 短い手順のテストの文を、対象（emit・merge1）を言う文に直した（同上）

## テスト
- `PYTHONIOENCODING=utf-8 uv run --with PySide6 python -m unittest houdini/tests/test_capture_readability.py houdini/tests/test_video_quality.py houdini/tests/test_video_script.py houdini/tests/test_video_progress.py houdini/tests/test_screen_capture_size.py houdini/tests/test_gallery_upload.py houdini/tests/test_run_20261106.py houdini/tests/test_graph_diagram.py houdini/tests/test_clip_20261106.py` → 200 件、すべて通る。
- 全体（`unittest discover -s houdini/tests`）: 722 件のうち 2 件が失敗（`test_package.InstallScriptTest` の 2 件。インストーラー側の別の担当の変更中の状態で、このタスクの変更とは無関係）。
- このテスト環境にフォント（日本語・Consolas）が無いので、描画の文字は豆腐になる。レイアウト（寸法・枚数・meta）だけ確認した。文字の見た目は、実機で要確認。

## 未対応・要確認（ユーザーの判断・実機確認が要るもの）

### 動画エンジン（RAGReel の C++。別の担当）へ渡すキー名
台本 `<slug>_video_script.json`（`--houdini-script`）:
- `"sources": [{"file": "Shelf tools", "namespace": "houdini22shelfindex", "cited": true, "similarity": 0, "excerpt": "", "numbers": [1, 3]}]`
  - キーは、metadata.json の `rag_sources` と同じ（`file` / `namespace` / `cited` / `similarity` / `excerpt`。`numbers` は元の番号）。**エンジンは、Houdini のチュートリアルのとき、`detail.ragSources` を、これから作る**と、ギャラリーの「出典なし」が直る（`app.js` は `cited` が true なら「活用」、false なら「検索のみ」と出す。`similarity` が 0 なら、点数は出さない）。「参照した情報源」のスライドも、ここから作れば、重複は出ない（`parseHoudiniReferenceItems` を、（title, db）で重複除去するのでも可）。
  - `cited` は、打ち切りの生成（バッジが無い）では、キー自体が無い。
- 各 `steps[]`:
  - `"points"`: 2 行（場所／変更前→後）。すでに使われているキー。
  - `"detail"`: `{"action": "create|set|code|connect|delete|cook", "node", "node_path", "location", "changes": [{"label", "name", "tab", "old", "new", "code"}], "more", "purpose", "remove"}`（新規。スライドの「どこを・何から何へ」に出せる）
  - `"source"`: `"claude"` | `"template"`（新規）
- `"quality"`: `{"ok", "errors", "warnings", "infos", "issues": [{"step", "level", "code", "message"}]}`（新規。エンジンは読まなくてよい）

手順の記録 `<slug>_screenshots.json`（`--houdini-screenshots`）:
- `"network_pages": ["…/step_003_network_p2.png", …]`（新規。長いコードの 2 枚目以降。**エンジンが、同じ手順のスライドで、順番に出す必要がある**）
- `"capture"`: `{"kind": "node_diagram" | "code_card", "nodes_shown", "nodes_total", "name_pt", "pages", "lines_total", "lines_hidden", …}`（新規。読まなくてよい）

### ギャラリー Worker（別の担当）
- 出典の形（変更なし）: アップロードの multipart の `metadata`（JSON 文字列）の `"rag_sources": [{"file", "namespace", "cited"（true/false。無いこともある）, "similarity", "excerpt"}]`。ギャラリー側のコードの変更は、不要（`cited` の表示は、すでにある）。`entry`（`manifest.json` の 1 件）の `source_tutorial`: `"houdini-tutorial:<md の名前>"` で、台本を探す。

### 担当外のファイルでの対応が要るもの
- `houdini_tools.py::_capture_step_screenshot`: 手順の記録に `changes`（`label` / `name` / `old` / `new` / `code` / `tab` / `kind`（`toggle` / `menu`）/ `menu_labels`）を入れると、変更前→後・チェックボックス（オン／オフ）・メニュー（表示名）が、台本とスライドに出る（`video_script.step_facts` が読む）。今は、`old` がメニューの番号（「2 → detail」）のまま。`menu_labels` は `parm.parmTemplate().menuLabels()`、`kind` は `parmTemplate().type()` から取れるはず。また、`screen_capture.focus_network_on(container_path, log_path=..., focus_path=focus_path)` と渡すと、撮影前の最初の範囲合わせも、注目ノードになる（渡さなくても、`capture_network_editor` が合わせ直す）。
- `tutorial_view.py`: `GalleryUploadWorker` が `gallery_upload.upload_missing(..., tutorial_dirs=[tutorials_dir])` を渡すと、手動アップロードで出典が入る。台本の `quality`（`ok` が false）を、状態に出す・書き出しを止めるかは、ここで決める。`status` に、すでに「品質チェック: 要修正N件・注意N件」が入る。
- `tutorial_agent.py`: 「## 参考」の行を作るとき、`video_script.dedupe_sources`（title・db が同じ行を 1 件にする）を通すと、md にも重複が出ない。

### 実機で確認が要るもの（推測を含む）
- ネットワークエディタの範囲の数値（`MIN_VIEW_WIDTH = 7`、`MAX_VIEW_WIDTH = 14`、`VIEW_PAD_X/Y`）。ノード 1 個の幅を、約 1.0〜1.6 と推測した。
- ペインの幅が 1000px 未満のとき、描き直した図にする（`PANE_PREFER_DIAGRAM_WIDTH`）。実画面のほうが好ましい場合は、この値を下げる。
- `reveal_parm_tabs`（タブの切り替え）は、公式 API を使っているが、実機未確認。
- 描画の文字の大きさ（名前 12pt 以上、コード 16pt）が、動画（1080p）で読めるか。このテスト環境では、フォントが無く、豆腐になる。
- 「パラメータのスクロール・折りたたみで隠れた項目」は、API が分からず、未対応。
- 章の冒頭の全体図は、未対応（手順ごとのグラフの記録が無い）。

## 2026-11-20 追記: 動画の構成・実画面の撮影・撮影ノードの追加

実機の動画（`magic-trail-star-design_20261120`、41 手順）で確認した不具合と、直した内容。

### 動画の構成が中途半端だった（原因を確認済み）
- **原因**: 短縮版（`video_short.select_steps`）が、点数の高い順に 10 手順だけを選んでいた（1・7・12・13・17・19・27・31・34・41）。間の手順は動画に出ない。
  動画エンジンは、見出しを「手順 1〜10」と振り直す。冒頭・まとめは全体を語る。結果、途中で話が飛び、冒頭で約束した内容が出てこず、「手順 5」が手順書の手順 5 ではなかった。
- **後**: 手順を選んで捨てるのをやめ、**全部の手順を、連続した最大 12 場面にまとめる**（`video_short.plan_groups` / `group_steps`）。場面の終わりは、近くの cook（結果の確認）に寄せる。
  動画エンジンには、場面の最後の手順を渡す（画面は、その時点の状態）。台本には、場面に含まれる全操作を渡し（`この場面にまとめる操作`）、飛ばさず説明させる（規則 25）。見出しは「…（手順書の7〜12）」。
  Claude が使えないときの定型の解説も、場面の中の手順を順に並べる。
- 動画エンジン（C++）は変更していない（見出しの「手順 N」は、場面の番号のまま）。

### 実画面（ネットワーク・パラメータ）の画像
- ペインの最大化が**効いていなかった**（capture.log で「pane maximized」と出たのに、直後の幅は 612px のまま）。`time.sleep` と `processEvents` だけでは、Houdini の画面の更新が進まない。
  → `hou.ui.waitUntil` の中で、幅が実際に広がるまで待つ（`_wait_for_ui`）。広がらなければ「did not get wider」と記録する（次の撮影で、capture.log の
  `pane maximized for the capture (612px -> …)` が出れば成功）。
- 612px の画像を 1280px に引き伸ばしていた（ぼやけ）→ 引き伸ばさない。
- 上端のノードが、パス欄・メニューの帯に隠れて切れていた → 範囲を上に広げる（`NETWORK_TOP_OVERLAY`）。
- パラメータ画面の合成が上寄せで、下の 3 割が空いていた → 縦の中央に置く。
- ビューポート: 何も表示されていない手順は、格子だけの絵になっていた → 撮らない（`viewport_is_empty`。ノード画面を使う）。
  縦長のペインで、作ったものが小さく映った → 実際の大きさを測って、倍率を合わせ直す（`_refine_framing`。`mapToScreen` が使えない版では、従来の一律の倍率のまま）。**実機未確認**。

### Reference の説明: 版の取り違えを発見
- 点検（`dump_parms.py`）が、`hou.nodeType(category, "attribnoise")` で種類を探していた。名前が同じで版が複数あるとき、これは**古い版**を返す。学習者が作る版は `attribnoise::2.0`。
  → `createNode` で実際にできる種類で調べる。17 件が新しい版に変わり、**Mountain・Scatter・Smooth の 3 件が、古い版のパラメータ名で書かれていた**（公開済み）。書き直して、公開し直した。
- 撮影レシピの前後の検査を追加（`hython_shot.py`）: 点・面の数、大きさ、位置・色・法線のどれも変わらない絵は撮らない。
- 撮影ノードを 5 → 17 件に増やした（xform・peak・polyreduce・color・blast・delete・polywire・boolean・copytopoints・attribwrangle・pointjitter・attribnoise を追加）。
  前後の絵は目で確認し、効果が見えないもの（facet・smooth・resample・carve・bend）は、レシピから外した。説明は、レシピの検証済みの手順から作り直し、点検に通ったものだけ公開した。
