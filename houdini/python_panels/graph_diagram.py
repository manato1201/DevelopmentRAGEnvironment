"""
graph_diagram.py — 保存したノードグラフ（<名前>.json）を、ネットワーク図の「モデル」にする（2026-10-21）

動画の説明スライドのうち、画像の無いスライドは、空のグラデーションの板（ぼやけた画面）になっていた。
「ノードの関係図」を出すため、保存済みのグラフ JSON（NodeGraphAsset 形式: nodes / edges）から、
screen_capture.py の描画（_assign_layers / _paint_network_diagram）が読む形のモデルを作る。

Houdini（hou）にも Qt にも依存しない純粋な関数だけを置く（単体テストできるように）。
描画そのものは screen_capture.render_graph_diagram が行う。
"""

from __future__ import annotations

MAX_NODES = 60  # screen_capture._MAX_DIAGRAM_NODES と同じ。多すぎると読めない


def pick_container(graph: dict) -> str | None:
    """図に出す「ひとつのネットワーク」の親ノードID。作業の本体の geo のように、**浅く**て、直下に2つ以上の
    ノードがある親を選ぶ（深い所にある、サブネット（APEXなど）の内部の数十ノードを選ぶと、読めない図になる）。
    親を持つノードが無ければ None（トップレベルのノードを出す）。"""
    counts: dict[str, int] = {}
    for node in graph.get("nodes") or []:
        parent = node.get("parent")
        if parent:
            counts[parent] = counts.get(parent, 0) + 1
    if not counts:
        return None
    # 浅い親を優先し、同じ深さなら、直下のノードが多いほう。直下が2つ以上あるものを先に探す。
    for minimum in (2, 1):
        candidates = [p for p, n in counts.items() if n >= minimum]
        if candidates:
            return min(candidates, key=lambda p: (p.count("/"), -counts[p], p))
    return None


def graph_to_model(graph: dict) -> tuple[str, list[dict]]:
    """(図の上部に出すパス, モデル) を返す。ノードが無ければ ("", [])。"""
    nodes_all = [n for n in (graph.get("nodes") or []) if isinstance(n, dict) and n.get("id")]
    if not nodes_all:
        return "", []
    container = pick_container(graph)
    nodes = [n for n in nodes_all if (n.get("parent") or None) == container][:MAX_NODES]
    if not nodes:
        return "", []
    known = {n["id"] for n in nodes}
    inputs: dict[str, list[tuple[str, int]]] = {n["id"]: [] for n in nodes}
    has_output: set[str] = set()
    for edge in graph.get("edges") or []:
        source, target = edge.get("source"), edge.get("target")
        if source in known and target in known and source != target:
            inputs[target].append((source, int(edge.get("targetInput") or 0)))
            has_output.add(source)

    model = []
    for n in nodes:
        node_id = n["id"]
        position = n.get("position") or [0.0, 0.0]
        try:
            x = float(position[0])
        except (TypeError, ValueError, IndexError):
            x = 0.0
        model.append({
            "path": node_id,
            "name": str(n.get("label") or node_id.rsplit("/", 1)[-1]),
            "type": str(n.get("kind") or ""),
            "color": (0.8, 0.8, 0.8),
            "display": node_id not in has_output,  # 出力先が無い末端が、画面に表示されるノード
            "render": False,
            "bypass": False,
            "error": False,
            "x": x,
            "inputs": inputs[node_id],
        })
    sandbox = str(graph.get("sandbox") or "").rstrip("/")
    label = f"{sandbox}/{container}" if sandbox and container and not container.startswith(sandbox) else (container or sandbox or "")
    return label, model
