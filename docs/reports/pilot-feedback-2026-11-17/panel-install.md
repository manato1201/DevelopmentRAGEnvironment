# panel-install（前と後の差）

担当: パネルの画面構成・チャットタブ・導入手順。実機の Houdini と別 PC は無いため、確認できたこと（コード・テスト・一時フォルダでの install.ps1 の実行・公式サイトの HTTP 確認）と、推測を分けて書く。

## 項目ごとの差

### 「保存先未設定」のエラー（チュートリアルを保存できない）
- **前**:
  - 保存先は設定の `local_bridge_dir`。パネルが読むキーと install.ps1 が書くキーは**同じ**（`local_bridge_dir`。キー名の食い違いではない）。
  - 参加者の PC で空だった**直接の原因は、コードからは断定できない**。確認できた欠陥は次のとおり。
    1. **直す場所が、参加者には無かった**: 案内の「設定タブ（Local RAG）で Bridge Directory…」の「設定」タブは、`rag_chatbot.py` の `_apply_role_visibility` により、設定者（admin / editor）にしか表示されない。しかも欄は、折りたたまれた「Local RAG（開発者向け）」の中。写真のタブ（はじめに〜接続）にも「設定」は無い。文面の「DevelopmentRAGEnvironment のパス」も、参加者には通じない（`tutorial_view.py` 1010 行ほか）。
    2. **install.ps1 が、変な設定ファイルで失敗・取りこぼす**（変更前の install.ps1 を、一時フォルダで実行して確認）: 空のファイル・JSON の `null`・`[]` の設定ファイルでは、導入が **rc=1 で失敗**し、設定が空のまま（パッケージは書かれたあとなので、パネルは出るのに保存先は空、という状態になる）。空白だけの値（`"   "`）は、そのまま残る。別の PC のパスは、そのまま残る。
    3. **パネル側**: 設定ファイルが BOM つき・空・壊れ・`{ }` でないとき、`_load_config` が**黙って全部を既定（空）に戻す**（URL・キーも消えたように見える）。保存は `open("w")` で直接書くため、途中で失敗すると空のファイルが残り得る。さらに、パネルを開いたまま install.cmd を実行して、パネルで「保存」すると、手元の古い空の値が、インストーラーの入れた保存先を消す。
  - 再現: `houdini/tests/test_panel_config.py`（11 件が変更前に失敗）、`test_package.py` の新しいテスト。
- **後**:
  - ①パネルは、未設定（空・空白・欠け・壊れたファイル）のとき、**ドキュメント内の `RAGReelTutorial` を自動で作って使う**（`panel_paths.py` 新規 / `rag_chatbot._load_config`）。tutorial_view.py などの読み側は、`cfg["local_bridge_dir"]` に値が入るので、変更なしで効く。作れないときは、利用者向けの案内（接続・アカウント画面の保存先の下）を出す。Local モード（開発者）では、既定を使わない。設定済みの値は、そのまま使い、勝手にフォルダを作らない。
  - ②案内を利用者向けに: 「接続・アカウント」（全員に見える）に「保存先フォルダ」の欄・「保存先を開く」・いまの保存先の表示を移した。ヘルプにも「保存先未設定と出たら」を足した。Settings の Local RAG の欄は、「共通」の注記だけにした。
  - ③install.ps1: 空・空白・null・欠け・BOM・空ファイル・壊れた JSON・`{ }` でない JSON・別の PC のパス（そのフォルダも 1 つ上も無い）でも、止まらず `DataDir`（既定 `ドキュメント\RAGReelTutorial`）を設定する。設定は一時ファイルに書いてから置き換える。作れないときは、案内を出して続ける。
  - 設定の保存（`_save_config`）も、一時ファイル→置き換えにし、ファイルにインストーラーの保存先があって手元が空・既定のときは、ファイルの値を残す（`panel_paths.choose_to_save`）。読みは BOM つきも読む。読めなかった理由は、デバッグの記録に残す。
  - 確認: `test_panel_paths.py`（14 件）、`test_panel_config.py`（8 件）、`test_package.py` の `test_every_odd_config_still_ends_with_a_save_folder` ほか。
- **状態**: 完了（コードとテストの範囲）。実験 PC で空だった**真の原因は未確認**。参加者に「設定タブ」が無かったことと、install の失敗パターンは確認済み。
- **別担当への連絡**: `tutorial_view.py`（1010・1680・2382 行）と `guide_view.py`（236 行）の文面「設定タブ（Local RAG）で Bridge Directory（DevelopmentRAGEnvironment のパス）を設定してください」は、まだ開発者向けのまま。パネル側で既定を入れるので通常は出ないが、出るときは `panel_paths.STORAGE_HELP`（または「歯車 →『接続・アカウント』→『保存先フォルダ』」）に変えてほしい。

### 他 PC への導入手順の見直し（エラーの洗い出し）
- **前**: 洗い出せたもの（コードから）:
  1. `.pypanel` が `includeInToolbarMenu` だけ。**ペインのタブのメニュー（New Pane Tab Type）に出ない**。なのに案内は「New Pane Tab Type → Misc」と書いていた（「Misc に見つからない」の有力な原因。実機では未確認）。
  2. Houdini の設定フォルダ（`Documents\houdiniXX.X`）が無いと、導入が**そこで止まった**（Houdini 本体は入っているのに、未起動）。OneDrive に移されたドキュメントも探さない。
  3. 失敗しても、画面には PowerShell の英語の追跡が出るだけ。成功しても、どこに何を書いたか分からない。
  4. 版の指定は `22.0` だけ（`22`・`22.0.504` は一致しない）。Houdini 20.5 以前（PySide6 が無い）にも登録してしまう。
  5. install.cmd を zip の中から開くと、install.ps1 が無く、分かりにくい失敗になる。
  6. パネルが `import rag_chatbot` に失敗すると、素のトレースバックだけで、原因の手がかり（環境変数・探した場所）が無い。
- **後**:
  - install.ps1: 導入後に**自己診断**（ファイルの場所と数・`rag_chatbot.py`・パネル定義・**Houdini の版ごとの登録の成否**〈パッケージ JSON を読み直して、指す先のファイルまで確認〉・検出した Houdini 本体〈`Program Files\Side Effects Software\Houdini x.y.z`〉と登録の有無・設定ファイルが BOM なしで読めるか・`cf_url` / `cf_api_key` が「入っています／空です」〈値は出さない〉・保存先と書き込み可否・動画エンジン）を表示し、`install_report.txt` にも残す。`[NG]` があれば終了コード 1。
  - Houdini 本体はあるのに設定フォルダが無いときは、フォルダを作る（`-HoudiniVersion` 明示でも）。OneDrive のドキュメントも探す。見つからないときの案内は、探した場所・見つかった `houdini*`・見つかった本体・対処（`-HoudiniVersion 22.0`、`hou.homeHoudiniDirectory()`）を出す。版は `22`・`22.0`・`22.0.504`・`houdini22.0` を受け付ける。21 より前は対象外と表示して登録しない。
  - `.pypanel` に `includeInPaneTabMenu` を追加（両方のメニュー）。読み込み失敗時は、原因（`RAGREEL_TUTORIAL_HOME`・`rag_chatbot.py` の有無・`sys.path`・トレースバック）を画面に出す（ASCII のみ。日本語は `\u` エスケープ）。
  - install.cmd: install.ps1 が無いとき、展開を促して止める。終了コードを引き継ぐ。
  - 手順書 `install-other-pc.md`（と .html）: 手順（先に Houdini を起動しなくてよい）・自己診断の読み方・困ったとき（保存先未設定／Misc・Python Panel に出ない／`ragreel_tutorial.json` が見つからない／zip から実行／SmartScreen／設定が壊れた）・**Houdini の Python Shell での確認**（`import rag_chatbot` ほか、結果の読み方の表）・版の確認欄を追加。`README.txt`、`manual-houdini-tutorial.md`（と .html）も更新。
  - 確認: `test_package.py` に 20 件ほど追加（変更前の動きは `scratchpad\pi_before.py` で、4 パターンの失敗・取りこぼしを確認）。
- **状態**: 完了（コード・一時フォルダでの実行の範囲）。**実機で未確認**: `includeInPaneTabMenu` で New Pane Tab Type（Misc）に実際に出ること、OneDrive ドキュメントの PC での動作、`hou.homeHoudiniDirectory()` などの手順書のコマンド。

### Houdini のバージョン比較（22.0.429 / 22.0.459 / 22.0.504）
- **前**: 手順書に欄が無い。
- **後**: `install-other-pc.md` に「版が違うときの確認のしかた」の欄（確認手順と、版×項目の記録表）だけ作った。22.0.x は、ビルド番号が違っても設定フォルダは同じ `houdini22.0` なので、1 回の登録で全部に効くこと、自己診断が版ごとの登録を出すことを書いた。この開発 PC の Program Files には 21.0.700 と 22.0.459 があるのを、診断の検出で見たが、**動かしてはいない**。
- **状態**: **未対応**（実機が無く、版ごとの動作比較はできない）。

### チャットタブ: 外部 URL のリンクの表示
- **前**: 回答は `QLabel`（自動判定）に文字のまま出ていて、URL はクリックできない。回答に `<b>` などが入ると、リッチテキストとして解釈され得た。
- **後**: `node_links.linkify_html`。回答の `http(s)` URL と `[文字](URL)` をリンクにし、クリックで外部ブラウザ（`QDesktopServices`）で開く。`javascript:`・`file:`・`data:`・ユーザー名つき URL・空白入りなどは、リンクにせず、開かない（`is_safe_url`、開く直前にも再検査）。日本語の句読点・括弧の手前で URL を止める。文字はすべてエスケープ。`[文字](URL)` は、見せかけに気づけるようホスト名を添える。リンクに触れると行き先をツールチップで出す。ユーザー発言・システム文は、プレーン表示（タグにならない）。
  - 確認: `test_node_links.py`（29 件）、`test_panel_nav.py` の `test_urls_in_an_answer_are_clickable…`、`test_dangerous_links_are_never_opened`、`test_a_javascript_link_in_an_answer_is_not_a_link`。画面の見た目はオフスクリーンの画像で確認（このオフスクリーン環境には日本語フォントが無く、文字は四角で出る）。
- **状態**: 完了。

### チャットタブ: ノード名 → SideFX の公式ドキュメント
- **前**: 無い。三輪さんが作ったノードの外部リンクのデータは、リポジトリ内（`docs/`・`knowledge`・`localRAG`・`data`・Worker の `src`）を検索したが**見つからなかった**（RAG の出典にも URL の項目は無い）。
- **後**: 新規 `houdini/python_panels/node_links.py`（関数）、`node_link_data.py`（データ）、`houdini/update_node_links.py`（データの作り直し）。
  - データは、**公式の各章の一覧ページ**（`https://www.sidefx.com/docs/houdini/nodes/<章>/index.html`。sop・dop・obj・lop・vop・top・chop・cop2・cop・out・apex）に載っているリンクだけ（4058 件。2026-11-17 時点）。推測で作った URL は入らない。ランダム 60 件を HEAD で確認し、全件 HTTP 200。規則（`kinefx::rigpose` → `kinefx--rigpose`、ROP は `out`）は、既存の `cloudflare-rag-poc/src/houdiniContext.ts` と同じ。
  - 見つけ方: 複数単語の表示名（Pyro Solver、Attribute Wrangle、`Pyro Solver (Sparse)` など）はそのまま。**単語 1 つ**（Group・Merge・Null など、ふつうの英単語と同じもの）は、「Scatter ノード」「`Scatter`」「「Scatter」」のように印があるときだけ。バッククォートで囲んだページ名（`attribwrangle`）も。同名が複数の章にあるときは、直後の「(DOP)」→直前の「DOP の」→回答全体で多い章→SOP の順。最大 8 件。
  - 表に無い名前は、「〇〇 ノード」と書かれているときだけ、ページを作らず、公式サイトの検索（`https://www.sidefx.com/search/?q=…`。公式サイトの検索フォームの `q` で確認）のリンクにして、別の行に出す（最大 3 件）。
  - 回答の下に「公式ドキュメント: …」の行を出す（`rag_chatbot._add_rag_bubble`）。
- **状態**: 完了。**限界**: リンク先は、公式の最新版のページ（版ごとのページではない）。DOP 側にしか無い名前（一覧に無いもの）は、SOP の同名ページへ行く場合がある。単語 1 つの名前は、印が無いと拾わない（見落とす側に倒した）。

### 画面構成（タブを切り替えると並行して見られない／設定タブが同じ重さで目立つ）
- **前**: タブは はじめに / Chat / Docs / Guide / Tutorial / History / 動画 / (課題) / 接続 / (設定 / デバッグ) の 10 個ほどが同じ重さで並ぶ。
- **後**:
  - タブは はじめに / Chat / Docs / Guide / Tutorial / 動画（課題は参加者だけ）に絞った。History・接続・設定・デバッグは、右上の**歯車メニュー**に移した（`panel_actions` に歯車・戻るのアイコンを追加。回答下のアイコン操作と同じ流儀）。歯車の中の画面は、「← タブに戻る」つきで、タブの代わりに出る。設定・デバッグは設定者だけ（役割を失うと閉じる）。接続ランプのクリックでも「接続・アカウント」が開く。History の「動画を再生」、`/tutorial` は、タブの画面に戻って動く。
  - **並行して見る**: 歯車の「このパネルを別ウィンドウで開く」（`hou.ui.curDesktop().createFloatingPaneTab` + `setActiveInterface`。失敗したら、理由と手動の案内を出す）と、「並べて見る方法」（Houdini 公式ドキュメント「Panes」の、ペインのメニューの Split left/right・Split top/bottom、新しいタブのアイコン、Windows → New floating panel）。手順書にも記載。
  - 確認: `test_panel_nav.py`（24 件。タブの構成、歯車、役割による出し分け、戻る、ランプ、動画へ戻る、課題タブ、偽の `hou` での別ウィンドウ）。
- **状態**: 一部。**別ウィンドウ／別ペインで並べる方法は完了**（ただし `createFloatingPaneTab` の呼び出しは、**実機で未確認**。失敗しても案内が出る）。**1 つのパネルの中で、2 つのタブを並べて表示する機能は未対応**（案: 左右 2 分割の表示。各タブのウィジェットを、2 つの領域に分けて持つ作りが要り、変更が大きい）。
- **別担当への連絡**: `panel_info.friendly_error`（接続エラーの文）などに、「「接続」タブで…」という文面が残る。歯車の「接続・アカウント」に変えてほしい（`panel_info.py` は担当外）。

### 動画エンジンの既定（1080p30）に合わせた手順書
- **前**: 手順書に、書き出しの遅さと設定の書き方が無い。
- **後**: `install-other-pc.md` に「動画の書き出しが遅いとき（画質の設定）」を追加（4 つのプロファイルと目安、`setx RAGREEL_VIDEO_PROFILE 1080p15` と Houdini の再起動、`--video-profile` が優先、知らない名前は既定）。`manual-houdini-tutorial.md` の動画の項にも一文。Houdini から環境変数を渡す口: `video_factory_bridge.py` は `os.environ.copy()` に `extra_env`（ギャラリー用だけ）を足してエンジンを起動するので、**ユーザー環境変数は、そのまま引き継がれる**。設定ファイルに、プロファイルの項目は**無い**（追加は、担当外の `tutorial_view.py` / `video_factory_bridge.py` の変更になる）。
- **状態**: 完了（書き方は手順書のみ）。

## 変更したファイル
- `houdini/python_panels/rag_chatbot.py`: 歯車メニュー・タブの整理・保存先欄・リンク・設定の読み書き・文面
- `houdini/python_panels/panel_paths.py`（新規）: 保存先の決め方
- `houdini/python_panels/panel_nav.py`（新規）: 画面構成・別ウィンドウで開く・案内文
- `houdini/python_panels/node_links.py`（新規）: URL とノード名のリンク化
- `houdini/python_panels/node_link_data.py`（新規・自動生成）: 公式のノード一覧（4058 件）
- `houdini/update_node_links.py`（新規）: 上のデータの作り直し・実在確認（開発者用）
- `houdini/python_panels/panel_actions.py`: 歯車・戻るのアイコン
- `houdini/python_panels/docs_view.py`: 案内の文面
- `houdini/deploy_panels.py`, `scripts/build_houdini_package.py`: 新しいモジュールの登録・説明
- `houdini/package/install.ps1`, `install.cmd`, `RAGReelTutorial.pypanel`, `README.txt`: 導入の見直し
- `docs/guides/install-other-pc.md` / `.html`, `docs/guides/manual-houdini-tutorial.md` / `.html`: 手順書
- テスト: `test_package.py`（更新）、`test_panel_paths.py` / `test_panel_config.py` / `test_node_links.py` / `test_panel_nav.py`（新規）

## テスト
- `PYTHONIOENCODING=utf-8 uv run --with PySide6 python -m unittest discover -s houdini/tests`: **759 件 OK**（途中、他担当の編集中に 1 回だけ 3 件失敗したが、再実行で全通過）（担当外の追加を含む全体。baseline の 467 件から増加）。
- 本物の `~\.houdini\rag_chatbot_config.json` は読み書きしていない（テストは一時フォルダと `-ConfigPath` を使用。install のテストは `-HoudiniInstallRoot` も一時にして、この PC の本物の Houdini を見ない）。
- `houdini/tests/smoke_feedback_panels.py`: OK。`smoke_pilot_panel.py`: 116 行（`panel._sampler.samples >= 1`、pilot_panel の内部）で失敗。pilot 側（別担当の変更中）の話で、本体パネルの部分（課題タブ）までは到達していない。discover の対象外。

## 未対応・要確認（ユーザーの判断・実機確認が要るもの）
1. **実機確認**: `includeInPaneTabMenu` で New Pane Tab Type に出ること／`createFloatingPaneTab` による別ウィンドウ／OneDrive のドキュメントの PC／手順書の `hou.*` コマンド。
2. **Houdini 22.0.429 / 22.0.459 / 22.0.504 の比較**: 未対応（実機が無い）。手順書に確認欄のみ。
3. **「保存先未設定」の真の原因**: 実験 PC のログ（`install_report.txt`・`rag_chatbot_config.json` の有無と形）が無いと断定できない。次回の導入では、自己診断の出力を回収してほしい。
4. 1 つのパネル内での 2 タブ並置: 未対応（案のみ）。
5. 他ファイルの文面（`tutorial_view.py`・`guide_view.py`・`panel_info.py` の「設定タブ」「接続タブ」「Bridge Directory」）の更新。
6. 動画のプロファイルを、パネルの設定ファイルから渡したい場合の追加（`tutorial_view.py` / `video_factory_bridge.py`）。
7. 手順書と README は、zip を作り直して配布しないと、参加者に届かない（`uv run python scripts/build_houdini_package.py`）。
