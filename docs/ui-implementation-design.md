# UI実装設計ドキュメント

**対象:** Unity EditorWindow / Houdini Python Panel / GAS WebApp / ローカルブリッジ  
**目的:** 実装済みの各コンポーネントの役割・構成・設計判断を説明する  
**更新日:** 2026-06-29

> このドキュメントは「これから作る設計案」ではなく「実際に動いているコードの説明書」です。

---

## 目次

1. [全体方針](#1-全体方針)
2. [Unity EditorWindow](#2-unity-editorwindow)
3. [Houdini Python Panel](#3-houdini-python-panel)
4. [GAS WebApp グラフ機能](#4-gas-webapp-グラフ機能)
5. [ローカルブリッジ](#5-ローカルブリッジ)
6. [GAS WebApp UI — ソース表示・管理機能](#6-gas-webapp-ui--ソース表示管理機能)
7. [セキュリティ設計](#7-セキュリティ設計)

---

## 1. 全体方針

### RAGには「クラウド版」と「ローカル版」の2種類がある

このシステムは、用途に応じてクラウドとローカルを切り替えられるように設計されています。

| モード | 接続先 | 主な用途 |
|--------|--------|---------|
| Cloud | GAS WebApp（Google のサーバー） | Notion に蓄積したゲーム開発ノウハウの検索 |
| Local | localhost:8766（自分のPC） | ローカルの Markdown ドキュメント検索 |

**切り替え方:** Unity / Houdini どちらの UI でも「Settings」タブからモードを切り替えられます。接続先が変わるだけで、質問の送り方・回答の受け取り方は同じです。

### 共通アーキテクチャ

```
[ユーザーが質問を入力]
        ↓
  Unity / Houdini UI
        ↓ HTTP POST（JSON）
  ┌─────────────────────────────────┐
  │ Cloud モード    │ Local モード   │
  │ GAS WebApp      │ localhost:8766 │
  │ （Google）      │ （ローカル）   │
  └─────────────────────────────────┘
        ↓
  Gemini / Claude が回答を生成
        ↓
  UI に回答を表示
```

---

## 2. Unity EditorWindow

Unity のエディタ拡張（Editor フォルダに置くスクリプト）として実装しています。Unity を使いながらエディタ上でそのまま RAG に質問できます。

### ファイル一覧と役割

```
Assets/Editor/RAGChatbot/
├── RAGMessage.cs          ← データの入れ物
├── IRAGClient.cs          ← クライアントの設計図（インターフェース）
├── CloudRAGClient.cs      ← Cloud モードの通信処理
├── LocalRAGClient.cs      ← Local モードの通信処理
├── RAGChatbotWindow.cs    ← メインウィンドウ（UI の親）
├── RAGGraphData.cs        ← グラフ用データの入れ物
└── RAGGraphView.cs        ← グラフ描画キャンバス
```

---

### RAGMessage.cs — データの入れ物

チャット履歴・検索結果・API レスポンスを表す単純なデータクラスです。

- `RAGMessage` — ひとつの発言（役割: user / assistant、本文テキスト）
- `RAGSource` — 検索でヒットしたソースページ（タイトル・スコア・DB名）
- `RAGResponse` — API からの返答全体（回答テキスト + ソース一覧）

---

### IRAGClient.cs — クライアントの設計図

クラウドとローカルで実装が違っても、ウィンドウ側は同じコードで呼び出せるように「インターフェース」（約束事の一覧）を定義しています。

```csharp
public interface IRAGClient
{
    Task<RAGResponse> QueryAsync(string query, string dbKey);
    Task<bool> HealthCheckAsync();
}
```

**なぜインターフェースを使うか:** ウィンドウ側は「`QueryAsync` を呼べばいい」とだけ知っていればよく、相手がクラウドかローカルかを意識する必要がなくなります。モードを切り替えても `RAGChatbotWindow.cs` のコードを変える必要がありません。

---

### CloudRAGClient.cs — クラウドへの通信処理

GAS WebApp に HTTPS POST でリクエストを送り、回答を受け取ります。

- `UnityWebRequest` を使って HTTPS 通信（Unity 標準の HTTP クライアント）
- リクエスト本文: `{ "query": "...", "dbKey": "..." }` の JSON 形式
- レスポンスから `answer`（回答テキスト）と `sources`（参照ページ一覧）を取り出す

---

### LocalRAGClient.cs — ローカルブリッジへの通信処理

`localhost:8766` で動いているローカルブリッジサーバーに HTTP POST を送ります。

- `UnityWebRequest` を使って HTTP 通信（ローカルなので HTTPS 不要）
- リクエスト先: `http://localhost:{port}/query`
- ポート番号はデフォルト 8766（Settings タブで変更可能）

---

### RAGChatbotWindow.cs — メインウィンドウ

IMGUI（Unity の古い UI システム）で作られたエディタウィンドウ本体です。3つのタブで構成されています。

```
[Chat タブ]    [Graph タブ]    [Settings タブ]
```

**主な処理:**

- `OnEnable()`: ウィンドウが開いたときに呼ばれる。Settings に保存されたモード・URL・ポートを読み込んで `IRAGClient` を生成する。また Local モードの場合はブリッジプロセスを自動起動する
- `Chat タブ`: メッセージ入力欄・送信ボタン・会話履歴のスクロールビューを表示。`QueryAsync()` を呼んで非同期で回答を取得する
- `Graph タブ`: `RAGGraphView.cs` を使ってグラフを描画する。「更新」ボタンでグラフデータを取得する
- `Settings タブ`: GAS URL と通信ポートを入力欄で設定できる。値は `EditorPrefs`（Unity が管理するエディタ設定ファイル）に保存され、Unity を閉じても消えない

---

### RAGGraphData.cs — グラフ用データの入れ物

グラフを描画するために必要なデータ構造を定義しています。

- `GraphNode` — グラフ上の1点（ページ ID・タイトル・DB 名・座標）
- `GraphEdge` — 2つのノードを結ぶ線（ノード ID ペア・類似度スコア）
- `GraphData` — ノード一覧とエッジ一覧をまとめたもの（API レスポンスの形と対応）

---

### RAGGraphView.cs — グラフ描画キャンバス

IMGUI の低レベル描画 API を直接使ってグラフを描画しています。グラフ描画ライブラリは使わず、すべて手書きです。

**描画方法:**
- エッジ（線）: `GL.LINES` で直線を描画。類似度スコアが高いほど不透明度が高い
- ノード（点）: `EditorGUI.DrawRect` で矩形を描画（丸ではなく正方形）。DB の種類によって色を変えている

**操作の実装:**
- パン（画面全体を移動）: 背景をドラッグすると `_panOffset`（移動量）が更新される
- ズーム: スクロールイベントで `_zoom`（倍率）を増減させ、描画時に座標に掛ける
- ノード選択: クリック位置と各ノードの座標を比較して最も近いノードを選択状態にする

---

## 3. Houdini Python Panel

Houdini の Python パネル（ドッキング可能なウィンドウ）として実装しています。PySide6（Python 用 GUI ライブラリ）を使っています。

### ファイル一覧と役割

```
houdini/python_panels/
├── rag_chatbot.py    ← メインパネル（Chat / Graph / Settings タブ）
└── graph_view.py     ← グラフ描画キャンバス
```

---

### rag_chatbot.py — メインパネル

Unity 版と同じく3タブ構成です。ただし Python の GUI なので実装方法が違います。

**タブ構成:**

```
[Chat タブ]    [Graph タブ]    [Settings タブ]
```

**QueryWorker（QThread）:**

Python の標準的な HTTP リクエストは「待っている間 UI が固まる」という問題があります。これを防ぐために `QThread`（別スレッドで処理を走らせる仕組み）を使って非同期でリクエストします。

```
ユーザーが送信ボタンを押す
  ↓
QueryWorker（別スレッド）が起動
  ↓ 別スレッドで HTTP リクエスト送信・待機
  ↓ 完了したらシグナルで結果を UI スレッドに通知
UI スレッドが回答を表示（UI は固まらない）
```

**BridgeStartWorker（QThread）:**

Local モードを選択したとき、ローカルブリッジプロセスを自動起動します。起動処理も別スレッドで行うため、UI を妨げません。

**設定の保存先:**

`%USERPROFILE%\.houdini\rag_chatbot_config.json` に JSON 形式で保存します。Unity の `EditorPrefs` に相当するものが Houdini にはないため、自前で JSON ファイルを読み書きしています。

---

### graph_view.py — グラフ描画キャンバス

PySide6 の `QGraphicsView` / `QGraphicsScene` を使ってグラフを描画しています。Unity 版よりもリッチな表現が可能です。

**主なクラス:**

- `NodeItem`（QGraphicsEllipseItem の拡張）: グラフ上のひとつのページを表す円形ノード。DB の種類によって色が変わる。マウスホバーで拡大・クリックで詳細表示
- `EdgeItem`（QGraphicsLineItem の拡張）: 2ノード間の類似度を表す線。スコアが高いほど線が濃く（不透明度が高く）なる
- `RAGGraphView`（QGraphicsView の拡張）: ノードとエッジをまとめたキャンバス全体。マウスドラッグでパン、ホイールでズームを実装している

**グラフデータの取得:**

`GraphFetchWorker`（QThread）が `/graph` エンドポイントに非同期でリクエストを送り、受け取ったデータを `NodeItem` / `EdgeItem` として描画します。

---

## 4. GAS WebApp グラフ機能

GAS（Google Apps Script）側でグラフデータを計算して返す機能です。`scripts/gas_cloud_rag.js` に実装されています。

### buildGraphData_() — グラフデータ計算の本体

「`_`（アンダースコア）がついた関数」は GAS の内部関数で、ブラウザから直接呼び出せません（後述の `getGraphData()` 経由で呼ぶ）。

**処理の流れ:**

```
1. RAG_Index シートを開く
2. 各ページの「代表埋め込み」を取得
     └─ page_id::0 チャンク（ページを分割した最初のかたまり）のベクトルを使用
3. 全ページ間でコサイン類似度を計算
4. スコアが 0.70 以上のペアを「エッジ（線）候補」とし、上位 3 件を残す
5. 結果を JSON に変換して返す
```

**コサイン類似度 0.70 という閾値について:** 実験的に決めた値です。低すぎると関係のないページにも線が引かれてグラフが複雑になり、高すぎると線がほとんど引かれません。

### getGraphData() — 公開ラッパー

```javascript
function getGraphData() {
    return buildGraphData_();
}
```

GAS では `google.script.run` でブラウザから呼び出せる関数名に `_` をつけられないため、`_` なしのラッパー関数を用意しています。

### CacheService による高速化

グラフデータは計算コストが高いため、GAS の `CacheService` を使って計算結果を **30分間キャッシュ** しています。

```
初回: 計算（30秒〜1分） → キャッシュに保存
2回目以降（30分以内）: キャッシュから即返却（数秒）
30分後: キャッシュ期限切れ → 再計算
```

### WebApp 側の D3.js グラフ描画

GAS の WebApp（ブラウザで開くチャット画面）にもグラフタブが実装されています。`D3.js`（JavaScriptのグラフ描画ライブラリ）の `force simulation`（物理シミュレーション）でノードを自動配置しています。

- **force simulation:** ノード同士が反発し、エッジで繋がったノードは引き合う「バネ」のような力をシミュレートして、自然な配置を自動計算します
- **操作:** ドラッグでノード移動、ホイールでズーム、ノードクリックで詳細表示

---

## 5. ローカルブリッジ

`scripts/rag_local_bridge.py` として実装されています。Python の `FastAPI` フレームワークで動く軽量なサーバーです。

**なぜブリッジが必要か:** ローカルの検索エンジン（`scripts/rag_service.py` 一式、ChromaDB ベース）は Python の関数として直接呼び出せますが、Unity（C#）や Houdini（別プロセスの Python）からは直接 import できません。ブリッジがその変換役を担います。

```
Unity / Houdini
  ↓ HTTP POST（Unity / Houdini が話せる言語）
rag_local_bridge.py（localhost:8766）
  ↓ LocalRAGClient（インプロセス直接呼び出し）
rag_service.py（ローカル検索エンジン、ChromaDB + 埋め込みモデル）
```

### 提供するエンドポイント一覧

| エンドポイント | 処理内容 |
|--------------|---------|
| `GET /health` | ブリッジが生きているかチェック。インデックス済みドキュメント数も返す |
| `POST /query` | 質問を受け取り、`rag_service.py` で検索 → Claude Haiku が回答を生成 → JSON で返す |
| `GET /graph` | rag_graph_export.py をサブプロセスとして実行し、グラフ JSON を返す |

### LocalRAGClient クラス

`scripts/rag_service.py` を**インプロセスで直接呼び出す**クラスです（旧 `MCPClient` の stdio JSON-RPC 方式を置き換えたもの）。

- `rag_service.py` の `create_rag_service_from_env()` で生成したサービスインスタンスを直接保持し、サブプロセスを起動しない
- 検索・インデックス確認などの処理は Python の関数呼び出しとして直接実行される（JSON-RPC のシリアライズ/デシリアライズが不要なため高速）
- `GET /health` は保持しているサービスインスタンスに対してドキュメント数取得を直接呼び出して生存確認する

### rag_graph_export.py の呼び出し

`GET /graph` は `rag_graph_export.py` を `uv run` でサブプロセス実行して結果を受け取ります。直接インポートせずサブプロセスにしている理由は、依存関係の分離（ブリッジとグラフ計算のライブラリ環境を分ける）です。

---

## 6. GAS WebApp UI — ソース表示・管理機能

### 6-1. 抽出度サマリー UI（情報抽出率の可視化）

RAG の回答がソースのどの割合を実際に引用したかを視覚的に示す UI です。GAS の `ragQueryInternal_()` が返す `extractionRate` / `extractionDetail` フィールドをクライアント側で描画します。

**ソースヘッダー部分**

```
📎 参考情報 4件  💡 抽出度: 2/4 (50%) ▾
```

- `📎 参考情報 N件`: 検索でヒットしたソース数
- `💡 抽出度: X/Y (ZZ%)`: LLM が実際に引用したソース数 / ヒット総数
- `▾`: ソース一覧の折りたたみトグル

**プログレスバー**

```css
.extract-bar  { height: 4px; background: #e2e8f0; border-radius: 2px; margin: 4px 0; }
.extract-fill { height: 100%; background: #6366f1; border-radius: 2px; }
              /* width は抽出率(%) を inline style で設定 */
```

**ソースごとの引用バッジ**

| クラス | 表示テキスト | 背景色 | 文字色 |
|--------|-------------|--------|--------|
| `.src-cited` | ✓引用 | `#dcfce7` | `#16a34a` |
| `.src-not-cited` | 未引用 | `#f1f5f9` | `#94a3b8` |

**データフロー**

```
GAS: parseExtractionRate_() → ragQueryInternal_()
  ↓ レスポンス
{ extractionRate: 0.5, extractionDetail: [true, false, true, false] }
  ↓ クライアント JavaScript
抽出度サマリー文字列を組み立て → プログレスバー width を設定
各ソースに .src-cited / .src-not-cited バッジを付与
```

`extractionDetail` は各ソースが引用されたか (`true`) / されていないか (`false`) の配列で、インデックスがソース一覧と対応しています。

---

### 6-2. 管理者 UI — API キーネームスペース編集モーダル

管理者画面の API キー一覧テーブルに「編集」ボタンを追加し、削除・再作成なしにネームスペース権限を変更できる UI です。

**「編集」ボタン**

各 API キー行の末尾に配置。クリックすると `openEditNs(preview, currentNs)` を呼び出します。

**モーダル構造**

```html
<!-- オーバーレイ背景 + 中央ダイアログ -->
<div id="editNsModal" style="display:none; position:fixed; ...">
  <div class="modal-body">
    <h3>ネームスペース権限を編集</h3>
    <!-- 全 DB に対応したチェックボックス一覧 -->
    <label><input type="checkbox" value="tool_docs"> tool_docs</label>
    ...
    <button onclick="saveEditNs()">保存</button>
    <button onclick="closeEditNs()">キャンセル</button>
  </div>
</div>
```

**JavaScript 関数**

| 関数 | 処理 |
|------|------|
| `openEditNs(preview, currentNs)` | モーダルを表示。`preview` に編集対象キーを保持。`currentNs`（カンマ区切り文字列）を分解してチェックボックスを初期化 |
| `closeEditNs()` | モーダルを非表示にする |
| `saveEditNs()` | チェックされた値を収集し `google.script.run.adminUpdateKey(preview, newNs)` を呼び出す。完了後モーダルを閉じてテーブルを再読み込み |

**呼び出しパターン**

```javascript
// 保存時
google.script.run
  .withSuccessHandler(() => { closeEditNs(); location.reload(); })
  .withFailureHandler(e => alert('保存失敗: ' + e.message))
  .adminUpdateKey(editTarget, newNamespaces.join(','));
```

キーを削除・再作成する操作が不要になり、他のユーザーのアクティブセッションを中断せずにネームスペースを変更できます。

---

## 7. セキュリティ設計

### 秘密情報の保存ルール

| 情報の種類 | 保存場所 | 補足 |
|-----------|---------|------|
| Anthropic API キー | 環境変数のみ（`ANTHROPIC_API_KEY`） | コードに絶対書かない |
| Gemini API キー | GAS スクリプトプロパティのみ | GAS の設定画面から登録 |
| Notion API キー | GAS スクリプトプロパティのみ | 同上 |
| GAS WebApp URL | Unity: EditorPrefs / Houdini: JSON ファイル | 半公開情報。URL を知っていれば誰でも叩ける |
| ローカルブリッジのポート番号 | コードのデフォルト値（8766） | ローカルネットワーク内のみ到達可能 |

### .env ファイルを使わない理由

このプロジェクトでは `.env` ファイルを使用しません。`.env` ファイルは誤って Git にコミットされるリスクがあるためです。API キーはすべて OS の環境変数（システム設定から登録）または GAS のスクリプトプロパティに保存します。

### GAS WebApp URL のアクセス制御

GAS WebApp のデプロイ設定で「アクセスできるユーザー」を制限できます。

| 設定値 | 説明 |
|--------|------|
| 自分のみ | Google ログイン必須。個人利用向け |
| 全員（Googleアカウント必要） | チームメンバーに共有する場合 |
| 全員（Googleアカウント不要） | 公開する場合。URL を知れば誰でも使える |

Unity / Houdini クライアントはリクエスト時に認証トークンを送らないため、現状は「全員（Googleアカウント不要）」相当で運用しています。
