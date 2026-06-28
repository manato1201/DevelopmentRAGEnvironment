using System;
using System.Collections.Generic;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

namespace RAGChatbot
{
    /// <summary>
    /// Google Apps Script の WebApp (doPost) に HTTPS で問い合わせる Cloud RAG クライアント。
    ///
    /// リクエスト形式（JSON POST body）:
    ///   {
    ///     "query"   : "質問文",
    ///     "dbKey"   : "all" | "tool_docs" | ...,  // 検索対象 DB の絞り込み
    ///     "history" : [{"role":"user","text":"..."},...],  // マルチターン会話履歴
    ///     "apiKey"  : "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"   // 32文字の認証キー
    ///   }
    ///
    /// URL・API Key・DB Key は EditorPrefs に保存した値を外部から渡す。
    /// （このクラス自体は EditorPrefs を参照しない）
    /// </summary>
    public class CloudRAGClient : IRAGClient
    {
        private readonly string _url;     // GAS WebApp のデプロイ URL
        private readonly string _apiKey;  // RAG 管理画面で発行した認証キー
        private readonly string _dbKey;   // 検索する DB の絞り込みキー

        /// <param name="gasWebAppUrl">GAS WebApp のデプロイ URL</param>
        /// <param name="apiKey">管理画面で発行した 32 文字の API キー</param>
        /// <param name="dbKey">検索対象 DB（空または null の場合は "all" = 全 DB）</param>
        public CloudRAGClient(string gasWebAppUrl, string apiKey, string dbKey = "all")
        {
            _url    = gasWebAppUrl;
            _apiKey = apiKey;
            // 空文字・null の場合は "all" にフォールバックして全 DB を検索する
            _dbKey  = string.IsNullOrEmpty(dbKey) ? "all" : dbKey;
        }

        /// <summary>
        /// GAS WebApp に POST リクエストを送り、Gemini の回答を返す。
        /// 会話履歴と API キーも同時に送ることでマルチターン認証に対応する。
        /// </summary>
        public async Task<RAGResponse> QueryAsync(string query, IReadOnlyList<RAGMessage> history)
        {
            // JsonUtility は Dictionary や List を直接シリアライズできないため手動で JSON を組み立てる
            var historyJson = BuildHistoryJson(history);
            var body = $"{{\"query\":{JsonEscape(query)},\"dbKey\":{JsonEscape(_dbKey)},\"history\":{historyJson},\"apiKey\":{JsonEscape(_apiKey)}}}";
            return await PostJsonAsync(_url, body);
        }

        /// <summary>
        /// GAS の RAG_Memory 行に 👍/👎 評価を送る。
        /// doPost に action:"rate" を POST し、rating/priority 列を更新する。
        /// </summary>
        public async Task<bool> RateAsync(string memoryId, string rating)
        {
            if (string.IsNullOrEmpty(_url) || string.IsNullOrEmpty(memoryId)) return false;
            var body = $"{{\"action\":\"rate\",\"memoryId\":{JsonEscape(memoryId)},\"rating\":{JsonEscape(rating)},\"apiKey\":{JsonEscape(_apiKey)}}}";
            var bytes = Encoding.UTF8.GetBytes(body);
            var req = new UnityWebRequest(_url, "POST")
            {
                uploadHandler   = new UploadHandlerRaw(bytes),
                downloadHandler = new DownloadHandlerBuffer(),
                timeout         = 15,
            };
            req.SetRequestHeader("Content-Type", "application/json");
            var op = req.SendWebRequest();
            while (!op.isDone) await Task.Yield();
            return req.result == UnityWebRequest.Result.Success;
        }

        /// <summary>
        /// GAS WebApp に GET リクエストを送って疎通を確認する。
        /// GAS の doGet はチャット UI の HTML を返すだけなので、200 OK なら「生きている」とみなす。
        /// URL が未設定のときは即 false を返して無駄なリクエストを避ける。
        /// </summary>
        public async Task<bool> HealthCheckAsync()
        {
            if (string.IsNullOrEmpty(_url)) return false;
            var req = UnityWebRequest.Get(_url);
            req.timeout = 5;  // 5 秒で判定（UI 応答を止めないよう短めに設定）
            var op = req.SendWebRequest();
            while (!op.isDone) await Task.Yield();
            return req.result == UnityWebRequest.Result.Success;
        }

        // ── 内部ユーティリティ ──────────────────────────────────────────────────

        /// <summary>
        /// JSON 文字列を POST ボディとして送り、レスポンスを RAGResponse に変換する。
        /// タイムアウトは 60 秒（Gemini の回答生成に時間がかかることがあるため長めに設定）。
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
            while (!op.isDone) await Task.Yield();  // Unity のフレームループをブロックしないよう yield

            if (req.result != UnityWebRequest.Result.Success)
                throw new Exception($"Cloud RAG エラー: {req.error}");

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
        /// バックスラッシュ・ダブルクォート・改行を手動でエスケープしているのは、
        /// Newtonsoft.Json 等の外部ライブラリを追加せずに済ませるため。
        /// </summary>
        private static string JsonEscape(string s)
        {
            if (s == null) return "null";
            return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"")
                            .Replace("\n", "\\n").Replace("\r", "\\r") + "\"";
        }
    }
}
