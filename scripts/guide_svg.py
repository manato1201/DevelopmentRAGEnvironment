"""
guide_svg.py — システムガイド（docs/system-guide.html）用のSVG部品とスタイル（2026-10-08追加）

AXChat:Dの外部サービス連携ガイド（external_integrations.html）の図の作り方を参考にした:
  ・色は層ごとに固定（UI=橙、サーバー/コア=緑、保存=紫、外部=青、安全=濃緑、検討中=黄の破線、警告=赤）
  ・色はCSS変数で持ち、ライト/ダークの両方で読める
  ・図はインラインSVG（外部ライブラリなし）。座標は手で決め、部品は「箱・菱形・レーン・矢印」だけ
図そのものは build_system_guide.py にある。ここは見た目と部品だけを持つ。
"""

from __future__ import annotations

from html import escape

# 矢印・枠の色（CSS変数名）。層の意味と対応させる
COLORS = {
    "muted": "var(--muted)",
    "ui": "var(--c-ui)",
    "core": "var(--c-core)",
    "store": "var(--c-store)",
    "rest": "var(--c-rest)",
    "safe": "var(--c-safe)",
    "plan": "var(--c-plan)",
    "warn": "var(--warn)",
    "ink": "var(--c-ink)",
}

STYLE = """
  :root {
    --bg: #f6f7f9; --surface: #ffffff; --fg: #1b2330; --muted: #5d6878; --line: #dde2ea;
    --accent: #0b5cad; --accent-soft: #e3effb; --code-bg: #eef1f5;
    --ok: #17794a; --ok-soft: #dff3e8; --wait: #8a5a00; --wait-soft: #fbefd3;
    --off: #5d6878; --off-soft: #e8ebf0; --warn: #a3321f; --warn-soft: #fbe5e0;
    --c-ui: #e0782f; --c-core: #14867a; --c-store: #6f4fbd; --c-rest: #2a58d1; --c-safe: #1b8a5e; --c-plan: #a87d12; --c-ink: #1b2330;
    --card: #ffffff; --panel: #f1f3f7; --item: #ffffff;
    --font-display: "Zen Kaku Gothic New", "Noto Sans JP", "Yu Gothic", sans-serif;
    --font-body: "Noto Sans JP", "Yu Gothic", system-ui, sans-serif;
    --font-mono: "IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #11161e; --surface: #181f2a; --fg: #e4e9f1; --muted: #9aa5b6; --line: #2a3443;
      --accent: #6db3f5; --accent-soft: #15283d; --code-bg: #1f2835;
      --ok: #62d195; --ok-soft: #14301f; --wait: #f0c25c; --wait-soft: #35290c;
      --off: #9aa5b6; --off-soft: #232c39; --warn: #ff9b86; --warn-soft: #3a1c16;
      --c-ui: #f09a5c; --c-core: #3fc4b3; --c-store: #a98bf0; --c-rest: #7ba2ff; --c-safe: #55cf98; --c-plan: #e0b84a; --c-ink: #2b3648;
      --card: #1b2230; --panel: #1f2736; --item: #232d3f;
      color-scheme: dark;
    }
  }
  :root[data-theme="dark"] {
    --bg: #11161e; --surface: #181f2a; --fg: #e4e9f1; --muted: #9aa5b6; --line: #2a3443;
    --accent: #6db3f5; --accent-soft: #15283d; --code-bg: #1f2835;
    --ok: #62d195; --ok-soft: #14301f; --wait: #f0c25c; --wait-soft: #35290c;
    --off: #9aa5b6; --off-soft: #232c39; --warn: #ff9b86; --warn-soft: #3a1c16;
    --c-ui: #f09a5c; --c-core: #3fc4b3; --c-store: #a98bf0; --c-rest: #7ba2ff; --c-safe: #55cf98; --c-plan: #e0b84a; --c-ink: #2b3648;
    --card: #1b2230; --panel: #1f2736; --item: #232d3f;
    color-scheme: dark;
  }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--fg); font: 15px/1.8 var(--font-body); margin: 0; padding-inline: 16px; padding-block: 24px 64px; }
  .page { max-width: 1320px; margin: 0 auto; display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 40px; }
  nav.index { position: sticky; top: 16px; align-self: start; font-size: 13px; max-height: calc(100vh - 32px); overflow-y: auto; }
  nav.index p { margin: 0 0 8px; font: 500 11px/1 var(--font-mono); letter-spacing: .12em; color: var(--muted); text-transform: uppercase; }
  nav.index a { display: block; padding: 5px 10px; margin-left: -10px; border-left: 2px solid transparent; color: var(--muted); text-decoration: none; }
  nav.index a:hover, nav.index a:focus-visible { color: var(--accent); border-left-color: var(--accent); outline: none; }
  nav.index .group { display: block; margin: 14px 0 4px; font: 700 12px/1.4 var(--font-body); color: var(--fg); }
  main { min-width: 0; }
  header.top { padding-bottom: 24px; border-bottom: 1px solid var(--line); margin-bottom: 8px; }
  header.top .kicker { font: 500 12px/1 var(--font-mono); letter-spacing: .1em; color: var(--accent); margin: 0 0 12px; }
  h1 { font: 900 clamp(28px, 4.4vw, 40px)/1.3 var(--font-display); margin: 0 0 12px; text-wrap: balance; }
  header.top p.lead { margin: 0; color: var(--muted); max-width: 70ch; }
  h2 { font: 900 24px/1.4 var(--font-display); margin: 56px 0 8px; scroll-margin-top: 16px; text-wrap: balance; }
  h2 small { font: 500 12px/1 var(--font-mono); color: var(--muted); letter-spacing: .08em; margin-left: 10px; vertical-align: middle; }
  h3 { font: 700 17px/1.5 var(--font-body); margin: 28px 0 6px; }
  p { margin: 8px 0; max-width: 76ch; }
  ul, ol { padding-left: 1.4em; margin: 8px 0; max-width: 76ch; }
  li { margin: 4px 0; }
  a { color: var(--accent); }
  code { font: 400 0.88em/1.4 var(--font-mono); background: var(--code-bg); padding: 1px 6px; border-radius: 4px; overflow-wrap: anywhere; }
  .scroll { overflow-x: auto; margin: 14px 0; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); }
  table { border-collapse: collapse; width: 100%; font-size: 13.5px; line-height: 1.6; min-width: 560px; }
  th, td { text-align: left; vertical-align: top; padding: 9px 14px; border-bottom: 1px solid var(--line); }
  th { font: 700 12px/1.4 var(--font-body); color: var(--muted); background: var(--code-bg); white-space: nowrap; }
  tr:last-child td { border-bottom: 0; }
  td code { white-space: normal; }
  td:first-child { min-width: 7.5em; }
  pre { margin: 14px 0; padding: 14px 16px; background: var(--code-bg); border-radius: 8px; overflow-x: auto; font: 400 13px/1.7 var(--font-mono); }
  pre code { background: none; padding: 0; font-size: inherit; }
  .pill { display: inline-block; font: 700 12px/1 var(--font-body); padding: 4px 9px; border-radius: 999px; white-space: nowrap; }
  .pill.ok { color: var(--ok); background: var(--ok-soft); }
  .pill.wait { color: var(--wait); background: var(--wait-soft); }
  .pill.off { color: var(--off); background: var(--off-soft); }
  .pill.warn { color: var(--warn); background: var(--warn-soft); }
  .note { margin: 16px 0; padding: 12px 16px; border-radius: 8px; background: var(--accent-soft); max-width: 76ch; }
  .note.warn { background: var(--warn-soft); }
  .note strong { display: block; margin-bottom: 2px; }
  .who { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; margin: 16px 0; }
  .who > div { padding: 14px 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); min-width: 0; }
  .who h3 { margin: 0 0 4px; font-size: 15px; }
  .who p { margin: 0; font-size: 13.5px; color: var(--muted); }
  .steps { counter-reset: step; list-style: none; padding: 0; margin: 14px 0; max-width: 76ch; }
  .steps > li { counter-increment: step; position: relative; padding: 2px 0 10px 40px; margin: 0; }
  .steps > li::before { content: counter(step); position: absolute; left: 0; top: 2px; width: 26px; height: 26px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); font: 700 13px/26px var(--font-mono); text-align: center; }
  .methods { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; margin: 16px 0; }
  .methods > div { padding: 14px 16px; border: 1px solid var(--line); border-top: 4px solid var(--c-core); border-radius: 8px; background: var(--surface); min-width: 0; }
  .methods > div:nth-child(2) { border-top-color: var(--c-rest); }
  .methods > div:nth-child(3) { border-top-color: var(--c-ui); }
  .methods > div:nth-child(4) { border-top-color: var(--c-store); }
  .methods h3 { margin: 0 0 4px; font-size: 15px; }
  .methods p { margin: 4px 0; font-size: 13.5px; }
  .methods .tag { display: inline-block; margin-top: 6px; font: 500 12px/1 var(--font-mono); color: var(--muted); }
  .diagram { margin: 18px 0; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); overflow-x: auto; }
  .diagram svg { display: block; width: 100%; min-width: 860px; height: auto; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 6px 0 0; font-size: 12.5px; color: var(--muted); }
  .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; background: var(--k); vertical-align: -1px; }
  .d-card { fill: var(--card); stroke: var(--line); stroke-width: 1.5; }
  .d-frame { fill: var(--surface); stroke: var(--fg); stroke-width: 2.5; }
  .d-panel { fill: var(--panel); stroke: none; }
  .d-item { fill: var(--item); stroke: var(--line); stroke-width: 1; }
  .d-chip { fill: var(--surface); stroke: var(--line); }
  .d-plan { fill: none; stroke: var(--c-plan); stroke-width: 1.5; stroke-dasharray: 6 4; }
  .d-step { fill: var(--item); stroke: var(--line); stroke-width: 1.2; }
  .d-lane-a { fill: var(--panel); }
  .d-lane-b { fill: var(--surface); }
  .copy { font: 500 12px/1 var(--font-body); padding: 5px 9px; margin-left: 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--muted); cursor: pointer; }
  .copy:hover, .copy:focus-visible { color: var(--accent); border-color: var(--accent); outline: none; }
  .theme { position: fixed; right: 16px; bottom: 16px; font: 500 12px/1 var(--font-body); padding: 9px 12px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface); color: var(--fg); cursor: pointer; }
  footer { margin-top: 56px; padding-top: 16px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; }
  @media (max-width: 820px) {
    .page { grid-template-columns: minmax(0, 1fr); gap: 16px; }
    nav.index { position: static; max-height: none; display: flex; flex-wrap: wrap; gap: 4px 6px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
    nav.index p, nav.index .group { display: none; }
    nav.index a { margin: 0; padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface); }
    h2 { margin-top: 44px; font-size: 21px; }
  }
"""


def _lines(text: str) -> list[str]:
    return [line for line in text.split("\n")] if text else []


class Svg:
    """1枚の図。部品を足していき、render() でSVG文字列にする。"""

    def __init__(self, width: int, height: int, ident: str, title: str, desc: str = "") -> None:
        self.w, self.h, self.ident, self.title, self.desc = width, height, ident, title, desc
        self.parts: list[str] = []

    # ── 文字 ──
    def text(self, x: float, y: float, text: str, size: float = 13.5, weight: int = 400, fill: str = "var(--fg)",
             anchor: str = "middle", mono: bool = False) -> None:
        family = "var(--font-mono)" if mono else "var(--font-body)"
        self.parts.append(
            f'<text x="{x:g}" y="{y:g}" font-size="{size:g}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" font-family="{family}">{escape(text)}</text>'
        )

    def _centered(self, cx: float, cy: float, title: str, sub: str = "", size: float = 13.5, mono_sub: bool = False,
                  title_fill: str = "var(--fg)") -> None:
        t_lines, s_lines = _lines(title), _lines(sub)
        n = len(t_lines) + len(s_lines)
        lh = size + 4.5
        y0 = cy - (n - 1) * lh / 2 + size * 0.36
        for i, line in enumerate(t_lines):
            self.text(cx, y0 + i * lh, line, size, 700, title_fill)
        for j, line in enumerate(s_lines):
            self.text(cx, y0 + (len(t_lines) + j) * lh, line, size - 1, 400, "var(--muted)", mono=mono_sub)

    # ── 面 ──
    def lane(self, x: float, y: float, w: float, h: float, label: str, alt: bool = True, fill: str = "var(--fg)") -> None:
        self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" class="{"d-lane-a" if alt else "d-lane-b"}"/>')
        if label:
            self.text(x + 16, y + 26, label, 15, 700, fill, "start")

    def group(self, x: float, y: float, w: float, h: float, label: str, color: str = "core", dashed: bool = False) -> None:
        stroke = COLORS[color]
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="14" class="d-panel" '
                          f'style="stroke:{stroke};stroke-width:2;fill:var(--panel)"{dash}/>')
        self.text(x + 16, y + 26, label, 14.5, 700, stroke, "start")

    def box(self, x: float, y: float, w: float, h: float, title: str, sub: str = "", accent: str | None = None,
            cls: str = "d-step", mono_sub: bool = False, size: float = 13.5) -> None:
        self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="10" class="{cls}"/>')
        if accent:
            self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="6" rx="3" fill="{COLORS[accent]}"/>')
        self._centered(x + w / 2, y + h / 2 + (2 if accent else 0), title, sub, size, mono_sub)

    def state(self, x: float, y: float, w: float, h: float, title: str, sub: str, accent: str = "core") -> None:
        self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="16" class="d-item"/>')
        self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="8" rx="4" fill="{COLORS[accent]}"/>')
        self.text(x + w / 2, y + h / 2 - 2, title, 17, 700)
        self.text(x + w / 2, y + h / 2 + 22, sub, 13, 400, "var(--muted)", mono=True)

    def chip(self, x: float, y: float, w: float, h: float, text: str) -> None:
        self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{h / 2:g}" class="d-chip"/>')
        self.text(x + w / 2, y + h / 2 + 4.5, text, 12, 500)

    def diamond(self, cx: float, cy: float, w: float, h: float, text: str) -> None:
        pts = f"{cx:g},{cy - h / 2:g} {cx + w / 2:g},{cy:g} {cx:g},{cy + h / 2:g} {cx - w / 2:g},{cy:g}"
        self.parts.append(f'<polygon points="{pts}" class="d-step"/>')
        lines = _lines(text)
        lh = 17
        y0 = cy - (len(lines) - 1) * lh / 2 + 4.5
        for i, line in enumerate(lines):
            self.text(cx, y0 + i * lh, line, 13, 700)

    def terminal(self, x: float, y: float, w: float, h: float, text: str, color: str = "core") -> None:
        self.parts.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{h / 2:g}" '
                          f'fill="{COLORS[color]}" opacity="0.14" stroke="{COLORS[color]}" stroke-width="2"/>')
        self._centered(x + w / 2, y + h / 2, text, "", 13.5, title_fill="var(--fg)")

    def plan(self, x: float, y: float, w: float, h: float, title: str, sub: str = "") -> None:
        self.box(x, y, w, h, title, sub, cls="d-plan")

    # ── 矢印 ──
    def arrow(self, pts: list[tuple[float, float]], color: str = "muted", label: str = "", lx: float | None = None,
              ly: float | None = None, dashed: bool = False, anchor: str = "middle") -> None:
        d = "M" + " L".join(f"{x:g} {y:g}" for x, y in pts)
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{COLORS[color]}" stroke-width="2.2"{dash} marker-end="url(#{self.ident}-{color})"/>')
        if label:
            mid = pts[len(pts) // 2]
            self.text(lx if lx is not None else mid[0], ly if ly is not None else mid[1] - 8, label, 12.5, 700, COLORS[color], anchor)

    def line(self, pts: list[tuple[float, float]], color: str = "muted", dashed: bool = True) -> None:
        d = "M" + " L".join(f"{x:g} {y:g}" for x, y in pts)
        dash = ' stroke-dasharray="4 4"' if dashed else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{COLORS[color]}" stroke-width="1.6"{dash}/>')

    def note(self, x: float, y: float, text: str, anchor: str = "start", color: str = "var(--muted)", size: float = 12.5) -> None:
        for i, line in enumerate(_lines(text)):
            self.text(x, y + i * (size + 4), line, size, 400, color, anchor)

    def render(self) -> str:
        markers = "".join(
            f'<marker id="{self.ident}-{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
            f'<path d="M0 0L10 5L0 10z" fill="{value}"/></marker>'
            for name, value in COLORS.items()
        )
        return (
            f'<div class="diagram"><svg viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="{self.ident}-t {self.ident}-d" '
            f'xmlns="http://www.w3.org/2000/svg"><title id="{self.ident}-t">{escape(self.title)}</title>'
            f'<desc id="{self.ident}-d">{escape(self.desc or self.title)}</desc><defs>{markers}</defs>'
            + "".join(self.parts) + "</svg></div>"
        )


LEGEND = (
    '<div class="legend">'
    '<span style="--k:var(--c-ui)">画面・利用者の操作</span><span style="--k:var(--c-core)">サーバー・エージェント・コア</span>'
    '<span style="--k:var(--c-store)">保存（D1・ファイル）</span><span style="--k:var(--c-rest)">外部サービス</span>'
    '<span style="--k:var(--c-safe)">安全・権限の制御</span><span style="--k:var(--warn)">失敗・打ち切り</span>'
    '<span style="--k:var(--c-plan)">未対応・検討中（破線）</span></div>'
)
