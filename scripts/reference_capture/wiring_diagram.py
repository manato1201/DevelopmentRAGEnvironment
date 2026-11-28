"""Reference のノード図を、ネットワークエディタの見た目で、ポートの位置どおりに描く（2026-11-28）。

実証実験で「Reference のノード図では、どの場所（どの出力・どの入力）からつなぐのかが分からず、再現しにくい」と言われた。
以前の図（screen_capture.render_graph_diagram）は、ノードどうしがつながっていることだけを描き、ポートを描かなかった。
ここでは、実機（hython）で書き出した条件（dump_conditions.py の出力）から、各ノードの入力の点（上辺）と出力の点（下辺）を、
実物と同じ並びで描き、線を「何番目の出力 → 何番目の入力」で結び、つないだ点に、番号と名前（Constraint Geometry など）を添える。
適用前の画像を並べるためだけのノード（表示するノードに届かないもの）は、描かない。

  uv run --with PySide6 python scripts/reference_capture/wiring_diagram.py --conditions build/reference_conditions.json --out build/reference_media [--only sop/vellumsolver]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BG = "#2f2f31"
NODE = "#cfcfcf"
NODE_TEXT = "#1c1c1e"
TYPE_TEXT = "#4a4a4f"
DISPLAY = "#3b9cff"
HIDDEN = "#f59e0b"
WIRE = ("#d4d4d8", "#e879f9", "#60a5fa", "#fbbf24", "#4ade80")  # 出力の番号ごとの色（1 番目は、画面と同じ灰色）
PILL_BG = "#1c1c1f"

NODE_H = 58
SLOT = 200          # 1 つのポートが使う横幅（名前の札が重ならないように）
MIN_W = 220
LAYER_GAP = 150     # 段の間（ここに、出力・入力の名前の札が入る）
COL_GAP = 60
MARGIN = 40


def _ancestors(nodes: dict, start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        name = stack.pop()
        if name in seen or name not in nodes:
            continue
        seen.add(name)
        stack.extend(c["from"] for c in nodes[name].get("inputs") or [] if c.get("from"))
    return seen


def _ports(node: dict, side: str) -> int:
    if side == "in":
        if node.get("multi_input"):
            return 1
        connected = max([c["index"] + 1 for c in node.get("inputs") or []] or [0])
        return max(len(node.get("input_labels") or []), connected)
    connected_out = node.get("_used_outputs") or [0]
    return max(len(node.get("output_labels") or []) or 1, max(connected_out) + 1)


def layout(cond: dict) -> tuple[list[dict], dict, int, int]:
    """描くノード（表示するノードに届くものだけ）と、位置。戻り値: (ノード, {名前: (x, y, w)}, 幅, 高さ)。"""
    by_name = {n["name"]: n for n in cond.get("nodes") or []}
    display = cond.get("display") or (cond["nodes"][-1]["name"] if cond.get("nodes") else "")
    keep = _ancestors(by_name, display) if display in by_name else set(by_name)
    nodes = [n for n in cond.get("nodes") or [] if n["name"] in keep]
    for n in nodes:
        n["_used_outputs"] = []
    for n in nodes:
        for c in n.get("inputs") or []:
            if c.get("from") in by_name and c["from"] in keep:
                by_name[c["from"]]["_used_outputs"].append(int(c.get("output") or 0))
    depth: dict[str, int] = {}

    def level(name: str, trail: tuple = ()) -> int:
        if name in depth:
            return depth[name]
        if name in trail:
            return 0
        sources = [c["from"] for c in by_name[name].get("inputs") or [] if c.get("from") in keep]
        depth[name] = 0 if not sources else 1 + max(level(s, trail + (name,)) for s in sources)
        return depth[name]

    for n in nodes:
        level(n["name"])
    rows: dict[int, list[dict]] = {}
    for n in nodes:
        rows.setdefault(depth[n["name"]], []).append(n)
    widths = {n["name"]: max(MIN_W, SLOT * max(_ports(n, "in"), _ports(n, "out"))) for n in nodes}
    canvas_w = max(sum(widths[n["name"]] for n in row) + COL_GAP * (len(row) - 1) for row in rows.values()) + 2 * MARGIN + 60
    pos: dict[str, tuple[int, int, int]] = {}
    for r, row in sorted(rows.items()):
        total = sum(widths[n["name"]] for n in row) + COL_GAP * (len(row) - 1)
        x = (canvas_w - total) // 2
        y = MARGIN + 40 + r * (NODE_H + LAYER_GAP)
        for n in row:
            pos[n["name"]] = (x, y, widths[n["name"]])
            x += widths[n["name"]] + COL_GAP
    canvas_h = MARGIN + 40 + (max(rows) + 1) * (NODE_H + LAYER_GAP) - LAYER_GAP + MARGIN + 20
    return nodes, pos, canvas_w, canvas_h


def _port_x(x: int, w: int, index: int, count: int) -> float:
    """ポートの x。1 つのポートに SLOT の幅を割り当て、ノードの中央にそろえる（名前の札が、となりと重ならない）。"""
    return x + (w - SLOT * count) / 2 + SLOT * (index + 0.5)


def render(cond: dict, path: Path, title: str = "/obj/ref") -> bool:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

    def font(size: int, bold: bool = False) -> QFont:
        f = QFont()
        f.setFamilies(["Segoe UI", "Yu Gothic UI", "Meiryo"])
        f.setPixelSize(size)
        f.setBold(bold)
        return f

    nodes, pos, width, height = layout(cond)
    if not nodes:
        return False
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor(BG))
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setFont(font(20, True))
    p.setPen(QColor("#e4e4e7"))
    p.drawText(QRectF(MARGIN, 10, width - 2 * MARGIN, 30), Qt.AlignLeft | Qt.AlignVCenter, title)
    by_name = {n["name"]: n for n in nodes}
    label_font = font(15)
    metrics = QFontMetricsF(label_font)
    labels: list[tuple[QRectF, str, str]] = []

    def pill(cx: float, cy: float, text: str, color: str) -> None:
        room = SLOT - 14
        shown = metrics.elidedText(text, Qt.ElideRight, room - 16)
        w = min(room, metrics.horizontalAdvance(shown) + 18)
        labels.append((QRectF(cx - w / 2, cy - 12, w, 24), shown, color))

    # 線（先に描き、ノードを上に重ねる）
    for n in nodes:
        x, y, w = pos[n["name"]]
        n_in = _ports(n, "in")
        for c in n.get("inputs") or []:
            src = by_name.get(c.get("from"))
            if src is None:
                continue
            sx, sy, sw = pos[src["name"]]
            out_i = int(c.get("output") or 0)
            ax, ay = _port_x(sx, sw, out_i, _ports(src, "out")), sy + NODE_H
            bx = x + w / 2 if n.get("multi_input") else _port_x(x, w, int(c["index"]), n_in)
            by = y
            color = WIRE[out_i % len(WIRE)]
            path_ = QPainterPath(QPointF(ax, ay))
            bend = max(40.0, (by - ay) * 0.5)
            path_.cubicTo(QPointF(ax, ay + bend), QPointF(bx, by - bend), QPointF(bx, by))
            p.setPen(QPen(QColor(color), 3))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path_)
            out_names = src.get("output_labels") or []
            out_name = out_names[out_i] if out_i < len(out_names) else ""
            out_text = f"出力{out_i + 1}" + (f" {out_name}" if out_name and not out_name.startswith("Output ") else "")
            pill(ax, ay + 22, out_text, color)
            if not n.get("multi_input"):
                in_name = c.get("label") or ""
                in_text = f"入力{int(c['index']) + 1}" + (f" {in_name}" if in_name and not in_name.startswith("Input ") else "")
                pill(bx, by - 22, in_text, color)
    # ノード
    name_font = font(20, True)
    type_font = font(14)
    for n in nodes:
        x, y, w = pos[n["name"]]
        rect = QRectF(x, y, w, NODE_H)
        p.setPen(QPen(QColor(HIDDEN if n.get("hidden") else "#1c1c1e"), 3 if n.get("hidden") else 1.5))
        p.setBrush(QColor(NODE))
        p.drawRoundedRect(rect, 7, 7)
        p.setPen(QColor(NODE_TEXT))
        p.setFont(name_font)
        p.drawText(QRectF(x, y + 4, w, 28), Qt.AlignCenter, n["name"])
        p.setPen(QColor(TYPE_TEXT))
        p.setFont(type_font)
        p.drawText(QRectF(x, y + 30, w, 22), Qt.AlignCenter, f"{n.get('label') or n['type']}（{n['type']}）")
        # 入力の点（上辺）。Merge のように、いくつでもつなげる入力は、横長の口
        connected_in = {int(c["index"]) for c in n.get("inputs") or []}
        if n.get("multi_input"):
            p.setPen(QPen(QColor("#1c1c1e"), 1.5))
            p.setBrush(QColor("#9ca3af"))
            p.drawRoundedRect(QRectF(x + w * 0.2, y - 6, w * 0.6, 10), 5, 5)
        else:
            count = _ports(n, "in")
            for i in range(count):
                cx = _port_x(x, w, i, count)
                p.setPen(QPen(QColor("#1c1c1e"), 1.5))
                p.setBrush(QColor("#e4e4e7") if i in connected_in else QColor("#6b7280"))
                p.drawEllipse(QPointF(cx, y), 6, 6)
        used_out = set(n.get("_used_outputs") or [])
        count_out = _ports(n, "out")
        for i in range(count_out):
            cx = _port_x(x, w, i, count_out)
            p.setPen(QPen(QColor("#1c1c1e"), 1.5))
            p.setBrush(QColor(WIRE[i % len(WIRE)]) if i in used_out else QColor("#6b7280"))
            p.drawEllipse(QPointF(cx, y + NODE_H), 6, 6)
        if n["name"] == cond.get("display"):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(DISPLAY))
            p.drawEllipse(QPointF(x + w + 16, y + NODE_H / 2), 9, 9)
    # ポートの名前の札（最後に、いちばん上に）
    p.setFont(label_font)
    for rect, text, color in labels:
        p.setPen(QPen(QColor(color), 1.5))
        p.setBrush(QColor(PILL_BG))
        p.drawRoundedRect(rect, 10, 10)
        p.setPen(QColor("#f4f4f5"))
        p.drawText(rect, Qt.AlignCenter, text)
    p.end()
    return bool(image.save(str(path), "PNG"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--conditions", default="build/reference_conditions.json")
    parser.add_argument("--out", default="build/reference_media")
    parser.add_argument("--only", default="")
    args = parser.parse_args(argv)
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from capture import slug_dir

    data = json.loads(Path(args.conditions).read_text(encoding="utf-8"))
    from recipes import RECIPES

    kinds = {r["key"]: r["kind"] for r in RECIPES}
    only = {k for k in args.only.split(",") if k}
    done = skipped = 0
    for key, cond in data.items():
        if only and key not in only:
            continue
        if not isinstance(cond, dict) or "error" in cond or any(n.get("vop") for n in cond.get("nodes") or []):
            skipped += 1  # VOP の中の配線は、別の図（capture.py の vop_diagram）のまま
            continue
        target = slug_dir(Path(args.out), kinds.get(key, "node"), key)
        target.mkdir(parents=True, exist_ok=True)
        if render(cond, target / "node.png"):
            done += 1
        else:
            skipped += 1
    print(f"描いた {done} 件 / 飛ばした {skipped} 件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
