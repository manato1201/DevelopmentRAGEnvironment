using System;

namespace RAGChatbot
{
    [Serializable]
    public class RAGGraphNode
    {
        public string id;
        public string label;
        public string db;         // "local" | "cloud"
        public int chunk_count;
        public float x;           // [0, 1] 正規化座標
        public float y;
    }

    [Serializable]
    public class RAGGraphEdge
    {
        public string source;
        public string target;
        public float score;       // コサイン類似度 [0, 1]
    }

    [Serializable]
    public class RAGGraphData
    {
        public RAGGraphNode[] nodes;
        public RAGGraphEdge[] edges;
    }
}
