# 別のPCへの導入手順（1枚）

**RAGReel Tutorial（Houdini パネル）＋ RAGReel（動画エンジン）** ／ 所要時間: 約10分 ／ 管理者権限: 不要 ／ 見直し: 2026-11-17（実証実験の結果を反映）

## 1. 用意するもの

| もの | 中身 |
|---|---|
| `RAGReelTutorial-<版>.zip` | Houdini のパネル本体（Python ファイルと `install.cmd`） |
| `RAGReel-Setup-1.1.0.exe` | 動画エンジン（動画を作る PC だけ） |
| 接続先の **URL** | 運営から。どの PC も同じ |
| **API キー** | その PC 用に、管理画面で**新しく発行**する（発行時に1度しか表示されません） |
| Houdini | 21.0 以降（22.0 を含む）／ Windows 10・11（64ビット）／ インターネット接続 |

> **やってはいけないこと:** 元の PC の `~\.houdini\rag_chatbot_config.json` をコピーしない（API キーが入っています）。

## 2. 手順

1. **動画を作るなら、先に** `RAGReel-Setup-1.1.0.exe` を実行する。ウィザードの指示どおりに進めるだけ（「自分だけ」へのインストールで可）。音声ソフト（VOICEVOX など）は要らない。
2. zip を好きな場所に**すべて展開**する（zip を右クリック →「すべて展開」）。**zip の画面の中から `install.cmd` を開かない**（他のファイルが無いため、失敗します）。
3. 展開したフォルダの **`install.cmd` をダブルクリック**する。「Windows によって PC が保護されました」と出たら、「詳細情報」→「実行」。
4. 聞かれたら **URL** と **API キー**を入れる（キーは画面に出ない）。空のまま Enter でもよい（あとでパネルの「接続・アカウント」で入れられる）。
5. 最後に出る**自己診断**を見る（次の節）。**`[NG]` が無ければ**、導入は成功。
6. **Houdini を起動**する（起動中だったときは、一度終了してから）。
7. **Windows メニュー → Python Panel → RAGReel Tutorial** を選ぶ。または、ペインのタブの「＋」→ **New Pane Tab Type** →（**Misc** の中の）「**RAGReel Tutorial**」。

> **Houdini を先に起動しておく必要はありません。** Houdini 本体が入っているのに `Documents\houdini22.0` がまだ無いときは、`install.cmd` がそのフォルダを作ります（以前は、ここで止まりました）。

### 自己診断の読み方

`install.cmd` の最後に、次のような一覧が出ます（同じ内容が `%LOCALAPPDATA%\RAGReelTutorial\install_report.txt` にも残ります）。**API キーや URL の値は表示しません**（「入っています」「空です」だけ）。

| 行 | 意味 | `[NG]` のとき |
|---|---|---|
| パネルのファイル / `rag_chatbot.py` / パネル定義 | 導入先（`%LOCALAPPDATA%\RAGReelTutorial`）に、ファイルが揃ったか | `install.cmd` をもう一度実行。ウイルス対策ソフトが書き込みを止めていないか確認 |
| **Houdini ○○.○ への登録** | **どの Houdini の版に登録したか**（`Documents\houdini21.0` / `houdini22.0` など、版ごと）。`packages\ragreel_tutorial.json` の場所も出る | 場所が違う可能性。「困ったとき」の「パネルが一覧に出ない」へ |
| 検出した Houdini 本体 | `C:\Program Files\Side Effects Software\Houdini 22.0.504` などの、入っている版と、登録の有無。**22.0.x は、ビルド番号が違っても、同じ `houdini22.0` を使う**（1回の登録で、すべての 22.0.x が対象） | 登録されていない版が出たら、`install.cmd -HoudiniVersion 22.0` のように版を指定して実行 |
| 設定ファイル | `~\.houdini\rag_chatbot_config.json` が、読める形で書けたか | もう一度実行（壊れた元のファイルは、`.backup_日時` として退避されます） |
| 接続先の URL / API キー | **入っている／空**（値は出さない）。`[注意]` は、あとから入力すればよい | パネルの「接続・アカウント」で入力して保存 |
| 保存先（`local_bridge_dir`） | チュートリアル・動画・記録の置き場所。書き込めるか。既定は `ドキュメント\RAGReelTutorial` | 書き込めない場所なら、「接続・アカウント」の「保存先フォルダ」を変更 |
| 動画エンジン | RAGReel が見つかったか（動画を作らないなら、`[注意]` のままでよい） | RAGReel を入れてから、もう一度実行 |

`install.cmd` の終了コードは、`[NG]` があれば 1、無ければ 0 です。

### 導入のときに選べること

```
install.cmd -HoudiniVersion 22.0      # 登録する版を指定（22 や 22.0.504 と書いても 22.0 として扱う）
install.cmd -DataDir D:\RAGReelData   # 保存先を指定（既定は ドキュメント\RAGReelTutorial）
install.cmd -Uninstall                # 取り除く
```

## 3. 動作の確認（3分）

1. パネルの右上の**ランプ**が「接続OK」になることを確認する（ならなければ、ランプをクリック → **接続・アカウント**で URL と API キーを確認）。
2. **Tutorial** タブにトピック（例: `岩を地面に散らす`）を入れ、レベル `basic` で**生成**を押す（2〜4分）。
3. プレビューが出たら**保存**する。「保存先未設定」とは出ずに、保存される（`ドキュメント\RAGReelTutorial\localRAG\tutorials\`）。RAGReel を入れていれば、続けて動画の生成が始まる。
4. **Movie**タブから、できた動画を開く。

### 動画の書き出しが遅いとき（画質の設定）

動画エンジンの既定は、**フル HD・30 fps**（`1080p30`）です。以前の既定（1280x720・15 fps）より、書き出しに**約 3〜4 倍**かかります（実機の長い動画での時間は、未測定）。遅くて困るときは、画質を下げます。

| 設定値 | 大きさ・fps | 書き出しの目安 |
|---|---|---|
| `1080p30`（既定） | 1920x1080・30 fps | 約 3〜4 倍 |
| `1080p15` | 1920x1080・15 fps | 約 2 倍 |
| `720p30` | 1280x720・30 fps | 約 2 倍 |
| `720p15` | 1280x720・15 fps | 以前と同じ |

**書き方:** パネルの設定ファイルには、この項目がありません。Windows の**ユーザー環境変数**で渡します（管理者権限は不要）。コマンドプロンプトで、次を実行し、**Houdini を終了して起動し直します**（Houdini が環境変数を引き継ぎ、動画エンジンに渡します）。

```
setx RAGREEL_VIDEO_PROFILE 1080p15
```

元に戻す（既定に戻す）ときは、環境変数 `RAGREEL_VIDEO_PROFILE` を削除します（「システム環境変数の編集」→「環境変数」）。動画エンジンを手で動かすときは、`--video-profile 1080p15` でも指定できます（こちらが優先）。知らない名前を書くと、既定（`1080p30`）になり、ログに警告が出ます。

## 4. 困ったとき

実証実験（2026-11-17）で起きたものを含みます。上から順に、当てはまるものを探してください。

| 症状 | 原因と対処 |
|---|---|
| 保存すると「保存先未設定」と出る | **以前の版の不具合**です。いまの版は、保存先が空でも、`ドキュメント\RAGReelTutorial` を自動で使います。最新の zip で `install.cmd` をやり直してください。それでも出るときは、パネル右上のメニュー（≡） →「**接続・アカウント**」→「**保存先フォルダ**」に、書き込める場所（例: ドキュメント内のフォルダ）を入れて保存。（以前は、案内の「設定タブ」が一般の利用者には表示されず、直せませんでした） |
| `RAGReel Tutorial` が、New Pane Tab Type の Misc にも、Windows → Python Panel にも出ない | 次の **A〜D を順に**確認する。**A** Houdini を一度終了して、起動し直したか（起動中に導入しても、読み込まれません）。**B** `install.cmd` の自己診断に、使っている版の「Houdini ○○.○ への登録」が **[OK]** で出ていたか。**C** 次の場所にファイルがあるか: `Documents\houdini22.0\packages\ragreel_tutorial.json`（使っている版の `houdiniXX.X`）。**D** ドキュメントが OneDrive に移されている PC では、場所が `OneDrive\ドキュメント\houdini22.0` のことがある。Houdini の Python Shell で `hou.homeHoudiniDirectory()` を実行し、出た場所の `packages` に、ファイルがあるか確認。無ければ、その場所に `ragreel_tutorial.json` をコピーする（導入先 `%LOCALAPPDATA%\RAGReelTutorial` を指す内容。別の PC のものをコピーしてはいけません。`install.cmd -HoudiniVersion 22.0` をやり直すのが確実です） |
| `ragreel_tutorial.json` が見つからない | Houdini の版のフォルダ名が違う（`houdini22.0` ではなく `houdini22.0.504` のようなフォルダは、使われません。Houdini は、`houdini` ＋ メジャー・マイナーだけの名前を使います）。または、ドキュメントの場所が違う（上の D）。`install.cmd -HoudiniVersion 22.0` で作り直す |
| パネルを選ぶと、エラー表示（赤い文字や、英語の長い文）が出る | 開けないときの確認（次の節）で、原因を調べる。パネルが開けなかったときは、**表示される画面に、原因（環境変数・探した場所・エラー）が出ます**ので、その内容をお知らせください |
| `install.cmd` の窓が、すぐ消える／「install.ps1 が見つかりません」 | zip の中から開いています。**すべて展開**してから、展開先の `install.cmd` を実行する |
| 「導入先の Houdini（21.0 以降）が見つかりません」 | 画面に、探した場所・見つかった `houdini*` フォルダ・見つかった Houdini 本体が出ます。Houdini を一度起動して終了するか、`install.cmd -HoudiniVersion 22.0` で版を指定する。Houdini 20.5 以前は対象外です（PySide6 が必要） |
| 「Windows によって PC が保護されました」 | 「詳細情報」→「実行」。それでも止まるときは、zip のプロパティで「許可する」にチェック → もう一度展開 |
| 「URL/APIキーが未設定です」・接続できない | パネルの右上のメニュー（≡） →「接続・アカウント」で、URL と API キーを入れて保存。誤りなら入れ直す（キーは再発行も可） |
| 設定ファイルが壊れた／空になった | `install.cmd` をやり直すと、作り直されます（元のファイルは、`.backup_日時` として残る）。パネルを開いたまま導入したときは、パネルを開き直す |
| 動画の書き出しが遅い | 上の「動画の書き出しが遅いとき（画質の設定）」で、`1080p15` や `720p15` にする |
| 動画が作られない | 「接続・アカウント」→「動画・ギャラリー」の `Video Factory exe` のパスを確認（RAGReel を入れると自動で入る）。入っていなければ RAGReel を入れてから、`install.cmd` をもう一度実行 |
| ギャラリーに載せる（実証実験） | 同じ「動画・ギャラリー」に、運営から受け取った**ギャラリーの URL とアップロードトークン**を入れて保存 |
| 更新したい | 新しい zip で、手順2〜6をやり直す（設定は残る） |
| 取り除きたい | `install.cmd -Uninstall` ／ RAGReel は「アプリと機能」から |

## 5. パネルが開けないときの確認（Houdini の Python Shell）

Houdini の **Windows → Python Shell** を開き、次を**1行ずつ**実行します（`hou` は最初から使えます）。

```python
import os, sys
print(hou.applicationVersionString())                          # 使っている Houdini の版（例: 22.0.504）
print(hou.homeHoudiniDirectory())                              # 設定フォルダ。packages\ragreel_tutorial.json は、この下にある必要がある
print(os.environ.get("RAGREEL_TUTORIAL_HOME"))                 # None なら、パッケージが読み込まれていない
print([p for p in hou.houdiniPath() if "RAGReel" in p])        # 空なら、パッケージが読み込まれていない
print([p for p in sys.path if "RAGReelTutorial" in p])         # 空なら、Python の探す場所に入っていない
print(hou.pypanel.interfaceByName("RAGReelTutorial"))          # None なら、パネル定義が見つかっていない
import rag_chatbot                                             # ここで出るエラーが、開けない原因
```

| 結果 | 意味と対処 |
|---|---|
| `homeHoudiniDirectory()` の場所に、`packages\ragreel_tutorial.json` が無い | 登録先が違う。`install.cmd -HoudiniVersion 22.0` をやり直すか、その場所の `packages` に、`ragreel_tutorial.json` を置く |
| `RAGREEL_TUTORIAL_HOME` が `None` | パッケージが読み込まれていない。Houdini を終了して起動し直す。それでも `None` なら、上の `packages` の場所を確認 |
| `RAGREEL_TUTORIAL_HOME` はあるが、`sys.path` が空 | Houdini を起動し直す（`PYTHONPATH` は、起動時に決まる） |
| `import rag_chatbot` で `ModuleNotFoundError: No module named 'PySide6'` | Houdini 21 より前の版。対象外 |
| `import rag_chatbot` で `ModuleNotFoundError`（別の名前、例: `panel_nav`） | 導入先のファイルが足りない。最新の zip で `install.cmd` をやり直す |
| `import rag_chatbot` がエラーなく終わる | Python 側は正常。`hou.pypanel.interfaceByName(...)` が `None` なら、`houdini\python_panels\RAGReelTutorial.pypanel` が読まれていない（`houdini_path` に `RAGReel` が出ているか確認）。Houdini を起動し直す |

問い合わせるときは、**この出力**と、`%LOCALAPPDATA%\RAGReelTutorial\install_report.txt` を添えてください。どちらにも API キーは含まれません（`rag_chatbot_config.json` そのものは、送らないでください）。

## 6. 版が違うときの確認のしかた（22.0.429 / 22.0.459 / 22.0.504）

> **状態: 未対応（実機での確認が、まだできていません）。** 開発側に実機が無いため、版ごとの動作比較は、実施していません。次の欄は、**確認するときの手順と、記録の書式**です。

- 22.0.x は、ビルド番号が違っても、設定フォルダは同じ `Documents\houdini22.0` です。**1 回の登録（`install.cmd`）で、すべての 22.0.x に効きます**（自己診断の「検出した Houdini 本体」に、版ごとの登録の有無が出ます）。
- 版ごとに、次をやって、結果を記録してください。

| 版 | 開けるか（手順 7） | Tutorial の生成 | Guide（ノードの強調） | 動画 | 備考 |
|---|---|---|---|---|---|
| 22.0.429 | 未確認 | 未確認 | 未確認 | 未確認 | |
| 22.0.459 | 未確認 | 未確認 | 未確認 | 未確認 | |
| 22.0.504 | 未確認 | 未確認 | 未確認 | 未確認 | |

1. **Help → About Houdini** で、版（ビルド番号）を確認する（Python Shell の `hou.applicationVersionString()` でも同じ）。
2. 手順7でパネルを開く。開けなければ、上の「パネルが開けないときの確認」の出力を記録する。
3. Tutorial タブで、同じトピック・同じレベルで生成し、保存まで通るか確認する。
4. Guide タブで「この手順を案内」を押し、ノードが選ばれて、画面に収まるか確認する。
5. 版によって違いがあったら、版・症状・Python Shell の出力を、運営に知らせる。

詳しくは [manual-houdini-tutorial.md](manual-houdini-tutorial.md) と [manual-ragreel.md](manual-ragreel.md)。
