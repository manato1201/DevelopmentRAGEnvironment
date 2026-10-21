using System;
using System.Collections.Generic;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

namespace RAGChatbot
{
    /// <summary>
    /// Cloudflare Worker（cloudflare-rag-poc）の POST /query に HTTPS で問い合わせる Cloud RAG クライアント。
    ///
    /// リクエスト形式（JSON POST body、Authorization: Bearer &lt;APIキー&gt;）:
    ///   {
    ///     "query"      : "質問文",
    ///     "history"    : [{"role":"user","content":"..."},...],  // マルチターン会話履歴
    ///     "namespaces" : ["houdini22", ...]                      // 省略 = 権限のある全ナレッジ
    ///   }
    ///
    /// URL・API Key・ナレッジ名は EditorPrefs に保存した値を外部から渡す。
    /// （このクラス自体は EditorPrefs を参照しない）
    /// </summary>
    public class CloudflareRAGClient : IRAGClient
    {
        private readonly string _baseUrl;      // Worker の URL（末尾の / は除く）
        private readonly string _apiKey;       // 管理画面で発行した API キー
        private readonly string[] _namespaces; // 検索するナレッジ（空 = 全部）

        // Cloudflare は Unity 既定の User-Agent を bot として拒否することがあるため、明示する。
        private const string UserAgent = "UnityRAGChatbot/1.0";

        /// <param name="workerUrl">Worker の URL（例: https://rag-poc.xxx.workers.dev）</param>
        /// <param name="apiKey">管理画面で発行した API キー</param>
        /// <param name="namespaces">検索対象ナレッジ（カンマ区切り。空または null は全ナレッジ）</param>
        public CloudflareRAGClient(string workerUrl, string apiKey, string namespaces = "")
        {
            _baseUrl = (workerUrl ?? "").Trim().TrimEnd('/');
            _apiKey  = apiKey ?? "";
            _namespaces = ParseNamespaces(namespaces);
        }

        /// <summary>Worker の /query に POST し、回答と出典を返す。</summary>
        public async Task<RAGResponse> QueryAsync(string query, IReadOnlyList<RAGMessage> history)
        {
            if (string.IsNullOrEmpty(_baseUrl))
                throw new Exception("Cloudflare の URL が未設定です（Settings タブで入力してください）");

            // JsonUtility は Dictionary や List を直接シリアライズできないため手動で JSON を組み立てる
            var sb = new StringBuilder();
            sb.Append("{\"query\":").Append(JsonEscape(query));
            sb.Append(",\"history\":").Append(BuildHistoryJson(history));
            if (_namespaces.Length > 0)
            {
                sb.Append(",\"namespaces\":[");
                for (int i = 0; i < _namespaces.Length; i++)
                {
                    if (i > 0) sb.Append(',');
                    sb.Append(JsonEscape(_namespaces[i]));
                }
                sb.Append(']');
            }
            sb.Append('}');

            var text = await PostJsonAsync(_baseUrl + "/query", sb.ToString(), 60);
            return ParseResponse(text);
        }

        /// <summary>
        /// 回答に 👍/👎 評価を送る（/memory/rate。id は数値、rating は 1 / -1）。
        /// memoryId が数値でないとき（Local モードなど）は false を返す。
        /// </summary>
        public async Task<bool> RateAsync(string memoryId, string rating)
        {
            if (string.IsNullOrEmpty(_baseUrl) || !long.TryParse(memoryId, out var id)) return false;
            var body = $"{{\"id\":{id},\"rating\":{(rating == "up" ? 1 : -1)}}}";
            try
            {
                await PostJsonAsync(_baseUrl + "/memory/rate", body, 15);
                return true;
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>
        /// Worker の /health に GET して疎通を確認する（200 OK で「生きている」）。
        /// URL が未設定のときは即 false を返して無駄なリクエストを避ける。
        /// </summary>
        public async Task<bool> HealthCheckAsync()
        {
            if (string.IsNullOrEmpty(_baseUrl)) return false;
            var req = UnityWebRequest.Get(_baseUrl + "/health");
            req.timeout = 5;  // 5 秒で判定（UI 応答を止めないよう短めに設定）
            req.SetRequestHeader("User-Agent", UserAgent);
            var op = req.SendWebRequest();
            while (!op.isDone) await Task.Yield();
            return req.result == UnityWebRequest.Result.Success;
        }

        // ── 内部ユーティリティ ──────────────────────────────────────────────────

        /// <summary>
        /// JSON を POST して、レスポンス本文を返す。HTTP エラーは、Worker が返す {"error": "..."} の
        /// メッセージ（認証エラー・利用上限など）を付けて例外にする。
        /// </summary>
        private async Task<string> PostJsonAsync(string url, string jsonBody, int timeoutSec)
        {
            var bytes = Encoding.UTF8.GetBytes(jsonBody);
            var req = new UnityWebRequest(url, "POST")
            {
                uploadHandler   = new UploadHandlerRaw(bytes),
                downloadHandler = new DownloadHandlerBuffer(),
                timeout         = timeoutSec,
            };
            req.SetRequestHeader("Content-Type", "application/json");
            req.SetRequestHeader("Authorization", "Bearer " + _apiKey);
            req.SetRequestHeader("User-Agent", UserAgent);
            var op = req.SendWebRequest();
            while (!op.isDone) await Task.Yield();  // Unity のフレームループをブロックしないよう yield

            if (req.result != UnityWebRequest.Result.Success)
            {
                var detail = req.downloadHandler?.text;
                var message = ExtractJsonString(detail, "error");
                throw new Exception($"Cloudflare RAG エラー: {(string.IsNullOrEmpty(message) ? req.error : message)}");
            }
            return req.downloadHandler.text;
        }

        /// <summary>
        /// レスポンス本文を RAGResponse に変換する。Worker の形（出典は file / namespace、memoryId は数値）を
        /// 既存の UI が読む形（title / db、memoryId は文字列）に読み替える。
        /// </summary>
        internal static RAGResponse ParseResponse(string text)
        {
            var res = JsonUtility.FromJson<WorkerResponse>(text) ?? new WorkerResponse();
            var sources = new List<RAGSource>();
            if (res.sources != null)
            {
                foreach (var s in res.sources)
                    sources.Add(new RAGSource { title = s.file, db = s.@namespace, score = s.score });
            }
            // JsonUtility は数値の memoryId を文字列フィールドへ入れられないため、本文から直接取り出す
            var m = Regex.Match(text ?? "", "\"memoryId\"\\s*:\\s*(\\d+)");
            return new RAGResponse
            {
                answer   = res.answer,
                sources  = sources.ToArray(),
                status   = res.status,
                memoryId = m.Success ? m.Groups[1].Value : "",
            };
        }

        // Worker のレスポンス形（JsonUtility 用）。"namespace" は C# の予約語なので @ を付けて宣言する
        // （フィールド名としては "namespace" になり、JSON のキーと一致する）。
        [Serializable]
        private class WorkerSource
        {
            public string file;
            public string @namespace;
            public float  score;
        }

        [Serializable]
        private class WorkerResponse
        {
            public string         answer;
            public WorkerSource[] sources;
            public string         status;
        }

        /// <summary>会話履歴を JSON 配列文字列にする（Worker は {role, content} 形式）。</summary>
        private static string BuildHistoryJson(IReadOnlyList<RAGMessage> history)
        {
            var sb = new StringBuilder("[");
            for (int i = 0; i < history.Count; i++)
            {
                if (i > 0) sb.Append(',');
                sb.Append($"{{\"role\":{JsonEscape(history[i].role)},\"content\":{JsonEscape(history[i].text)}}}");
            }
            sb.Append(']');
            return sb.ToString();
        }

        private static string[] ParseNamespaces(string text)
        {
            var list = new List<string>();
            foreach (var part in (text ?? "").Replace('、', ',').Replace(' ', ',').Split(','))
            {
                var p = part.Trim();
                if (p.Length > 0 && !list.Contains(p)) list.Add(p);
            }
            return list.ToArray();
        }

        private static string ExtractJsonString(string json, string key)
        {
            if (string.IsNullOrEmpty(json)) return "";
            var m = Regex.Match(json, "\"" + key + "\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
            return m.Success ? Regex.Unescape(m.Groups[1].Value) : "";
        }

        /// <summary>
        /// 文字列を JSON 値としてエスケープして二重引用符で包む。
        /// Newtonsoft.Json 等の外部ライブラリを追加せずに済ませるため、手動でエスケープする。
        /// </summary>
        private static string JsonEscape(string s)
        {
            if (s == null) return "null";
            return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"")
                            .Replace("\n", "\\n").Replace("\r", "\\r").Replace("\t", "\\t") + "\"";
        }
    }
}
