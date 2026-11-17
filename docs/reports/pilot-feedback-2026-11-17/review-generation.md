# review-generation（チュートリアル生成エンジンの確認）

担当ファイル: `houdini/python_panels/` の `tutorial_agent.py`・`houdini_tools.py`・`tutorial_review.py`・`graph_diagram.py`・`tutorial_feedback.py`、テスト `houdini/tests/test_generation_20261117.py`。
`lesson_design.py`・`token_usage.py`・`trial_pruning.py`・`tutorial_graph_simplify.py` は、今回の変更が無い（確認のみ）。`guide_mode.py`・`video_script.py`・`guide_view.py` は、読むだけ。

## ① 確認した範囲

- `tutorial_agent.py` の差分すべて: 仕上げの促し（`wrapup_stage`）・予備の4回・リトライ（`_call_api_cloudflare`）・`TransientApiError`・計測・環境変数（`RAG_TUTORIAL_EFFORT`）・手順書の自動補足の呼び出し。
- `houdini_tools.py` の差分すべて: 計測・約10秒クリップの遅延・自動整列・ネットワークボックス・近いパラメータ名・`purpose`/`changes` の記録・`finish_tutorial` の点検・`RAG_TUTORIAL_STRICT_STEPS`・note の差し戻し。
- `tutorial_review.py` の追加部分すべて（抜けの検出・自動補足・題材別の基準）。
- `graph_diagram.py`・`tutorial_feedback.py` の差分。
- 読む側との突き合わせ: `guide_mode.parm_value_info`（引数 = `parmTemplate()`、戻り値 = `kind`・`items`・`labels`・`int_menu`。呼び方と一致）、`video_script._clean_change`（キー名・型が一致）、`guide_mode.build_guide`（`guide["purpose"]` を優先して読む。一致）。
- 秘密の確認: API キーは `Authorization` ヘッダーにだけ使われ、監査ログ・metrics・進行表示・例外文のどこにも出ない（`api_unavailable`・`api_call`・`capture` のイベントも、数値と、応答本文の先頭 160〜300 字だけ）。`RAG_TUTORIAL_*` の環境変数は、不正な値でも例外にならない（効果は既定のまま）。ユーザーのパスワードを扱う箇所は、この範囲に無い。

## ② 見つけた不備と、直したこと

### 重大度が高い（費用）
1. **費用の上限（$5）を、救済の催促で超えて呼び続けられた**（`tutorial_agent.py::_run_loop`）。
   - 原因: 費用の確認は、ターンの終わりにだけあった。「何も作らず終了」「下書き未確定」「確定後に直さず終了」「finish 未呼び出し」の救済は `continue` で、その確認を通らない。上限を超えたあとでも、最大 7 回、API を呼べた（1回が $0.3〜1 なら、$2〜7 の超過）。この数の救済は、今回の変更（`rejected_stop`）で 1 種類増えた。
   - 直し: ループの先頭（API を呼ぶ前）に、`result.cost_usd > COST_LIMIT_USD` の確認を足した（予備の入口の直後）。
   - テスト: `CostLimitTest`（1回で上限を超える応答 → 呼び出しは 1 回で止まる／上限を外すと、救済で複数回呼ぶ＝確認が効いていることの対照／予備の 4 回も、上限を超えたら始まらない）。

### 安全性（手順書の自動補足）
2. **コード全文の囲いが、コードの中の ``` で壊れた**（`tutorial_review.py::operation_appendix`）。値に ``` があると、囲いが途中で閉じ、その先が地の文（Markdown）になる。記録の値は、モデルが資料から写した文字列を含み得るので、地の文になると、あとで読む側（動画の台本づくり・次の段の要約）が、指示として読む入口になる。
   - 直し: 囲いは、コードの中のバッククォートの並びより長くする（`_fence_for`）。`` `…` `` の中の値は、バッククォートを `’` に替える（`_inline`）。
3. **補足の長さの上限が、無い**（コード 1 つ 3,000 字で黙って切る・全体は無制限）。
   - 直し: 切ったときは「以下は省略: 全 N 文字のうち…」と書く。全体は 12,000 字までで、超えた分は「ここから先は省略しました」の 1 行にする。
4. **ランプ・キーフレームの値が、80 字で切られて、意味が変わった**（補足の目的に反する）。
   - 直し: ランプ・キーフレーム・式は 300 字まで。
5. **補足が、二重に足される恐れ**（`tutorial_agent.py::generate`）。手順書にすでに補足の見出しがあるときは、足さない（`APPENDIX_TITLE`）。
   - テスト: `AppendixSafetyTest`（囲いの衝突・バッククォート・長いコード・全体の上限・ランプ・指示文は囲いの中・二重にならない）、`GenerateEndToEndTest.test_a_steps_text_that_already_has_the_appendix_gets_no_second_one`。
   - 限界（直せない）: 記録のコードに、指示文が含まれていても、補足は、コードを書き換えない（再現に要るため）。囲いの中に入れて、地の文にはしない、までが限度。

### 自動整列・ネットワークボックス（`houdini_tools.py`）
6. **ロックされたアセットを `layout_network` の対象に直接指定すると、例外**（`_layout_targets` が、ルートをそのまま含め、`layoutChildren` が失敗）。直し: ルートがロックされていれば対象にしない。
7. **整列できない場所が 1 か所あると、`layout_network` 全体が失敗**。直し: コンテナごとに `try` し、整列できた分だけ報告する。
8. **`groups` の `nodes` が、リストでないと例外**（数値など）。直し: リストでなければ、その組を飛ばす。
9. **別の親にある同名のノードを、取り違えて箱に入れた**（パスの最後の名前だけを見ていた）。直し: パスなら、このコンテナの直下を指すときだけ使う（`_child_name_of`）。
   - テスト: `LayoutTest` に 6 件（ロックされた対象・失敗する場所・存在しないノード・壊れた groups・別の親・接続のたびの自動整列が失敗しても接続は成功）。

### `purpose`・`changes` の記録（`houdini_tools.py`）
10. **接続の手順の目的が、「つなぎ先ノードの目的」にならなかった**（`_purpose_for` が、接続のとき `node_path` を空にして、作成時に覚えた目的を引けなかった。報告書の説明と食い違い）。直し: 空にしない（覚えるのは、作成のときだけのまま）。テスト: `test_a_connection_uses_the_purpose_of_the_node_it_connects_to`。
11. **`changes` の `old_raw`・`new_raw` が、切られていなかった**（長いコードが、記録に二重に、無制限に入る。マニフェストの JSON が膨らむ）。直し: 値と同じ上限で切る。`truncated` は、前の値が長いときも立てる。テスト: `test_the_raw_values_of_a_long_code_are_cut_too`。

### その他
12. `tutorial_review.py` の題材「リグ」の正規表現 `ik\b` が、語頭の境界が無く、語末が ik で終わる語（例: 「Fabrik」「Nik」）に当たった。直し: `\bik\b`。
13. **常に通るテストを、失敗しうる形にした**（`StepRecordTest.test_the_parm_panel_tab_is_recorded`）。`assertIn("tab", …)` は、キーが常にあるので、何があっても通った。直し: パラメータをフォルダ「Settings」に入れ、`tab == "Settings"`、ガイドの `where` と一致、を確かめる。
14. 追加のテスト: リトライが、反復の数え方・費用を変えない（`test_a_retry_does_not_change_the_turn_count_or_the_cost`。5xx を 3 回挟んでも、`api_calls`・iteration・費用は、成功した 3 回の分だけ）。`RAG_TUTORIAL_STRICT_STEPS` に、空・不正な値を入れても、既定の動き。

### 確認して、問題が無かったもの
- 無限ループ: `_run_loop` は `range(1, 80 + 4 + 1)` で、必ず終わる。救済は、種類ごとに回数の上限がある（2・2・2・1）。予備は 4 回で、ノードを作ってあって、未確定のときだけ。促しの段階は、段階が上がったときだけ（最大 3 回）。リトライは、HTTP の一時エラーが最大 2 回（3 秒・8 秒）、通信断が 1 回で、どちらも、`while True` の中で、カウンターが必ず進む。リトライが失敗すると、`TransientApiError` → 途中経過で打ち切り（反復は進めない）。
- リトライは、`result.cost_usd`・`iteration` を触らない（上のテスト）。
- 429・認証エラーは、リトライしない（従来どおり）。
- `_auto_layout`: ロックされたアセット・60 個超・例外のすべてで、何もしないか、握りつぶす（生成を止めない）。存在しないノードは、`_resolve` の通常のエラー。
- `_make_network_boxes`: 1 つの箱の失敗で、残りを止めない。古い箱を作り直す（二重にしない）。
- `RAG_TUTORIAL_EFFORT`: 受け付けない値は、既定に戻る。大文字・前後の空白は許す。
- 秘密: 上記のとおり、出ていない。`abort_reason` は 120 字までで、Cloudflare へ送る metrics に入る（応答本文の先頭を含み得るが、キーは含まない）。

## ③ リファクタリング

大きな書き換えはしていない。追加した関数は、`_inline`・`_fence_for`（補足の組み立ての安全）・`_child_name_of`（グループのノード名の解決）だけ。補足の組み立ては、1 関数のまま（長さは増えたが、種類ごとに 1 ブロックで読める）。

## ④ 直していないもの

- **`video_script.py` が、記録した `purpose` を読んでいない**（読む側の問題。報告のみ）。`entry["purpose"]`・`entry["guide"]["purpose"]` を、どこでも読んでおらず、台本の `purpose` は、台本づくりのモデルの出力か、`_NODE_HELP`（定型文）から来る。記録した目的（モデルが書いたもの）を、`video_script.py` の `create` の手順の目的の第 1 候補にすると、生成側の努力が動画に出る。動画の担当が、`facts` に `purpose` を足して読むとよい。ガイド側（`guide_mode.build_guide`）は読んでいる。
- **リトライが、Worker の予算を二重に消費し得る**（通信断・タイムアウトの再試行は、サーバー側で処理が進んでいた場合）。ローカルの費用には、失敗した試行を数えられない（応答が無いので、usage が無い）。コードのコメントにも書いてあり、再試行を 1 回に抑えている。これ以上は、Worker 側の冪等キーが要る（担当外・設計の判断）。
- **記録のコードの中の指示文**: 上記 2 のとおり、囲いの中に入れるのが限度。コードの内容は、書き換えない。
- **題材「竜巻」の判定語**（「渦」・`vortex`）が広く、水の渦などでも、竜巻の基準（縦長の柱・漏斗）が出る。基準の確認は、1 回の差し戻しだけで、`pitfalls` に理由を書けば進める。語を絞ると、本物の竜巻を逃すので、そのままにした。
- **note の差し戻しの語**（`広がり…弱` など）の誤検出（「広がりは十分で、弱点は無い」）: 否定の語の判定が既にあり、差し戻しは最大 2 回なので、そのままにした。
- `houdini_tools.py` と `tutorial_agent.py` は、長大（約 2,900 行・約 2,050 行）。分割は、動きを変えない範囲でも差分が大きいので、今回はしない。

## ⑤ テストの結果

- 担当範囲: `test_generation_20261117.py` 96 件（確認前 75 件 + 21 件）、成功。
- 全体: `PYTHONIOENCODING=utf-8 uv run --with PySide6 python -m unittest discover -s houdini/tests` → **800 件、すべて成功**（確認前 759 件。他の担当の追加分を含む）。
- 実機（Houdini）での確認が要るもの（偽物では確かめられない）: ネットワークボックスの見た目、ロックされたアセットでの `layoutChildren` の挙動、メニューの表示名。
