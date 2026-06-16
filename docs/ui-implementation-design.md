# UI実装設計ドキュメント

**対象:** Unity / Houdini / Web / Desktop アプリ  
**目的:** 各環境からCloudRAG（GAS + Gemini）およびLocalRAG（mcp-rag-server）を呼び出すUIの実装設計  
**更新日:** 2026-06-10

---

## 目次

1. [全体方針](#1-全体方針)
2. [Unity エディタ拡張](#2-unity-エディタ拡張)
3. [Houdini Python UIパネル](#3-houdini-python-uiパネル)
4. [Webアプリ（Vercel / GitHub Pages）](#4-webアプリ)
5. [デスクトップアプリ（Electron / Tauri）](#5-デスクトップアプリ)
6. [ラジアル / パイメニュー](#6-ラジアルパイメニュー)
7. [共通: GAS WebApp呼び出し仕様](#7-共通-gas-webapp呼び出し仕様)

---

## 1. 全体方針

### RAG参照先の使い分け

| UI環境 | 参照RAG | 理由 |
|--------|---------|------|
| Unity エディタ | CloudRAG（GAS） | ツール仕様・Unity公式ドキュメント系 |
| Houdini パネル | CloudRAG（GAS） | Houdiniリファレンス・共有ノウハウ |
| Webアプリ | CloudRAG（GAS） | ブラウザからLocalRAGには直接届かない |
| Desktop（Electron/Tauri） | LocalRAG（MCP） | 個人情報・チャット履歴・草稿参照 |
| Claude Desktop | LocalRAG（MCP） | 既存のMCP設定でそのまま使用 |

### 共通アーキテクチャ（Cloud系）

```
各UI → HTTP POST → GAS WebApp → Notion検索 + Gemini API → 回答
```

GAS WebAppのURLとdbKeyを渡すだけで全UI共通で動作する。UIごとに実装方法が違うだけでロジックは同一。

---

## 2. Unity エディタ拡張

### 概要

`EditorWindow` を使ってUnityエディタ内にチャットUIを実装する。Playモード中でも使えるよう `[ExecuteAlways]` の考慮は不要（EditorWindowはエディタ専用）。

### ファイル構成

```
Assets/
└── Editor/
    └── RAGChatWindow/
        ├── RAGChatWindow.cs      ← メインウィンドウ
        ├── RAGClient.cs          ← GAS WebApp 呼び出し
        └── RAGChatWindow.uss     ← UI Toolkit スタイル（任意）
```

### RAGChatWindow.cs

```csharp
using UnityEngine;
using UnityEditor;
using System.Collections.Generic;

public class RAGChatWindow : EditorWindow
{
    // ===== 設定 =====
    private const string GAS_ENDPOINT = "https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec";

    private static readonly string[] DB_LABELS = {
        "Tool Docs（Unity / Houdini / DX12）",
        "Game Info（ゲーム情報）",
        "Research（論文・技術記事）",
        "Team Notes（ゼミ・議事録）"
    };
    private static readonly string[] DB_KEYS = {
        "tool_docs", "game_info", "research", "team_notes"
    };

    // ===== 状態 =====
    private int _selectedDb = 0;
    private string _inputText = "";
    private Vector2 _scrollPos;
    private readonly List<(string role, string text)> _messages = new();
    private bool _isLoading = false;
    private RAGClient _client;

    [MenuItem("Tools/RAG Chat")]
    public static void Open() => GetWindow<RAGChatWindow>("RAG Chat");

    private void OnEnable()
    {
        _client = new RAGClient(GAS_ENDPOINT);
    }

    private void OnGUI()
    {
        // DB選択
        EditorGUILayout.LabelField("参照DB", EditorStyles.boldLabel);
        _selectedDb = EditorGUILayout.Popup(_selectedDb, DB_LABELS);
        EditorGUILayout.Space(4);

        // チャット履歴
        float chatHeight = position.height - 120;
        _scrollPos = EditorGUILayout.BeginScrollView(
            _scrollPos,
            GUILayout.Height(chatHeight)
        );
        foreach (var (role, text) in _messages)
        {
            var style = role == "user"
                ? new GUIStyle(EditorStyles.helpBox) { alignment = TextAnchor.MiddleRight }
                : new GUIStyle(EditorStyles.helpBox);
            EditorGUILayout.LabelField($"[{role}] {text}", style);
        }
        EditorGUILayout.EndScrollView();

        // 入力欄
        EditorGUILayout.BeginHorizontal();
        GUI.enabled = !_isLoading;
        _inputText = EditorGUILayout.TextField(_inputText);

        if (GUILayout.Button(_isLoading ? "..." : "送信", GUILayout.Width(60)))
            SendQuery();

        GUI.enabled = true;
        EditorGUILayout.EndHorizontal();

        // ローディング表示
        if (_isLoading)
            EditorGUILayout.LabelField("Geminiが考え中...", EditorStyles.centeredGreyMiniLabel);
    }

    private async void SendQuery()
    {
        if (string.IsNullOrWhiteSpace(_inputText) || _isLoading) return;

        var query = _inputText.Trim();
        _inputText = "";
        _messages.Add(("user", query));
        _isLoading = true;
        Repaint();

        var answer = await _client.QueryAsync(query, DB_KEYS[_selectedDb]);
        _messages.Add(("assistant", answer));
        _isLoading = false;
        Repaint();
    }
}
```

### RAGClient.cs

```csharp
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;

public class RAGClient
{
    private readonly string _endpoint;
    private static readonly HttpClient Http = new();

    public RAGClient(string endpoint) => _endpoint = endpoint;

    public async Task<string> QueryAsync(string query, string dbKey)
    {
        try
        {
            var body = JsonConvert.SerializeObject(new { query, dbKey });
            var content = new StringContent(body, Encoding.UTF8, "application/json");
            var res = await Http.PostAsync(_endpoint, content);
            var json = await res.Content.ReadAsStringAsync();
            var data = JsonConvert.DeserializeObject<dynamic>(json);
            return data?.answer ?? "回答を取得できませんでした";
        }
        catch (System.Exception e)
        {
            return $"エラー: {e.Message}";
        }
    }
}
```

### ラジアルメニューとの連携

```csharp
// Scene View にホットキーでRAG Chatを開く
[InitializeOnLoadMethod]
static void RegisterSceneViewCallback()
{
    SceneView.duringSceneGui += sv => {
        Event e = Event.current;
        // Q キー長押しでウィンドウを開く
        if (e.type == EventType.KeyDown && e.keyCode == KeyCode.Q && e.shift)
        {
            RAGChatWindow.Open();
            e.Use();
        }
    };
}
```

---

## 3. Houdini Python UIパネル

### 概要

Houdiniの `hou.ui.createDialog()` または `PySide2.QtWidgets` で独立したQDialogを作成する。HDKを使わずPure Pythonで実装できる。

### ファイル構成

```
$HOUDINI_USER_PREF_DIR/
└── scripts/
    └── python/
        └── rag_chat/
            ├── __init__.py
            ├── panel.py          ← メインUI
            ├── client.py         ← GAS WebApp 呼び出し
            └── shelf_tool.py     ← シェルフボタン登録用
```

### panel.py

```python
"""
Houdini RAG Chat パネル
起動: import rag_chat; rag_chat.show()
"""
import hou
import urllib.request
import urllib.parse
import json
import threading
from PySide2 import QtWidgets, QtCore, QtGui

GAS_ENDPOINT = "https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec"

DB_OPTIONS = {
    "Tool Docs（Houdini / Unity / DX12）": "tool_docs",
    "Game Info（ゲーム情報）":              "game_info",
    "Research（論文・技術記事）":           "research",
    "Team Notes（ゼミ・議事録）":           "team_notes",
}


class RAGChatPanel(QtWidgets.QDialog):
    answer_received = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent or hou.qt.mainWindow())
        self.setWindowTitle("RAG Chat — Houdini")
        self.setMinimumSize(480, 560)
        self.setWindowFlags(
            QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint
        )
        self._build_ui()
        self.answer_received.connect(self._on_answer)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # DB選択
        db_row = QtWidgets.QHBoxLayout()
        db_row.addWidget(QtWidgets.QLabel("参照DB:"))
        self.db_combo = QtWidgets.QComboBox()
        for label in DB_OPTIONS:
            self.db_combo.addItem(label)
        db_row.addWidget(self.db_combo)
        layout.addLayout(db_row)

        # チャット表示
        self.chat_view = QtWidgets.QTextEdit()
        self.chat_view.setReadOnly(True)
        self.chat_view.setStyleSheet(
            "background:#1a1a2e; color:#e0e0e0; font-size:13px;"
        )
        layout.addWidget(self.chat_view)

        # 入力欄
        input_row = QtWidgets.QHBoxLayout()
        self.input_field = QtWidgets.QLineEdit()
        self.input_field.setPlaceholderText("質問を入力... (Enter で送信)")
        self.input_field.returnPressed.connect(self._send)
        input_row.addWidget(self.input_field)

        self.send_btn = QtWidgets.QPushButton("送信")
        self.send_btn.clicked.connect(self._send)
        self.send_btn.setFixedWidth(72)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

        # ステータス
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet("color:#888; font-size:11px;")
        layout.addWidget(self.status_label)

    def _send(self):
        query = self.input_field.text().strip()
        if not query:
            return
        db_label = self.db_combo.currentText()
        db_key = DB_OPTIONS[db_label]

        self.input_field.clear()
        self._append_chat("あなた", query, "#4ea8de")
        self.send_btn.setEnabled(False)
        self.status_label.setText("Geminiが考え中...")

        # 別スレッドで HTTP リクエスト（UIをブロックしない）
        threading.Thread(
            target=self._fetch_answer,
            args=(query, db_key),
            daemon=True
        ).start()

    def _fetch_answer(self, query: str, db_key: str):
        try:
            payload = json.dumps({"query": query, "dbKey": db_key}).encode()
            req = urllib.request.Request(
                GAS_ENDPOINT,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as res:
                data = json.loads(res.read().decode())
                self.answer_received.emit(data.get("answer", "回答なし"))
        except Exception as e:
            self.answer_received.emit(f"エラー: {e}")

    def _on_answer(self, answer: str):
        self._append_chat("RAG", answer, "#3fb950")
        self.send_btn.setEnabled(True)
        self.status_label.setText("")

    def _append_chat(self, role: str, text: str, color: str):
        self.chat_view.append(
            f'<span style="color:{color};font-weight:bold;">[{role}]</span>'
            f'<span style="color:#e0e0e0;"> {text}</span><br>'
        )


_panel_instance = None

def show():
    """シェルフボタンやホットキーから呼び出す"""
    global _panel_instance
    if _panel_instance is None or not _panel_instance.isVisible():
        _panel_instance = RAGChatPanel()
    _panel_instance.show()
    _panel_instance.raise_()
    _panel_instance.activateWindow()
```

### シェルフへの登録

Houdiniのシェルフエディタで新規ツールを作成し、スクリプト欄に記入：

```python
import rag_chat
rag_chat.show()
```

ホットキーは `Ctrl+Shift+R` を推奨。

---

## 4. Webアプリ

### 概要

Next.js（App Router）でチャットUIを実装し、Vercelにデプロイする。静的コンテンツのみの場合はGitHub Pagesも可。

### 技術スタック

| 項目 | 選択 | 理由 |
|------|------|------|
| フレームワーク | Next.js 14（App Router） | Vercelとの親和性 |
| デプロイ | Vercel | 無料・CI/CD自動 |
| スタイル | Tailwind CSS | セットアップが最速 |
| HTTP | fetch（組み込み） | 依存なし |

### ファイル構成

```
rag-web/
├── app/
│   ├── layout.tsx
│   ├── page.tsx              ← チャットページ
│   └── api/
│       └── chat/
│           └── route.ts      ← GAS WebApp プロキシ
├── components/
│   └── ChatWindow.tsx
└── lib/
    └── rag-client.ts
```

### app/api/chat/route.ts（GASプロキシ）

```typescript
// GAS WebApp を直接クライアントから叩くと CORS エラーになる場合があるため
// Next.js のAPI Routeをプロキシとして使う
import { NextRequest, NextResponse } from 'next/server'

const GAS_ENDPOINT = process.env.GAS_ENDPOINT!

export async function POST(req: NextRequest) {
  const body = await req.json()
  try {
    const res = await fetch(GAS_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    return NextResponse.json(data)
  } catch (e) {
    return NextResponse.json({ answer: `エラー: ${e}`, status: 'error' }, { status: 500 })
  }
}
```

### components/ChatWindow.tsx

```typescript
'use client'
import { useState, useRef, useEffect } from 'react'

const DB_OPTIONS = [
  { label: 'Tool Docs（Unity / Houdini / DX12）', value: 'tool_docs' },
  { label: 'Game Info（ゲーム情報）',              value: 'game_info' },
  { label: 'Research（論文・技術記事）',           value: 'research' },
  { label: 'Team Notes（ゼミ・議事録）',           value: 'team_notes' },
]

type Message = { role: 'user' | 'assistant'; text: string }

export default function ChatWindow() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [dbKey, setDbKey] = useState('tool_docs')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    if (!input.trim() || loading) return
    const query = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', text: query }])
    setLoading(true)

    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, dbKey }),
    })
    const data = await res.json()
    setMessages(prev => [...prev, { role: 'assistant', text: data.answer }])
    setLoading(false)
  }

  return (
    <div className="flex flex-col h-screen max-w-2xl mx-auto p-4">
      <select
        value={dbKey}
        onChange={e => setDbKey(e.target.value)}
        className="mb-3 p-2 rounded border text-sm"
      >
        {DB_OPTIONS.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      <div className="flex-1 overflow-y-auto space-y-3 mb-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] px-3 py-2 rounded-xl text-sm whitespace-pre-wrap
              ${m.role === 'user'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-800'}`}>
              {m.text}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 px-3 py-2 rounded-xl text-sm text-gray-400">
              考え中...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="質問を入力..."
          className="flex-1 px-3 py-2 rounded border text-sm"
        />
        <button
          onClick={send}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-50"
        >
          送信
        </button>
      </div>
    </div>
  )
}
```

### Vercelへのデプロイ

```bash
# プロジェクト作成
npx create-next-app@latest rag-web --typescript --tailwind --app

# 環境変数を .env.local に設定
echo "GAS_ENDPOINT=https://script.google.com/macros/s/YOUR_ID/exec" > .env.local

# Vercel CLIでデプロイ
npx vercel --prod
```

Vercelの環境変数に `GAS_ENDPOINT` を設定すること。

---

## 5. デスクトップアプリ

### 概要

LocalRAG（mcp-rag-server）を直接呼び出したい場合はElectronまたはTauriで実装する。Node.js（Electron）またはRust（Tauri）のバックエンドからWSL2のMCPサーバーにアクセスできる。

### Electron vs Tauri 比較

| 項目 | Electron | Tauri |
|------|----------|-------|
| 言語 | Node.js + HTML/CSS/JS | Rust + HTML/CSS/JS |
| バンドルサイズ | 大（100MB超） | 小（数MB） |
| パフォーマンス | 普通 | 高速 |
| 実装難易度 | 低（JS全部） | 中（Rust部分） |
| 推奨ケース | 速く作りたい | 本番品質・軽量化 |

ゲームエンジニア的には**Tauri推奨**。Rustの学習コストはあるがバイナリが小さく配布しやすい。

### Tauri: ディレクトリ構成

```
rag-desktop/
├── src-tauri/
│   ├── src/
│   │   ├── main.rs          ← エントリポイント
│   │   └── rag.rs           ← MCP / GAS 呼び出しロジック
│   └── tauri.conf.json
└── src/                     ← フロントエンド（同じChrome UIを流用可）
    ├── index.html
    ├── main.ts
    └── ChatWindow.svelte     ← または React
```

### src-tauri/src/rag.rs（GAS呼び出し）

```rust
use serde::{Deserialize, Serialize};
use tauri::command;

#[derive(Serialize)]
struct RagRequest {
    query: String,
    db_key: String,
}

#[derive(Deserialize)]
struct RagResponse {
    answer: String,
}

#[command]
pub async fn query_cloud_rag(query: String, db_key: String) -> Result<String, String> {
    let client = reqwest::Client::new();
    let endpoint = "https://script.google.com/macros/s/YOUR_ID/exec";

    let res = client
        .post(endpoint)
        .json(&RagRequest { query, db_key })
        .send()
        .await
        .map_err(|e| e.to_string())?;

    let data: RagResponse = res.json().await.map_err(|e| e.to_string())?;
    Ok(data.answer)
}

// LocalRAG呼び出し（WSL2のMCPサーバーにSSEで接続）
#[command]
pub async fn query_local_rag(query: String, namespace: String) -> Result<String, String> {
    // mcp-rag-server のCLI検索機能を直接呼び出す
    let output = tokio::process::Command::new("wsl")
        .args([
            "bash", "-c",
            &format!(
                "/home/tk_render/.local/bin/uv run --directory /home/tk_render/mcp-rag-server \
                 python -m src.cli search --query '{}' --namespace '{}'",
                query.replace("'", "\\'"),
                namespace
            )
        ])
        .output()
        .await
        .map_err(|e| e.to_string())?;

    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}
```

### Electron: 最速実装（既存WebコードをそのままElectronで包む）

```javascript
// main.js（Electronメインプロセス）
const { app, BrowserWindow } = require('electron')
const path = require('path')

function createWindow() {
  const win = new BrowserWindow({
    width: 480,
    height: 640,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  })
  // Webアプリを内包 or VercelのURLを読み込む
  win.loadFile('src/index.html')
}

app.whenReady().then(createWindow)
```

---

## 6. ラジアル / パイメニュー

### 設計方針

各UI環境に対して「よく使う操作を素早く実行できる」ためのラジアルメニューを実装する。

### Unity: Scene Viewでのラジアルメニュー

```csharp
// RadialMenu.cs（EditorWindow内）
public class RadialMenu : EditorWindow
{
    private static readonly (string label, System.Action action)[] ITEMS = {
        ("RAG Chat", () => RAGChatWindow.Open()),
        ("Tool Docs検索", () => OpenWithDB("tool_docs")),
        ("Game Info検索", () => OpenWithDB("game_info")),
        ("Research検索", () => OpenWithDB("research")),
    };

    // 右クリック長押しで表示
    // Q + 右クリックで呼び出し
}
```

### Houdini: Pythonラジアルメニュー

```python
# radial_menu.py
# シェルフに登録して右クリックメニューに追加

import hou
from PySide2 import QtWidgets

def show_radial_menu():
    menu = QtWidgets.QMenu()
    menu.addAction("RAG Chat を開く",     lambda: __import__('rag_chat').show())
    menu.addAction("Tool Docs を検索",    lambda: quick_search("tool_docs"))
    menu.addAction("Houdini ノード検索",  lambda: quick_search("tool_docs", preset="houdini node"))
    menu.exec_(QtGui.QCursor.pos())

def quick_search(db_key, preset=""):
    import rag_chat
    panel = rag_chat.show()
    if preset:
        panel.input_field.setText(preset)
```

### Web: フローティングアクションボタン（FAB）

Webアプリではラジアルメニューの代わりにFABパターンが自然。

```typescript
// FABMenu.tsx
const FAB_ITEMS = [
  { label: 'Tool Docs', db: 'tool_docs', shortcut: '1' },
  { label: 'Research',  db: 'research',  shortcut: '2' },
  { label: 'Game Info', db: 'game_info', shortcut: '3' },
]
// 右下固定ボタン → クリックでDB切り替え + フォーカス
```

---

## 7. 共通: GAS WebApp呼び出し仕様

全UI環境から同一のインターフェースでGASを呼び出す。

### リクエスト仕様

```
POST https://script.google.com/macros/s/{DEPLOYMENT_ID}/exec

Content-Type: application/json

{
  "query": "HoudiniのVEX wrangleの使い方",
  "dbKey": "tool_docs"
}
```

### レスポンス仕様

```json
{
  "answer": "VEX wrangleは...",
  "status": "ok"
}
```

エラー時：

```json
{
  "answer": "エラー: ...",
  "status": "error"
}
```

### dbKeyの値

| dbKey | 参照DB |
|-------|--------|
| `tool_docs` | Tool Docs DB |
| `game_info` | Game Info DB |
| `research` | Research DB |
| `team_notes` | Team Notes DB |

### タイムアウト設定

GASの処理時間（Notion検索 + Gemini API）は通常3〜8秒かかる。各UIのHTTPクライアントは**30秒**のタイムアウトを設定すること。
