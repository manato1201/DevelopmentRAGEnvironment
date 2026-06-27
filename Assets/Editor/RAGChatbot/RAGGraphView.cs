using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace RAGChatbot
{
    /// <summary>
    /// IMGUI ベースの RAG ドキュメントグラフビュー。
    /// パン（左ドラッグ）・ズーム（スクロールホイール）・右クリックリセット対応。
    /// RAGChatbotWindow の Graph タブから Draw() を呼んで使う。
    ///
    /// 描画方式:
    ///   - エッジ: GL（グラフィックスプリミティブ）で線を直接描画。アルファ合成が効く。
    ///   - ノード: IMGUI の EditorGUI.DrawRect で矩形を描画。
    ///   - ラベル: IMGUI の GUI.Label。ズーム 0.5 未満では省略。
    ///   - ツールチップ: ホバー / 選択ノードの詳細をマウス付近に表示。
    ///
    /// 座標系:
    ///   ノードの x, y は [0, 1] に正規化されたワールド座標。
    ///   WorldToScreen() / ScreenToWorld() でキャンバス座標に変換する。
    /// </summary>
    public class RAGGraphView
    {
        // ── 状態 ──────────────────────────────────────────────────────────────
        private RAGGraphData _data;
        private Vector2 _pan    = Vector2.zero;  // キャンバスのパン（ピクセル単位）
        private float   _zoom   = 1f;            // ズーム倍率
        private string  _hovered;                // ホバー中ノード ID
        private string  _selected;               // 選択中ノード ID

        // ── ドラッグ操作 ────────────────────────────────────────────────────
        private bool    _isDragging;
        private Vector2 _dragStart;
        private Vector2 _panAtDragStart;

        // ── 定数 ────────────────────────────────────────────────────────────
        private const float NODE_RADIUS = 22f;   // ノードの基本半径（ズームに応じてスケーリング）
        private const float MIN_ZOOM    = 0.2f;
        private const float MAX_ZOOM    = 4f;

        // ノード色: Local（青系）/ Cloud（緑系）/ ホバー（黄）/ 選択（オレンジ）
        private static readonly Color BG_COLOR      = new Color(0.13f, 0.13f, 0.13f);
        private static readonly Color NODE_LOCAL     = new Color(0.25f, 0.55f, 0.90f);
        private static readonly Color NODE_CLOUD     = new Color(0.25f, 0.75f, 0.50f);
        private static readonly Color NODE_HOVER     = new Color(1.00f, 0.80f, 0.20f);
        private static readonly Color NODE_SELECTED  = new Color(1.00f, 0.45f, 0.10f);
        private static readonly Color EDGE_COLOR     = new Color(0.55f, 0.55f, 0.55f, 0.6f);
        private static readonly Color EDGE_HOT       = new Color(1.00f, 0.80f, 0.20f, 0.9f);  // ホバー/選択ノードに繋がるエッジ

        // ── GL 用マテリアル（遅延初期化） ───────────────────────────────────
        // シェーダー "Hidden/Internal-Colored" は Unity 内蔵のシンプルな頂点色シェーダー。
        // アルファブレンドを有効にして半透明エッジを描画する。
        private static Material s_lineMat;
        private static Material LineMat
        {
            get
            {
                if (s_lineMat == null)
                {
                    s_lineMat = new Material(Shader.Find("Hidden/Internal-Colored"))
                    {
                        hideFlags = HideFlags.HideAndDontSave,  // シーンに保存しない
                    };
                    s_lineMat.SetInt("_SrcBlend", (int)BlendMode.SrcAlpha);
                    s_lineMat.SetInt("_DstBlend", (int)BlendMode.OneMinusSrcAlpha);
                    s_lineMat.SetInt("_Cull",     (int)CullMode.Off);
                    s_lineMat.SetInt("_ZWrite",   0);
                }
                return s_lineMat;
            }
        }

        // ── GUIStyle キャッシュ ─────────────────────────────────────────────
        // GUIStyle の生成は毎フレームやると遅いので初回だけ生成してキャッシュする。
        private GUIStyle _centeredLabel;
        private GUIStyle CenteredLabel
        {
            get
            {
                if (_centeredLabel == null)
                {
                    _centeredLabel = new GUIStyle(EditorStyles.miniLabel)
                    {
                        alignment = TextAnchor.MiddleCenter,
                        wordWrap  = false,
                        fontSize  = 9,
                    };
                    _centeredLabel.normal.textColor = Color.white;
                }
                return _centeredLabel;
            }
        }

        // ─────────────────────────────────────────────────────────────────────

        /// <summary>
        /// グラフデータをセットして再描画する。
        /// null を渡すと空表示（"データがありません" ラベル）になる。
        /// </summary>
        public void SetData(RAGGraphData data)
        {
            _data     = data;
            _hovered  = null;
            _selected = null;
            CenterView();  // データ変更時にビューをリセット
        }

        /// <summary>選択中のノード ID。RAGChatbotWindow が詳細表示に使う。</summary>
        public string SelectedNodeId => _selected;

        // ── 描画エントリポイント ──────────────────────────────────────────────

        /// <summary>
        /// IMGUI OnGUI() 内から呼ぶ。graphRect がグラフ描画領域。
        /// データがない場合はプレースホルダーを表示して早期リターンする。
        /// </summary>
        public void Draw(Rect graphRect, EditorWindow repaintTarget)
        {
            if (_data == null || _data.nodes == null || _data.nodes.Length == 0)
            {
                EditorGUI.DrawRect(graphRect, BG_COLOR);
                var style = new GUIStyle(EditorStyles.centeredGreyMiniLabel);
                GUI.Label(graphRect, "グラフデータがありません\n「更新」ボタンを押してください", style);
                return;
            }

            // 入力処理は Repaint イベント以外でも毎回行う（ホバー・クリック検知のため）
            HandleInput(graphRect, repaintTarget);

            // 描画は Repaint イベントのときのみ実行（そうしないと GL が正しく動かない）
            if (Event.current.type == EventType.Repaint)
            {
                EditorGUI.DrawRect(graphRect, BG_COLOR);
                DrawEdges(graphRect);
                DrawNodes(graphRect);
            }

            DrawTooltip(graphRect);
        }

        // ── 入力処理 ──────────────────────────────────────────────────────────

        /// <summary>
        /// マウス入力を処理してパン・ズーム・選択を更新する。
        /// ズームはマウス位置を中心に拡大縮小する（拡大後も同じ点を指すようにパンを補正）。
        /// </summary>
        private void HandleInput(Rect graphRect, EditorWindow repaintTarget)
        {
            var ev     = Event.current;
            bool inRect = graphRect.Contains(ev.mousePosition);

            // スクロールホイール → ズーム（マウス位置中心）
            if (ev.type == EventType.ScrollWheel && inRect)
            {
                var before = ScreenToWorld(ev.mousePosition, graphRect);
                _zoom = Mathf.Clamp(_zoom * (1f - ev.delta.y * 0.05f), MIN_ZOOM, MAX_ZOOM);
                var after = ScreenToWorld(ev.mousePosition, graphRect);
                // ズーム前後でマウス下のワールド座標が一致するようにパンを補正
                _pan += (after - before) * _zoom;
                repaintTarget.Repaint();
                ev.Use();
            }

            // 左ボタン押下 → ドラッグ開始
            if (ev.type == EventType.MouseDown && ev.button == 0 && inRect)
            {
                _isDragging     = true;
                _dragStart      = ev.mousePosition;
                _panAtDragStart = _pan;
                ev.Use();
            }

            // ドラッグ中 → パン
            if (ev.type == EventType.MouseDrag && _isDragging)
            {
                _pan = _panAtDragStart + (ev.mousePosition - _dragStart);
                repaintTarget.Repaint();
                ev.Use();
            }

            // 左ボタン解放 → ドラッグ終了。移動距離 5px 未満ならクリックとして選択処理
            if (ev.type == EventType.MouseUp && _isDragging)
            {
                if (Vector2.Distance(ev.mousePosition, _dragStart) < 5f)
                {
                    var clicked = NodeAt(ev.mousePosition, graphRect);
                    _selected = clicked;
                    repaintTarget.Repaint();
                }
                _isDragging = false;
                ev.Use();
            }

            // マウス移動 → ホバー更新（変化があったときだけ Repaint）
            if (ev.type == EventType.MouseMove && inRect)
            {
                var prev = _hovered;
                _hovered = NodeAt(ev.mousePosition, graphRect);
                if (_hovered != prev) repaintTarget.Repaint();
            }

            // 右クリック → ビューをリセット（パン・ズームを初期値に戻す）
            if (ev.type == EventType.MouseDown && ev.button == 1 && inRect)
            {
                CenterView();
                repaintTarget.Repaint();
                ev.Use();
            }
        }

        // ── エッジ描画（GL） ─────────────────────────────────────────────────

        /// <summary>
        /// GL（低レベルグラフィクス API）でエッジを線分として描画する。
        /// ホバー / 選択ノードに繋がるエッジは EDGE_HOT 色で強調表示する。
        /// それ以外のエッジは score を alpha に掛けて類似度を視覚化する。
        /// </summary>
        private void DrawEdges(Rect graphRect)
        {
            if (_data.edges == null) return;

            LineMat.SetPass(0);
            GL.PushMatrix();
            GL.Begin(GL.LINES);

            foreach (var edge in _data.edges)
            {
                var srcNode = FindNode(edge.source);
                var tgtNode = FindNode(edge.target);
                if (srcNode == null || tgtNode == null) continue;

                var a = WorldToScreen(new Vector2(srcNode.x, srcNode.y), graphRect);
                var b = WorldToScreen(new Vector2(tgtNode.x, tgtNode.y), graphRect);

                // ホバーまたは選択中のノードに接続するエッジは強調色で描画
                bool hot = (edge.source == _hovered || edge.target == _hovered ||
                            edge.source == _selected || edge.target == _selected);
                var c = hot ? EDGE_HOT : new Color(EDGE_COLOR.r, EDGE_COLOR.g, EDGE_COLOR.b,
                                                    EDGE_COLOR.a * edge.score);
                GL.Color(c);
                GL.Vertex(new Vector3(a.x, a.y, 0));
                GL.Vertex(new Vector3(b.x, b.y, 0));
            }

            GL.End();
            GL.PopMatrix();
        }

        // ── ノード描画（IMGUI） ─────────────────────────────────────────────

        /// <summary>
        /// IMGUI でノードを矩形として描画する。
        /// 色の優先順位: 選択 > ホバー > DB 種別（cloud は緑、その他は青）。
        /// ズーム 0.5 未満ではラベルを省略（小さすぎて読めないため）。
        /// 画面外のノードはスキップしてパフォーマンスを確保する。
        /// </summary>
        private void DrawNodes(Rect graphRect)
        {
            if (_data.nodes == null) return;

            foreach (var node in _data.nodes)
            {
                var center = WorldToScreen(new Vector2(node.x, node.y), graphRect);
                // ズームに応じてノードサイズを平方根でスケーリング（線形より穏やかに変化する）
                float r    = NODE_RADIUS * Mathf.Sqrt(_zoom);
                var   rect = new Rect(center.x - r, center.y - r, r * 2, r * 2);

                // 画面外のノードは描画をスキップ
                if (!new Rect(graphRect.x - r, graphRect.y - r,
                               graphRect.width + r * 2, graphRect.height + r * 2).Contains(center))
                    continue;

                // 色の決定（優先順位: 選択 > ホバー > DB 種別）
                Color col = node.db == "cloud" ? NODE_CLOUD : NODE_LOCAL;
                if (node.id == _selected)       col = NODE_SELECTED;
                else if (node.id == _hovered)   col = NODE_HOVER;

                EditorGUI.DrawRect(rect, col);

                // ラベル（ズームが小さいときは表示しない）
                if (_zoom >= 0.5f)
                {
                    var labelRect = new Rect(rect.x - 20, rect.yMax + 2, rect.width + 40, 16);
                    GUI.Label(labelRect, node.label, CenteredLabel);
                }
            }
        }

        // ── ツールチップ ────────────────────────────────────────────────────

        /// <summary>
        /// ホバー中（または選択中）のノードの詳細をマウス付近に表示する。
        /// ツールチップがウィンドウ端にはみ出さないよう座標をクランプする。
        /// </summary>
        private void DrawTooltip(Rect graphRect)
        {
            string id = _hovered ?? _selected;
            if (string.IsNullOrEmpty(id)) return;

            var node = FindNode(id);
            if (node == null) return;

            string text = $"{node.label}\nチャンク数: {node.chunk_count}\nDB: {node.db}";
            var    size  = GUI.skin.box.CalcSize(new GUIContent(text));
            var    mouse = Event.current.mousePosition;
            float  tx    = Mathf.Min(mouse.x + 12, graphRect.xMax - size.x - 4);
            float  ty    = Mathf.Min(mouse.y + 12, graphRect.yMax - size.y - 4);
            GUI.Box(new Rect(tx, ty, size.x + 8, size.y + 4), text);
        }

        // ── 座標変換ユーティリティ ───────────────────────────────────────────

        /// <summary>
        /// ワールド座標（[0, 1] 正規化）をスクリーン座標（ピクセル）に変換する。
        /// キャンバスの中心を原点にして、パンとズームを適用する。
        /// </summary>
        private Vector2 WorldToScreen(Vector2 worldPos, Rect graphRect)
        {
            var center  = graphRect.center + _pan;
            var scaled  = (worldPos - Vector2.one * 0.5f) * _zoom;
            return center + scaled * new Vector2(graphRect.width, graphRect.height);
        }

        /// <summary>
        /// スクリーン座標（ピクセル）をワールド座標（[0, 1] 正規化）に変換する。
        /// WorldToScreen の逆変換。ズームの中心補正に使う。
        /// </summary>
        private Vector2 ScreenToWorld(Vector2 screenPos, Rect graphRect)
        {
            var center     = graphRect.center + _pan;
            var delta      = screenPos - center;
            if (_zoom == 0) return Vector2.zero;
            var normalized = delta / (_zoom * new Vector2(graphRect.width, graphRect.height));
            return normalized + Vector2.one * 0.5f;
        }

        /// <summary>パンとズームを初期値に戻す。</summary>
        private void CenterView()
        {
            _pan  = Vector2.zero;
            _zoom = 1f;
        }

        // ── ヘルパー ────────────────────────────────────────────────────────

        /// <summary>ノード ID からノードデータを線形検索する。</summary>
        private RAGGraphNode FindNode(string id)
        {
            if (_data?.nodes == null) return null;
            foreach (var n in _data.nodes)
                if (n.id == id) return n;
            return null;
        }

        /// <summary>
        /// スクリーン座標にあるノードの ID を返す。
        /// 判定半径は NODE_RADIUS × √zoom + 4px（クリックしやすいよう少し大きくしている）。
        /// </summary>
        private string NodeAt(Vector2 screenPos, Rect graphRect)
        {
            if (_data?.nodes == null) return null;
            float threshold = NODE_RADIUS * Mathf.Sqrt(_zoom) + 4f;
            foreach (var node in _data.nodes)
            {
                var center = WorldToScreen(new Vector2(node.x, node.y), graphRect);
                if (Vector2.Distance(screenPos, center) <= threshold)
                    return node.id;
            }
            return null;
        }
    }
}
