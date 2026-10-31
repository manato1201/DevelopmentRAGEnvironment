"""
doc_tools.py — チュートリアル生成エージェントが、生成の途中でHoudiniのドキュメントを引くツール（2026-10-31）

これまでの生成は、トピックの文だけで「最初に1回」検索し、その結果（6件前後）をシステムプロンプトに
固定していた。実際の生成ログ（localRAG/tutorials の指標10件）では、引用率の平均が15%で、取れていたのは
概要ページが中心だった。ノードを組む段階で必要な「このノードのパラメータの意味・選択肢」は、その場で
引けなかった。Houdini21MCP / fxhoudinimcp などが持つ search_docs / get_doc と同じ型のツールを足す。

  search_docs(query)       … Worker の /search（意味＋全文検索）で、該当ページの抜粋を返す
  get_doc(file, offset)    … Worker の /docs/get で、1ページの全文（長ければ続き）を返す

・検索先は、生成が使うナレッジ（shared:houdini22 など）に固定する。モデルは namespace を選べない。
・引いたページは sources に追記し、最初の検索結果の続き番号を付ける（finish_tutorial の sources_used で引用できる）。
・ネットワーク呼び出しなので、Houdini のメインスレッドでは実行しない（HoudiniToolExecutor.execute が分岐する）。
・失敗しても生成は止めない（エラー文を返す。モデルは手元の知識と他のツールで続けられる）。
"""

from __future__ import annotations

import re
from typing import Callable

from rag_client import error_message, post_json

DOC_TOOL_NAMES = ("search_docs", "get_doc")

# 1回の生成で呼べる回数の上限（暴走・検索ばかり続ける状態の防止。Worker側のレート制限は1分30回）。
MAX_DOC_CALLS = 30
SEARCH_DEFAULT_LIMIT = 5
SEARCH_MAX_LIMIT = 8
# 検索結果の1ページあたりの抜粋の長さ（チャンクは最大1000文字）。
EXCERPT_CHARS = 700
# get_doc の1回の取得量。長いページは offset で続きを読む。
GET_DOC_CHARS = 8000
HTTP_TIMEOUT_SEC = 60

DOC_TOOLS: list[dict] = [
    {
        "name": "search_docs",
        "description": (
            "Houdini の公式ドキュメント（ナレッジベース）を検索して、該当ページの抜粋を返す。"
            "最初に渡された「参考ドキュメント」は、トピックだけで生成の最初に1回検索した断片で、"
            "使うノードのパラメータ解説を含まないことが多い。足りない部分をこれで補う。"
            "使いどき: ①初めて使うノードのパラメータの意味・メニューの選択肢・注意点を確かめるとき（推測で値を入れない）、"
            "②cook のエラーの原因が分からないとき（エラー文の語で検索）、③VEX の関数や属性名が不確かなとき。"
            "query はノード名や用語（例: 'rbdmaterialfracture パラメータ', 'copytopoints pack and instance', 'vellum cloth constraint')。"
            "同じ内容を繰り返し検索しない。結果の番号 [n] は finish_tutorial の sources_used で引用できる。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索語（ノード名・用語・エラー文の一部。日本語でも英語でもよい）"},
                "limit": {
                    "type": "integer",
                    "description": f"返す件数（1〜{SEARCH_MAX_LIMIT}、省略時{SEARCH_DEFAULT_LIMIT}）",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_doc",
        "description": (
            "search_docs の結果にあるページの全文を読む（長いページは offset で続きを読む）。"
            "抜粋ではパラメータの一覧・手順・注意点が足りないときに使う。"
            "file は search_docs の結果に出た名前をそのまま渡す。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "search_docs の結果にあるドキュメント名（そのまま）"},
                "offset": {"type": "integer", "description": "続きを読むときの開始位置（前回の結果に書かれた値。省略時0）"},
            },
            "required": ["file"],
        },
    },
]

# システムプロンプトに差し込む使い方の説明（ツールを渡すときだけ入れる）。
DOC_TOOLS_SECTION = """
## ドキュメント検索ツール（search_docs / get_doc）
下の「参考ドキュメント」は、トピックの文だけで最初に1回検索した断片です。使うノードのパラメータ解説を含まないことが多いので、次のように補ってください。
- 初めて使うノードは、set_parameter の前に search_docs でノード名を引き、パラメータの意味・選択肢・注意点を確かめる（推測で値を入れない）。1ノードにつき1〜2回まで。
- 抜粋で足りないときだけ get_doc で全文を読む。
- cook のエラーの原因が分からないときは、エラー文の語で検索する。
- 検索結果の番号（[7] 以降）も、参考にしたものは finish_tutorial の sources_used に書く。実際に使っていないものは書かない。
- 調べてもドキュメントに書かれていないことは、断定せず「この環境では確かめていません」と書く。検索ばかり続けず、組み立てを優先すること。
"""


class DocToolError(Exception):
    """ドキュメントの取得に失敗した（モデルに見せるメッセージを持つ）。"""


PostFn = Callable[[str, dict], dict]

_RESULT_RE = re.compile(r"^\s*\[(\d+)\]\s*ファイル:\s*([^\n]*)\n(.*)$", re.DOTALL)


def parse_search_hits(data: dict) -> list[tuple[str, int | None, list[str]]]:
    """Worker の /search の応答（texts と sources）を、ファイルごとの (file, 関連度, 抜粋の一覧) にまとめる（出てきた順）。"""
    sources = data.get("sources") or []
    grouped: dict[str, tuple[int | None, list[str]]] = {}
    order: list[str] = []
    for text in data.get("texts") or []:
        m = _RESULT_RE.match(str(text))
        if not m:
            continue  # 見出し（「検索結果（N 件）」）や、作業の章のメモ
        index = int(m.group(1)) - 1
        file = m.group(2).strip()
        body = " ".join(m.group(3).split())
        score = None
        if 0 <= index < len(sources) and isinstance(sources[index], dict):
            score = sources[index].get("score")
        if file not in grouped:
            grouped[file] = (score, [])
            order.append(file)
        grouped[file][1].append(body)
    return [(f, grouped[f][0], grouped[f][1]) for f in order]


class DocClient:
    """
    Worker の /search と /docs/get を呼ぶ。1回の生成につき1つ作る。

    sources: TutorialResult.sources と同じリスト（参照を共有する）。最初の検索結果が入っている状態で渡すと、
             ここで引いたページは続き番号で追記される。
    post:    テスト用の差し込み口。(パス, JSON) -> 応答のdict。省略時は urllib で Worker を呼ぶ。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        namespace: str,
        sources: list[dict],
        context_hint: list[str] | None = None,
        post: PostFn | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self.namespace = namespace
        self.sources = sources
        self._context_hint = list(context_hint or [])
        self._post = post or self._http_post
        self.initial_source_count = len(sources)
        self.searches = 0
        self.reads = 0

    # ── 公開 ─────────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int | None = None) -> str:
        query = (query or "").strip()
        if not query:
            raise DocToolError("query が空です。ノード名や用語を指定してください")
        self._count_call()
        n = _clamp(limit, SEARCH_DEFAULT_LIMIT, 1, SEARCH_MAX_LIMIT)
        payload: dict = {"query": query[:300], "limit": n, "namespaces": [self.namespace]}
        if self._context_hint:
            payload["context"] = self._context_hint
        data = self._post("/search", payload)
        self.searches += 1
        hits = parse_search_hits(data)
        if not hits:
            return f"「{query}」に一致するドキュメントはありませんでした。別の語（英語のノード名など）で試してください。"

        lines = [f"検索結果 {len(hits)} 件（「{query}」）。全文が必要なら get_doc(file=…) を使う。"]
        for file, score, excerpts in hits:
            number = self._register(file, score)
            body = " … ".join(excerpts)
            if len(body) > EXCERPT_CHARS:
                body = body[:EXCERPT_CHARS].rstrip() + "…"
            lines.append(f"\n[{number}] {file}\n{body}")
        return "\n".join(lines)

    def get(self, file: str, offset: int | None = 0) -> str:
        file = (file or "").strip()
        if not file:
            raise DocToolError("file が空です。search_docs の結果にある名前を指定してください")
        self._count_call()
        start = _clamp(offset, 0, 0, 10_000_000)
        data = self._post(
            "/docs/get",
            {"namespace": self.namespace, "file": file, "offset": start, "maxChars": GET_DOC_CHARS},
        )
        self.reads += 1
        text = str(data.get("text") or "")
        total = int(data.get("totalChars") or len(text))
        number = self._register(file, None)
        end = start + len(text)
        lines = [f"[{number}] {file}（全 {total:,} 文字のうち {start:,}〜{end:,} 文字目）", "", text]
        next_offset = data.get("nextOffset")
        if next_offset is not None:
            lines.append(f"\n（続きがあります: get_doc(file=\"{file}\", offset={int(next_offset)})）")
        return "\n".join(lines)

    # ── 内部 ─────────────────────────────────────────────────────────────────

    def _count_call(self) -> None:
        if self.searches + self.reads >= MAX_DOC_CALLS:
            raise DocToolError(
                f"ドキュメントの検索・取得の回数が上限（{MAX_DOC_CALLS}回）に達しました。"
                "これまでに分かったことと、list_available_node_types / get_node_info で続けてください"
            )

    def _register(self, file: str, score: int | None) -> int:
        """sources にあれば、その番号。なければ続き番号で追記する（引用率の計算にも入る）。"""
        for i, s in enumerate(self.sources, start=1):
            if s.get("file") == file:
                return i
        entry: dict = {"file": file, "namespace": self.namespace, "title": file, "db": self.namespace, "fetched": True}
        if score is not None:
            entry["score"] = score
        self.sources.append(entry)
        return len(self.sources)

    def _http_post(self, path: str, payload: dict) -> dict:
        try:
            return post_json(f"{self._base}{path}", payload, timeout=HTTP_TIMEOUT_SEC, api_key=self._key)
        except Exception as exc:  # noqa: BLE001 -- HTTPエラー・ネットワーク断・タイムアウトなど。画面・モデルに出せる文にする
            raise DocToolError(error_message(exc)) from exc


_HOUDINI_NS_RE = re.compile(r"^shared:houdini(\d+)$")


def pick_default_namespace(namespaces: list[str], preferred: str = "") -> str:
    """最初に開くナレッジ。設定で選んだもの → 一番新しい shared:houdini<数字> → 先頭、の順。"""
    if not namespaces:
        return ""
    wanted = (preferred or "").strip().lower()
    if wanted and not wanted.startswith(("shared:", "personal:")):
        wanted = f"shared:{wanted}"
    for ns in namespaces:
        if ns.lower() == wanted:
            return ns
    versions = [(int(m.group(1)), ns) for ns in namespaces if (m := _HOUDINI_NS_RE.match(ns))]
    if versions:
        return max(versions)[1]
    return namespaces[0]


def sort_namespaces(namespaces: list[str]) -> list[str]:
    """共有ナレッジを先に、個人用を後に。"""
    return sorted(namespaces, key=lambda ns: (ns.startswith("personal:"), ns))


def excerpt_for_list(excerpts: list[str], limit: int = 90) -> str:
    """一覧に出す抜粋（長ければ切る）。"""
    text = " … ".join(excerpts)
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _clamp(value: object, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        n = int(value)
    except ValueError:
        return default
    return max(low, min(high, n))
