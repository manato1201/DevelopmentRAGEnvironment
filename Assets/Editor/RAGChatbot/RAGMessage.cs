using System;

namespace RAGChatbot
{
    [Serializable]
    public class RAGMessage
    {
        public string role;   // "user" | "assistant"
        public string text;
        public long timestamp;

        public RAGMessage(string role, string text)
        {
            this.role = role;
            this.text = text;
            this.timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        }
    }

    [Serializable]
    public class RAGSource
    {
        public string title;
        public string db;
        public float score;
    }

    [Serializable]
    public class RAGResponse
    {
        public string answer;
        public RAGSource[] sources;
        public string status;
    }
}
