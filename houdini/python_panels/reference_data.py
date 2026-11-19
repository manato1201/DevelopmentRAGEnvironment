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


def catalog(kind: str) -> list[dict]:
    """その種類の項目の一覧（表示名の順）。shelf は、一覧を持たない（検索して作る）。"""
    if kind == "node":
        items = _node_items(None, exclude=("apex",))
    elif kind == "apex":
        items = _node_items(("apex",))
    elif kind == "vex":
        items = [{"kind": "vex", "key": f"vex/{name}", "name": name, "label": name, "context": "vex",
                  "doc_url": f"{VEX_DOC_BASE}/{name}.html"} for name in VEX_FUNCTIONS]
    else:
        items = []
    return sorted(items, key=lambda i: (i["label"].lower(), i["context"]))


def custom_item(kind: str, text: str) -> dict:
    """一覧に無い名前（シェルフツール・VEX の別の関数など）を、検索で作った項目にする。公式サイトの検索へのリンクをつける。"""
    name = " ".join(str(text or "").split())[:80]
    return {"kind": kind, "key": f"{kind}/{slug(name)}", "name": name, "label": name, "context": kind,
            "doc_url": SEARCH_BASE + quote(name), "custom": True}


def search(kind: str, query: str, limit: int = 120) -> list[dict]:
    """表示名・ページ名の部分一致（大文字・小文字は区別しない）。空なら、先頭から limit 件。"""
    items = catalog(kind)
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


def used_items(guide: dict | None) -> dict[str, set[str]]:
    """チュートリアル（Guide のデータ）で使ったものの、キーの集合。{"node": {"sop/scatter", ...}, "vex": {"vex/chf", ...}, "apex": {...}}。
    ノードは、手順の node_type（例: scatter::2.0）を、一覧のページ名に合わせる。VEX は、コードを入れた欄の中の関数名。"""
    used: dict[str, set[str]] = {k: set() for k, _ in KINDS}
    if not isinstance(guide, dict):
        return used
    by_base: dict[str, list[dict]] = {}
    for item in catalog("node") + catalog("apex"):
        by_base.setdefault(item["name"].split("--")[-1].lower(), []).append(item)
    for entries in by_base.values():  # 同じ名前が複数の章にあるとき、SOP を先に（Merge・Attribute Wrangle など）
        entries.sort(key=lambda i: _CONTEXT_ORDER.index(i["context"]) if i["context"] in _CONTEXT_ORDER else len(_CONTEXT_ORDER))
    vex_names = set(VEX_FUNCTIONS)
    for step in guide.get("steps") or []:
        if not isinstance(step, dict):
            continue
        node_type = str(step.get("node_type") or "")
        if node_type:
            base = base_type(node_type).lower()
            for item in by_base.get(base, [])[:1]:  # 同じ名前が複数の章にあるときは、先頭（SOP が先）
                used[item["kind"]].add(item["key"])
        for parm in step.get("parms") or []:
            text = str(parm.get("new") or "") if isinstance(parm, dict) else ""
            if "\n" in text or ";" in text:  # コードの欄
                for match in _VEX_CALL_RE.finditer(text):
                    name = match.group(1)
                    if name in vex_names:
                        used["vex"].add(f"vex/{name}")
    return used


# ── HoudiniReference の抜粋 ────────────────────────────────────────────────

def match_reference_items(items: list[dict], label: str, kind: str, limit: int = MAX_REFERENCE_ITEMS) -> list[dict]:
    """HoudiniReference の項目（Tips・動画・ニュース）から、この項目に関係するものを選ぶ。題名・抜粋・タグに、名前が入っているもの。
    新しい順。種類が vex / apex のときは、同じ名前のタグ（VEX / APEX）も、関係の手がかりにする。"""
    name = " ".join(str(label or "").lower().split())
    if len(name) < 3:
        return []
    tag = {"vex": "vex", "apex": "apex"}.get(kind, "")
    scored: list[tuple[int, str, dict]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").lower()
        excerpt = str(item.get("excerpt") or "").lower()
        tags = [str(t).lower() for t in (item.get("tags") or [])]
        score = 0
        if name in title:
            score += 3
        if name in excerpt:
            score += 1
        if tag and tag in tags and score:
            score += 1
        if score:
            scored.append((score, str(item.get("published") or ""), item))
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
- 資料に書かれていないことは、書かない。分からない項目は、空の文字列にする。推測で、パラメータ名・値・性能を作らない。
- 専門用語は、初出で、短く言い換える。1 項目は、2〜4 文までに収める（各 {limit} 文字まで）。
- 出力は、次の JSON だけ（前後に文章やコードブロックを付けない）:
  {{"what": "何をするもの・どんなものか（1〜2 文）", "use": "どういったものに使うか（用途の例。1〜2 文）", "example": "実例（短い。資料・参考に例があれば、それを元に。無ければ空）", "example_point": "実例のポイント（見るところ。1〜2 文。実例が無ければ空）", "when": "使いどころ・向いている場面と、向かない場面（1〜2 文）"}}
""".format(limit=MAX_FIELD_CHARS)


def build_prompt(kind: str, label: str, doc_texts: list[str], references: list[dict]) -> tuple[str, str]:
    """(system, user)。資料は、長くなりすぎないよう、1 件 1500 文字・合計 6000 文字までに切る。"""
    docs: list[str] = []
    total = 0
    for text in doc_texts or []:
        chunk = str(text or "").strip()[:1500]
        if not chunk or total + len(chunk) > 6000:
            continue
        docs.append(chunk)
        total += len(chunk)
    refs = [f"- {reference_line(r)}: {str(r.get('excerpt') or '')[:200]}" for r in (references or [])[:MAX_REFERENCE_ITEMS]]
    user = (
        f"項目: {label}（{KIND_LABELS.get(kind, kind)}）\n\n"
        "【資料（SideFX 公式）】\n" + ("\n\n".join(f"({i}) {d}" for i, d in enumerate(docs, 1)) if docs else "（資料が見つかりませんでした）") + "\n\n"
        "【参考（HoudiniReference）】\n" + ("\n".join(refs) if refs else "（なし）")
    )
    return SYSTEM_PROMPT, user


def _clip(text: object) -> str:
    return " ".join(str(text or "").split())[:MAX_FIELD_CHARS]


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
    return entry if any(entry.values()) else None


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


def entry_html(item: dict, entry: dict | None, references: list[dict] | None = None, used: bool = False) -> str:
    """項目の詳細の HTML。文字は、すべてエスケープする。entry が無いときは、「説明を作る」の案内。"""
    esc = html.escape
    parts = [f"<h3 style='margin-bottom:2px'>{esc(item.get('label') or item.get('name') or '')}</h3>"]
    meta = [KIND_LABELS.get(item.get("kind", ""), ""), str(item.get("context") or "").upper() if item.get("kind") in ("node", "apex") else ""]
    meta_text = " / ".join(m for m in meta if m)
    if used:
        meta_text += ("　" if meta_text else "") + "<span style='color:#4ade80'><b>● このチュートリアルで使いました</b></span>"
        parts.append(f"<p style='margin-top:0'>{meta_text}</p>")
    elif meta_text:
        parts.append(f"<p style='margin-top:0;color:#94a3b8'>{esc(meta_text)}</p>")
    if entry:
        for key, title in _SECTIONS:
            body = str(entry.get(key) or "").strip()
            if body:
                parts.append(f"<p style='margin-bottom:0'><b style='color:#7dd3fc'>{esc(title)}</b></p><p style='margin-top:2px'>{esc(body)}</p>")
    else:
        parts.append("<p style='color:#fbbf24'>まだ説明がありません。「説明を作る」を押すと、公式のドキュメントと HoudiniReference を元に、AI が数秒でまとめます（保存され、次からは、すぐ出ます）。</p>")
    if references:
        parts.append("<p style='margin-bottom:0'><b style='color:#7dd3fc'>HoudiniReference の関連（出典は、それぞれの元のページ）</b></p><ul style='margin-top:2px'>")
        for ref in references[:MAX_REFERENCE_ITEMS]:
            url = str(ref.get("url") or "")
            title = esc(reference_line(ref))
            if url.startswith(("http://", "https://")):
                parts.append(f'<li><a href="{esc(url)}">{title}</a></li>')
            else:
                parts.append(f"<li>{title}</li>")
        parts.append("</ul>")
    parts.append("<p style='color:#94a3b8'>適用前後の動画（5〜6 秒）・ノード画面は、今後追加します。</p>")
    return "".join(parts)
