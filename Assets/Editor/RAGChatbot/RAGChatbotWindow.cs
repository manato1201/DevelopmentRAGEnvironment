using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading.Tasks;
using UnityEditor;
using UnityEngine;

namespace RAGChatbot
{
    /// <summary>
    /// RAG チャットボット Editor ウィンドウ（Unity 6 対応）
    /// メニュー: Window > RAG Chatbot
    /// </summary>
    public class RAGChatbotWindow : EditorWindow
    {
        // ── EditorPrefs キー ──────────────────────────────────────────────────────
        private const string PREF_GAS_URL   = "RAGChatbot_GasUrl";
        private const string PREF_LOCAL_PORT = "RAGChatbot_LocalPort";
        private const string PREF_MODE      = "RAGChatbot_Mode";   // "cloud" | "local"

        // ── タブ ─────────────────────────────────────────────────────────────────
        private static readonly string[] TAB_LABELS = { "Chat", "Graph", "Settings" };
        private int _tabIndex;

        // ── チャット状態 ──────────────────────────────────────────────────────────
        private readonly List<RAGMessage> _chatHistory = new();
        private string _inputText = "";
        private bool _isSending;
        private string _statusText = "";
        private Vector2 _chatScroll;

        // ── モード / クライアント ────────────────────────────────────────────────
        private enum Mode { Cloud, Local }
        private Mode _mode = Mode.Local;
        private IRAGClient _client;

        // ── ブリッジプロセス（Local モード） ────────────────────────────────────
        private Process _bridgeProcess;

        // ── 設定フィールド ────────────────────────────────────────────────────────
        private string _gasUrl   = "";
        private string _localPortStr = "8766";

        // ── グラフデータ（Phase 5 で実装） ───────────────────────────────────────
        private Vector2 _graphScroll;

        // ─────────────────────────────────────────────────────────────────────────
        [MenuItem("Window/RAG Chatbot")]
        public static void Open() => GetWindow<RAGChatbotWindow>("RAG Chatbot");

        private void OnEnable()
        {
            _gasUrl       = EditorPrefs.GetString(PREF_GAS_URL, "");
            _localPortStr = EditorPrefs.GetString(PREF_LOCAL_PORT, "8766");
            _mode         = EditorPrefs.GetString(PREF_MODE, "local") == "cloud" ? Mode.Cloud : Mode.Local;

            RebuildClient();
            _ = EnsureBridgeAsync();
        }

        private void OnDisable()
        {
            // ウィンドウを閉じてもブリッジは残す（再起動コストを避ける）
        }

        // ── クライアント再構築 ─────────────────────────────────────────────────
        private void RebuildClient()
        {
            _client = _mode == Mode.Cloud
                ? (IRAGClient)new CloudRAGClient(_gasUrl)
                : new LocalRAGClient(ParsePort());
        }

        private int ParsePort()
        {
            return int.TryParse(_localPortStr, out var p) ? p : 8766;
        }

        // ── ブリッジ自動起動 ───────────────────────────────────────────────────
        private async Task EnsureBridgeAsync()
        {
            if (_mode != Mode.Local) return;
            if (await _client.HealthCheckAsync()) return;

            _statusText = "ローカルブリッジを起動中...";
            Repaint();

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = $"scripts/rag_local_bridge.py --port {ParsePort()}",
                    WorkingDirectory = FindProjectRoot(),
                    CreateNoWindow = true,
                    UseShellExecute = false,
                    RedirectStandardOutput = false,
                    RedirectStandardError = false,
                };
                _bridgeProcess = Process.Start(psi);

                // 起動待ち（最大 8 秒）
                for (int i = 0; i < 16; i++)
                {
                    await Task.Delay(500);
                    if (await _client.HealthCheckAsync())
                    {
                        _statusText = "ブリッジ接続済み";
                        Repaint();
                        return;
                    }
                }
                _statusText = "ブリッジ起動タイムアウト — 手動で起動してください";
            }
            catch (Exception ex)
            {
                _statusText = $"ブリッジ起動失敗: {ex.Message}";
            }
            Repaint();
        }

        private static string FindProjectRoot()
        {
            // Application.dataPath は Assets フォルダへのパス
            return System.IO.Path.GetFullPath(
                System.IO.Path.Combine(Application.dataPath, ".."));
        }

        // ── GUI ─────────────────────────────────────────────────────────────────
        private void OnGUI()
        {
            DrawHeader();
            _tabIndex = GUILayout.Toolbar(_tabIndex, TAB_LABELS);
            EditorGUILayout.Space(4);

            switch (_tabIndex)
            {
                case 0: DrawChatTab();     break;
                case 1: DrawGraphTab();    break;
                case 2: DrawSettingsTab(); break;
            }
        }

        private void DrawHeader()
        {
            using (new EditorGUILayout.HorizontalScope())
            {
                GUILayout.Label("RAG Chatbot", EditorStyles.boldLabel);
                GUILayout.FlexibleSpace();

                var newMode = (Mode)EditorGUILayout.EnumPopup(_mode, GUILayout.Width(80));
                if (newMode != _mode)
                {
                    _mode = newMode;
                    EditorPrefs.SetString(PREF_MODE, _mode == Mode.Cloud ? "cloud" : "local");
                    RebuildClient();
                    if (_mode == Mode.Local) _ = EnsureBridgeAsync();
                }

                var statusColor = _isSending ? Color.yellow : Color.green;
                using (new GUIColorScope(statusColor))
                    GUILayout.Label("●", GUILayout.Width(20));
            }

            if (!string.IsNullOrEmpty(_statusText))
                EditorGUILayout.HelpBox(_statusText, MessageType.Info);
        }

        // ── Chat タブ ─────────────────────────────────────────────────────────
        private void DrawChatTab()
        {
            float inputHeight = 60f;
            float chatAreaHeight = position.height - 140f;

            // メッセージリスト
            _chatScroll = EditorGUILayout.BeginScrollView(
                _chatScroll, GUILayout.Height(Mathf.Max(chatAreaHeight, 100)));

            foreach (var msg in _chatHistory)
            {
                bool isUser = msg.role == "user";
                var style = isUser ? EditorStyles.helpBox : EditorStyles.wordWrappedLabel;

                using (new EditorGUILayout.HorizontalScope())
                {
                    if (isUser) GUILayout.FlexibleSpace();
                    var label = $"{(isUser ? "You" : "RAG")}: {msg.text}";
                    GUILayout.Label(label, style, GUILayout.MaxWidth(position.width * 0.85f));
                    if (!isUser) GUILayout.FlexibleSpace();
                }
                EditorGUILayout.Space(2);
            }

            EditorGUILayout.EndScrollView();

            // 入力エリア
            EditorGUILayout.Space(4);
            _inputText = EditorGUILayout.TextArea(_inputText, GUILayout.Height(inputHeight));

            using (new EditorGUI.DisabledScope(_isSending))
            using (new EditorGUILayout.HorizontalScope())
            {
                GUILayout.FlexibleSpace();
                if (GUILayout.Button(_isSending ? "応答中..." : "送信", GUILayout.Width(100)))
                    _ = SendMessageAsync();

                if (GUILayout.Button("クリア", GUILayout.Width(60)))
                {
                    _chatHistory.Clear();
                    _statusText = "";
                }
            }

            // Enter で送信（Shift+Enter は改行）
            var ev = Event.current;
            if (ev.type == EventType.KeyDown && ev.keyCode == KeyCode.Return
                && !ev.shift && !_isSending && !string.IsNullOrWhiteSpace(_inputText))
            {
                _ = SendMessageAsync();
                ev.Use();
            }
        }

        private async Task SendMessageAsync()
        {
            var query = _inputText.Trim();
            if (string.IsNullOrEmpty(query)) return;

            _inputText = "";
            _isSending = true;
            _statusText = "応答中...";
            Repaint();

            _chatHistory.Add(new RAGMessage("user", query));

            try
            {
                var resp = await _client.QueryAsync(query, _chatHistory);
                _chatHistory.Add(new RAGMessage("assistant", resp.answer ?? "(空の回答)"));
                _statusText = resp.sources?.Length > 0
                    ? $"参照: {string.Join(", ", Array.ConvertAll(resp.sources, s => s.title))}"
                    : "";
            }
            catch (Exception ex)
            {
                _chatHistory.Add(new RAGMessage("assistant", $"エラー: {ex.Message}"));
                _statusText = ex.Message;
            }
            finally
            {
                _isSending = false;
                _chatScroll.y = float.MaxValue;
                Repaint();
            }
        }

        // ── Graph タブ（Phase 5 スタブ） ──────────────────────────────────────
        private void DrawGraphTab()
        {
            EditorGUILayout.HelpBox(
                "Graph ビューは Phase 5 で実装予定です。\n" +
                "RAG_Graph シートのデータを D3.js 風に可視化します。",
                MessageType.Info);
        }

        // ── Settings タブ ─────────────────────────────────────────────────────
        private void DrawSettingsTab()
        {
            EditorGUILayout.LabelField("Cloud RAG 設定", EditorStyles.boldLabel);
            var newUrl = EditorGUILayout.TextField("GAS WebApp URL", _gasUrl);
            if (newUrl != _gasUrl)
            {
                _gasUrl = newUrl;
                EditorPrefs.SetString(PREF_GAS_URL, _gasUrl);
                RebuildClient();
            }

            EditorGUILayout.Space(8);
            EditorGUILayout.LabelField("Local RAG 設定", EditorStyles.boldLabel);
            var newPort = EditorGUILayout.TextField("Bridge Port", _localPortStr);
            if (newPort != _localPortStr)
            {
                _localPortStr = newPort;
                EditorPrefs.SetString(PREF_LOCAL_PORT, _localPortStr);
                RebuildClient();
            }

            EditorGUILayout.Space(8);
            if (GUILayout.Button("ブリッジ接続確認"))
                _ = CheckBridgeStatusAsync();

            if (GUILayout.Button("ブリッジ再起動"))
            {
                _bridgeProcess?.Kill();
                _ = EnsureBridgeAsync();
            }

            EditorGUILayout.Space(8);
            EditorGUILayout.HelpBox(
                "ANTHROPIC_API_KEY は環境変数で設定してください。\n" +
                "Editor の起動前に OS 環境変数に追加するか、\n" +
                "rag_local_bridge.py 実行時にシェルに設定してください。",
                MessageType.Warning);
        }

        private async Task CheckBridgeStatusAsync()
        {
            _statusText = "接続確認中...";
            Repaint();
            bool ok = await _client.HealthCheckAsync();
            _statusText = ok ? "接続OK" : "接続失敗 — ブリッジが起動しているか確認してください";
            Repaint();
        }
    }

    // ── ユーティリティ ─────────────────────────────────────────────────────────
    internal readonly struct GUIColorScope : IDisposable
    {
        private readonly Color _prev;
        public GUIColorScope(Color c) { _prev = GUI.color; GUI.color = c; }
        public void Dispose() => GUI.color = _prev;
    }
}
