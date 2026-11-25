"""
chat_figures.py — チャットの回答に、Reference の絵（撮影した画像）を添える（2026-11-25。Qt にも Houdini にも依存しない。単体テストできる）

背景（実証実験の意見）: 質問によっては、回答に図があったほうが分かりやすい。
方針: 図を AI に作らせない（誤りが、そのまま図になる）。回答に出てくるノード・VEX 関数・シェルフツールのうち、
  Reference に、実機で撮影した画像があるものだけを、回答の下に並べる（押すと、Reference タブで、その項目を開く）。

  ・figure_items(text, index)  … 回答の文から、絵を添える項目を選ぶ（出てきた順。ノード → VEX → シェルフ。最大 MAX_FIGURES 件）
  ・pick_media(media)          … 1 項目の画像のうち、回答に添えるもの（適用前・適用後の組。無ければ、操作する場所・ノード図）
index は reference_remote.fetch_index の結果（{"node|sop/scatter": {"kind", "key", "title", "mediaCount", ...}}）。
"""

from __future__ import annotations

import re

import node_links

MAX_FIGURES = 3

_VEX_CALL_RE = re.compile(r"(?<![A-Za-z0-9_@.])([a-z_][a-z0-9_]*)\(")   # noise( / fit01( など（@P. や obj.method( は除く。「point (点)」のような、空白の後の括弧は、呼び出しとみなさない）
_VEX_TICK_RE = re.compile(r"`([a-z_][a-z0-9_]*)(?:\(\))?`")                 # `noise` / `noise()`
_SHELF_MARK = re.compile(r"^\s?(?:ツール|シェルフ|tool\b|Tool\b)")
_DOC_URL_RE = re.compile(r"/nodes/([a-z0-9]+)/([^/]+)\.html$")


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text).lower()))


def _has_media(meta: dict | None) -> bool:
    try:
        return isinstance(meta, dict) and int(meta.get("mediaCount") or 0) > 0
    except (TypeError, ValueError):
        return False


def _node_keys(text: str) -> list[str]:
    """回答に出てくるノード（node_links が、公式の一覧で確かめたもの）の Reference のキー（sop/scatter など）。出てきた順。"""
    keys = []
    for link in node_links.find_node_links(text):
        match = _DOC_URL_RE.search(link.get("url", "")) if link.get("kind") == "doc" else None
        if match:
            keys.append(f"{match.group(1)}/{match.group(2)}")
    return keys


def _vex_names(text: str) -> list[str]:
    """回答に出てくる VEX 関数の名前（noise( のような呼び出し、または `noise`）。出てきた順。"""
    hits = sorted([(m.start(), m.group(1)) for m in _VEX_CALL_RE.finditer(text)] + [(m.start(), m.group(1)) for m in _VEX_TICK_RE.finditer(text)])
    names: list[str] = []
    for _pos, name in hits:
        if name not in names:
            names.append(name)
    return names


def _shelf_hits(text: str, shelf: list[dict]) -> list[tuple[int, dict]]:
    """シェルフツールの名前（Billowy Smoke など）が出てくる位置。単語 1 つの名前（Fireball など）は、「ツール」「シェルフ」の印があるときだけ。
    shelf の各要素の title は、Houdini の表示名（figure_items が、shelf_labels で置き換えたもの）。"""
    hits = []
    for meta in shelf:
        title = str(meta.get("title") or "").strip()
        if len(title) < 3:
            continue
        for match in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(title) + r"(?![A-Za-z0-9])", text):
            if " " in title or _SHELF_MARK.match(text[match.end():match.end() + 8]):
                hits.append((match.start(), meta))
                break
    return sorted(hits, key=lambda h: h[0])


def figure_items(text: str, index: dict | None, limit: int = MAX_FIGURES, shelf_labels: dict[str, str] | None = None) -> list[dict]:
    """回答に添える項目（{"kind", "key", "title"}）。Reference に画像があるものだけ。同じ名前（ノードと、同名のシェルフツール）は 1 回だけ。
    shelf_labels: {シェルフのキー: Houdini の表示名}（reference_data.catalog("shelf") から）。公開の一覧の名前は、内部名から作った
    「Pyro Billowysmoke」のような名前で、回答の「Billowy Smoke」と一致しないため、表示名で探す。無いキーは、一覧の名前のまま。"""
    text = str(text or "")
    index = index or {}
    if not text or not index:
        return []
    out: list[dict] = []
    titles: set[str] = set()

    def add(meta: dict | None) -> None:
        if len(out) >= limit or not _has_media(meta):
            return
        title = str(meta.get("title") or meta.get("key") or "")
        if _norm(title) in titles or any(o["kind"] == meta.get("kind") and o["key"] == meta.get("key") for o in out):
            return
        titles.add(_norm(title))
        out.append({"kind": str(meta["kind"]), "key": str(meta["key"]), "title": title})

    for key in _node_keys(text):
        add(index.get(f"node|{key}"))
    for name in _vex_names(text):
        add(index.get(f"vex|vex/{name}"))
    labels = shelf_labels or {}
    shelf = [{**m, "title": labels.get(str(m.get("key")), m.get("title"))} for m in index.values()
             if isinstance(m, dict) and m.get("kind") == "shelf" and _has_media(m)]
    for _pos, meta in _shelf_hits(text, shelf):
        add(meta)
    return out


_PAIR = ("before", "after")
_SINGLE_ORDER = ("after", "where", "node")


def pick_media(media: list[dict] | None) -> list[dict]:
    """1 項目の画像（説明の "media"）から、回答に添えるものを選ぶ。静止画（png・jpg）だけ。
    適用前・適用後が両方あれば、その 2 枚（組で見せる）。無ければ、適用後・操作する場所・ノード図の、どれか 1 枚。"""
    stills = {}
    for m in media or []:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        if not str(m["id"]).lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        stills.setdefault(str(m.get("role") or ""), m)
    if all(role in stills for role in _PAIR):
        return [stills[role] for role in _PAIR]
    for role in _SINGLE_ORDER:
        if role in stills:
            return [stills[role]]
    return []


ROLE_LABELS = {"before": "適用前", "after": "適用後", "where": "操作する場所", "node": "ノードのつなぎ方"}
KIND_LABELS = {"node": "ノード", "vex": "VEX", "shelf": "シェルフ", "apex": "APEX"}
