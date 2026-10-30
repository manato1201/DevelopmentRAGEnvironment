# 第6回 Houdini パネルのコードを読む（Qt・スレッド・`hou`・配置とテスト）

**到達目標:** [図15](../../images/15-houdini-panel.svg) の構成を説明できる。Qt の**画面は、メインスレッドだけで触る**ことと、**通信は別スレッドで行う**ことの理由を言える。画面に依存しない部品と、その単体テストを足せる。**配置（コピー）して再起動する**手順を、間違えずにできる。
**前提:** 第1回、Python の基本（関数・クラス・`import`）。 **目安:** 4時間

---

## 1. 全体像

[![Houdini パネルの内部構成](../../images/15-houdini-panel.svg)](../../images/15-houdini-panel.svg)

Houdini の中に、Python で書いた**パネル**を埋め込んでいます。パネルは、**画面（Qt）**と、**画面に依存しない部品**と、**サーバーとの通信**に分かれています。

## 2. 基礎

### 2.1 Qt（PySide6）とは

**Qt** は、ボタンや入力欄のある画面を作る道具です。Houdini 21 以降は、Python から **PySide6** で使います。

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton

class Hello(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)              # 縦に並べる箱
        self._label = QLabel("こんにちは")        # 文字
        button = QPushButton("押す")             # ボタン
        button.clicked.connect(self._on_click)   # 押されたら、この関数を呼ぶ（signal/slot）
        layout.addWidget(self._label)
        layout.addWidget(button)

    def _on_click(self):
        self._label.setText("押されました")
```

- **ウィジェット**: 画面の部品（`QLabel`・`QPushButton`・`QLineEdit`・`QTabWidget`…）。
- **レイアウト**: 部品を並べる箱（`QVBoxLayout`＝縦、`QHBoxLayout`＝横、`QFormLayout`＝ラベルと入力欄）。
- **signal / slot**: 「何かが起きたら、この関数を呼ぶ」の結びつけ。`ボタン.clicked.connect(関数)`。
- **イベントループ**: 画面は、**1つのループ**が、クリックや再描画を順番に処理して動く。**このループを、長い処理で塞ぐと、画面が固まる**。

### 2.2 スレッド：通信は、画面の裏で

サーバーに質問を送ると、数秒〜数十秒かかります。これを**ボタンの関数の中で**待つと、その間、**画面が固まります**（Houdini 全体が反応しなくなる）。そこで、**別のスレッド（`QThread`）**で通信し、終わったら**signal で画面に知らせます**。

```python
class _CallWorker(QThread):                         # houdini/python_panels/pilot_panel.py
    finished_with = Signal(object, str)             # (応答, エラー文)
    def __init__(self, fn): super().__init__(); self._fn = fn
    def run(self):                                  # ← 別スレッドで動く
        try:    self.finished_with.emit(self._fn(), "")
        except Exception as exc: self.finished_with.emit(None, str(exc))
```

```python
def _call(self, fn, on_done, on_error=None):
    worker = _CallWorker(fn)
    def done(result, error):
        if worker in self._workers: self._workers.remove(worker)
        if error:
            self._message.setText(friendly_error(error))   # ← 画面を触るのは、ここ（メインスレッド）
            if on_error: on_error()
            return
        on_done(result)
    worker.finished_with.connect(done)
    self._workers.append(worker)       # ★終わるまで、参照を持ち続ける
    worker.start()
```

**守ること**:
1. **画面（ウィジェット）を触るのは、メインスレッドだけ。** 別スレッドから `setText` しない（落ちる・壊れる）。signal で、メインに戻す。
2. **`QThread` は、変数に持ち続ける**（`self._workers.append(worker)`）。ローカル変数のままだと、関数が終わった瞬間に**消されて、スレッドが途中で止まる**。
3. **通信の失敗は、握りつぶさず、利用者向けの文にする**（`friendly_error`）。生のエラーは、デバッグの記録（`panel_debug`）に残す。

### 2.3 タイマー

```python
self._tick = QTimer(self)
self._tick.timeout.connect(self._on_tick)
self._tick.start(1000)       # 1000ミリ秒ごとに、_on_tick を呼ぶ
```

「課題」タブの経過時間の表示（1秒ごと）と、cook エラーの採取（20秒ごと）が、これです。**タイマーの関数も、メインスレッドで動く**ので、**長い処理を入れると、画面が止まります**。だから、採取には**時間の上限（1秒）**を付けてあります（`pilot_task.py` の `SCAN_BUDGET_SEC`）。

### 2.4 `hou`（Houdini を操作する）

`hou` は、Houdini が提供する Python のモジュールです。**Houdini の中（または `hython`）でだけ**、`import` できます。

```python
try:
    import hou            # Houdini の外では、ImportError
except ImportError:
    hou = None            # 外では「測れない」（None）。0 とは区別する
```

- `hou.node("/obj")` でノードを取り、`node.allSubChildren()` で配下の全部、`node.errors()` でエラーを取る。
- **Houdini の外（単体テスト）では `hou` が無い**。だから、`hou` を**引数で渡す**作りにして、テストでは**偽物**を渡します（`ErrorSampler(hou)`・`scan_error_nodes(hou, …)`）。

### 2.5 画面に依存しない部品を、別ファイルにする

画面（Qt）のコードは、**Houdini が無いと、テストしにくい**。そこで、**計算・文言・送信内容**は、Qt を `import` しないファイルに置きます。

| ファイル | 中身 | テスト |
|---|---|---|
| `pilot_task.py` | エラーの採取（`ErrorSampler`）・途中経過の保存（`ProgressStore`）・文言・送信内容 | `houdini/tests/test_pilot_task.py` |
| `panel_info.py` | 出典の集計・エラーの言い換え（`friendly_error`） | `test_panel_debug.py`・`test_panel_info.py` |
| `tutorial_feedback.py` | 評価の保存・再送・集計 | `test_report.py` ほか |

画面（`pilot_panel.py`）は、これらを**呼ぶだけ**にします。

## 3. 配置と再起動（最大の落とし穴）

Houdini は、**`Documents/houdini22.0/python_panels/` の中の、コピー**を読みます。**リポジトリを直しても、コピーしなければ、実機に反映されません**（2026-09-26、約12日間の修正が届いていなかったことがありました）。

```bash
# リポジトリのルートで
uv run python houdini/deploy_panels.py 22.0 --check     # 何も書かず、差分だけ見る
uv run python houdini/deploy_panels.py 22.0 --pypanel   # 配置（上書き前に、自動でバックアップ）
# → Houdini を再起動する（起動中は、モジュールがキャッシュされたまま）
```

- 新しいモジュールを足したら、`deploy_panels.py` の `MODULES` に**名前を足す**（足さないと、コピーされず、`ImportError`）。
- `--pypanel` は、パネル本体（`rag_chatbot.py`）を、パネル定義（`default.pypanel`）に**埋め込み直す**。

## 4. テスト

### 4.1 単体テスト（Houdini なし）

```bash
uv run python -m unittest discover -s houdini/tests          # 全部（186件）
uv run python -m unittest houdini.tests.test_pilot_task -v   # 1ファイル
```

偽の `hou`（`FakeHou`・`FakeNode`）と、一時フォルダ（`tempfile`）、`unittest.mock` で、外部に出ずに動きます。

### 4.2 通しの確認（hython、画面を作る）

`hython` は、画面なしで動く Houdini の Python です。**`QT_QPA_PLATFORM=offscreen`** にすると、画面を出さずに Qt が動きます。

```bash
export QT_QPA_PLATFORM=offscreen
"C:/Program Files/Side Effects Software/Houdini 22.0.459/bin/hython.exe" houdini/tests/smoke_pilot_panel.py
# → "pilot panel smoke OK"
```

`smoke_pilot_panel.py` は、**偽のサーバー**（`FakeClient`）を差し込み、実際に `PilotTaskPanel` を作り、**ボタンの関数を呼んで**、事前アンケート → 開始 → 計測のやり直し → 送信の失敗と再送 → 終了 → やり直し → 再開、を通します。

> 単体テストは通るのに、画面の結びつけ（ボタン → 関数）が壊れている、ということがあります。**通しの確認**は、その検出のためです。

## 5. このプロジェクトでは

- 構成: [図15](../../images/15-houdini-panel.svg)。メインは `rag_chatbot.py`（タブを束ねる。「課題」タブは、既定で**非表示**。接続タブの「実証実験に参加する」で出す）。
- 通信: `rag_client.py` の `RAGClient`（`pilot_plan`・`pilot_session_start/end/reset`…）。`post_json` は、`urllib`（標準ライブラリだけ）で POST し、`Authorization: Bearer` を付ける。
- 生成の本体: `tutorial_agent.py`（Claude に道具を使わせる繰り返し。**最大 80 回**）と `houdini_tools.py`（`hou` を操作する道具。**サンドボックス `/obj/ai_tutorial_*` の中だけ**）。
- 画面の状態の保存: `panel_widgets.py` の `ui_state_get/set`（`~/.houdini/rag_chatbot_ui.json`）。課題の途中経過は、`~/.houdini/rag_pilot_progress.json`。

## 6. 演習

**演習 6.1（読む）** `pilot_panel.py` の `PilotTaskPanel._on_finish` と `_send_end` を読み、次に答えてください。(a) 「戻る」を押すと、何が変わるか。(b) 送信に失敗したあと、もう一度ボタンを押すと、アンケートの画面は、また出るか。(c) `surveySec` は、どこで計算されるか。

**演習 6.2（動かす）** 単体テストを全部動かし、通ることを確認してください。そのあと、`houdini/python_panels/pilot_task.py` の `PAUSE_MIN_SEC` を 40 から 10 に変えて、もう一度動かし、**どのテストが落ちるか**を見て、なぜか説明してください。**終わったら、元に戻す。**

**演習 6.3（書く）** `pilot_task.py` に、「経過秒を、`H:MM:SS` ではなく『12分』と短く言う関数 `format_short(seconds)`」を足してください。手順: ①`test_pilot_task.py` に先にテストを書く（`format_short(5) == "1分未満"`、`format_short(750) == "12分"`）②落ちることを確認 ③実装 ④通ることを確認。

**演習 6.4（考える）** 次のコードの問題を挙げてください。

```python
def _on_click(self):
    result = RAGClient(cfg).query(text)      # 数十秒かかる
    self._answer.setText(result["answer"])
```

**演習 6.5（確認する）** `uv run python houdini/deploy_panels.py 22.0 --check` を実行し、リポジトリと、配置済みのコピーの**差分**を読んでください（何も書き換わりません）。

## 7. つまずきやすい点

- **配置し忘れ・再起動し忘れ。** 「直したのに、変わらない」の第1の原因。
- **`import hou` が、単体テストで失敗する。** `try/except ImportError` で包む。`hou` を引数で渡す。
- **画面の文字が、日本語の絵文字・特殊記号で、表示されない。** Houdini のフォントに無い字がある（例: `⚠` が出ず、`▲` に変えた）。
- **`QThread` が、途中で消える。** 参照を持ち続ける（2.2 の 2）。
- **Windows で、日本語を含む複雑なコマンド（ヒアドキュメント）が崩れる。** スクリプトをファイルに書いてから実行する。

## 8. 確認問題

1. 通信を、別スレッドにする理由は？
2. 別スレッドから、画面を触ると、どうなるか？ どうすればよいか？
3. `hou` を、引数で渡す作りにする理由は？
4. 「直したのに、実機で変わらない」とき、最初に疑うことは？
5. `hython` と `QT_QPA_PLATFORM=offscreen` で、何ができるか？

## 解答の方針

- 6.1: (a) ダイアログが閉じ、課題は続く（終了は取り消される）。(b) 出ない。`_pending_end` に答えが残っているので、そのまま再送する。(c) `_send_end` で、「終了を押した時刻（`pressed`）」から現在までの秒（`time.monotonic()` の差）。
- 6.2: 「短い空きは中断として数えない」を確かめるテストが、10 秒の空きを数えて落ちる。
- 6.4: 通信で画面が固まる。別スレッドにして、signal で結果を受け取る。エラー処理も無い。
- 6.5: 差分が無ければ、配置は最新。あれば、`--pypanel` で配置して再起動。
