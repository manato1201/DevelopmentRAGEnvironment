using System;
using System.Collections.Generic;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

namespace RAGChatbot
{
    /// <summary>
    /// rag_local_bridge.py (localhost:8766) に HTTP で問い合わせる Local RAG クライアント。
    /// ポートは EditorPrefs に保存した値を使う。
    /// </summary>
    public class LocalRAGClient : IRAGClient
    {
        private readonly string _baseUrl;

        public LocalRAGClient(int port = 8766)
        {
            _baseUrl = $"http://localhost:{port}";
        }

        public async Task<RAGResponse> QueryAsync(string query, IReadOnlyList<RAGMessage> history)
        {
            var historyJson = BuildHistoryJson(history);
            var body = $"{{\"query\":{JsonEscape(query)},\"history\":{historyJson},\"limit\":5}}";
            return await PostJsonAsync($"{_baseUrl}/query", body);
        }

        public async Task<bool> HealthCheckAsync()
        {
            var req = UnityWebRequest.Get($"{_baseUrl}/health");
            req.timeout = 3;
            var op = req.SendWebRequest();
            while (!op.isDone) await Task.Yield();
            return req.result == UnityWebRequest.Result.Success;
        }

        // ── 内部ユーティリティ ──────────────────────────────────────────────────
        private static async Task<RAGResponse> PostJsonAsync(string url, string jsonBody)
        {
            var bytes = Encoding.UTF8.GetBytes(jsonBody);
            var req = new UnityWebRequest(url, "POST")
            {
                uploadHandler = new UploadHandlerRaw(bytes),
                downloadHandler = new DownloadHandlerBuffer(),
                timeout = 60,
            };
            req.SetRequestHeader("Content-Type", "application/json");
            var op = req.SendWebRequest();
            while (!op.isDone) await Task.Yield();

            if (req.result != UnityWebRequest.Result.Success)
                throw new Exception($"Local RAG エラー: {req.error}");

            return JsonUtility.FromJson<RAGResponse>(req.downloadHandler.text);
        }

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

        private static string JsonEscape(string s)
        {
            if (s == null) return "null";
            return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"")
                            .Replace("\n", "\\n").Replace("\r", "\\r") + "\"";
        }
    }
}
