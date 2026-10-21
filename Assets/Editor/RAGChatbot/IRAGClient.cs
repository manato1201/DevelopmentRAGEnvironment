using System.Collections.Generic;
using System.Threading.Tasks;

namespace RAGChatbot
{
    /// <summary>
    /// RAG クライアントの共通インターフェース。
    ///
    /// Cloudflare モード（Cloudflare Worker への HTTPS リクエスト）と
    /// Local モード（localhost の Python ブリッジへの HTTP リクエスト）を
    /// 同じ呼び出し口で切り替えられるよう、依存性逆転の原則に従って抽象化している。
    ///
    /// 実装クラス:
    ///   - CloudflareRAGClient : Cloudflare Worker (/query) に問い合わせる
    ///   - LocalRAGClient : rag_local_bridge.py (localhost:8766) に問い合わせる
    ///
    /// RAGChatbotWindow は IRAGClient 型のフィールドを1つだけ持ち、
    /// モード切り替え時に RebuildClient() で実装を差し替える。
    /// </summary>
    public interface IRAGClient
    {
        /// <summary>
        /// RAG システムに質問を送り、回答と参照ソースを返す。
        /// </summary>
        /// <param name="query">ユーザーの質問文</param>
        /// <param name="history">
        ///   これまでの会話履歴。Gemini がマルチターン対話の文脈を維持するために
        ///   クエリと一緒に送る。長すぎるとトークン上限を超えるため、
        ///   呼び出し元で件数を絞ること（RAGChatbotWindow では直近 12 件）。
        /// </param>
        Task<RAGResponse> QueryAsync(string query, IReadOnlyList<RAGMessage> history);

        /// <summary>
        /// 回答に対して 👍/👎 の評価を送る。
        /// Cloudflare モードでは Worker の /memory/rate で、回答の履歴に評価を記録する。
        /// Local モードでは評価の永続化先がないため常に true を返す（no-op）。
        /// </summary>
        /// <param name="memoryId">QueryAsync が返した RAGResponse.memoryId</param>
        /// <param name="rating">"up"（👍）または "down"（👎）</param>
        Task<bool> RateAsync(string memoryId, string rating);

        /// <summary>
        /// サーバーが応答するか確認するヘルスチェック。
        /// ウィンドウ起動時・モード切り替え時・ブリッジ自動起動の
        /// 待機ループ内で呼ぶ。
        /// 接続できれば true、タイムアウトや例外なら false を返す。
        /// </summary>
        Task<bool> HealthCheckAsync();
    }
}
