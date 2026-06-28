using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading.Tasks;
using UnityEditor;
using UnityEngine;

namespace RAGChatbot
{
    /// <summary>
    /// RAG チャットボット Editor ウィンドウ（Unity 6 対応）。
    /// メニュー: Window > RAG Chatbot
    ///
    /// 機能:
    ///   - Chat タブ : Cloud / Local RAG にテキストで質問し、回答を会話形式で表示
    ///   - Graph タブ: ドキュメント間の意味的類似度をグラフで可視化（Local モード専用）
    ///   - Settings タブ: GAS URL / API Key / DB Key / ブリッジポートを設定
    ///
    /// モード切り替え:
    ///   Header のドロップダウンで Cloud ⇄ Local を切り替える。
    ///   切り替え時に RebuildClient() で IRAGClient の実装を差し替える。
    /// </summary>
    public class RAGChatbotWindow : EditorWindow
    {
        // ── EditorPrefs キー ──────────────────────────────────────────────────────
        // Editor を再起動しても設定が残るよう EditorPrefs（レジストリ）に保存する。
        // キー名に "RAGChatbot_" プレフィックスを付けて他の拡張と衝突しないようにしている。
        private const string PREF_GAS_URL    = "RAGChatbot_GasUrl";
        private const string PREF_API_KEY    = "RAGChatbot_ApiKey";
        private const string PREF_DB_KEY     = "RAGChatbot_DbKey";
        private const string PREF_LOCAL_PORT = "RAGChatbot_LocalPort";
        private const string PREF_MODE       = "RAGChatbot_Mode";   // "cloud" | "local"

        // ── タブ ─────────────────────────────────────────────────────────────────
        private static readonly string[] TAB_LABELS = { "Chat", "Graph", "Settings" };
        private int _tabIndex;

        // ── チャット状態 ──────────────────────────────────────────────────────────
        private readonly List<RAGMessage> _chatHistory = new();  // 全会話履歴（表示用）
        private string  _inputText   = "";
        private bool    _isSending;
        private string  _statusText  = "";
        private Vector2 _chatScroll;

        // ── モード / クライアント ────────────────────────────────────────────────
        private enum Mode { Cloud, Local }
        private Mode       _mode   = Mode.Local;
        private IRAGClient _client;  // 実際の通信実装（Cloud か Local かで差し替え）

        // ── ブリッジプロセス（Local モード） ────────────────────────────────────
        // Python ブリッジを Editor から自動起動した場合のプロセス参照。
        // ウィンドウを閉じても残す（再起動コストを避けるため OnDisable では Kill しない）。
        private Process _bridgeProcess;

        // ── 設定フィールド ────────────────────────────────────────────────────────
        private string _gasUrl       = "";
        private string _apiKey       = "";
        private string _dbKey        = "all";
        private string _localPortStr = "8766";

        // ── グラフビュー ──────────────────────────────────────────────────────────
        private readonly RAGGraphView _graphView = new();
        private bool _graphLoading;

        // ─────────────────────────────────────────────────────────────────────────

        /// <summary>メニュー "Window > RAG Chatbot" でウィンドウを開く。</summary>
        [MenuItem("Window/RAG Chatbot")]
        public static void Open() => GetWindow<RAGChatbotWindow>("RAG Chatbot");

        /// <summary>
        /// ウィンドウが有効になったとき（起動・再コンパイル後）に呼ばれる。
        /// EditorPrefs から設定を読み込み、クライアントを再構築してブリッジを起動する。
        /// </summary>
        private void OnEnable()
        {
            _gasUrl       = EditorPrefs.GetString(PREF_GAS_URL, "");
            _apiKey       = EditorPrefs.GetString(PREF_API_KEY, "");
            _dbKey        = EditorPrefs.GetString(PREF_DB_KEY, "all");
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

        /// <summary>
        /// 現在のモードと設定値を元に IRAGClient の実装を差し替える。
        /// 設定変更のたびに呼び出すことで、次の送信から新しい設定が反映される。
        /// </summary>
        private void RebuildClient()
        {
            _client = _mode == Mode.Cloud
                ? (IRAGClient)new CloudRAGClient(_gasUrl, _apiKey, _dbKey)
                : new LocalRAGClient(ParsePort());
        }

        /// <summary>ポート文字列を int に変換し、不正値は 8766 にフォールバック。</summary>
        private int ParsePort()
        {
            return int.TryParse(_localPortStr, out var p) ? p : 8766;
        }

        // ── ブリッジ自動起動 ───────────────────────────────────────────────────

        /// <summary>
        /// Local モード時にブリッジが未起動なら自動で python を起動する。
        /// ポーリング間隔 500ms × 16 回 = 最大 8 秒待機する。
        /// </summary>
        private async Task EnsureBridgeAsync()
        {
            if (_mode != Mode.Local) return;
            if (await _client.HealthCheckAsync()) return;  // すでに起動済み

            _statusText = "ローカルブリッジを起動中...";
            Repaint();

            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName               = "python",
                    Arguments              = $"scripts/rag_local_bridge.py --port {ParsePort()}",
                    WorkingDirectory       = FindProjectRoot(),
                    CreateNoWindow         = true,
                    UseShellExecute        = false,
                    // stdout / stderr をリダイレクトするとバッファが詰まる場合があるため false
                    RedirectStandardOutput = false,
                    RedirectStandardError  = false,
                };
                _bridgeProcess = Process.Start(psi);

                // 起動待ち（最大 8 秒 = 500ms × 16 回）
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

        /// <summary>
        /// プロジェクトルートのパスを取得する。
        /// Application.dataPath は "Assets" フォルダへのパスなので、
        /// 一段上（"Assets/.."）を取得してプロジェクトルートにする。
        /// </summary>
        private static string FindProjectRoot()
        {
            return System.IO.Path.GetFullPath(
                System.IO.Path.Combine(Application.dataPath, ".."));
        }

        // ── GUI ─────────────────────────────────────────────────────────────────

        /// <summary>
        /// IMGUI の描画エントリポイント。毎フレーム呼ばれる。
        /// ヘッダー → タブバー → 各タブの中身、という順で描画する。
        /// </summary>
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

        /// <summary>
        /// ヘッダー行を描画する。
        /// 左: タイトル、中央: Cloud/Local ドロップダウン、右: 送信中インジケーター（●）。
        /// モード変更を検知したら EditorPrefs に保存し RebuildClient() を呼ぶ。
        /// </summary>
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

                // 応答中は黄色、待機中は緑のインジケーターで状態を示す
                var statusColor = _isSending ? Color.yellow : Color.green;
                using (new GUIColorScope(statusColor))
                    GUILayout.Label("●", GUILayout.Width(20));
            }

            if (!string.IsNullOrEmpty(_statusText))
                EditorGUILayout.HelpBox(_statusText, MessageType.Info);
        }

        // ── Chat タブ ─────────────────────────────────────────────────────────

        /// <summary>
        /// Chat タブの描画。
        /// メッセージリスト（スクロール可能）→ テキスト入力エリア → 送信/クリアボタン。
        /// Enter キーで送信（Shift+Enter は改行）。
        /// </summary>
        private void DrawChatTab()
        {
            float inputHeight    = 60f;
            float chatAreaHeight = position.height - 140f;

            // ── メッセージリスト（スクロール） ──
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

                // RAG 回答にのみ 👍/👎 ボタンを表示する
                if (!isUser && !string.IsNullOrEmpty(msg.memoryId))
                {
                    using (new EditorGUILayout.HorizontalScope())
                    {
                        GUILayout.Space(8);
                        // 評価済みなら対応ボタンをハイライト
                        using (new GUIColorScope(msg.rating == 1 ? Color.green : Color.white))
                        {
                            if (GUILayout.Button("👍", GUILayout.Width(36), GUILayout.Height(20))
                                && msg.rating != 1)
                            {
                                msg.rating = 1;
                                _ = _client.RateAsync(msg.memoryId, "up");
                            }
                        }
                        using (new GUIColorScope(msg.rating == -1 ? new Color(1f, 0.4f, 0.4f) : Color.white))
                        {
                            if (GUILayout.Button("👎", GUILayout.Width(36), GUILayout.Height(20))
                                && msg.rating != -1)
                            {
                                msg.rating = -1;
                                _ = _client.RateAsync(msg.memoryId, "down");
                            }
                        }
                        GUILayout.FlexibleSpace();
                    }
                }
                EditorGUILayout.Space(2);
            }

            EditorGUILayout.EndScrollView();

            // ── 入力エリア ──
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

            // Enter で送信（Shift+Enter は通常の改行として残す）
            var ev = Event.current;
            if (ev.type == EventType.KeyDown && ev.keyCode == KeyCode.Return
                && !ev.shift && !_isSending && !string.IsNullOrWhiteSpace(_inputText))
            {
                _ = SendMessageAsync();
                ev.Use();
            }
        }

        /// <summary>
        /// 質問を RAG クライアントに送り、回答を _chatHistory に追加する。
        /// IRAGClient のインターフェース経由で呼ぶため Cloud / Local を意識しない。
        /// 送信中フラグを立てることで二重送信を防ぐ。
        /// </summary>
        private async Task SendMessageAsync()
        {
            var query = _inputText.Trim();
            if (string.IsNullOrEmpty(query)) return;

            _inputText  = "";
            _isSending  = true;
            _statusText = "応答中...";
            Repaint();

            _chatHistory.Add(new RAGMessage("user", query));

            try
            {
                var resp = await _client.QueryAsync(query, _chatHistory);
                var assistantMsg = new RAGMessage("assistant", resp.answer ?? "(空の回答)")
                {
                    memoryId = resp.memoryId ?? "",
                };
                _chatHistory.Add(assistantMsg);
                // 参照ソースがあればステータスバーに表示する
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
                _isSending       = false;
                _chatScroll.y    = float.MaxValue;  // 最新メッセージまで自動スクロール
                Repaint();
            }
        }

        // ── Graph タブ ────────────────────────────────────────────────────────

        /// <summary>
        /// Graph タブの描画。ブリッジの /graph エンドポイントからデータを取得して描画する。
        /// グラフキャンバスは残りの全高さを使う。
        /// Local モードでのみ利用可能（Cloud モードには /graph エンドポイントがない）。
        /// </summary>
        private void DrawGraphTab()
        {
            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUILayout.LabelField("ドキュメント関係グラフ", EditorStyles.boldLabel);
                GUILayout.FlexibleSpace();
                using (new EditorGUI.DisabledScope(_graphLoading))
                {
                    if (GUILayout.Button(_graphLoading ? "読み込み中..." : "更新", GUILayout.Width(70)))
                        _ = LoadGraphAsync();
                }
                if (GUILayout.Button("リセット", GUILayout.Width(60)))
                {
                    _graphView.SetData(null);
                    Repaint();
                }
            }

            // GUILayoutUtility.GetRect で残り領域をすべてグラフキャンバスに割り当てる
            Rect graphRect = GUILayoutUtility.GetRect(0, 0,
                GUILayout.ExpandWidth(true), GUILayout.ExpandHeight(true));
            _graphView.Draw(graphRect, this);

            // 選択ノードの詳細情報を下部に表示
            string sel = _graphView.SelectedNodeId;
            if (!string.IsNullOrEmpty(sel))
            {
                EditorGUILayout.HelpBox($"選択: {System.IO.Path.GetFileName(sel)}\n{sel}", MessageType.None);
            }

            // 操作ヒント
            EditorGUILayout.LabelField(
                "ドラッグ: パン  |  スクロール: ズーム  |  右クリック: リセット  |  クリック: 選択",
                EditorStyles.centeredGreyMiniLabel);
        }

        /// <summary>
        /// ブリッジの /graph エンドポイントからグラフデータを取得して描画する。
        /// タイムアウト 120 秒（大量ドキュメントのエンベディング計算に時間がかかる場合があるため）。
        /// </summary>
        private async Task LoadGraphAsync()
        {
            if (_mode != Mode.Local)
            {
                _statusText = "Graph ビューは現在 Local モードのみ対応しています";
                Repaint();
                return;
            }

            _graphLoading = true;
            _statusText   = "グラフデータ取得中...";
            Repaint();

            try
            {
                var req = UnityEngine.Networking.UnityWebRequest.Get(
                    $"http://localhost:{ParsePort()}/graph");
                req.timeout = 120;
                var op = req.SendWebRequest();
                while (!op.isDone) await Task.Yield();

                if (req.result != UnityEngine.Networking.UnityWebRequest.Result.Success)
                    throw new Exception(req.error);

                var data = JsonUtility.FromJson<RAGGraphData>(req.downloadHandler.text);
                _graphView.SetData(data);
                _statusText = $"グラフ読み込み完了: {data.nodes?.Length ?? 0} ノード / {data.edges?.Length ?? 0} エッジ";
            }
            catch (Exception ex)
            {
                _statusText = $"グラフ取得失敗: {ex.Message}";
            }
            finally
            {
                _graphLoading = false;
                Repaint();
            }
        }

        // ── Settings タブ ─────────────────────────────────────────────────────

        /// <summary>
        /// Settings タブの描画。
        /// 各フィールドの変更を即座に EditorPrefs に保存し RebuildClient() を呼ぶことで、
        /// 保存ボタン不要でリアルタイムに設定が反映される。
        /// </summary>
        private void DrawSettingsTab()
        {
            EditorGUILayout.LabelField("Cloud RAG 設定", EditorStyles.boldLabel);

            // GAS WebApp URL
            var newUrl = EditorGUILayout.TextField("GAS WebApp URL", _gasUrl);
            if (newUrl != _gasUrl)
            {
                _gasUrl = newUrl;
                EditorPrefs.SetString(PREF_GAS_URL, _gasUrl);
                RebuildClient();
            }

            // API Key（入力が見えないよう PasswordField を使う）
            var newKey = EditorGUILayout.PasswordField("API Key", _apiKey);
            if (newKey != _apiKey)
            {
                _apiKey = newKey;
                EditorPrefs.SetString(PREF_API_KEY, _apiKey);
                RebuildClient();
            }

            // DB Key（検索対象の絞り込み。"all" で全 DB を対象にする）
            var newDb = EditorGUILayout.TextField("DB Key (例: all, tool_docs)", _dbKey);
            if (newDb != _dbKey)
            {
                _dbKey = newDb;
                EditorPrefs.SetString(PREF_DB_KEY, _dbKey);
                RebuildClient();
            }

            EditorGUILayout.Space(8);
            EditorGUILayout.LabelField("Local RAG 設定", EditorStyles.boldLabel);

            // ローカルブリッジのポート番号
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
            // Anthropic API キーは .env を使わず OS 環境変数に直接設定する
            EditorGUILayout.HelpBox(
                "ANTHROPIC_API_KEY は環境変数で設定してください。\n" +
                "Editor の起動前に OS 環境変数に追加するか、\n" +
                "rag_local_bridge.py 実行時にシェルに設定してください。",
                MessageType.Warning);
        }

        /// <summary>現在のクライアントでヘルスチェックし、ステータスバーに結果を表示する。</summary>
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

    /// <summary>
    /// using スコープで GUI.color を一時的に変更するヘルパー。
    /// using (new GUIColorScope(Color.red)) { ... } とすると
    /// ブロックを抜けた時点で元の色に戻る。
    /// </summary>
    internal readonly struct GUIColorScope : IDisposable
    {
        private readonly Color _prev;
        public GUIColorScope(Color c) { _prev = GUI.color; GUI.color = c; }
        public void Dispose() => GUI.color = _prev;
    }
}
