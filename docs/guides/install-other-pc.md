# 別のPCへの導入手順（1枚）

**RAGReel Tutorial（Houdini パネル）＋ RAGReel（動画エンジン）** ／ 所要時間: 約10分 ／ 管理者権限: 不要

## 1. 用意するもの

| もの | 中身 |
|---|---|
| `RAGReelTutorial-<版>.zip` | Houdini のパネル本体（28 個の Python と `install.cmd`） |
| `RAGReel-Setup-1.1.0.exe` | 動画エンジン（動画を作る PC だけ） |
| 接続先の **URL** | 運営から。どの PC も同じ |
| **API キー** | その PC 用に、管理画面で**新しく発行**する（発行時に1度しか表示されません） |
| Houdini | 21.0 または 22.0 ／ Windows 10・11（64ビット）／ インターネット接続 |

> **やってはいけないこと:** 元の PC の `~\.houdini\rag_chatbot_config.json` をコピーしない（API キーが入っています）。

## 2. 手順

1. **動画を作るなら、先に** `RAGReel-Setup-1.1.0.exe` を実行する。ウィザードの指示どおりに進めるだけ（「自分だけ」へのインストールで可）。音声ソフト（VOICEVOX など）は要らない。
2. Houdini を**一度起動して、終了**する（`Documents\houdini22.0` を作るため。使い込んでいる PC では不要）。
3. zip を好きな場所に**展開**し、**`install.cmd` をダブルクリック**する。
4. 聞かれたら **URL** と **API キー**を入れる（キーは画面に出ない）。空のまま Enter でもよい（あとで**接続**タブで入れられる）。
5. 「完了しました」と出たら **Houdini を起動**する。
6. ペインのタブ「＋」→ **New Pane Tab Type** →「**RAGReel Tutorial**」を選ぶ。

## 3. 動作の確認（3分）

1. **接続**タブで、接続が通ることを確認する。
2. **Tutorial** タブにトピック（例: `岩を地面に散らす`）を入れ、レベル `basic` で**生成**を押す（2〜4分）。
3. プレビューが出たら**保存**する。RAGReel を入れていれば、続けて動画の生成が始まる。
4. **動画**タブから、できた動画を開く。

## 4. 困ったとき

| 症状 | 対処 |
|---|---|
| `RAGReel Tutorial` が一覧に出ない | Windows → Python Panel も確認。それでも無ければ Houdini を一度終了して起動し直す |
| 「URL/APIキーが未設定です」・接続できない | **接続**タブの URL と API キーを入れて保存。誤りなら入れ直す（キーは再発行も可） |
| 動画が作られない | **接続**タブ「動画・ギャラリー」の `Video Factory exe` のパスを確認（RAGReel を入れると自動で入る）。入っていなければ RAGReel を入れ直す |
| ギャラリーに載せる（実証実験） | 同じ「動画・ギャラリー」に、運営から受け取った**ギャラリーの URL とアップロードトークン**を入れて保存 |
| 更新したい | 新しい zip で、手順3〜5をやり直す（設定は残る） |
| 取り除きたい | `install.cmd -Uninstall` ／ RAGReel は「アプリと機能」から |

詳しくは [manual-houdini-tutorial.md](manual-houdini-tutorial.md) と [manual-ragreel.md](manual-ragreel.md)。
