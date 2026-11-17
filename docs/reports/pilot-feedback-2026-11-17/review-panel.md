# レビュー: panel（Houdini パネルの画面・ガイド・導入）

2026-11-17。担当ファイルの変更を読み、`install.ps1` は一時フォルダで実際に動かして確かめた。

## 1. 確認した範囲

- `rag_chatbot.py`: 設定の読み書き（`_read_config_file` / `_load_config` / `_save_config` / `_on_save_settings`）、歯車メニュー、チャットのリンク、デバッグ表示（秘密の扱い）
- `panel_paths.py` / `panel_nav.py` / `panel_info.py` / `panel_actions.py` / `docs_view.py` / `node_links.py` / `update_node_links.py`（`node_link_data.py` は読まず、形だけ確かめた）
- `guide_mode.py`（`resolve_step_target` ほか）/ `guide_view.py`（自動切り替え）/ `tutorial_view.py`（差分すべて）
- `houdini/package/`（`install.ps1`・`install.cmd`・`.pypanel`・`README.txt`）、`houdini/deploy_panels.py`、`scripts/build_houdini_package.py`
- `docs/guides/`（導入手順・使い方・ユーザーマニュアル）
- `install.ps1` の実行（`-DocumentsDir` `-InstallDir` `-ConfigPath` `-DataDir` `-HoudiniInstallRoot` をすべて一時フォルダにして、`-NoPrompt`。本物の設定ファイルには触れていない）。
  確かめた設定: なし・空ファイル・BOM つき・壊れた JSON・配列・別の PC のパス・使える保存先・空白つきの保存先・数値の保存先。2 回続けて実行（結果が同じか）、`-Uninstall`（2 回）。
- `deploy_panels.py` の `MODULES` と、パネルが import するモジュールの突き合わせ（足りないものは無かった）

## 2. 見つけた不備と、直したこと

| # | 不備 | 直したこと（ファイル・場所） | テスト |
|---|---|---|---|
| 1 | **保存先を、画面で空にして保存しても、ファイルにある古い値で上書きされ、空にできない**（`choose_to_save` が、手元の値が空のとき、常にファイルの値を残していた。さらに、手元の設定にもその値が入り、画面の表示とずれた） | `rag_chatbot._save_config(cfg, dir_edited=False)` を追加。利用者が画面で保存先を変えた・空にしたとき（`_on_save_settings` が、入力欄と手元の値の違いで判定）は、その値をそのまま書く。触っていないときだけ、インストーラーの値を守る（従来どおり）。保存後、入力欄を、いま使っている値にそろえる | `test_panel_config.test_clearing_the_folder_on_purpose_is_saved_as_empty` / `test_panel_nav.test_saving_tells_the_config_writer_only_when_the_folder_was_edited` |
| 2 | 壊れた設定ファイルを、保存で上書きすると、元の中身（API キーなど）が、手で直せない形で消える | `_save_config`: 壊れている・形が違うときだけ、上書き前に `.broken` として残す（空のファイル・読めないファイルは残さない） | `test_panel_config.test_a_broken_file_is_kept_as_a_copy_before_it_is_replaced` |
| 3 | **`install.ps1` が、実行のたびに、API キーの入った設定の控え（`.backup_日時`）を、増やし続けた**（2 回実行すると、同じ内容の控えが 2 つ。何度でも増える） | 設定が変わらないときは、控えを作らない。控えは、新しいものから 3 つだけ残す（`install.ps1` の「3. 設定ファイル」。控えの作成を、新しい内容を作ったあとに移した）。`docs/guides/manual-houdini-tutorial.md`（と html）の文面も合わせた | `test_package.test_reinstall_with_the_same_config_does_not_pile_up_backups` / `test_backups_are_pruned_to_the_latest_few` |
| 4 | `is_safe_url` が、向きを変える制御文字（U+202E など）・幅ゼロの文字を含む URL を通した（表示と行き先をずらせる。`[文字](URL)` の形で、リンクになり得た）。範囲外・数でないポート（`:99999`）も通した | `node_links.is_safe_url`: Unicode の分類が Cc / Cf / Zl / Zp の文字を含む URL は不可。ポートが不正なものは不可。あわせて、`_URL_RE` の、見えない文字で書かれていた範囲を、`\u0080-\U0010ffff` の書き方にした（動きは同じ） | `test_node_links.test_direction_control_characters_and_bad_ports_are_not_safe` / `test_linkify_does_not_link_a_markdown_url_with_control_characters` |
| 5 | 回答の下の「説明レベル／紹介した用語」の行が、書式の自動判定（AutoText）のままで、サーバーが返した文字の `<b>` などを解釈した | `rag_chatbot._add_rag_bubble`: `PlainText` にした | `test_panel_nav.test_the_explain_line_under_an_answer_is_plain_text` |
| 6 | ガイドのノード探し: 名前だけで探すとき、探索の上限（3000 個）で打ち切っても、見つかった 1 つを「唯一」として選んでいた（上限の先に、同じ名前がもう 1 つあるかもしれない = 当て推量） | `guide_mode._search_base`: 打ち切ったときは、名前での選択をせず、理由（「探索の上限に達した」）を出す | `test_guide_target.test_a_name_match_is_not_used_when_the_search_was_cut_short` |
| 7 | ガイドの自動切り替えが、利用者が **Chat など別のタブで入力中でも**、生成の完了で、Guide タブへ引き離した | `guide_view.GuideWidget.announce(..., from_index)`: 自動のとき、利用者が生成したタブ（Tutorial）にいないなら、切り替えず、タブに印（「Guide ●」）と文を出す。切り替えを明示したとき（`switch=True`）は、従来どおり | `test_guide_display.test_generation_does_not_pull_the_user_away_from_another_tab` / `test_an_explicit_switch_still_switches_from_another_tab` |
| 8 | 保存したとき、生成直後の手順（未保存）が、保存したものに置き換わると、見ていた手順の位置が、先頭に戻った | `guide_view.GuideWidget.select_saved`: 置き換えのときは、見ていた位置を戻す（`_restore_index`） | `test_guide_display.test_saving_keeps_the_step_the_user_is_on` |
| 9 | 「設定者に、設定タブで…」「接続タブの…」など、**もう無いタブ**を指す文が、`tutorial_view.py`（音声・ギャラリー・動画エンジンの案内）と `docs/guides/user-manual.md` に残っていた。ギャラリー・動画エンジンの設定は、いまは「接続・アカウント」にあり、全員が自分で入れられる | 文面を「歯車メニュー →「接続・アカウント」」に直した。`user-manual.md` の §9.2 の表を、歯車メニューの構成に書き直し、html を作り直した | （文面のみ。既存のテストが通る） |
| 10 | `update_node_links.py`: 公式サイトの文字を、そのまま Python のソースに書き出していた（名前に `"""` や改行があると、ソースが壊れる、または、コードが混ざる。書き出したファイルは、Houdini の中で実行される）。`urllib.error` の import も抜けていた | `_is_safe_entry`: ページ名は英数字と `_ . -` だけ、表示名は引用符・バックスラッシュ・`|`・改行・制御文字を含まないものだけを書き出す（いまのデータ 4000 件余りは、すべて通る）。`import urllib.error` を追加 | 新規 `test_update_node_links.py`（3 件） |

## 3. リファクタリング

- 「保存先のフォルダを用意できません…」の同じ文が、`tutorial_view.py` に 4 か所、`guide_view.py` に 1 か所あった → `panel_paths.SAVE_DIR_MISSING` にまとめた（動きは同じ）。
- `node_links._URL_RE` の、見えない文字の範囲を、エスケープの書き方に（動きは同じ）。

## 4. 直していないもの（理由）

- **`rag_client.py:114`** の「（設定タブで入力してください）」: 担当外のファイル。`panel_info.friendly_error` が、画面の文に直す経路は、先に「接続・アカウント」の文を出す。持ち主が、文面を直すとよい。
- **`pilot_panel.py` の docstring**（「接続タブの…」）: 担当外。画面には出ない。
- `install.ps1` の `-Uninstall` は、`-InstallDir` の中身を再帰的に消す。既定の値では安全だが、`-InstallDir` に、ドキュメントなどを指定すると、消える。内部用の引数で、利用者向けの手順には出ていないので、そのまま（変えるなら、`RAGReelTutorial` という名前のフォルダだけ消す、という検査を足す）。
- `install.ps1` は、毎回 `mode` を `cloudflare` に書き換える。開発者（Local モード）が再実行すると、Local → Cloudflare になる。以前からの動き（今回の変更ではない）で、配布版の前提（テスターは Cloudflare）に合うので、変えていない。
- `_load_config` / `_save_config` は、設定ファイルの全体を、手元の値で書く。パネルを開いたまま、別の手段で `cf_url` などを書き換えると、保存で戻る。保存先（`local_bridge_dir`）だけは守る作りで、ほかのキーは、以前から同じ。
- 「名前だけが一致する 1 つのノード」を示す動き（パスが違っても、唯一なら示す）は、仕様として残した（画面に、示したパスを出している。テストあり）。当て推量ではなく、「複数あれば決めない」が守られていることを、確かめた。
- 実機の Houdini が無いため、`panel_nav.open_in_new_window()`（`createFloatingPaneTab` / `setActiveInterface`）は、実機で未確認。失敗したときは、手動の方法を案内する作りになっている。

## 5. テストの結果

- Houdini: `PYTHONIOENCODING=utf-8 uv run --with PySide6 python -m unittest discover -s houdini/tests` → **806 件が通る**（開始時 759 件 + 他担当の追加分 + この担当で足した 10 件前後）。
- `install.ps1` の実行（一時フォルダ）: 全ケース終了コード 0。2 回目は、設定ファイルが 1 バイトも変わらない。`-Uninstall` は 2 回続けても、止まらない。設定ファイルの値（API キー）は、画面にも `install_report.txt` にも出ていない。
- 空・BOM つき・壊れた・配列・数値の `local_bridge_dir`・別の PC のパスのいずれも、保存先が、`Documents\RAGReelTutorial`（または、既存の使える値）になった。
