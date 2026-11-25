"""
houdini_terms.py — Houdini の基本の用語の一覧（2026-11-26。Qt にも Houdini にも依存しない）

背景: 実証実験の参加者の多くは Houdini が初めてで、「Guide の手順の言葉（表示フラグ・SOP・属性など）が、そもそも分からない」
という声があった。Reference タブは、ノード・VEX 関数・シェルフツールの説明で、こうした「画面と考え方の言葉」は引けない。
→ 手で書いた短い一覧を持ち、Guide の「用語の一覧」で読めるようにし、手順の文の語をダブルクリックしたときも、ここを先に引く
  （ここに無い語は、これまでどおり Reference で探す）。基本操作の練習（basics_guide）の手順には、その手順の用語を添える。

方針: 専門用語を専門用語で説明しない。1〜2 文。「どこにあるか」と、練習のどの手順で触るかを添える。
AI は使わない（誤りが入らない）。内容を変えたら、houdini/tests/test_houdini_terms_20261126.py も見直す。
"""

from __future__ import annotations

import html
import re

# (用語, 別の書き方, 意味, どこで見るか, 基本操作の練習の手順の番号)
_TERMS: tuple[tuple[str, tuple[str, ...], str, str, tuple[int, ...]], ...] = (
    # ── 画面 ──
    ("ネットワークエディタ", ("Network Editor", "ネットワークビュー", "Network View"),
     "ノードを置いて、線でつなぐ画面。Houdini での作業の中心です。", "ふつうは画面の右下", (1, 3)),
    ("パラメータエディタ", ("Parameter Editor", "パラメータ画面", "パラメータペイン", "Parameters"),
     "選んだノードの設定値（パラメータ）を見て、変える画面。", "ふつうは画面の右上", (1, 9)),
    ("ビューポート", ("Viewport", "Scene View", "シーンビュー"),
     "結果の形を、3D で見る画面。Space を押しながらマウスで、回す・近づく・平行移動ができます。", "ふつうは画面の左", (1, 2)),
    ("Geometry Spreadsheet", ("ジオメトリスプレッドシート", "スプレッドシート", "Spreadsheet"),
     "形の中身（点やプリミティブと、その属性の値）を、表で見る画面。", "ビューポートのとなりのタブ", (11,)),
    ("タイムライン", ("Timeline", "プレイバー", "Playbar"),
     "フレームを進めて再生する帯。シミュレーションは、ここで再生すると、フレームごとに計算されます。", "画面の下", ()),
    ("シェルフ", ("Shelf", "シェルフツール", "Shelf Tool"),
     "上に並んだボタンの棚。押すと、決まったノードの組み合わせを、まとめて作ります（中身はノードなので、あとで読めます）。", "画面の上", ()),
    # ── ノードとネットワーク ──
    ("ノード", ("Node", "オペレータ", "Operator"),
     "1 つの処理をする部品。Tab で作り、線でつなぐと、上から下へ順に処理されます。", "ネットワークエディタ", (3, 5, 7)),
    ("ネットワーク", ("Network", "ノードネットワーク"),
     "線でつないだノードの並び。全体で、1 つの形やシミュレーションを作る手順になります。", "ネットワークエディタ", (8,)),
    ("線", ("ワイヤー", "Wire", "接続"),
     "ノードとノードをつなぐ線。上のノードの結果が、下のノードへ流れます。", "ネットワークエディタ", (8,)),
    ("入力", ("Input", "入力端子", "インプット"),
     "ノードの上の丸。ここに、ほかのノードの結果を受け取ります。", "ノードの上側", (8,)),
    ("出力", ("Output", "出力端子", "アウトプット"),
     "ノードの下の丸。ここから、このノードの結果を、次のノードへ渡します。", "ノードの下側", (8,)),
    ("パラメータ", ("Parameter", "parm", "パラメーター"),
     "ノードの設定値（大きさ・位置・数など）。パラメータエディタで変えます。", "パラメータエディタ", (9,)),
    ("表示フラグ", ("Display Flag", "ディスプレイフラグ", "表示のフラグ"),
     "ノードの右端の青い部分。付いたノード 1 つの結果だけが、ビューポートに出ます。ふつうは最後のノードに付けます。", "ノードの右端", (6, 10)),
    ("バイパス", ("Bypass", "バイパスフラグ", "Bypass Flag"),
     "ノードの左端の黄色い部分。付けると、そのノードの処理を飛ばします（効き目を比べるときに使います）。", "ノードの左端", ()),
    ("クック", ("Cook", "クッキング", "再計算"),
     "ノードが計算すること。パラメータを変えると、そのノードと、下につながったノードが計算し直されます。", "", (10,)),
    ("パス", ("Path", "ノードのパス"),
     "/obj/geo1/box1 のような、ノードの場所の書き方。左から、外側の入れ物 → 中のノードの順です。", "ネットワークエディタの上の道筋", (4,)),
    ("階層", ("レベル", "Level", "コンテキスト", "Context"),
     "ノードの中に、さらにノードが入る、入れ子の段。Enter（またはダブルクリック）で中に入り、U で 1 つ上に戻ります。", "ネットワークエディタの上の道筋", (4,)),
    ("HDA", ("デジタルアセット", "Digital Asset", "Houdini Digital Asset", "アセット"),
     "ノードの組み合わせを、1 つのノードにまとめたもの。中に入ると、元のノードが並んでいます。", "", ()),
    # ── 階層の種類 ──
    ("Object", ("オブジェクト", "/obj", "Object レベル", "OBJ"),
     "シーンに置く入れ物（形・カメラ・ライトなど）を並べる階層（/obj）。形を作るときは、ここに Geometry を作ります。", "/obj", (3,)),
    ("Geometry", ("ジオメトリノード", "Geometry ノード"),
     "/obj に置く、形の入れ物のノード。中に入ると、形を作る SOP のノードを並べます。", "/obj", (3, 4)),
    ("SOP", ("ソップ", "Surface Operator", "SOP ネットワーク"),
     "形（ジオメトリ）を作る・変えるノードの階層。Geometry の中です。Box・Transform などがここのノードです。", "Geometry の中", (4, 5, 7)),
    ("DOP", ("ドップ", "Dynamics", "DOP ネットワーク", "DOP Network", "dopnet"),
     "シミュレーション（物理の計算）のノードの階層。DOP Network の中です。最後に Output ノードへつなぎます。", "DOP Network の中", ()),
    ("VEX", ("ヴェックス",),
     "Houdini の中で使う、短いプログラムの言葉。Attribute Wrangle などに書いて、属性の値を計算します。", "Wrangle のパラメータ", ()),
    # ── 形の中身 ──
    ("ジオメトリ", ("形", "形状"),
     "点・プリミティブと、それに付いた属性でできた、形のデータ。", "Geometry Spreadsheet", (11,)),
    ("点", ("ポイント", "Point", "Points"),
     "形の角などの位置。形は、点を結んでできています。", "Geometry Spreadsheet の Points", (11,)),
    ("プリミティブ", ("Primitive", "Primitives", "プリム", "ポリゴン", "Polygon"),
     "点を結んでできた面や線（ポリゴン・曲線など）の 1 つ 1 つ。", "Geometry Spreadsheet の Primitives", ()),
    ("属性", ("アトリビュート", "Attribute", "Attributes"),
     "点などに付いた値。P は位置、Cd は色、N は向き（法線）、v は速度です。チュートリアルの多くの手順は、属性を作る・変える作業です。", "Geometry Spreadsheet の列", (11,)),
    ("グループ", ("Group", "Groups"),
     "点やプリミティブの一部に、名前を付けて選べるようにしたもの。ノードの処理を、その部分だけに効かせます。", "パラメータの Group の欄", ()),
    # ── シミュレーション ──
    ("フレーム", ("Frame", "コマ"),
     "時間の 1 コマ。タイムラインの数字です。シミュレーションは、1 フレームずつ前の結果から計算します。", "タイムライン", ()),
    ("シミュレーション", ("Simulation", "シム", "Sim"),
     "物理の計算で、時間とともに動きを作ること（落ちる・壊れる・燃えるなど）。再生して、フレームごとに確かめます。", "タイムラインで再生", ()),
    ("ソルバー", ("Solver",),
     "シミュレーションを、1 フレームずつ進める計算のノード（RBD Bullet Solver・Pyro Solver など）。", "", ()),
    ("RBD", ("剛体", "Rigid Body", "Rigid Body Dynamics", "リジッドボディ"),
     "変形しない固い物体（剛体）のシミュレーション。物を落とす・ぶつける・壊すときに使います。", "", ()),
    ("破壊", ("Fracture", "フラクチャー", "破砕"),
     "形を、あらかじめ破片に割っておくこと（RBD Material Fracture など）。割った破片を、RBD で動かすと、壊れて見えます。", "", ()),
    ("コンストレイント", ("Constraint", "拘束", "Constraints"),
     "破片どうしを、つないでおく決まり。強さを超える力がかかると外れ、そこから壊れます。", "", ()),
    ("Pyro", ("パイロ",),
     "煙・炎のシミュレーション。", "", ()),
    ("キャッシュ", ("Cache", "File Cache", "ファイルキャッシュ"),
     "計算した結果を、ファイルに書いておくこと。2 回目からは計算しないので、再生が速くなります。", "", ()),
)

NOTE = "Houdini の画面と考え方の、基本の言葉です。ノードそれぞれの説明は、Reference タブで探せます。"


def _norm(text: str) -> str:
    text = str(text or "").strip().strip("「」『』（）()[]【】\"'：:、。・ ").strip()
    return re.sub(r"\s+", " ", text).lower()


def _entry(row) -> dict:
    term, aliases, meaning, where, steps = row
    return {"term": term, "aliases": list(aliases), "meaning": meaning, "where": where, "steps": list(steps)}


ENTRIES: list[dict] = [_entry(row) for row in _TERMS]
_INDEX: dict[str, dict] = {}
for _e in ENTRIES:
    for _name in [_e["term"], *_e["aliases"]]:
        _INDEX.setdefault(_norm(_name), _e)
# 文の中から探すときの候補（長い語から。「表示フラグ」を「フラグ」より先に）。1 文字の語（点・線）は、完全一致のときだけ
_CONTAINED = sorted(((k, e) for k, e in _INDEX.items() if len(k) >= 2), key=lambda kv: -len(kv[0]))

# 文の中では、別の意味でよく出る語（「Geometry と入力して Enter」の入力）。ダブルクリックでは引くが、手順の用語には数えない
_NOT_IN_TEXT = {"入力"}

_LOOKUP_MAX = 24  # これより長い選択は、文のまとまりなので、用語として引かない


def find(term: str) -> dict | None:
    """用語（別の書き方を含む。大文字・小文字、かぎかっこは無視）にぴったり合う項目。無ければ None。"""
    return _INDEX.get(_norm(term))


def lookup(selection: str) -> dict | None:
    """ダブルクリックで選ばれた語から、用語を引く。ぴったり合わなければ、選ばれた語に含まれる、いちばん長い用語
    （日本語は、「表示フラグを」のように、助詞までまとめて選ばれることがある）。"""
    key = _norm(selection)
    if not key or len(key) > _LOOKUP_MAX:
        return None
    if key in _INDEX:
        return _INDEX[key]
    for name, entry in _CONTAINED:
        if name in key:
            return entry
    if len(key) <= 3:  # 1 文字の用語（点・線）は、「線を」「点の」のように、先頭に来るときだけ
        for name, entry in _INDEX.items():
            if len(name) == 1 and key.startswith(name):
                return entry
    return None


def one_line(entry: dict) -> str:
    """画面の下の欄に出す 1 文。"""
    where = f"（{entry['where']}）" if entry.get("where") else ""
    return f"用語「{entry['term']}」{where}: {entry['meaning']}"


def terms_in(text: str, limit: int = 4) -> list[dict]:
    """文に出てくる用語（出てくる順。同じ項目は 1 回。英語は語の区切りで、大文字・小文字を無視）。"""
    low = str(text or "").lower()
    hits: list[tuple[int, dict]] = []
    seen: set[str] = set()
    taken: list[tuple[int, int]] = []
    for name, entry in _CONTAINED:
        if entry["term"] in seen or name in _NOT_IN_TEXT:
            continue
        pattern = re.escape(name)
        if re.fullmatch(r"[a-z0-9 /_]+", name):
            pattern = rf"(?<![a-z0-9_]){pattern}(?![a-z0-9_])"
        for match in re.finditer(pattern, low):
            span = (match.start(), match.end())
            if any(a < span[1] and span[0] < b for a, b in taken):  # 長い語の一部（「表示フラグ」の中の「フラグ」など）は数えない
                continue
            taken.append(span)
            hits.append((span[0], entry))
            seen.add(entry["term"])
            break
    return [entry for _pos, entry in sorted(hits, key=lambda h: h[0])][:limit]


def html_block(entries: list[dict]) -> str:
    """手順の下に添える、用語の短い説明（基本操作の練習の手順）。"""
    if not entries:
        return ""
    items = "".join(f"<li><b>{html.escape(e['term'])}</b>: {html.escape(e['meaning'])}</li>" for e in entries)
    return ("<div style='background:#1e293b;padding:6px;margin-top:6px'><b>この手順の用語</b>"
            f"<ul style='margin:2px 0 0 0'>{items}</ul></div>")


def html_list(query: str = "") -> str:
    """用語の一覧（Guide の「用語の一覧」）。query で、用語・別の書き方・意味を絞る。"""
    q = _norm(query)
    rows = [e for e in ENTRIES if not q or q in _norm(" ".join([e["term"], *e["aliases"], e["meaning"]]))]
    if not rows:
        return f"<p>「{html.escape(query)}」に合う用語はありません。ノードの名前は、Reference タブで探せます。</p>"
    parts = [f"<p style='color:#94a3b8'>{html.escape(NOTE)}</p>"]
    for e in rows:
        aliases = f" <span style='color:#94a3b8'>（{html.escape('・'.join(e['aliases'][:3]))}）</span>" if e["aliases"] else ""
        where = f"<br><span style='color:#94a3b8'>見る場所: {html.escape(e['where'])}</span>" if e["where"] else ""
        steps = (f"<br><span style='color:#94a3b8'>基本操作の練習: 手順 {'・'.join(str(n) for n in e['steps'])}</span>"
                 if e["steps"] else "")
        parts.append(f"<p><b>{html.escape(e['term'])}</b>{aliases}<br>{html.escape(e['meaning'])}{where}{steps}</p>")
    return "".join(parts)
