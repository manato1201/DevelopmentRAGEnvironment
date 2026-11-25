"""
reference_data.py — リファレンスタブ（ノード・VEX・APEX・シェルフツールの「何をする・使いどころ・実例」）の、データと文章（2026-11-19）

要望: 生成したチュートリアルで使われたノードやツールの詳しい内容を見られるようにしたい。APEX・VEX・ノード・シェルフツールに、それぞれ特化して。
  構成: 何をする・どんなもの / どういったものに使うか（実例・実例のポイント）/ 使いどころ
  ・チュートリアルで使ったものを強調表示（Guide との連携）
  ・適用前後の動画（5〜6 秒）・ノード画面（まだ無い。あとから足せるよう、欄だけ用意する）

内容の作り方（決定: 2026-11-19）: SideFX 公式の説明（RAG に入っている Houdini のドキュメント）+ HoudiniReference の抜粋（Tips・動画の題名・出典・短い抜粋）を材料に、
  AI が、上の 3 つの項目にまとめる。作ったものは、保存先のフォルダにキャッシュする（同じ項目は、2 回目から、AI を呼ばない）。

このモジュールは、Qt にも Houdini にも通信にも依存しない（単体テストできる）。通信と画面は、reference_view.py。

  ・KINDS / catalog(kind) / search(kind, query)  … 項目の一覧と検索
  ・doc_url(kind, item)                           … 公式ドキュメントのページ
  ・used_items(guide)                             … チュートリアル（Guide のデータ）で使ったノード・VEX の関数
  ・match_reference_items(items, label, kind)     … HoudiniReference の項目から、関係するものを選ぶ
  ・build_prompt / parse_entry                    … AI への依頼文と、返事の読み取り
  ・entry_path / load_entry / save_entry          … キャッシュ
  ・entry_html(entry, ...)                        … 画面に出す HTML
"""

from __future__ import annotations

import html

import tool_analogies
import json
import re
from pathlib import Path
from urllib.parse import quote

try:
    from node_link_data import BASE as DOC_BASE
    from node_link_data import NODES
except ImportError:  # データが無い環境でも、VEX の一覧は動く
    DOC_BASE = "https://www.sidefx.com/docs/houdini/nodes"
    NODES = {}

KINDS: tuple[tuple[str, str], ...] = (("node", "ノード"), ("vex", "VEX"), ("apex", "APEX"), ("shelf", "シェルフ"))
KIND_LABELS = dict(KINDS)
VEX_DOC_BASE = "https://www.sidefx.com/docs/houdini/vex/functions"
SEARCH_BASE = "https://www.sidefx.com/search/?q="
HOUDINI_REFERENCE_URL = "https://raw.githubusercontent.com/manato1201/HoudiniReference/main/data/items.json"
SECTION_KEYS = ("what", "use", "example", "example_point", "when")
MAX_FIELD_CHARS = 700
REFERENCE_MAX_TOKENS = 1800   # 説明 1 件の出力の上限（5 つの欄 × 700 文字以内。思考も数える）
REFERENCE_EFFORT = "low"      # 短い要約なので、思考は浅くてよい（費用と時間を抑える）
MAX_REFERENCE_ITEMS = 3

# VEX の、よく使う関数（公式ドキュメントに、同じ名前のページがあるもの）。一覧に出す入口で、これ以外の関数も、検索で作れる。
VEX_FUNCTIONS = (
    "abs", "addpoint", "addprim", "addvertex", "append", "atan2", "ceil", "chf", "chi", "chramp", "chs", "chv", "clamp", "cos", "cross",
    "degrees", "distance", "dot", "efit", "exp", "fit", "fit01", "floor", "frac", "length", "lerp", "length2", "max", "min", "neighbours",
    "nearpoint", "nearpoints", "noise", "normalize", "npoints", "nprimitives", "pcfind", "pcopen", "point", "pow", "primuv", "printf",
    "rand", "removepoint", "removeprim", "resample_point", "rotate", "sample_volume", "set", "setpointattrib", "setprimattrib", "sin",
    "smooth", "sort", "sqrt", "trunc", "xnoise", "snoise", "anoise", "curlnoise", "volumesample", "volumegradient", "xyzdist", "pointattrib",
    "hasattrib", "getbbox", "invert", "ident", "slerp", "qrotate", "quaternion", "dihedral", "maketransform", "matrix", "transpose",
    "tolower", "toupper", "strlen", "sprintf", "split", "join", "find", "atof", "atoi", "len", "push", "pop", "foreach",
    # 2026-11-24 に足した分（vcc で、関数が在ることを確かめた）
    "acos", "asin", "atan", "cbrt", "cosh", "sinh", "tanh", "sign",
    "log", "log10", "radians", "avg", "sum", "reflect", "refract", "fresnel",
    "distance2", "lookat", "cracktransform", "scale", "translate", "determinant", "outerproduct", "qconvert",
    "qmultiply", "eulertoquaternion", "quaterniontoeuler", "prim", "primattrib", "vertex", "vertexattrib", "primpoints",
    "pointprims", "pointvertices", "vertexpoint", "vertexprim", "primvertices", "vertexindex", "vertexnext", "vertexprev",
    "neighbourcount", "neighbour", "intersect", "uvsample", "minpos", "nvertices", "npointsgroup", "nprimitivesgroup",
    "inpointgroup", "inprimgroup", "setpointgroup", "setprimgroup", "setvertexpoint", "setdetailattrib", "detail", "detailattrib",
    "hasdetailattrib", "haspointattrib", "hasprimattrib", "getattrib", "setattrib", "addattrib", "attribsize", "pointattribsize",
    "findattribval", "findattribvalcount", "uniqueval", "uniquevals", "nuniqueval", "setprimintrinsic", "primintrinsic", "re_find",
    "re_match", "re_replace", "re_split", "startswith", "endswith", "strip", "itoa", "concat",
    "insert", "removeindex", "removevalue", "resize", "reverse", "slice", "array", "isvalidindex",
    "rgbtohsv", "hsvtorgb", "ctransform", "luminance", "colormap", "random", "nrandom", "onoise",
    "pnoise", "wnoise", "curlnoise2d", "flownoise", "pcfilter", "pcnumfound", "pciterate", "chp",
    "getpointbbox", "relbbox", "relpointbbox", "sample_direction_uniform", "sample_hemisphere", "isnan", "isfinite", "ptransform",
    "vtransform", "ntransform", "tan", "nametopoint",
)

_KEY_RE = re.compile(r"[^0-9a-zA-Z_]+")


def slug(text: str) -> str:
    """名前から、ファイル名・キーに使える文字列。"""
    return _KEY_RE.sub("_", str(text or "").strip()).strip("_").lower() or "item"


# ── 一覧 ────────────────────────────────────────────────────────────────────

def _node_items(contexts: tuple[str, ...] | None, exclude: tuple[str, ...] = ()) -> list[dict]:
    items: list[dict] = []
    for context, body in NODES.items():
        if context in exclude or (contexts is not None and context not in contexts):
            continue
        for line in str(body).splitlines():
            if "|" not in line:
                continue
            page, label = line.split("|", 1)
            page, label = page.strip(), label.strip()
            if not page or not label or page.startswith("_"):
                continue
            items.append({"kind": "apex" if context == "apex" else "node", "key": f"{context}/{page}", "name": page, "label": label,
                          "context": context, "doc_url": f"{DOC_BASE}/{context}/{page}.html"})
    return items


_SHELF_TOOLS: list[dict] = []


def shelf_items(tools: list[tuple[str, str, str]]) -> list[dict]:
    """Houdini のシェルフツールの一覧から、項目を作る。tools: [(シェルフの名前（Create など）, ツールの内部名, ツールの表示名), ...]。
    表示名は、重複がある（別のシェルフに、同じ名前のツール）ので、キーは内部名にする。公式ドキュメントには、ツールごとのページが無いので、検索へのリンクにする。"""
    items: list[dict] = []
    seen: set[str] = set()
    for shelf, name, label in tools:
        label = " ".join(str(label or "").split())
        key = f"shelf/{slug(name or label)}"
        if not label or key in seen:
            continue
        seen.add(key)
        items.append({"kind": "shelf", "key": key, "name": str(name or label), "label": label, "context": str(shelf or ""),
                      "doc_url": SEARCH_BASE + quote(label)})
    return items


def set_shelf_tools(items: list[dict]) -> None:
    """画面側が、Houdini から取ったシェルフツールの一覧を登録する（Houdini の外では、空のまま）。"""
    _SHELF_TOOLS[:] = [i for i in items if isinstance(i, dict) and i.get("key")]


def catalog(kind: str) -> list[dict]:
    """その種類の項目の一覧（表示名の順）。shelf は、Houdini の中でだけ、set_shelf_tools で登録された一覧（外では空）。"""
    if kind == "node":
        items = _node_items(None, exclude=("apex",))
    elif kind == "apex":
        items = _node_items(("apex",))
    elif kind == "vex":
        items = [{"kind": "vex", "key": f"vex/{name}", "name": name, "label": name, "context": "vex",
                  "doc_url": f"{VEX_DOC_BASE}/{name}.html"} for name in VEX_FUNCTIONS]
    elif kind == "shelf":
        items = list(_SHELF_TOOLS)
    else:
        items = []
    return sorted(items, key=lambda i: (i["label"].lower(), i["context"]))


def custom_item(kind: str, text: str) -> dict:
    """一覧に無い名前（シェルフツール・VEX の別の関数など）を、検索で作った項目にする。公式サイトの検索へのリンクをつける。"""
    name = " ".join(str(text or "").split())[:80]
    return {"kind": kind, "key": f"{kind}/{slug(name)}", "name": name, "label": name, "context": kind,
            "doc_url": SEARCH_BASE + quote(name), "custom": True}


def remote_items(kind: str, remote: dict | None) -> list[dict]:
    """Cloudflare にある説明の一覧（reference_remote.fetch_index の結果）のうち、一覧データ（catalog）に載っていない項目。
    一覧データは、公式ドキュメントの索引から作っていて、Mountain・Twist のような基本のノードが抜けていることがある。
    公開した項目は、必ず探せるようにする。"""
    known = {i["key"] for i in catalog(kind)}
    items = []
    for meta in (remote or {}).values():
        if not isinstance(meta, dict) or meta.get("kind") != kind or not meta.get("key") or meta["key"] in known:
            continue
        key = str(meta["key"])
        name = key.split("/")[-1]
        context = key.split("/")[0] if kind in ("node", "apex") and "/" in key else kind
        items.append({"kind": kind, "key": key, "name": name, "label": str(meta.get("title") or name), "context": context,
                      "doc_url": f"{DOC_BASE}/{key}.html" if kind == "node" and "/" in key else SEARCH_BASE + quote(name)})
    return items


def search(kind: str, query: str, limit: int = 120, extra: list[dict] | None = None) -> list[dict]:
    """表示名・ページ名の部分一致（大文字・小文字は区別しない）。空なら、先頭から limit 件。extra は、一覧に足す項目（remote_items）。"""
    items = catalog(kind)
    if extra:
        items = sorted(items + list(extra), key=lambda i: (i["label"].lower(), i["context"]))
    q = " ".join(str(query or "").lower().split())
    if not q:
        return items[:limit]
    def rank(item: dict) -> tuple[int, int, str]:
        label, name = item["label"].lower(), item["name"].lower()
        if q in (label, name) or name.endswith("--" + q):
            order = 0  # 完全に一致（scatter → Scatter）
        elif label.startswith(q) or name.startswith(q):
            order = 1
        else:
            order = 2
        return order, 0 if item.get("context") in ("sop", "vex") else 1, label  # 同じなら、SOP・VEX を先に

    hits = [i for i in items if q in i["label"].lower() or q in i["name"].lower()]
    return sorted(hits, key=rank)[:limit]


def find_item(kind: str, key: str) -> dict | None:
    for item in catalog(kind):
        if item["key"] == key:
            return item
    return None


# ── チュートリアルで使ったもの ───────────────────────────────────────────────

_CONTEXT_ORDER = ("sop", "obj", "dop", "vop", "lop", "top", "chop", "cop2", "cop", "out", "apex")
_VEX_CALL_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*\(")


def base_type(type_name: str) -> str:
    """'labs::foo::1.0' / 'scatter::2.0' → 'foo' / 'scatter'（先頭の名前空間とバージョンを外す）。"""
    parts = [p for p in str(type_name or "").split("::") if p]
    if len(parts) >= 3:
        return parts[1]
    return parts[0] if parts else ""


def _step_keys(step: dict, by_base: dict[str, list[dict]], vex_names: set[str]) -> dict[str, set[str]]:
    """1 手順で使ったものの、キー。"""
    found: dict[str, set[str]] = {k: set() for k, _ in KINDS}
    node_type = str(step.get("node_type") or "")
    if node_type:
        base = base_type(node_type).lower()
        for item in by_base.get(base, [])[:1]:  # 同じ名前が複数の章にあるときは、先頭（SOP が先）
            found[item["kind"]].add(item["key"])
    for parm in step.get("parms") or []:
        text = str(parm.get("new") or "") if isinstance(parm, dict) else ""
        if "\n" in text or ";" in text:  # コードの欄
            for match in _VEX_CALL_RE.finditer(text):
                if match.group(1) in vex_names:
                    found["vex"].add(f"vex/{match.group(1)}")
    return found


def _index(extra: list[dict] | None = None) -> tuple[dict[str, list[dict]], set[str]]:
    """名前（ページ名）から項目を引く表。extra は、一覧データに無い公開済みの項目（remote_items）。"""
    by_base: dict[str, list[dict]] = {}
    for item in catalog("node") + catalog("apex") + [i for i in (extra or []) if i.get("kind") in ("node", "apex")]:
        by_base.setdefault(item["name"].split("--")[-1].lower(), []).append(item)
    for entries in by_base.values():  # 同じ名前が複数の章にあるとき、SOP を先に（Merge・Attribute Wrangle など）
        entries.sort(key=lambda i: _CONTEXT_ORDER.index(i["context"]) if i["context"] in _CONTEXT_ORDER else len(_CONTEXT_ORDER))
    return by_base, set(VEX_FUNCTIONS)


def used_steps(guide: dict | None, kind: str, key: str, extra: list[dict] | None = None) -> list[tuple[int, str]]:
    """この項目を使っている手順。[(手順の番号（0 始まり）, 短い説明), ...]。Reference タブから、使っている場所へ飛ぶのに使う（2026-11-19）。"""
    if not isinstance(guide, dict):
        return []
    by_base, vex_names = _index(extra)
    out: list[tuple[int, str]] = []
    for i, step in enumerate(guide.get("steps") or []):
        if not isinstance(step, dict):
            continue
        if key in _step_keys(step, by_base, vex_names).get(kind, set()):
            text = " ".join(str(step.get("instruction") or step.get("hint") or step.get("node") or "").split())
            out.append((i, text[:50]))
    return out


def used_items(guide: dict | None, extra: list[dict] | None = None) -> dict[str, set[str]]:
    """チュートリアル（Guide のデータ）で使ったものの、キーの集合。{"node": {"sop/scatter", ...}, "vex": {"vex/chf", ...}, "apex": {...}}。
    ノードは、手順の node_type（例: scatter::2.0）を、一覧のページ名に合わせる。VEX は、コードを入れた欄の中の関数名。"""
    used: dict[str, set[str]] = {k: set() for k, _ in KINDS}
    if not isinstance(guide, dict):
        return used
    by_base, vex_names = _index(extra)
    for step in guide.get("steps") or []:
        if isinstance(step, dict):
            for kind, keys in _step_keys(step, by_base, vex_names).items():
                used[kind] |= keys
    return used


# ── HoudiniReference の抜粋 ────────────────────────────────────────────────

_CONTEXT_WORDS = ("sop", "vop", "lop", "cop", "dop", "top", "chop", "rop", "node", "ノード", "vex", "apex")
_CONTEXT_RE = "(?:" + "|".join(_CONTEXT_WORDS) + ")"


def _word_re(text: str) -> re.Pattern:
    """名前の前後が、英数字でない（単語として入っている）ことを求める正規表現。「scatter」が「scattering」に当たらないように。"""
    return re.compile(r"(?<![0-9a-z_])" + re.escape(text) + r"(?![0-9a-z_])")


# VEX の関数のうち、ふつうの英単語としても使われるもの（文の中の語と、区別できない）。これ以外の関数名（xyzdist など）は、名前だけで関数と分かる。
_COMMON_VEX_WORDS = frozenset({
    "abs", "append", "ceil", "clamp", "cos", "cross", "degrees", "distance", "dot", "exp", "fit", "floor", "frac", "length", "max", "min",
    "noise", "normalize", "point", "pow", "printf", "rand", "rotate", "set", "sin", "smooth", "sort", "sqrt", "trunc", "find", "join", "len",
    "push", "pop", "split", "invert", "matrix", "ident", "foreach", "lerp", "sprintf", "transpose", "random", "sample",
})


# 内部の名前が、ふつうの英単語そのもののもの（primitive・geometry など）。表示名（Primitive Properties）の頭の語に過ぎないので、別名として使わない
# （使うと、「primitive number」を語る別の話題の投稿が当たる。2026-11-21）
_ORDINARY_ALIASES = frozenset({"primitive", "geometry", "transform", "attribute", "parameter", "material", "object", "particle", "volume", "group", "point", "polygon"})


def _name_forms(label: str, kind: str = "", internal: bool = False) -> tuple[list[str], bool]:
    """表示名から、探す書き方（小文字）と、「名前だけで、そのノード・関数と分かるか」を返す。
    「Copy to Points」「attribwrangle」のような長い・複数語の名前は、名前だけで分かる。「Color」「Delete」「Peak」のような、
    ふつうの英単語は、「Color SOP」のように、ノード・関数だと分かる言い方が一緒にあるときだけ、関係があるとみなす。"""
    name = " ".join(re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", str(label or "")).lower().split())
    if len(name) < 3:
        return [], False
    compact = name.replace(" ", "")
    forms = [name] + ([compact] if compact != name else [])
    if kind in ("vex", "apex"):
        return forms, compact not in _COMMON_VEX_WORDS and len(compact) >= 4 or " " in name
    # 表示名（Transform・Geometry など）は、ふつうの英単語なので、1 語なら、長くても、名前だけでは足りない。
    # 内部の名前（attribwrangle・polyextrude など）は、作られた語なので、9 文字以上なら、名前だけで足りる
    return forms, (" " in name or (internal and len(compact) >= 9))


_COPERNICUS_RE = re.compile(r"(?<![0-9a-z_])(?:copernicus|cop)(?![0-9a-z_])")


def item_context(item: dict | None) -> str:
    """一覧の項目の、文脈（"sop/scatter" → "sop"）。"""
    return str((item or {}).get("key") or "").split("/")[0]


def item_aliases(item: dict | None) -> tuple[str, ...]:
    """一覧の項目の、内部の名前（"sop--attribwrangle" → "attribwrangle"）。表示名と別の書き方で、書かれていることがある。"""
    name = str((item or {}).get("name") or (item or {}).get("key") or "")
    base = re.split(r"--|/", name)[-1].split("::")[0]
    return (base,) if base else ()


def match_reference_items(items: list[dict], label: str, kind: str, limit: int = MAX_REFERENCE_ITEMS, aliases: tuple[str, ...] = (), context: str = "") -> list[dict]:
    """HoudiniReference の項目（Tips・動画・ニュース）から、この項目に関係するものを選ぶ。新しい順。
    （2026-11-21 厳しくした。前は、名前を含むだけで選び、「Scatter」に「Transmission Scattering」、「Color」に色の表示の不具合の変更履歴が当たった）
      ・名前は、単語として入っているものだけ（「scatter」は「scattering」に当たらない）
      ・題名か、タグに入っているもの。抜粋にだけ入っているものは、名前が長い・複数語のときだけ
      ・「Color」のような、ふつうの英単語の名前は、「Color SOP」のように、ノード・関数だと分かる言い方があるときだけ
      ・VEX・APEX は、題名・抜粋・タグに、VEX・APEX の語も入っているものだけ（「fit」「set」などが、ふつうの文に当たらないように）
      ・context（そのノードの文脈。sop・obj など）が cop 以外のとき、Copernicus（COP）の記事は選ばない（COP にも Block Begin・Transform などの同名のノードがあり、別物）"""
    forms, distinctive = _name_forms(label, kind)
    strong = list(forms) if distinctive else []  # 名前だけで、そのノード・関数と分かる書き方
    weak = [] if distinctive else list(forms)    # ふつうの英単語（題名かタグに入り、かつ、ノード・関数だと分かる言い方が一緒のときだけ）
    for alias in aliases:  # 内部の名前（attribwrangle など）。表示名と別の書き方で書かれていることがある
        if str(alias).lower() in _ORDINARY_ALIASES:
            continue
        more, more_distinctive = _name_forms(alias, kind, internal=True)
        # 別名は、その語自身が名前だけで足りるときだけ、強い書き方にする（表示名が複数語でも、別名の rest・solver などは、ふつうの語）
        (strong if more_distinctive else weak).extend(f for f in more if f not in strong and f not in weak)
    if not strong and not weak:
        return []
    strong_res = [_word_re(f) for f in strong]
    weak_res = [_word_re(f) for f in weak]
    words = _CONTEXT_WORDS
    if kind == "node" and context:
        words = tuple(dict.fromkeys((context, "node", "ノード")))  # そのノードの文脈の言い方だけ（SOP の Merge に、Merge LOP の動画が当たらないように）
    ctx = "(?:" + "|".join(words) + ")"
    cue_res = [re.compile(r"(?<![0-9a-z_])" + re.escape(f) + r"\s*(?:\[)?\s*" + ctx + r"(?![0-9a-z_])|(?<![0-9a-z_])" + ctx + r"\s+" + re.escape(f) + r"(?![0-9a-z_])|(?<![0-9a-z_])" + re.escape(f) + r"\(") for f in weak]
    scored: list[tuple[int, str, dict]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").lower()
        excerpt = str(item.get("excerpt") or "").lower()
        tags = [str(t).lower() for t in (item.get("tags") or [])]
        if context and context != "cop" and kind == "node" and (_COPERNICUS_RE.search(title) or any(_COPERNICUS_RE.search(t) for t in tags)):
            continue
        strong_title = any(r.search(title) for r in strong_res) or any(t in strong for t in tags)
        weak_title = any(r.search(title) for r in weak_res) or any(t in weak for t in tags)
        strong_excerpt = any(r.search(excerpt) for r in strong_res)
        if strong_title or strong_excerpt:
            in_title = strong_title
        elif weak_title and any(r.search(title + " " + excerpt) for r in cue_res):
            in_title = True
        else:
            continue
        if kind in ("vex", "apex"):
            hint = kind
            if not (hint in tags or hint in title or hint in excerpt):
                continue
        scored.append((3 if in_title else 1, str(item.get("published") or ""), item))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)  # 関係の強い順、同じなら新しい順
    return [s[2] for s in scored[:limit]]


def reference_line(item: dict) -> str:
    """1 件を、1 行に（題名・出典・日付）。"""
    date = str(item.get("published") or "")[:10]
    return f"{str(item.get('title') or '')[:90]}（{item.get('source') or ''}{'・' + date if date else ''}）"


# ── AI への依頼と、返事の読み取り ───────────────────────────────────────────

SYSTEM_PROMPT = """あなたは Houdini の教材を書く人です。与えられた「資料」（SideFX 公式のドキュメントの抜粋）と「参考」（Tips・動画の題名と短い抜粋）だけを根拠に、
指定された項目（ノード・VEX の関数・APEX・シェルフツール）の説明を、日本語で、初学者に分かるように書いてください。

ルール:
- 「資料」に書かれていることを優先する。資料に無いときは、Houdini の基本として確立している内容（そのノード・関数が何をするか、典型的な使いどころ）だけを、短く書く。確かでないことは書かず、その欄は空の文字列にする。
- パラメータ名・メニュー項目を挙げるときは、「資料」か、【実在するパラメータ名】の一覧にあるものだけを使い、「」で囲む。一覧にある名前は、その表記のまま書く。
  一覧にも資料にも無い名前は、書かない（似た名前を推測で作らない）。「」『』は、このためだけに使う（用語の強調・属性名・値には使わない）。
- 関数の引数・数値・性能も、資料に書かれているものだけを使う。推測で作らない。
- 【検証済みの手順】が付いているときは、実例（example）は、その手順と値だけで書く（ほかの手順・値は、書かない）。
- 「資料に無かった」「確認できなかった」といった、調べた経過は書かない。利用者が読む説明だけを書く。
- 専門用語は、初出で、短く言い換える。1 項目は、2〜4 文までに収める（各 {limit} 文字まで）。
- 出力は、次の JSON だけ（前後に文章やコードブロックを付けない）:
  {{"what": "何をするもの・どんなものか（1〜2 文）", "use": "どういったものに使うか（用途の例。1〜2 文）", "example": "実例（短い。資料・参考に例があれば、それを元に。無ければ空）", "example_point": "実例のポイント（見るところ。1〜2 文。実例が無ければ空）", "when": "使いどころ・向いている場面と、向かない場面（1〜2 文）"}}
""".format(limit=MAX_FIELD_CHARS)


MAX_PARM_NAMES = 150


def build_prompt(kind: str, label: str, doc_texts: list[str], references: list[dict],
                 parm_names: list[str] | None = None, verified: str = "", facts: str = "") -> tuple[str, str]:
    """(system, user)。資料は、空白を詰めて（公式ページの先頭は、空白だらけ）、1 件 1800 文字・合計 7000 文字までに切る。
    parm_names: 実機（Houdini）の、そのノードの本物のパラメータ名・メニュー項目（説明に、無い名前を書かせないため）。
    verified: 実機で実行して確かめた手順（撮影のレシピ）。あれば、実例は、これだけで書かせる。
    facts: 実機で確かめた事実（APEX の入出力のポートの名前と型、シェルフツールの所属など）。あれば、その表記のまま使わせ、食い違うことは書かせない。"""
    docs: list[str] = []
    total = 0
    for text in doc_texts or []:
        chunk = " ".join(str(text or "").split())[:1800]
        if not chunk or total + len(chunk) > 7000:
            continue
        docs.append(chunk)
        total += len(chunk)
    refs = [f"- {reference_line(r)}: {str(r.get('excerpt') or '')[:200]}" for r in (references or [])[:MAX_REFERENCE_ITEMS]]
    user = (
        f"項目: {label}（{KIND_LABELS.get(kind, kind)}）\n\n"
        "【資料（SideFX 公式）】\n" + ("\n\n".join(f"({i}) {d}" for i, d in enumerate(docs, 1)) if docs else "（資料が見つかりませんでした）") + "\n\n"
        "【参考（HoudiniReference）】\n" + ("\n".join(refs) if refs else "（なし）")
    )
    if parm_names:
        names = sorted({str(n) for n in parm_names if n}, key=lambda n: (not (n != n.lower() or " " in n), n))[:MAX_PARM_NAMES]  # 表示名（大文字・空白を含む）を先に
        user += "\n\n【実在するパラメータ名（Houdini 22 の実機。この表記のまま使う）】\n" + " / ".join(names)
    if facts:
        user += "\n\n【実機（Houdini 22）で確かめた事実。この内容と食い違うことは、書かない】\n" + facts
    if verified:
        user += "\n\n【検証済みの手順（実機で実行して、結果を確かめたもの）】\n" + verified
    return SYSTEM_PROMPT, user


def _clip(text: object) -> str:
    return " ".join(str(text or "").split())[:MAX_FIELD_CHARS]


# 調べた経過（「資料に無かった」など）が、利用者の読む説明に混ざったときの目印。「確認できます」のような普通の言い方は、引っかけない。
_PROCESS_LEAK_RE = re.compile(r"資料|確認できません|確認できていません|確認できない|見つかりません|載っていません|含まれていません")


def sanitize_entry(entry: dict | None) -> dict | None:
    """調べた経過が混ざった欄を空にする。「何をするもの（what）」に混ざっていたら、説明として使えないので None（AI が、資料の無い項目で、
    「このノードの説明は資料に無い」と書いたときなど）。欄が 1 つも残らなければ、None。"""
    if not isinstance(entry, dict):
        return None
    if _PROCESS_LEAK_RE.search(str(entry.get("what") or "")):
        return None
    clean = {k: ("" if _PROCESS_LEAK_RE.search(str(entry.get(k) or "")) else str(entry.get(k) or "")) for k in SECTION_KEYS}
    return clean if clean.get("what") else None


def parse_entry(text: str) -> dict | None:
    """AI の返事から、項目の内容を取り出す。JSON が読めない・全部の欄が空なら None。"""
    raw = str(text or "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    entry = {k: _clip(data.get(k)) for k in SECTION_KEYS}
    return sanitize_entry(entry) if any(entry.values()) else None


# ── キャッシュ ──────────────────────────────────────────────────────────────

def entry_path(base_dir: str | Path, kind: str, key: str) -> Path:
    """<保存先>/localRAG/reference/<種類>/<キー>.json"""
    return Path(base_dir) / "localRAG" / "reference" / slug(kind) / f"{slug(key)}.json"


def load_entry(base_dir: str | Path, kind: str, key: str) -> dict | None:
    try:
        data = json.loads(entry_path(base_dir, kind, key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and any(str(data.get(k) or "").strip() for k in SECTION_KEYS) else None


def save_entry(base_dir: str | Path, kind: str, key: str, entry: dict, meta: dict | None = None) -> bool:
    path = entry_path(base_dir, kind, key)
    data = {k: _clip(entry.get(k)) for k in SECTION_KEYS}
    data.update({k: v for k, v in (meta or {}).items() if isinstance(v, (str, int, float, bool, list))})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return False
    return True


# ── 画面に出す HTML ────────────────────────────────────────────────────────

_SECTIONS = (("what", "何をする・どんなもの"), ("use", "どういったものに使うか"), ("example", "実例"), ("example_point", "実例のポイント"), ("when", "使いどころ"))


_MEDIA_TITLES = {"where": "操作する場所（シェルフ）", "before": "適用前", "after": "適用後", "node": "ノード画面"}


_TEXT_MUTED = "#cbd5e1"   # 補足の文字（暗い背景で読める明るさ）
_HEAD_BLUE = "#2b5a8c"    # 見出しの背景（文字は白）
_HEAD_GREEN = "#1f6b43"


def _heading(text: str, bg: str = _HEAD_BLUE) -> str:
    """見出し: 背景色つき・白い太字（青い文字は、暗い背景で読みづらいため）。text は、エスケープ済みであること。"""
    return (f"<table width='100%' cellspacing='0' cellpadding='4' style='margin-top:8px'><tr><td bgcolor='{bg}'>"
            f"<b><span style='color:#ffffff'>{text}</span></b></td></tr></table>")


def media_widths(width: int | None = None) -> tuple[int, int]:
    """詳細欄の幅から、画像の表示幅（適用前後の 2 枚並び, 1 枚で幅いっぱい）を決める。画面側は、この幅に、なめらかに縮めてから載せる。"""
    usable = max(120, int(width) - 36) if width else None   # 余白・スクロールバーの分を引く
    # 上限は、2 枚並び 340px・1 枚 640px（2026-11-25。以前は 260・420 で、図の文字が、広い画面でも潰れていた）
    pair = 260 if usable is None else max(60, min(340, (usable - 24) // 2))
    wide = 420 if usable is None else max(100, min(640, usable))
    return pair, wide


def media_display_width(role: str, width: int | None = None) -> int:
    """その役割の画像を、何 px の幅で出すか（適用前・適用後は 2 枚並び、ほかは 1 枚で幅いっぱい）。"""
    pair, wide = media_widths(width)
    return pair if role in ("before", "after") else wide


def media_html(media: list[dict] | None, sources: dict[str, str] | None, width: int | None = None) -> str:
    """適用前後・ノード画面の画像（静止画）を並べる HTML。sources: {メディアの id: <img> の src}（読み込めたものだけ）。動画・GIF は、画面側が別に出す。
    width: 詳細欄の幅（px）。狭い所に置かれても、画像が欠けないように、幅に合わせて縮める（無ければ、既定の大きさ）。"""
    esc = html.escape
    sources = sources or {}
    by_role: dict[str, list[dict]] = {}
    for m in media or []:
        if isinstance(m, dict) and m.get("id") in sources and m.get("role") in _MEDIA_TITLES:
            by_role.setdefault(str(m["role"]), []).append(m)
    pair, wide = media_widths(width)
    out = ""
    if by_role.get("where"):  # シェルフツールの、操作する場所（いちばん上。横に長い図なので、幅いっぱいに出す）
        m = by_role["where"][0]
        out += f"<p style='margin-bottom:0;color:{_TEXT_MUTED}'>{_MEDIA_TITLES['where']}</p><p style='margin-top:2px'><a href='refopen:{esc(m['id'])}'><img src='{esc(sources[m['id']])}' width='{wide}'></a></p>"
    cells = []
    for role in ("before", "after"):
        if by_role.get(role):
            m = by_role[role][0]
            cells.append(f"<td align='center'><span style='color:{_TEXT_MUTED}'>{_MEDIA_TITLES[role]}</span><br><a href='refopen:{esc(m['id'])}'><img src='{esc(sources[m['id']])}' width='{pair}'></a></td>")
    out += f"<table cellspacing='6'><tr>{''.join(cells)}</tr></table>" if cells else ""
    if by_role.get("node"):
        m = by_role["node"][0]
        out += f"<p style='margin-bottom:0;color:{_TEXT_MUTED}'>{_MEDIA_TITLES['node']}</p><p style='margin-top:2px'><a href='refopen:{esc(m['id'])}'><img src='{esc(sources[m['id']])}' width='{wide}'></a></p>"
    if out:
        out += f"<p style='margin-top:0;color:{_TEXT_MUTED}'><small>画像を押すと、元の大きさで開きます</small></p>"
    return out


def entry_html(item: dict, entry: dict | None, references: list[dict] | None = None, used: bool = False,
               steps: list[tuple[int, str]] | None = None, media: str = "", author: bool = False, loading: bool = False) -> str:
    """項目の詳細の HTML。文字は、すべてエスケープする。entry が無いときは、参加者には「まだ用意していません」、開発者（author）には「説明を作る」の案内。
    media は media_html() の結果。loading は、Cloudflare から取っている最中。"""
    esc = html.escape
    parts = [f"<h3 style='margin-bottom:2px'>{esc(item.get('label') or item.get('name') or '')}</h3>"]
    meta = [KIND_LABELS.get(item.get("kind", ""), ""), str(item.get("context") or "").upper() if item.get("kind") in ("node", "apex") else ""]
    meta_text = " / ".join(m for m in meta if m)
    if used:
        meta_text += ("　" if meta_text else "") + "<span style='color:#86efac'><b>● このチュートリアルで使いました</b></span>"
        parts.append(f"<p style='margin-top:0'>{meta_text}</p>")
    elif meta_text:
        parts.append(f"<p style='margin-top:0;color:{_TEXT_MUTED}'>{esc(meta_text)}</p>")
    if steps:
        # 使っている場所（クリックで、Guide のその手順へ飛ぶ。リンクは step:<番号>。画面側が開く）
        parts.append(_heading("このチュートリアルで使っている場所", _HEAD_GREEN) + "<p style='margin-bottom:0'>クリックで、Guide のその手順へ飛びます。</p><ul style='margin-top:2px'>")
        for index, text in steps[:30]:
            parts.append(f'<li><a href="step:{int(index)}">手順 {int(index) + 1}{": " + esc(text) if text else ""}</a></li>')
        if len(steps) > 30:
            parts.append(f"<li>…ほか {len(steps) - 30} 件</li>")
        parts.append("</ul>")
    if media:
        parts.append(media)
    analogy = tool_analogies.for_item(item)  # Maya・Blender でいうと（手で書いた対応だけ。2026-11-25、A27）
    if analogy:
        parts.append(tool_analogies.html_block(analogy))
    if entry:
        for key, title in _SECTIONS:
            body = str(entry.get(key) or "").strip()
            if body:
                parts.append(_heading(esc(title)) + f"<p style='margin-top:2px'>{esc(body)}</p>")
    elif loading:
        parts.append(f"<p style='color:{_TEXT_MUTED}'>説明を読み込んでいます…</p>")
    elif not author:
        parts.append("<p style='color:#fbbf24'>この項目の説明は、まだ用意していません。下の「公式ドキュメントを開く」で、SideFX の説明を見られます。</p>")
    else:
        parts.append("<p style='color:#fbbf24'>まだ説明がありません。「説明を作る」を押すと、公式のドキュメントと HoudiniReference を元に、AI（設定のモデル）が数秒でまとめます。"
                     "<b>AI を 1 回呼ぶので、Claude の予算を、1 件あたり、入力 約 5,000・出力 約 1,000 トークン使います（約 2〜3 セント。推定）。</b>保存され、次からは、すぐ出ます（予算を使いません）。</p>")
    if references:
        parts.append(_heading("HoudiniReference の関連（出典は、それぞれの元のページ）") + "<ul style='margin-top:2px'>")
        for ref in references[:MAX_REFERENCE_ITEMS]:
            url = str(ref.get("url") or "")
            title = esc(reference_line(ref))
            if url.startswith(("http://", "https://")):
                parts.append(f'<li><a href="{esc(url)}">{title}</a></li>')
            else:
                parts.append(f"<li>{title}</li>")
        parts.append("</ul>")
    return "".join(parts)
