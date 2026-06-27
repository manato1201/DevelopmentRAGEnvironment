using System;

namespace RAGChatbot
{
    /// <summary>
    /// グラフのノード1件分。
    /// Local ブリッジの /graph エンドポイントが返す nodes 配列の各要素に対応する。
    /// x, y は [0, 1] に正規化された座標で、RAGGraphView 内でキャンバスサイズに
    /// スケーリングしてから描画する。
    /// </summary>
    [Serializable]
    public class RAGGraphNode
    {
        public string id;           // ドキュメントの一意 ID（ファイルパスなど）
        public string label;        // 表示名（短縮ファイル名など）
        public string db;           // 所属 DB（"cloud" | "local" | "tool_docs" など）
        public int    chunk_count;  // このドキュメントが分割されたチャンク数
        public float  x;            // 正規化 X 座標 [0, 1]
        public float  y;            // 正規化 Y 座標 [0, 1]
    }

    /// <summary>
    /// グラフのエッジ1件分。
    /// ドキュメント間の意味的類似度（コサイン類似度）を表す。
    /// score が高いほど太く・明るく描画されるため、
    /// 関連性の強いドキュメントのペアが視覚的に分かりやすくなる。
    /// </summary>
    [Serializable]
    public class RAGGraphEdge
    {
        public string source;  // 始点ノード ID
        public string target;  // 終点ノード ID
        public float  score;   // コサイン類似度 [0, 1]
    }

    /// <summary>
    /// /graph エンドポイントのレスポンス全体。
    /// LoadGraphAsync() で取得後、RAGGraphView.SetData() に渡してグラフを描画する。
    /// </summary>
    [Serializable]
    public class RAGGraphData
    {
        public RAGGraphNode[] nodes;
        public RAGGraphEdge[] edges;
    }
}
