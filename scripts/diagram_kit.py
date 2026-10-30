"""
diagram_kit.py — ドキュメント用の構成図（SVG）を作る小さな部品（2026-10-23追加）

方針:
  ・単体で表示できるSVG（外部ライブラリ・外部フォントなし）。Markdownから ![](images/xxx.svg) で読み込む
  ・ライト/ダークは、SVGの中の @media (prefers-color-scheme: dark) で切り替える
  ・部品は「枠（グループ）・タイル（アイコン代わりの記号つき）・矢印（ラベルつき）・番号の丸」だけ
  ・色は層ごとに固定（意味は凡例に出す）: 画面=橙 / 中核=緑 / 保存=紫 / 外部=青 / 安全=濃緑 / 注意=赤 / 検討中=黄
  ・座標は手で決める（自動配置はしない。図の意図を、そのまま固定するため）
  ・ブランドのロゴは使わない（記号の文字で代用する。他社のロゴ・画像を写さない）

読みやすさの決まり（2026-10-30。DNS・構成図の参考例から）:
  ・順番のある流れは、矢印に番号の丸（step）をつける。番号は、本文の説明と同じ順にする
  ・枠は「目的」の名前で呼ぶ（「画面を届ける」「ログイン」のように）。技術名は、枠の中のタイルの名前にする
  ・主役の流れは実線、補助（鍵の受け渡し・保存の裏側・デプロイ）は破線にする
  ・特別な道筋（直接つなぐ・書き込みなど）だけ、色を変える。ほかは同じ色
  ・矢印は、枠の見出しと文字の上を通さない（label_at と via で逃がす）
"""

from __future__ import annotations

from html import escape

FONT = '"Noto Sans JP","Yu Gothic UI","Yu Gothic","Meiryo",system-ui,sans-serif'
MONO = 'ui-monospace,"Cascadia Mono",Consolas,monospace'

KINDS = {
    "ui": ("--ui", "画面・利用者側"),
    "core": ("--core", "中核（処理）"),
    "store": ("--store", "保存"),
    "ext": ("--ext", "外部サービス"),
    "safe": ("--safe", "安全・権限"),
    "warn": ("--warn", "注意・制限"),
    "plan": ("--plan", "検討中"),
    "gray": ("--gray", "補助"),
}

STYLE = """
  :root { --bg:#f7f8fa; --panel:#eef1f5; --card:#ffffff; --fg:#1b2330; --muted:#5d6878; --line:#9aa5b6; --grid:#e6eaf0;
    --ui:#e0782f; --core:#14867a; --store:#6f4fbd; --ext:#2a58d1; --safe:#1b8a5e; --warn:#c0392b; --plan:#a87d12; --gray:#5d6878; }
  @media (prefers-color-scheme: dark) { :root { --bg:#11161e; --panel:#1a2230; --card:#232d3f; --fg:#e4e9f1; --muted:#9aa5b6; --line:#6b778a; --grid:#1d2635;
    --ui:#f09a5c; --core:#3fc4b3; --store:#a98bf0; --ext:#7ba2ff; --safe:#55cf98; --warn:#ff9b86; --plan:#e0b84a; --gray:#9aa5b6; } }
  text { font-family: %(font)s; fill: var(--fg); }
  .muted { fill: var(--muted); }
  .title { font-size: 22px; font-weight: 700; }
  .gtitle { font-size: 19px; font-weight: 700; }
  .gsub { font-size: 13px; }
  .label { font-size: 16px; font-weight: 700; }
  .sub { font-size: 13px; }
  .elabel { font-size: 14px; font-weight: 600; paint-order: stroke; stroke: var(--bg); stroke-width: 5px; stroke-linejoin: round; }
  .glyph { font-family: %(mono)s; font-weight: 700; fill: #fff; }
  .edge { fill: none; stroke: var(--line); stroke-width: 2; }
  .edge.dash { stroke-dasharray: 6 5; }
  .badge-n { font-size: 12px; font-weight: 700; fill: #fff; }
""" % {"font": FONT, "mono": MONO}


class Diagram:
    def __init__(self, width: int, height: int, title: str = "", subtitle: str = "", legend: list[str] | None = None) -> None:
        self.w, self.h = width, height
        self.title, self.subtitle = title, subtitle
        self.legend = legend or []
        self.parts: list[str] = []
        self.edges: list[str] = []
        self.nodes: dict[str, tuple[int, int, int, int]] = {}  # id -> (x, y, w, h) タイル部分
        self.label_bottom: dict[str, int] = {}  # id -> 名前・説明の文字の下端（縦の矢印を、文字の下から出すため）

    # ── 部品 ────────────────────────────────────────────────────────────
    def group(self, x: int, y: int, w: int, h: int, title: str, sub: str = "", kind: str = "gray", dashed: bool = False) -> None:
        var = KINDS[kind][0]
        dash = ' stroke-dasharray="8 6"' if dashed else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="var(--panel)" fill-opacity="0.75" stroke="var({var})" stroke-width="2"{dash}/>'
        )
        self.parts.append(f'<text class="gtitle" x="{x + 18}" y="{y + 28}" fill="var({var})" style="fill:var({var})">{escape(title)}</text>')
        if sub:
            self.parts.append(f'<text class="gsub muted" x="{x + 18}" y="{y + 46}">{escape(sub)}</text>')

    def node(self, nid: str, x: int, y: int, label: str, sub: str = "", glyph: str = "", kind: str = "core", size: int = 56, sub2: str = "") -> None:
        """タイル（size四方）と、その下の名前・説明。x,y はタイルの左上。"""
        var = KINDS[kind][0]
        self.nodes[nid] = (x, y, size, size)
        self.label_bottom[nid] = y + size + 24 + (16 if sub else 0) + (14 if sub2 else 0)
        self.parts.append(f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="12" fill="var({var})"/>')
        if glyph:
            fs = 22 if len(glyph) <= 2 else (17 if len(glyph) == 3 else 13)
            self.parts.append(f'<text class="glyph" x="{x + size / 2}" y="{y + size / 2 + fs * 0.35}" font-size="{fs}" text-anchor="middle">{escape(glyph)}</text>')
        cx = x + size / 2
        self.parts.append(f'<text class="label" x="{cx}" y="{y + size + 20}" text-anchor="middle">{escape(label)}</text>')
        if sub:
            self.parts.append(f'<text class="sub muted" x="{cx}" y="{y + size + 36}" text-anchor="middle">{escape(sub)}</text>')
        if sub2:
            self.parts.append(f'<text class="sub muted" x="{cx}" y="{y + size + 50}" text-anchor="middle">{escape(sub2)}</text>')

    def box(self, nid: str, x: int, y: int, w: int, h: int, label: str, sub: str = "", kind: str = "core", sub2: str = "") -> None:
        """文字だけの角丸の箱（手順の1段など）。label・sub・sub2 の最大3行。"""
        var = KINDS[kind][0]
        self.nodes[nid] = (x, y, w, h)
        self.label_bottom[nid] = y + h
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="var(--card)" stroke="var({var})" stroke-width="2"/>')
        cx, cy = x + w / 2, y + h / 2
        if sub2:
            lines = [(cy - 14, "label", label), (cy + 4, "sub muted", sub), (cy + 20, "sub muted", sub2)]
        elif sub:
            lines = [(cy - 3, "label", label), (cy + 15, "sub muted", sub)]
        else:
            lines = [(cy + 5, "label", label)]
        for ly, cls, text in lines:
            self.parts.append(f'<text class="{cls}" x="{cx}" y="{ly}" text-anchor="middle">{escape(text)}</text>')

    def badge(self, n: int | str, x: int, y: int, kind: str = "core") -> None:
        var = KINDS[kind][0]
        self.parts.append(f'<circle cx="{x}" cy="{y}" r="11" fill="var({var})"/>')
        self.parts.append(f'<text class="badge-n" x="{x}" y="{y + 4.5}" text-anchor="middle">{escape(str(n))}</text>')

    def note(self, x: int, y: int, text: str, anchor: str = "start", size: float = 12.5, bold: bool = False) -> None:
        w = ' font-weight="700"' if bold else ""
        self.parts.append(f'<text class="muted" x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}"{w}>{escape(text)}</text>')

    # ── 矢印 ────────────────────────────────────────────────────────────
    def anchor(self, nid: str, side: str) -> tuple[float, float]:
        x, y, w, h = self.nodes[nid]
        if side == "bb":  # タイルの下の文字の、さらに下
            return (x + w / 2, float(self.label_bottom.get(nid, y + h)))
        return {"l": (x, y + h / 2), "r": (x + w, y + h / 2), "t": (x + w / 2, y), "b": (x + w / 2, y + h)}[side]

    def edge(self, a: str, a_side: str, b: str, b_side: str, label: str = "", dashed: bool = False, via: list[tuple[int, int]] | None = None,
             kind: str = "gray", label_at: tuple[int, int] | None = None, both: bool = False, step: int | str | None = None) -> None:
        """a から b へ。via は、途中の折れ点（直角に曲げる）。ラベルは、既定で中点。"""
        pts = [self.anchor(a, a_side)] + [(float(px), float(py)) for px, py in (via or [])] + [self.anchor(b, b_side)]
        var = KINDS[kind][0]
        d = "M " + " L ".join(f"{px:.1f} {py:.1f}" for px, py in pts)
        cls = "edge dash" if dashed else "edge"
        marker_end = f'marker-end="url(#arrow-{kind})"'
        marker_start = f'marker-start="url(#arrow-{kind})"' if both else ""
        self.edges.append(f'<path class="{cls}" d="{d}" style="stroke:var({var})" {marker_end} {marker_start}/>')
        if label:
            if label_at:
                lx, ly = label_at
            else:
                # 一番長い線分の中点に置く
                best, seg = -1.0, (pts[0], pts[1])
                for p, q in zip(pts, pts[1:]):
                    length = abs(p[0] - q[0]) + abs(p[1] - q[1])
                    if length > best:
                        best, seg = length, (p, q)
                lx, ly = (seg[0][0] + seg[1][0]) / 2, (seg[0][1] + seg[1][1]) / 2 - 6
            self.edges.append(f'<text class="elabel" x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" style="fill:var({var})">{escape(label)}</text>')
        if step is not None:
            self._step_badge(step, pts, label, var, label_at)

    def _step_badge(self, step, pts, label: str, var: str, label_at) -> None:
        """矢印の番号の丸。ラベルがあれば、その左に。無ければ、一番長い線分の中点に。"""
        if label_at:
            bx, by = label_at[0] - (len(label) * 7 + 18 if label else 0), label_at[1] - 5
        else:
            best, seg = -1.0, (pts[0], pts[1])
            for p, q in zip(pts, pts[1:]):
                length = abs(p[0] - q[0]) + abs(p[1] - q[1])
                if length > best:
                    best, seg = length, (p, q)
            bx = (seg[0][0] + seg[1][0]) / 2 - (len(label) * 7 + 18 if label else 0)
            by = (seg[0][1] + seg[1][1]) / 2 - 6 - 5
        self.edges.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="11" fill="var({var})"/>')
        self.edges.append(f'<text class="badge-n" x="{bx:.1f}" y="{by + 4.5:.1f}" text-anchor="middle">{escape(str(step))}</text>')

    def decision(self, nid: str, x: int, y: int, w: int, h: int, label: str, sub: str = "", kind: str = "warn") -> None:
        """判断（ひし形）。分かれ道の文字は、矢印のラベルに書く。"""
        var = KINDS[kind][0]
        self.nodes[nid] = (x, y, w, h)
        self.label_bottom[nid] = y + h
        cx, cy = x + w / 2, y + h / 2
        self.parts.append(f'<polygon points="{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}" fill="var(--card)" stroke="var({var})" stroke-width="2"/>')
        if sub:
            self.parts.append(f'<text class="label" x="{cx}" y="{cy - 2}" text-anchor="middle">{escape(label)}</text>')
            self.parts.append(f'<text class="sub muted" x="{cx}" y="{cy + 15}" text-anchor="middle">{escape(sub)}</text>')
        else:
            self.parts.append(f'<text class="label" x="{cx}" y="{cy + 5}" text-anchor="middle">{escape(label)}</text>')

    def line(self, pts: list[tuple[int, int]], label: str = "", dashed: bool = False, kind: str = "gray", label_at: tuple[int, int] | None = None, arrow: bool = True,
             step: int | str | None = None) -> None:
        """ノードに結ばない矢印（座標だけ）。"""
        var = KINDS[kind][0]
        d = "M " + " L ".join(f"{px} {py}" for px, py in pts)
        cls = "edge dash" if dashed else "edge"
        end = f' marker-end="url(#arrow-{kind})"' if arrow else ""
        self.edges.append(f'<path class="{cls}" d="{d}" style="stroke:var({var})"{end}/>')
        if label:
            lx, ly = label_at if label_at else ((pts[0][0] + pts[-1][0]) // 2, (pts[0][1] + pts[-1][1]) // 2 - 6)
            self.edges.append(f'<text class="elabel" x="{lx}" y="{ly}" text-anchor="middle" style="fill:var({var})">{escape(label)}</text>')
        if step is not None:
            fpts = [(float(px), float(py)) for px, py in pts]
            self._step_badge(step, fpts, label, var, label_at)

    # ── 出力 ────────────────────────────────────────────────────────────
    def svg(self) -> str:
        defs = "".join(
            f'<marker id="arrow-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" style="fill:var({v[0]})"/></marker>'
            for k, v in KINDS.items()
        )
        head = ""
        if self.title:
            head += f'<text class="title" x="26" y="36">{escape(self.title)}</text>'
        if self.subtitle:
            head += f'<text class="muted" x="26" y="58" font-size="13">{escape(self.subtitle)}</text>'
        legend = ""
        if self.legend:
            x = self.w - 24
            items = []
            for k in reversed(self.legend):
                var, name = KINDS[k]
                width = 28 + len(name) * 13
                x -= width
                items.append(f'<rect x="{x}" y="{self.h - 34}" width="14" height="14" rx="4" fill="var({var})"/><text class="muted" x="{x + 20}" y="{self.h - 22}" font-size="12">{escape(name)}</text>')
            legend = "".join(items)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" role="img">'
            f'<style>{STYLE}</style><defs>{defs}</defs>'
            f'<rect width="{self.w}" height="{self.h}" fill="var(--bg)"/>'
            f'{head}{"".join(self.parts)}{"".join(self.edges)}{legend}</svg>'
        )
