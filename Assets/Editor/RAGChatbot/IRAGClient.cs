using System.Collections.Generic;
using System.Threading.Tasks;

namespace RAGChatbot
{
    public interface IRAGClient
    {
        /// <summary>
        /// RAG クエリを送信して回答を返す。
        /// </summary>
        Task<RAGResponse> QueryAsync(string query, IReadOnlyList<RAGMessage> history);

        /// <summary>
        /// エンドポイントの疎通確認。接続可能なら true。
        /// </summary>
        Task<bool> HealthCheckAsync();
    }
}
