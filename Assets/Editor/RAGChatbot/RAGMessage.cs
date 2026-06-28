using System;

namespace RAGChatbot
{
    /// <summary>
    /// チャット1件分のメッセージ。
    /// role は "user"（ユーザー発言）か "assistant"（RAG の回答）のどちらか。
    /// JsonUtility でシリアライズするため [Serializable] が必須。
    /// </summary>
    [Serializable]
    public class RAGMessage
    {
        public string role;       // "user" | "assistant"
        public string text;       // メッセージ本文
        public long   timestamp;  // Unix 秒。履歴のソートや表示に使う
        public string memoryId;   // Cloud RAG の RAG_Memory 行ID（評価リクエスト用）
        public int    rating;     // 0=未評価, 1=👍, -1=👎

        public RAGMessage(string role, string text)
        {
            this.role      = role;
            this.text      = text;
            this.timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        }
    }

    /// <summary>
    /// RAG 回答が参照したドキュメント1件分。
    /// GAS や Local ブリッジが返す sources 配列の各要素に対応する。
    /// </summary>
    [Serializable]
    public class RAGSource
    {
        public string title;  // ドキュメントタイトル（ファイル名など）
        public string db;     // 所属 DB キー（例: "tool_docs", "game_info"）
        public float  score;  // クエリとのコサイン類似度スコア [0, 1]
    }

    /// <summary>
    /// RAG クエリへのレスポンス全体。
    /// QueryAsync の戻り値として使う。JsonUtility でデシリアライズする。
    /// </summary>
    [Serializable]
    public class RAGResponse
    {
        public string      answer;    // Gemini が生成した回答テキスト
        public RAGSource[] sources;   // 参照したドキュメントの一覧（上位 N 件）
        public string      status;    // "ok" | "error" など
        public string      memoryId;  // 保存された RAG_Memory の行ID（評価に使う）
    }
}
