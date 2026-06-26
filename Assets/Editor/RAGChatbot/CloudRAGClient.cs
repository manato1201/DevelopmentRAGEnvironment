using System;
using System.Collections.Generic;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

namespace RAGChatbot
{
    /// <summary>
    /// GAS WebApp (doPost) に HTTPS で問い合わせる Cloud RAG クライアント。
    /// URL は EditorPrefs に保存した値を使う。
    /// </summary>
    public class CloudRAGClient : IRAGClient
    {
        private readonly string _url;
        private readonly string _apiKey;
        private readonly string _dbKey;

        public CloudRAGClient(string gasWebAppUrl, string apiKey, string dbKey = "all")
        {
            _url    = gasWebAppUrl;
            _apiKey = apiKey;
            _dbKey  = string.IsNullOrEmpty(dbKey) ? "all" : dbKey;
        }

        public async Task<RAGResponse> QueryAsync(string query, IReadOnlyList<RAGMessage> history)
        {
            var historyJson = BuildHistoryJson(history);
            var body = $"{{\"query\":{JsonEscape(query)},\"dbKey\":{JsonEscape(_dbKey)},\"history\":{historyJson},\"apiKey\":{JsonEscape(_apiKey)}}}";
            return await PostJsonAsync(_url, body);
        }

        public async Task<bool> HealthCheckAsync()
        {
            if (string.IsNullOrEmpty(_url)) return false;
            // GAS WebApp は GET でチャット UI を返すだけなので 200 なら生きていると見なす
            var req = UnityWebRequest.Get(_url);
            req.timeout = 5;
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
                throw new Exception($"Cloud RAG エラー: {req.error}");

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
