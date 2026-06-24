using System;
using System.Collections.Generic;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace RAGChatbot
{
    /// <summary>
    /// IMGUI ベースの RAG ドキュメントグラフビュー。
    /// パン（ドラッグ）・ズーム（スクロールホイール）対応。
    /// RAGChatbotWindow の Graph タブで呼ぶ。
    /// </summary>
    public class RAGGraphView
    {
        // ── 状態 ──────────────────────────────────────────────────────────────
        private RAGGraphData _data;
        private Vector2 _pan    = Vector2.zero;
        private float   _zoom   = 1f;
        private string  _hovered;
        private string  _selected;

        // ── ドラッグ操作 ────────────────────────────────────────────────────
        private bool    _isDragging;
        private Vector2 _dragStart;
        private Vector2 _panAtDragStart;

        // ── 定数 ────────────────────────────────────────────────────────────
        private const float NODE_RADIUS   = 22f;
        private const float MIN_ZOOM      = 0.2f;
        private const float MAX_ZOOM      = 4f;
        private static readonly Color BG_COLOR     = new Color(0.13f, 0.13f, 0.13f);
        private static readonly Color NODE_LOCAL    = new Color(0.25f, 0.55f, 0.90f);
        private static readonly Color NODE_CLOUD    = new Color(0.25f, 0.75f, 0.50f);
        private static readonly Color NODE_HOVER    = new Color(1.00f, 0.80f, 0.20f);
        private static readonly Color NODE_SELECTED = new Color(1.00f, 0.45f, 0.10f);
        private static readonly Color EDGE_COLOR    = new Color(0.55f, 0.55f, 0.55f, 0.6f);
        private static readonly Color EDGE_HOT      = new Color(1.00f, 0.80f, 0.20f, 0.9f);

        // GL 用マテリアル
        private static Material s_lineMat;
        private static Material LineMat
        {
            get
            {
                if (s_lineMat == null)
                {
                    s_lineMat = new Material(Shader.Find("Hidden/Internal-Colored"))
                    {
                        hideFlags = HideFlags.HideAndDontSave,
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
        public void SetData(RAGGraphData data)
        {
            _data     = data;
            _hovered  = null;
            _selected = null;
            CenterView();
        }

        /// <summary>選択中ノード ID（詳細表示用）</summary>
        public string SelectedNodeId => _selected;

        // ── 描画エントリポイント ──────────────────────────────────────────────
        /// <summary>
        /// IMGUI OnGUI() 内から呼ぶ。graphRect がグラフ描画領域。
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

            HandleInput(graphRect, repaintTarget);

            if (Event.current.type == EventType.Repaint)
            {
                EditorGUI.DrawRect(graphRect, BG_COLOR);
                DrawEdges(graphRect);
                DrawNodes(graphRect);
            }

            DrawTooltip(graphRect);
        }

        // ── 入力処理 ──────────────────────────────────────────────────────────
        private void HandleInput(Rect graphRect, EditorWindow repaintTarget)
        {
            var ev = Event.current;
            bool inRect = graphRect.Contains(ev.mousePosition);

            if (ev.type == EventType.ScrollWheel && inRect)
            {
                var before = ScreenToWorld(ev.mousePosition, graphRect);
                _zoom = Mathf.Clamp(_zoom * (1f - ev.delta.y * 0.05f), MIN_ZOOM, MAX_ZOOM);
                var after = ScreenToWorld(ev.mousePosition, graphRect);
                _pan += (after - before) * _zoom;
                repaintTarget.Repaint();
                ev.Use();
            }

            if (ev.type == EventType.MouseDown && ev.button == 0 && inRect)
            {
                _isDragging     = true;
                _dragStart      = ev.mousePosition;
                _panAtDragStart = _pan;
                ev.Use();
            }

            if (ev.type == EventType.MouseDrag && _isDragging)
            {
                _pan = _panAtDragStart + (ev.mousePosition - _dragStart);
                repaintTarget.Repaint();
                ev.Use();
            }

            if (ev.type == EventType.MouseUp && _isDragging)
            {
                // ドラッグ距離が小さければクリックとして扱う
                if (Vector2.Distance(ev.mousePosition, _dragStart) < 5f)
                {
                    var clicked = NodeAt(ev.mousePosition, graphRect);
                    _selected = clicked;
                    repaintTarget.Repaint();
                }
                _isDragging = false;
                ev.Use();
            }

            // ホバー更新
            if (ev.type == EventType.MouseMove && inRect)
            {
                var prev = _hovered;
                _hovered = NodeAt(ev.mousePosition, graphRect);
                if (_hovered != prev) repaintTarget.Repaint();
            }

            // 右クリックでリセット
            if (ev.type == EventType.MouseDown && ev.button == 1 && inRect)
            {
                CenterView();
                repaintTarget.Repaint();
                ev.Use();
            }
        }

        // ── エッジ描画（GL） ─────────────────────────────────────────────────
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
        private void DrawNodes(Rect graphRect)
        {
            if (_data.nodes == null) return;

            foreach (var node in _data.nodes)
            {
                var center = WorldToScreen(new Vector2(node.x, node.y), graphRect);
                float r = NODE_RADIUS * Mathf.Sqrt(_zoom);
                var rect = new Rect(center.x - r, center.y - r, r * 2, r * 2);

                // 外枠のクリッピング（画面外は skip）
                if (!new Rect(graphRect.x - r, graphRect.y - r,
                               graphRect.width + r * 2, graphRect.height + r * 2).Contains(center))
                    continue;

                Color col = node.db == "cloud" ? NODE_CLOUD : NODE_LOCAL;
                if (node.id == _selected) col = NODE_SELECTED;
                else if (node.id == _hovered) col = NODE_HOVER;

                EditorGUI.DrawRect(rect, col);

                // ラベル（ズームが一定以上のときだけ表示）
                if (_zoom >= 0.5f)
                {
                    var labelRect = new Rect(rect.x - 20, rect.yMax + 2, rect.width + 40, 16);
                    GUI.Label(labelRect, node.label, CenteredLabel);
                }
            }
        }

        // ── ツールチップ ────────────────────────────────────────────────────
        private void DrawTooltip(Rect graphRect)
        {
            string id = _hovered ?? _selected;
            if (string.IsNullOrEmpty(id)) return;

            var node = FindNode(id);
            if (node == null) return;

            string text = $"{node.label}\nチャンク数: {node.chunk_count}\nDB: {node.db}";
            var size = GUI.skin.box.CalcSize(new GUIContent(text));
            var mouse = Event.current.mousePosition;
            float tx = Mathf.Min(mouse.x + 12, graphRect.xMax - size.x - 4);
            float ty = Mathf.Min(mouse.y + 12, graphRect.yMax - size.y - 4);
            GUI.Box(new Rect(tx, ty, size.x + 8, size.y + 4), text);
        }

        // ── 座標変換ユーティリティ ───────────────────────────────────────────
        private Vector2 WorldToScreen(Vector2 worldPos, Rect graphRect)
        {
            var center = graphRect.center + _pan;
            var scaled = (worldPos - Vector2.one * 0.5f) * _zoom;
            return center + scaled * new Vector2(graphRect.width, graphRect.height);
        }

        private Vector2 ScreenToWorld(Vector2 screenPos, Rect graphRect)
        {
            var center = graphRect.center + _pan;
            var delta  = screenPos - center;
            if (_zoom == 0) return Vector2.zero;
            var normalized = delta / (_zoom * new Vector2(graphRect.width, graphRect.height));
            return normalized + Vector2.one * 0.5f;
        }

        private void CenterView()
        {
            _pan  = Vector2.zero;
            _zoom = 1f;
        }

        // ── ヘルパー ────────────────────────────────────────────────────────
        private RAGGraphNode FindNode(string id)
        {
            if (_data?.nodes == null) return null;
            foreach (var n in _data.nodes)
                if (n.id == id) return n;
            return null;
        }

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
