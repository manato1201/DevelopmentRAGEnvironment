"""
node_links.py — チャットの回答の中の「URL」と「ノード名」を、クリックできるリンクにする（Qt に依存しない純粋な関数。単体テストできる）

背景（2026-11-17の実証実験の要望）:
  ・回答の中の外部 URL を、リンクとして表示したい（外部ブラウザで開く）
  ・ノードについて聞いたとき、回答に出るノード名から、SideFX の公式ドキュメントへのリンクを出したい

  ・is_safe_url(url)       … リンクにしてよい URL か（http / https だけ。javascript: などは、リンクにしない）
  ・linkify_html(text)     … 回答の文を、リッチテキスト（HTML）にする。http(s) の URL と [文字](URL) をリンクにする。文字は、すべてエスケープする
  ・find_node_links(text)  … 回答に出てくるノード名を探し、公式ドキュメントへのリンクの一覧を返す
  ・node_links_html(links) … その一覧を、回答の下に出す 1 行（リッチテキスト）にする
  ・doc_url / search_url   … URL の作り方

公式ドキュメントのページがあるノードだけを、ページへのリンクにする:
  node_link_data.py は、公式の各章の一覧（https://www.sidefx.com/docs/houdini/nodes/<章>/index.html）に載っているページだけを集めたもの
  （houdini/update_node_links.py で作り直す）。表に無い名前は、ページを推測して作らず、公式サイトの検索のリンク
  （https://www.sidefx.com/search/?q=…）にする。リンク先は、公式の最新版のページ（版ごとの違いは、ページの上のバージョン切り替えで見る）。
"""

from __future__ import annotations

import html
import re
import unicodedata
from functools import lru_cache
from urllib.parse import quote, urlsplit

try:
    from node_link_data import BASE as DOC_BASE
    from node_link_data import CHECKED_ON, NODES
except ImportError:  # データが無い環境でも、URL のリンクだけは動かす
    DOC_BASE = "https://www.sidefx.com/docs/houdini/nodes"
    CHECKED_ON = ""
    NODES = {}

SEARCH_BASE = "https://www.sidefx.com/search/?q="

# 同じ表示名が、複数の章にあるときの優先順（Merge / Transform などは、SOP を先にする）
CONTEXT_ORDER = ("sop", "dop", "obj", "lop", "vop", "top", "chop", "cop2", "cop", "out", "apex")
CONTEXT_LABELS = {"out": "ROP"}  # 公式の URL では ROP は out。それ以外は、大文字にしたもの（sop → SOP）

MAX_DOC_LINKS = 8
MAX_SEARCH_LINKS = 3
_MAX_WORDS = 7  # 表示名の、最大の単語数

# ─── URL ─────────────────────────────────────────────────────────────────────


def is_safe_url(url: str) -> bool:
    """外部ブラウザで開いてよい URL か。http / https だけ（javascript: file: data: などは不可）。

    ホスト名が無い、空白や制御文字（向きを変える文字を含む）を含む、ポートが不正な、ユーザー名つき（https://公式@別のサイト/ のような、見せかけ）のものも不可。
    """
    if not isinstance(url, str) or not url or len(url) > 2000:
        return False
    # 空白・制御文字・書式の文字（右から左への並べ替え U+202E、幅ゼロの文字など）は、表示と行き先をずらせるので、不可
    if any(ch.isspace() or unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") for ch in url):
        return False
    try:
        parts = urlsplit(url)
        parts.port  # 数でない・範囲外のポートは、ここで ValueError になる
    except ValueError:
        return False
    if parts.scheme.lower() not in ("http", "https"):
        return False
    if not parts.hostname or "@" in parts.netloc:
        return False
    return True


def doc_url(context: str, slug: str) -> str:
    return f"{DOC_BASE}/{context}/{slug}.html"


def search_url(name: str) -> str:
    return SEARCH_BASE + quote(name.strip(), safe="")


# 文の中の URL。ASCII の文字だけ（日本語の文字・句読点・全角の括弧の手前で止める。日本語を含む URL は、%エンコードの形なら、そのまま通る）
_URL_RE = re.compile(r"https?://[^\s<>\"'`\u0080-\U0010ffff]+")
_MD_LINK_RE = re.compile(r"\[([^\[\]\n]{1,200})\]\((https?://[^\s()<>\"'`]+)\)")
_TRAILING = ".,;:!?]}>"


def _trim_url(url: str) -> str:
    """URL の末尾の、文の記号（. , ) など）を落とす。閉じ括弧は、URL の中に対応する開き括弧が無いときだけ落とす。"""
    while url:
        last = url[-1]
        if last in _TRAILING:
            url = url[:-1]
        elif last == ")" and url.count("(") < url.count(")"):
            url = url[:-1]
        else:
            break
    return url


LINK_COLOR = "#7dd3fc"  # 暗い背景で読めるリンクの色（Qt のラベルは、<a> の色を、中の <span> の色で決める）


def _anchor(url: str, label: str) -> str:
    return (
        f'<a href="{html.escape(url, quote=True)}">'
        f'<span style="color:{LINK_COLOR};text-decoration:underline;">{html.escape(label)}</span></a>'
    )


def linkify_html(text: str) -> str:
    """回答の文を、リッチテキスト（HTML）にする。

    ・文字は、すべてエスケープする（回答に <b> などが入っていても、画面の見た目を変えさせない）。改行は <br> にする
    ・http(s) の URL は、そのままの文字でリンクにする。[文字](URL) は、「文字（ホスト名）」のリンクにする
      （表示の文字と、リンク先が違うことに気づけるように、ホスト名を添える）
    ・http / https 以外（javascript: など）は、リンクにしない（そのまま文字で出る）
    """
    text = str(text or "")
    out: list[str] = []
    pos = 0
    pattern = re.compile(_MD_LINK_RE.pattern + "|" + _URL_RE.pattern)
    for match in pattern.finditer(text):
        out.append(html.escape(text[pos:match.start()]))
        pos = match.end()
        if match.group(1) is not None:  # [文字](URL)
            url = match.group(2)
            if is_safe_url(url):
                host = urlsplit(url).hostname or ""
                out.append(_anchor(url, match.group(1)) + html.escape(f"（{host}）"))
            else:
                out.append(html.escape(match.group(0)))
            continue
        raw = match.group(0)
        url = _trim_url(raw)
        pos -= len(raw) - len(url)  # 落とした末尾は、ふつうの文字として、次に出す
        out.append(_anchor(url, url) if is_safe_url(url) else html.escape(url))
    out.append(html.escape(text[pos:]))
    return "".join(out).replace("\r\n", "\n").replace("\n", "<br>")


# ─── ノード名 → 公式ドキュメント ─────────────────────────────────────────────


def _norm(text: str) -> str:
    """表示名の比較用。英数字だけを小文字にして、空白 1 つでつなぐ（「Pyro Solver (Sparse)」と「pyro-solver sparse」を同じにする）。"""
    return " ".join(re.findall(r"[a-z0-9]+", str(text).lower()))


@lru_cache(maxsize=1)
def _indexes() -> tuple[dict[str, list[tuple[str, str, str]]], dict[str, list[tuple[str, str, str]]]]:
    """(表示名の小文字 → [(章, ページ名, 表示名)], ページ名 → [(章, ページ名, 表示名)])。章は CONTEXT_ORDER の順。"""
    by_title: dict[str, list[tuple[str, str, str]]] = {}
    by_slug: dict[str, list[tuple[str, str, str]]] = {}
    for context in CONTEXT_ORDER:
        for line in NODES.get(context, "").splitlines():
            slug, sep, title = line.partition("|")
            if not sep or not slug or not title or slug.startswith("_"):
                continue
            entry = (context, slug, title)
            by_title.setdefault(_norm(title), []).append(entry)
            by_slug.setdefault(slug.lower(), []).append(entry)
    return by_title, by_slug


def lookup(name: str, context: str | None = None) -> dict | None:
    """ノードの名前（表示名 "Pyro Solver"、ページ名 "pyrosolver"、名前空間つき "kinefx::rigpose"）から、公式ドキュメントのページを探す。

    context（"sop" など）を渡すと、その章を優先する。表に無ければ None（ページを推測しない）。
    戻り値: {"title", "context", "label"（SOP など）, "url", "slug"}
    """
    by_title, by_slug = _indexes()
    raw = " ".join(str(name).strip().lower().split())
    entries = by_title.get(_norm(raw)) or by_slug.get(raw.replace("::", "--").replace(" ", "")) or []
    if not entries:
        return None
    chosen = next((e for e in entries if context and e[0] == context), entries[0])
    return _result(chosen)


def _result(entry: tuple[str, str, str]) -> dict:
    context, slug, title = entry
    return {
        "title": title,
        "context": context,
        "label": CONTEXT_LABELS.get(context, context.upper()),
        "url": doc_url(context, slug),
        "slug": slug,
    }


_CONTEXT_WORD = re.compile(r"\b(SOP|DOP|VOP|LOP|TOP|CHOP|COP2|COP|OBJ|ROP|APEX)s?\b")
_CONTEXT_FOLLOW = re.compile(r"^\s{0,2}(?:ノード)?\s{0,2}[（(]?\s{0,2}(SOP|DOP|VOP|LOP|TOP|CHOP|COP2|COP|OBJ|ROP|APEX)\b")
_CONTEXT_BEFORE = re.compile(r"(SOP|DOP|VOP|LOP|TOP|CHOP|COP2|COP|OBJ|ROP|APEX)\s?(?:の|内の|上の|側の|で使う|では)?\s*$")
_CONTEXT_KEY = {"ROP": "out", "SOP": "sop", "DOP": "dop", "VOP": "vop", "LOP": "lop", "TOP": "top", "CHOP": "chop",
                "COP2": "cop2", "COP": "cop", "OBJ": "obj", "APEX": "apex"}
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]*")
_JOINER_RE = re.compile(r"^[ \-:()/&]{1,3}$")  # 名前の単語と単語の間（「Pyro Solver (Sparse)」の「 (」など。句点・読点は含めない）
_BACKTICK_RE = re.compile(r"`([A-Za-z0-9_]+(?:::[A-Za-z0-9_.]+)*)`")
_OPEN = "`「『\"'*（("
_CLOSE = "`」』\"'*）)"
# 単語 1 つの名前（Group・Merge・Null など、ふつうの英単語と同じもの）は、「ノード」などの印があるときだけ、ノード名とみなす
_NODE_MARK = re.compile(r"^\s?(?:ノード|node\b|Node\b|SOP\b|DOP\b|VOP\b|LOP\b|CHOP\b|COP2\b|COP\b|TOP\b|OBJ\b|ROP\b)")
_NAMED_NODE_RE = re.compile(r"((?:[A-Z][A-Za-z0-9\-]*)(?: [A-Z][A-Za-z0-9\-]*){0,3}) ?(?:ノード|node\b)")
_NOT_A_NODE = {
    "Houdini", "SOP", "DOP", "VOP", "LOP", "TOP", "CHOP", "COP", "COP2", "ROP", "OBJ", "APEX", "VEX", "HDA", "HOM",
    "Python", "The", "A", "This", "That", "Each", "Any", "New", "Your", "Same", "Another", "Network", "Parameter",
    "Labs", "SideFX", "Claude", "Cloudflare", "RAG",
}


def _context_hint(text: str) -> str | None:
    """回答全体で、いちばん多く出てくる章（SOP / DOP …）。同じ名前が複数の章にあるときの手がかり。"""
    counts: dict[str, int] = {}
    for word in _CONTEXT_WORD.findall(text):
        counts[word] = counts.get(word, 0) + 1
    if not counts:
        return None
    return _CONTEXT_KEY[max(counts, key=lambda w: (counts[w], -CONTEXT_ORDER.index(_CONTEXT_KEY[w])))]


def _pick(entries: list[tuple[str, str, str]], text: str, start: int, end: int, hint: str | None) -> tuple[str, str, str]:
    """同じ名前が複数の章にあるとき、どれにするか。直後の「(DOP)」→ 直前の「DOP の」→ 回答全体で多い章 → 既定の順。"""
    follow = _CONTEXT_FOLLOW.match(text[end:end + 16])
    before = _CONTEXT_BEFORE.search(text[max(0, start - 12):start])
    if follow:
        wanted = _CONTEXT_KEY[follow.group(1)]
    elif before:
        wanted = _CONTEXT_KEY[before.group(1)]
    else:
        wanted = hint
    return next((e for e in entries if wanted and e[0] == wanted), entries[0])


def find_node_links(text: str, limit: int = MAX_DOC_LINKS) -> list[dict]:
    """回答の中のノード名を、出てきた順に探して、公式ドキュメントのリンクの一覧を返す（同じページは 1 回だけ）。

    戻り値の各要素: {"kind": "doc" | "search", "name", "label", "url"}
      ・"doc"    … 公式のノード一覧に載っているページ（実在する）
      ・"search" … 「〇〇 ノード」と書かれているが、一覧に無い名前。ページを推測せず、公式サイトの検索のリンクにする
    名前の見つけ方:
      ・複数の単語の表示名（Pyro Solver・Attribute Wrangle など）は、そのまま見つける（大文字小文字は問わない）
      ・単語 1 つ（Merge・Scatter など）は、「Scatter ノード」「`Scatter`」「「Scatter」」のように、ノード名と分かる印があるときだけ
      ・`attribwrangle` / `kinefx::rigpose` のような、バッククォートで囲んだページ名も、見つける
    """
    text = str(text or "")
    by_title, by_slug = _indexes()
    if not by_title:
        return []
    hint = _context_hint(text)
    found: list[tuple[int, dict]] = []
    consumed: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in consumed)

    # 1) バッククォートで囲んだページ名
    for match in _BACKTICK_RE.finditer(text):
        entries = by_slug.get(match.group(1).lower().replace("::", "--")) or by_title.get(_norm(match.group(1)))
        if entries:
            found.append((match.start(), _result_doc(_pick(entries, text, match.start(), match.end(), hint))))
            consumed.append((match.start(), match.end()))

    # 2) 表示名（長い名前を先に）
    words = [(m.group(), m.start(), m.end()) for m in _WORD_RE.finditer(text)]
    i = 0
    while i < len(words):
        matched = False
        for n in range(min(_MAX_WORDS, len(words) - i), 0, -1):
            window = words[i:i + n]
            if any(not _JOINER_RE.match(text[window[k][2]:window[k + 1][1]]) for k in range(n - 1)):
                continue
            start, end = window[0][1], window[-1][2]
            if not free(start, end):
                continue
            entries = by_title.get(_norm(" ".join(w for w, _, _ in window)))
            if not entries:
                continue
            if n == 1:
                before = text[start - 1] if start > 0 else ""
                after = text[end] if end < len(text) else ""
                wrapped = before != "" and before in _OPEN and after != "" and after in _CLOSE
                marked = bool(_NODE_MARK.match(text[end:end + 12]))
                if not (marked or wrapped) or not window[0][0][0].isupper() and not wrapped:
                    continue
            found.append((start, _result_doc(_pick(entries, text, start, end, hint))))
            consumed.append((start, end))
            i += n
            matched = True
            break
        if not matched:
            i += 1

    docs: list[dict] = []
    seen: set[str] = set()
    for _pos, link in sorted(found, key=lambda item: item[0]):
        if link["url"] not in seen:
            seen.add(link["url"])
            docs.append(link)
    docs = docs[:limit]

    # 3) 「〇〇 ノード」と書かれているが、一覧に無い名前 → 検索のリンク
    searches: list[dict] = []
    known = {link["name"].lower() for link in docs}
    for match in _NAMED_NODE_RE.finditer(text):
        name = match.group(1).strip()
        if (not free(match.start(1), match.end(1)) or name in _NOT_A_NODE or name.lower() in known
                or _norm(name) in by_title or any(w in _NOT_A_NODE for w in name.split())):
            continue
        known.add(name.lower())
        searches.append({"kind": "search", "name": name, "label": name, "url": search_url(name)})
        if len(searches) >= MAX_SEARCH_LINKS:
            break
    return docs + searches


def _result_doc(entry: tuple[str, str, str]) -> dict:
    result = _result(entry)
    return {"kind": "doc", "name": result["title"], "label": f"{result['title']}（{result['label']}）", "url": result["url"]}


def node_links_html(links: list[dict]) -> str:
    """find_node_links の結果を、回答の下に出す、リッチテキストにする。無ければ空の文字列。"""
    docs = [link for link in links if link["kind"] == "doc" and is_safe_url(link["url"])]
    searches = [link for link in links if link["kind"] == "search" and is_safe_url(link["url"])]
    parts: list[str] = []
    if docs:
        parts.append("公式ドキュメント: " + " ・ ".join(_anchor(link["url"], link["label"]) for link in docs))
    if searches:
        parts.append("ページを確認できなかった名前（公式サイトで検索）: " + " ・ ".join(_anchor(link["url"], link["label"]) for link in searches))
    return "<br>".join(parts)
