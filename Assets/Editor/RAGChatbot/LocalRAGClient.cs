using System;
using System.Collections.Generic;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

namespace RAGChatbot
{
    /// <summary>
    /// rag_local_bridge.py（localhost:8766）に HTTP で問い合わせる Local RAG クライアント。
    ///
    /// ローカルブリッジは Python プロセスとして起動し、ChromaDB で
    /// インデックス済みのドキュメントを Claude / Anthropic API を使って検索・回答する。
    ///
    /// リクエスト形式（JSON POST body）:
    ///   {
    ///     "query"   : "質問文",
    ///     "history" : [{"role":"user","text":"..."},...],
    ///     "limit"   : 5   // 類似ドキュメントの上位取得件数
    ///   }
    ///
    /// ポート番号は EditorPrefs に保存した値を外部から渡す。
    /// （このクラス自体は EditorPrefs を参照しない）
    /// </summary>
    public class LocalRAGClient : IRAGClient
    {
        // ベース URL（例: "http://localhost:8766"）
        private readonly string _baseUrl;

        /// <param name="port">ブリッジが LISTEN するポート番号（デフォルト 8766）</param>
        public LocalRAGClient(int port = 8766)
        {
            _baseUrl = $"http://localhost:{port}";
        }

        /// <summary>
        /// ローカルブリッジに POST して RAG 回答を返す。
        /// limit=5 で類似度上位 5 チャンクをコンテキストとして使う。
        /// </summary>
        public async Task<RAGResponse> QueryAsync(string query, IReadOnlyList<RAGMessage> history)
        {
            var historyJson = BuildHistoryJson(history);
            var body = $"{{\"query\":{JsonEscape(query)},\"history\":{historyJson},\"limit\":5}}";
            return await PostJsonAsync($"{_baseUrl}/query", body);
        }

        /// <summary>
        /// /health エンドポイントに GET して疎通を確認する。
        /// ブリッジが {"status":"ok"} を返せれば成功。
        /// タイムアウト 3 秒（ブリッジ未起動時に UI が固まらないよう短く設定）。
        /// </summary>
        public async Task<bool> HealthCheckAsync()
        {
            var req = UnityWebRequest.Get($"{_baseUrl}/health");
            req.timeout = 3;
            var op = req.SendWebRequest();
            while (!op.isDone) await Task.Yield();
            return req.result == UnityWebRequest.Result.Success;
        }

        // ── 内部ユーティリティ ──────────────────────────────────────────────────

        /// <summary>
        /// JSON 文字列を POST ボディとして送り、レスポンスを RAGResponse に変換する。
        /// タイムアウト 60 秒（Claude の回答生成に時間がかかることがあるため長めに設定）。
        /// </summary>
        private static async Task<RAGResponse> PostJsonAsync(string url, string jsonBody)
        {
            var bytes = Encoding.UTF8.GetBytes(jsonBody);
            var req = new UnityWebRequest(url, "POST")
            {
                uploadHandler   = new UploadHandlerRaw(bytes),
                downloadHandler = new DownloadHandlerBuffer(),
                timeout         = 60,
            };
            req.SetRequestHeader("Content-Type", "application/json");
            var op = req.SendWebRequest();
            while (!op.isDone) await Task.Yield();  // Unity フレームループをブロックしないよう yield

            if (req.result != UnityWebRequest.Result.Success)
                throw new Exception($"Local RAG エラー: {req.error}");

            return JsonUtility.FromJson<RAGResponse>(req.downloadHandler.text);
        }

        /// <summary>
        /// 会話履歴リストを JSON 配列文字列に変換する。
        /// JsonUtility が IReadOnlyList に非対応なため StringBuilder で手動構築する。
        /// </summary>
        private static string BuildHistoryJson(IReadOnlyList<RAGMessage> history)
        {
            var sb = new StringBuilder("[");
            for (int i = 0; i < history.Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append($"{{\"role\":{JsonEscape(history[i].role)},\"text\":{JsonEscape(history[i].text)}}}");
            }
            sb.Append(']');
            return sb.ToString();
        }

        /// <summary>
        /// 文字列を JSON 値としてエスケープして二重引用符で包む。
        /// 外部 JSON ライブラリを追加せずに済ませるため手動実装している。
        /// </summary>
        private static string JsonEscape(string s)
        {
            if (s == null) return "null";
            return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"")
                            .Replace("\n", "\\n").Replace("\r", "\\r") + "\"";
        }
    }
}
