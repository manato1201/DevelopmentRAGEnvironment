"""
video_script.py — チュートリアル動画の「解説の台本」を作る（2026-10-19。2026-11-01にレベル別にした）

これまでの動画は、手順のスライドにツールの実行結果文（「emit のパラメータを設定: Run Over を 0、
VEXpression を int n = 30000; float rin = ...」）を出し、ナレーションはチュートリアル本文の朗読だった。
どちらも「操作の記録」であって、初めて Houdini を触る人への「説明」になっていなかった。

ここでは、保存したチュートリアル（.md）と、生成中に撮った手順ごとのスクリーンショット一覧から、
  ・導入（何を作るか。何が身につくか）
  ・手順ごとの解説（いま何をする／なぜそうする／画面のどこを見る／つまずきやすい点。初出の用語は一言で）
  ・全体の構成の説明
  ・まとめ（次の一歩）
を Claude に書かせ、`<slug>_video_script.json` に保存する。動画エンジン（RAGReel）は、これを
`--houdini-script` で受け取り、手順ごとに音声を作って、画面と同期させる。

2026-11-17（実証実験を受けた変更）:
  ・各手順の解説・字幕に、対象（ノード名・変えたパラメータの表示名）を必ず入れる（step_facts / ensure_target）。
    チェックボックス・メニューは、数字でなく表示名で言う。消す手順は「消します」と言う。
  ・スライドの短い文（points）に、ノードのパス・タブ・変更前→後を入れ、台本の手順に "detail"（場所・変更・目的）を付ける
  ・"sources": 参照した情報源（重複を除く。キーはギャラリーの rag_sources と同じ）と、"quality": 品質チェッカーの結果
    （check_video_quality。書き出す前に、台本と素材が最低限の基準を満たすかを調べる）

安全策:
  ・Claude の出力は検証する。コードのような文章、長すぎる文章、英字だらけの文章は採用しない。
  ・Claude が使えない・出力が壊れている・一部の手順が不合格のときは、定型の解説（_template_step）で
    その手順を補う。台本が全く作れないときだけ、台本なし（従来の動画）になる。
  ・ベストエフォート: どの段階でも例外を外に出さず、状態を表す短い日本語を返す。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

SCRIPT_VERSION = 1

# 1手順のナレーションの長さ（文字）。短すぎると「説明」にならず、長すぎると動画が間延びする。
STEP_NARRATION_MIN = 40
ASCII_RATIO_MAX = 0.5  # 英字（識別子を除く）の割合の上限。ノード名を言う短い文（「emitの出力を、mergeにつなぎます」）が、0.3だと、定型の文に落ちていた
SHORT_STEP_MIN = 20  # つなぐ・消す、のような短い操作の最小の文字数（40だと、正しい短い解説が定型の文に落ちた）
STEP_NARRATION_MAX = 320
INTRO_NARRATION_MAX = 520
OUTRO_NARRATION_MAX = 360
STRUCTURE_NARRATION_MAX = 360
POINT_MAX_CHARS = 44

# 画面に出す短い文は最大2行
MAX_POINTS = 2

# complete(system, user) -> (text, usage)。TutorialAgent.complete_text がこの形。
CompleteFn = Callable[[str, str], "tuple[str, dict]"]

# ── 台本のルール（Claudeへの指示） ─────────────────────────────────────────

LEVELS = ("basic", "applied", "advanced")

# 2026-11-01: 台本は常に「Houdiniを初めて触る人向け」だった。チュートリアル本文はレベル（basic / applied / advanced）で
# 説明の深さを変えているのに、動画で初心者向けに言い直されて、3本の密度が同じになっていた。
# 台本もレベルに合わせて書き分ける（視聴者・用語の扱い・順序・コードの扱い・長さ）。
_ROLE: dict[str, str] = {
    "basic": (
        "あなたは、Houdini（フーディニ）の講師です。Houdiniの基本操作は分かる人に向けた、解説動画の台本を書きます。\n\n"
        "【視聴者】ノードを置く・つなぐ・パラメータを変える、といった基本操作は知っている。基本の言葉（ノード、パラメータ、ジオメトリ、ビューポート）は説明しなくてよい。"
        "このトピックの仕組みは、まだ知らない。\n"
        "【目的】画面に映る操作を「読み上げる」のではなく「説明」する。何をしているか、なぜそうするのか、パラメータを変えると何がどう変わるのかを、具体的に伝える。"
    ),
    "applied": (
        "あなたは、Houdini（フーディニ）の講師です。仕事でHoudiniを使う人に向けた、解説動画の台本を書きます。\n\n"
        "【視聴者】基本操作はもちろん、ノードの構成を自分で組める。専門用語（アトリビュート、パックド、ベックスなど）は、説明しなくても分かる。"
        "知りたいのは、「なぜその構成にするのか」「代わりの方法は何で、どう選ぶのか」。\n"
        "【目的】操作の説明は短く済ませ、設計の理由、代わりの方法との違い、再利用や書き出しのときの注意を伝える。"
    ),
    "advanced": (
        "あなたは、Houdini（フーディニ）の講師です。複数の案件でHoudiniを使ってきた人に向けた、解説動画の台本を書きます。\n\n"
        "【視聴者】手法そのものの説明は要らない。知りたいのは、判断の根拠、トレードオフ、規模を上げたときの挙動、壊れる条件、パイプラインへの載せ方。\n"
        "【目的】比べた結果と測った数値をもとに、「どれを選ぶか」と「なぜか」を伝える。手順は、ノード名と設定値を簡潔に言うだけにする。"
    ),
}

_ORDER: dict[str, str] = {
    "basic": "次の順で書く。①②③は必ず入れる。\n   ①いま何をするか　②なぜそうするのか　③パラメータを変えたときや、画面で何がどう変わるか　④つまずきやすい点（あれば）",
    "applied": "次の順で書く。①②は必ず入れる。\n   ①いま何をするか（短く）　②なぜその構成にするのか　③代わりの方法と、選ぶ基準（手順に関係するとき）　④ハマりどころ（あれば）",
    "advanced": "次の順で書く。①②は必ず入れる。\n   ①操作（ノード名と設定値だけ。短く）　②なぜそうするのか。比べた結果や測った数値が入力にあれば、その数値　③壊れる条件と、気づく方法（あれば）",
}
_TERMS: dict[str, str] = {
    "basic": "新しく出てくる専門用語（アトリビュート、パックド、ランプなど）は、初めて出たときに一言で説明する。例:「パックドは、たくさんの面を1つの塊として扱う形式です」。基本の言葉は説明しない。2回目以降は説明しない。",
    "applied": "専門用語（アトリビュート、パックド、ベックス、エイチディーエーなど）は、説明せずにそのまま使う。このレッスンで初めて出る特殊な言葉だけ、半文で添える。",
    "advanced": "用語の説明はしない。専門用語は、そのまま使う。",
}
_CODE: dict[str, str] = {
    "basic": "コード（VEXなど）は、1行ずつ読まない。「何をするコードか」を、先に説明する。変数名・記号・数式は読み上げない。",
    "applied": "コード（VEXなど）は、1行ずつ読まない。「何をするコードか → ハマりどころ → 代わりの方法」の順で話す。変数名・記号・数式は読み上げない。",
    "advanced": "コード（VEXなど）は、1行ずつ読まない。「意図 → ハマりどころ → 代わりの方法」の順で話す。変数名・記号・数式は読み上げない。",
}
_STYLE: dict[str, str] = {
    "basic": "話し言葉の「です・ます」調で、1文は40文字くらいまで。日常で使わない難しい漢語は避ける。",
    "applied": "話し言葉の「です・ます」調で、1文は45文字くらいまで。",
    "advanced": "話し言葉の「です・ます」調で、1文は50文字くらいまで。専門用語は使ってよいが、1文に詰め込まない。",
}
_SECTIONS_RULE: dict[str, str] = {
    "basic": "「その他の節」（つまずきやすい点、応用のヒントなど）は、読むための文章で書かれている。そのまま読まず、基本操作を知っている人が知っておくとよい要点を1〜3つ選び、話し言葉に言い直す（2〜4文）。コード・関数名・記号は読み上げない。",
    "applied": "「その他の節」（つまずきやすい点、応用のヒントなど）は、読むための文章で書かれている。そのまま読まず、実務で効く要点を2〜3つ選び、判断の理由を添えて話し言葉に言い直す（3〜5文）。コード・関数名・記号は読み上げない。",
    "advanced": "「その他の節」（つまずきやすい点、応用のヒントなど）は、読むための文章で書かれている。そのまま読まず、判断の根拠・壊れる条件・気づく方法を中心に2〜4つ選び、話し言葉に言い直す（3〜6文）。コード・関数名・記号は読み上げない。",
}
_INTRO: dict[str, str] = {
    "basic": "この動画で何を作り、どの仕組みを理解するか、何が身につくかを話す（3〜5文）",
    "applied": "この動画で、何を実務で使える形にするか、どんな判断をするかを話す（3〜5文）",
    "advanced": "この動画で、何を比べ、何を測り、何を判断できるようになるかを話す（3〜5文）",
}
_STEP_SENTENCES: dict[str, str] = {"basic": "3〜5文", "applied": "3〜6文", "advanced": "4〜7文"}
_OUTRO: dict[str, str] = {
    "basic": "まとめと、次にやってみるとよいこと（2〜3文）",
    "applied": "まとめと、現場で気をつける点（2〜3文）",
    "advanced": "判断の要点のまとめと、次に検証するとよいこと（2〜4文）",
}
_AUDIENCE: dict[str, str] = {
    "basic": "基本操作を知っている人向け",
    "applied": "実務でHoudiniを使う人向け",
    "advanced": "経験者向け",
}

_PROMPT_TEMPLATE = """@@ROLE@@

【手順ごとのナレーションの書き方】
1. @@ORDER@@
2. @@TERMS@@
3. @@CODE@@
4. 数字には意味を添える。ただし、与えられた情報から言えることだけにする。
5. @@STYLE@@
6. ナレーションには、英字（アルファベット）を使わない。ノード名・用語はカタカナで書く（例: アトリビュート、スキャッター、ジオメトリ）。数字は算用数字でよい。
7. 画面に出す短い文（points）は、1行30文字くらいまで。ノード名やパラメータ名は、英字のままでよい。コードは入れない。
8. 与えられた手順・値・ノード名にないことは、書かない。分からないことは、書かない。
9. 「それでは始めましょう」のような決まり文句を、手順ごとに繰り返さない。
10. @@SECTIONS@@
11. 本文に「先に知っておく考え方」があるときは、手順の説明でその用語・たとえ・設計判断を使い、考え方と画面の操作を結びつける（「さっきの考え方で言うと、ここが〇〇にあたります」）。
12. 本文の手順に「✅ 確認ポイント」があるときは、その手順（または直前の手順）のナレーションで、「ここで〇〇が見えれば正しいです。見えないときは、△△を確認してください」と、視聴者が自分で確かめられるように伝える。
13. 「パラメータを動かして確かめよう」の節は、「前→後」で話す（「〇〇を△△から□□に変えると、…が変わります」）。数字そのものより、「何がどう変わるか」を伝える。本文にない結果は作らない。
14. 本文に「前提条件」「どんな場面で使うか」「作る前に」の節があるときは、手順に入る前の案内として話す。前提条件は「この動画は〇〇ができる人向けです。分からないときは、先に△△を見てください。知っている人は、〇番の手順から見てください」、場面は「たとえば〇〇のときに使います」、作る前には「使うノードは、順に〇〇（何ができるか）、△△（何ができるか）です」の形で。本文にあることだけを話す。
15. 本文に「TIPS」の節があるときは、コツを1つずつ短く「こうすると楽です」の形で話す。「自分でやってみよう」の節は、結果の条件を読み、「手本を見ずに作ってみてください。できたかどうかは、〇〇で確かめられます」と促す。
16. 手順を、目的や確認ポイント（✅）の切り替わりで2〜5個の章に分ける（chapters）。章の最初の手順の前に、場面が変わることが分かるつなぎの1文（bridge）を書く: 「ここまでで〇〇ができました。次は△△をします」。
17. 手順が20を超えるときは、動画が長くなりすぎないよう、1手順の解説を短くする（ノードを作る・つなぐだけの手順は1〜2文）。
18. ノード名（column_tube のような英字と_の名前）は、そのまま書いてよい。途中をカタカナに直したり、日本語の語を混ぜたりしない。
19. 入力に「動く映像」がある手順は、その映像が再生されている間に話す。「いま動いているのは〇〇です。注目してほしいのは△△です」と、画面の動きに目を向けさせる（入力にある事実だけ。入力にない動きは作らない）。
20. 「動画に出る手順」は、作って、あとで消したノードの手順を省いてある。本文に、試して消した方式の話が出てきても、動画では触れない。最終的に残る構成の説明に絞る。
21. 各手順の最初の文で、対象（ノード名と、変えるパラメータの表示名）を必ず言う。入力の「対象ノード」「変更」にある名前を、そのまま使う。「4にすると、最大値は約0.998になりました」のような、何を変えたのか分からない文は書かない（「noise1の『Element Size』を4にすると、…」のように、対象を言ってから値を言う）。
22. チェックボックスとメニューは、数字で言わない。「0にします」ではなく、「オフにします」「Detailにします」と、画面に出る表示名で言う。入力に表示名が無いときは、数字を言わず、「切り替えます」と言う。
23. ノードやパラメータを消す手順は、「〇〇を消します」とはっきり言う（「整理します」「外します」にしない）。
24. ノードを作る手順では、そのノードを使う目的を、1文で言う（purpose にも、30文字まで）。入力にない目的は作らない。

【出力】JSONだけを出力する（前後に説明やコードブロックを付けない）。形式:
{
  "intro": {"narration": "@@INTRO@@", "points": ["作るもの（短く）", "身につくこと（短く）"]},
  "steps": [
    {"step": 手順の番号（入力と同じ数字）, "heading": "手順の見出し（20文字まで。例: スキャッターで点を散らす）",
     "narration": "解説（@@STEP@@）", "points": ["画面に出す短い文（任意、最大2行）"],
     "purpose": "ノードを使う目的（30文字まで。ノードを作る手順では必ず書く。それ以外は空でよい）"}
  ],
  "chapters": [{"from_step": 章の最初の手順の番号, "title": "章の名前（20文字まで）", "bridge": "章のつなぎの1文（30〜80字。前の章で何ができて、次に何をするか）"}],
  "structure": {"narration": "作ったノード全体の流れを、上から下へ順に説明（2〜3文）", "points": []},
  "sections": [{"id": 節の番号（入力の【節1】の数字）, "match": "その他の節の見出し（入力と同じ文字）", "heading": "見出し（20文字まで。例: つまずきやすいところ）", "narration": "@@AUDIENCE@@の言い直し", "points": ["要点（短く）"]}],
  "outro": {"narration": "@@OUTRO@@", "points": ["次にやってみること（短く）"]}
}
stepsには、入力のすべての手順を、同じ順番で入れること。sectionsには、入力のすべての「その他の節」を入れること（無ければ空の配列）。"""


def system_prompt(level: str = "") -> str:
    """台本を書かせる指示。level（basic / applied / advanced）で、視聴者・用語の扱い・順序・長さが変わる。未知・空は basic。"""
    key = level if level in LEVELS else "basic"
    return (
        _PROMPT_TEMPLATE.replace("@@ROLE@@", _ROLE[key])
        .replace("@@ORDER@@", _ORDER[key])
        .replace("@@TERMS@@", _TERMS[key])
        .replace("@@CODE@@", _CODE[key])
        .replace("@@STYLE@@", _STYLE[key])
        .replace("@@SECTIONS@@", _SECTIONS_RULE[key])
        .replace("@@INTRO@@", _INTRO[key])
        .replace("@@STEP@@", _STEP_SENTENCES[key])
        .replace("@@AUDIENCE@@", _AUDIENCE[key])
        .replace("@@OUTRO@@", _OUTRO[key])
    )


SYSTEM_PROMPT = system_prompt("basic")  # 互換用（レベルを指定しない呼び出し）

# レベルごとの長さの上限（文字）。上のレベルほど、判断の理由や比較に文字数を使うので長くなる。
# レベル不明（""）は、これまでの上限のまま。
_LIMITS: dict[str, dict[str, int]] = {
    "": {"step": STEP_NARRATION_MAX, "section": 360, "intro": INTRO_NARRATION_MAX, "structure": STRUCTURE_NARRATION_MAX, "outro": OUTRO_NARRATION_MAX},
    "basic": {"step": 340, "section": 380, "intro": 520, "structure": 380, "outro": 380},
    "applied": {"step": 420, "section": 460, "intro": 560, "structure": 440, "outro": 420},
    "advanced": {"step": 520, "section": 560, "intro": 600, "structure": 520, "outro": 480},
}


def limits_for(level: str) -> dict[str, int]:
    return _LIMITS.get(level, _LIMITS[""])


def level_from_md(md_text: str) -> str:
    """チュートリアル(.md)のフロントマターの difficulty（= 生成したレベル）。無い・未知は空文字。"""
    m = re.match(r"^---\n(.*?)\n---\n", md_text.replace("\r\n", "\n"), re.S)
    if not m:
        return ""
    d = re.search(r"^difficulty:\s*(\w+)\s*$", m.group(1), re.M)
    return d.group(1) if d and d.group(1) in LEVELS else ""


def usable_steps(step_screenshots: list[dict]) -> list[dict]:
    """動画エンジン（script_composer.cpp）が手順スライドにする手順だけを返す。
    画像が1枚も無い手順、操作文が空の手順は、動画に出ないので台本も要らない。"""
    steps: list[dict] = []
    for s in step_screenshots or []:
        result = str(s.get("result") or "").strip()
        has_image = any(s.get(k) and Path(str(s[k])).exists() for k in ("viewport", "network"))
        if has_image and result:
            steps.append(s)
    return steps


# ── コードかどうかの判定（C++側 looksLikeCode と同じ考え方） ───────────────────

_CODE_RE = re.compile(
    r"(@[A-Za-z_]\w*\s*[-+*/]?=)|(\b(float|int|vector|string|matrix)\s+[A-Za-z_]\w*\s*=)"
    r"|(\bfor\s*\()|(\b[a-z_]\w*\([^)]{0,60}\)\s*;)|(\}\s*$)"
)


def looks_like_code(text: str) -> bool:
    if "```" in text or _CODE_RE.search(text):
        return True
    symbols = sum(1 for c in text if c in "{};=[]<>")
    return symbols >= 4 and symbols * 12 >= len(text)


# ── 英語の用語 → カタカナ（音声が読めるように） ─────────────────────────────────
# ナレーションに英字が残ったときの救済。Claudeには最初から書かせている（SYSTEM_PROMPT 6）。
# エンジン側にも同じ読み替え辞書がある（engine/assets/tts_dictionary.json）が、ここで先に直しておくと
# 字幕も読みやすくなる。長い語から順に置き換える。
READINGS: dict[str, str] = {
    "Attribute Wrangle": "アトリビュートラングル", "Copy to Points": "コピートゥポイント",
    "Poly Extrude": "ポリエクストルード", "Geometry Spreadsheet": "ジオメトリスプレッドシート",
    "Network Editor": "ネットワークエディタ", "Scene View": "シーンビュー", "Run Over": "ランオーバー",
    "VEXpression": "ベックスプレッション", "Wrangle": "ラングル", "Houdini": "フーディニ", "VEX": "ベックス",
    "Geometry": "ジオメトリ", "Scatter": "スキャッター", "Merge": "マージ", "Null": "ヌル",
    "Transform": "トランスフォーム", "Sphere": "スフィア", "Box": "ボックス", "Grid": "グリッド",
    "Detail": "ディテール", "Points": "ポイント", "Primitives": "プリミティブ", "Parameters": "パラメータ",
    "cook": "クック", "SOP": "ソップ", "DOP": "ドップ", "VOP": "ヴォップ", "HDA": "エイチディーエー",
    "PDG": "ピーディージー", "USD": "ユーエスディー", "LOP": "ロップ", "COP": "コップ", "Packed": "パックド",
    "Attribute": "アトリビュート", "Multiparm": "マルチパーム",
}

# ノードの表示名（create_node の定型文で、「Blastノード」のように英語が残っていた。2026-11-06）。
# 大文字・小文字を区別して置き換える（blast・group のような、小文字のノード名は、そのまま読ませる）。
LABEL_READINGS: dict[str, str] = {
    "Blast": "ブラスト", "Attribute Create": "アトリビュートクリエイト", "Attribute Promote": "アトリビュートプロモート",
    "Attribute Randomize": "アトリビュートランダマイズ", "Attribute Delete": "アトリビュートデリート",
    "Attribute Transfer": "アトリビュートトランスファー", "Attribute VOP": "アトリビュートヴォップ",
    "Group": "グループ", "Delete": "デリート", "Switch": "スイッチ", "Resample": "リサンプル", "Remesh": "リメッシュ",
    "Fuse": "フューズ", "Trail": "トレイル", "Sort": "ソート", "Smooth": "スムーズ", "Normal": "ノーマル",
    "Subdivide": "サブディバイド", "Time Shift": "タイムシフト", "Color": "カラー", "Line": "ライン", "Circle": "サークル",
    "Tube": "チューブ", "Torus": "トーラス", "Add": "アド", "Ray": "レイ", "Mountain": "マウンテン", "Foreach": "フォーイーチ",
    "attribwrangle": "アトリビュートラングル", "Point Wrangle": "ポイントラングル",
}

# モデルが「Wrangle」を、「ラン」＋英字の途中（「アトリビュートランgl」）で書いてしまうことがある（2026-11-06の紙燃焼で4回）。
_WRANGLE_MANGLED_RE = re.compile(r"ラン(?:gl|GL|gle|GLE)(?![A-Za-z0-9_])")


def to_katakana(text: str) -> str:
    text = _WRANGLE_MANGLED_RE.sub("ラングル", text)
    for term in sorted(LABEL_READINGS, key=len, reverse=True):
        text = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", LABEL_READINGS[term], text)
    for term in sorted(READINGS, key=len, reverse=True):
        # 前後が英数字・アンダースコアのときは置き換えない（fire_sphere・マージ_layers のような名前の途中を壊さない）
        text = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", READINGS[term], text, flags=re.IGNORECASE)
    return text


_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9]*[_0-9][A-Za-z0-9_]*")


def _ascii_letter_ratio(text: str) -> float:
    """英字の割合。ノード名（column_tube・merge1 のように _ か数字を含む名前）は、英語の文ではないので数えない。"""
    if not text:
        return 0.0
    words_only = _IDENTIFIER_RE.sub("", text)
    return sum(1 for c in words_only if c.isascii() and c.isalpha()) / len(text)


def _first_sentences(text: str, count: int) -> str:
    """先頭から count 文（「。」で終わる文）まで。足りなければ全部。"""
    end = -1
    for _ in range(count):
        end = text.find("。", end + 1)
        if end < 0:
            return text
    return text[: end + 1]


def clean_narration_pair(raw: object, max_chars: int, min_chars: int = 0) -> tuple[str, str] | None:
    """ナレーションとして使える文章に整える。戻り値: (読み上げる文, 字幕に出す文)。使えないときは None。
    読み上げる文は、英語名をカタカナにしたもの（音声が正しく読めるように）。字幕に出す文は、英語名を元のつづりのままにしたもの
    （動画を見て、Houdini で探すノードの名前を確かめられるように。2026-11-08）。文の数（「。」の数）は、どちらも同じ。
    英字が多すぎる・長すぎるかの判定と、長いときに切る位置は、読み上げる文で決める。"""
    if not isinstance(raw, str):
        return None
    text = re.sub(r"[`*#]+", "", raw)
    text = re.sub(r"\s*\n+\s*", " ", text).strip()
    shown = _WRANGLE_MANGLED_RE.sub("ラングル", text)
    text = to_katakana(text)
    if len(text) < min_chars or looks_like_code(text):
        return None
    if _ascii_letter_ratio(text) > ASCII_RATIO_MAX:  # 英字だらけ。音声が読めない
        return None
    if len(text) > max_chars:
        # 文の切れ目（。）で切る。切れ目が無いときは使わない。
        cut = text.rfind("。", 0, max_chars)
        if cut < min_chars:
            return None
        text = text[: cut + 1]
        shown = _first_sentences(shown, text.count("。"))
    return text, shown


def clean_narration(raw: object, max_chars: int, min_chars: int = 0) -> str | None:
    """ナレーションとして使える文章に整える（読み上げる文だけ）。使えないときは None（理由はcheck_narrationで）。"""
    pair = clean_narration_pair(raw, max_chars, min_chars)
    return pair[0] if pair else None


def with_subtitle(entry: dict, spoken: str, shown: str) -> dict:
    """台本の項目に、読み上げる文と字幕の文を入れる。同じなら字幕は書かない（動画エンジンは、無ければ読み上げる文を出す）。"""
    entry["narration"] = spoken
    entry.pop("subtitle", None)
    if shown != spoken:
        entry["subtitle"] = shown
    return entry


def clean_points(raw: object) -> list[str]:
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for p in raw:
        if not isinstance(p, str):
            continue
        s = re.sub(r"\s+", " ", re.sub(r"[`*#]+", "", p)).strip()
        if not s or looks_like_code(s) or "\n" in p:
            continue
        out.append(s if len(s) <= POINT_MAX_CHARS else s[: POINT_MAX_CHARS - 1] + "…")
        if len(out) >= MAX_POINTS:
            break
    return out


def clean_heading(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    s = re.sub(r"\s+", " ", re.sub(r"[`*#]+", "", raw)).strip()
    if looks_like_code(s):
        return ""
    return s if len(s) <= 24 else s[:23] + "…"


# ── 定型の解説（Claudeが使えない・不合格のときの補い） ──────────────────────────

_NODE_HELP = {
    "geo": "ジオメトリノードは、形を作るための作業場所です。このあと、この中にノードを並べていきます",
    "attribwrangle": "アトリビュートラングルは、短いプログラムを書いて、点や面の値をまとめて計算するノードです",
    "sphere": "スフィアは、球の形を作るノードです",
    "box": "ボックスは、四角い箱の形を作るノードです",
    "grid": "グリッドは、平らな板の形を作るノードです",
    "merge": "マージは、いくつかの形を1つにまとめるノードです",
    "null": "ヌルは、何も変えない目印のノードです。流れの出口に置いておくと、あとで見つけやすくなります",
    "xform": "トランスフォームは、形を動かしたり、回したり、大きさを変えたりするノードです",
    "transform": "トランスフォームは、形を動かしたり、回したり、大きさを変えたりするノードです",
    "scatter": "スキャッターは、面の上に点をばらまくノードです",
    "copytopoints": "コピートゥポイントは、点の位置に、形をコピーして並べるノードです",
    "polyextrude": "ポリエクストルードは、面を押し出して、厚みや出っ張りを作るノードです",
}

_CREATE_RE = re.compile(r"「(.+?)」ノード（(\w+)）を作り、名前を (\S+) にする")
_CONNECT_RE = re.compile(r"^(\S+) の出力を、(\S+) の(.*?)入力につなぐ")
def _spoken_pairs(text: str) -> str:
    """「a → b、b → c ほか2本」を、「aからbへ、次に、bからcへ」にする（「ほか」は読まない）。"""
    out = []
    for chunk in text.split("、"):
        parts = [p.strip() for p in chunk.split("→")]
        if len(parts) == 2 and parts[0] and parts[1]:
            out.append(f"{parts[0]}から{parts[1].split(' ')[0]}へ")
    return "、次に、".join(out) or text


_CONNECT_GROUP_RE = re.compile(r"^(\d+)本のノードをつなぐ: (.+)$")  # 連続した接続を1手順にまとめた操作文（houdini_tools）
_PARAM_RE = re.compile(r"^(\S+) のパラメータを設定: (.+)$")
_PARAM_ONE_RE = re.compile(r"(.+?) を (.+?)(?:、|$)")
_CODE_INPUT_RE = re.compile(r"^(\S+) の「(.+?)」欄に、次のコードを入力する")


def _merge_points(first: list[str], second: list[str]) -> list[str]:
    """画面に出す短い文。事実から作った行（場所・変更前→後）を先に、足りなければ、あとの行（解説の要点）で埋める。最大 MAX_POINTS 行。"""
    out = list(first)
    for p in second:
        if len(out) >= MAX_POINTS:
            break
        if p and p not in out:
            out.append(p)
    return out[:MAX_POINTS]


def _short(text: str) -> str:
    return text[:POINT_MAX_CHARS] if len(text) <= POINT_MAX_CHARS else text[: POINT_MAX_CHARS - 1] + "…"


def _template_step(entry: dict, seen: set[str] | None = None, compact: bool = False) -> dict:
    """1手順ぶんの定型の解説。操作文（entry['result']）の最初の行だけを使い、コードは使わない。
    seen: これまでの手順で説明済みの話題。2回目以降は、同じ説明を繰り返さず、短く言う。
    compact: レベルが分かっているとき（基本操作を知っている人向け）は、ノードの基本の説明・Tabキー・つなぎ方の一般論を省く。"""
    seen = seen if seen is not None else set()
    tool = str(entry.get("tool") or "")
    result = str(entry.get("result") or "").strip()
    first_line = result.split("\n", 1)[0].strip()
    code_like = looks_like_code(result) or "\n" in result
    if looks_like_code(first_line) or len(first_line) > 120:
        first_line = ""
    points = [_short(first_line)] if first_line and not code_like else []

    if tool == "create_node":
        m = _CREATE_RE.search(first_line)
        if m:
            desc, ntype, name = to_katakana(m.group(1)), m.group(2), m.group(3)
            key = f"node:{ntype.lower()}"
            if key in seen:
                narration = f"もう1つ、{desc}ノードを作ります。名前は{name}にします。"
            else:
                narration = f"{desc}ノードを作って、名前を{name}にします。"
                help_text = "" if compact else _NODE_HELP.get(ntype.lower(), "")
                if help_text:
                    narration += help_text + "。"
            if not compact and "tab" not in seen:
                narration += "ノードは、Tabキーを押して、名前の一部を打つと見つかります。"
                seen.add("tab")
            seen.add(key)
            return {
                "heading": f"{m.group(1)}を作る",  # 画面に出す見出し。読まないので、英語のノード名のままで短くする
                "narration": narration,
                "points": [_short(f"{m.group(1)} ノードを作る（名前: {name}）")],
            }
        seen.add("node:geo")
        return {
            "heading": "作業場所を作る",
            "narration": "作業場所になるジオメトリノードを作ります。" + ("このあとの処理は、この中に並べます。" if compact else _NODE_HELP["geo"] + "。"),
            "points": points,
        }
    if tool == "connect_nodes" and _CONNECT_GROUP_RE.match(first_line):
        g = _CONNECT_GROUP_RE.match(first_line)
        count, pairs = g.group(1), g.group(2)
        return {
            "heading": f"ノードを{count}本つなぐ",
            "narration": f"ここで、{count}本のノードを、順につなぎます。つなぐのは、{_spoken_pairs(pairs)}です。"
                         "上から下へ、データが流れる順につなぎます。",
            "points": [_short(f"{count}本つなぐ: {pairs}")],
        }
    if tool == "connect_nodes":
        m = _CONNECT_RE.search(first_line)
        src, dst, nth = (m.group(1), m.group(2), m.group(3).strip()) if m else ("", "", "")
        what = f"{src}の出力を、{dst}につなぎます。" if m else "ノードを線でつなぎます。"
        if m:
            points = [_short(f"{src} → {dst}" + (f"（{nth}入力）" if nth else ""))]
        if nth:
            what = f"{src}の出力を、{dst}の{nth}入力につなぎます。入力が2つ以上あるノードは、つなぐ場所で意味が変わります。"
        if "connect" in seen or compact:
            return {"heading": "ノードをつなぐ", "narration": what, "points": points}
        seen.add("connect")
        return {
            "heading": "ノードをつなぐ",
            "narration": what + "Houdiniでは、上のノードから下のノードへ、順番にデータが流れます。つなぐ順番が、そのまま処理の順番になります。",
            "points": points,
        }
    if tool == "set_parameter":
        m = _CODE_INPUT_RE.search(first_line or result.split("\n", 1)[0])
        node = m.group(1) if m else (result.split(" のパラメータ", 1)[0].strip() if " のパラメータ" in result else "")
        if code_like or m:
            who = f"{node}に、" if node and not looks_like_code(node) and len(node) <= 24 else "ここでは、"
            if "code" in seen:
                narration = f"{who}もう1つ、プログラムを書きます。何をするためのコードかを意識して見てください。"
            else:
                narration = (
                    f"{who}プログラムを書きます。点や面の値を、まとめて計算するための命令です。"
                    "細かい書き方は、いまは分からなくても大丈夫です。何をするためのコードなのかを意識して見てください。"
                )
            seen.add("code")
            return {"heading": "プログラムを書く", "narration": narration, "points": ["プログラムを書く"]}
        pm = _PARAM_RE.search(first_line)
        detail = ""
        if pm:
            one = _PARAM_ONE_RE.match(pm.group(2))
            if one:
                value = one.group(2).strip()
                parts = value.split()
                if len(parts) > 1 and len(set(parts)) == 1:  # 「0.8 0.8 0.8」のような、同じ値の並び
                    value = f"すべて{parts[0]}"
                detail = f"{pm.group(1)}の「{one.group(1)}」を{value}にします。".replace("をすべて", "を、すべて")
        if "param" in seen or compact:
            return {"heading": "パラメータを設定する", "narration": (detail or "もう1つ、設定を変えます。"), "points": points}
        seen.add("param")
        return {
            "heading": "パラメータを設定する",
            "narration": (detail or "ノードの設定を変えます。") + "パラメータは、ノードの動きを決める設定項目です。"
                         "数字を変えると、結果がすぐに変わるので、動かしながら確かめてみてください。",
            "points": points,
        }
    if tool == "cook_node":
        if "cook" in seen or compact:
            return {"heading": "結果を確認する", "narration": "クックして、エラーが出ないことと、形が狙いどおりかを確認します。", "points": ["エラーが出ないか確認する"]}
        seen.add("cook")
        return {
            "heading": "結果を確認する",
            "narration": "クック、つまり計算を実行して、結果を確認します。エラーが出なければ成功です。"
                         "画面に形が出ているか、見てみましょう。",
            "points": ["エラーが出ないか確認する"],
        }
    if tool == "delete_node":
        return {
            "heading": "いらないノードを消す",
            "narration": "使わなくなったノードを消します。ノードを減らすと、流れが読みやすくなります。",
            "points": points,
        }
    return {"heading": "次の操作", "narration": (first_line + "。") if first_line else "", "points": points}


SECTION_NARRATION_MAX = 360


def _template_section(heading: str) -> dict:
    """その他の節の定型の言い直し。中身を読まず、その節の役目だけを伝える（専門家向けの本文を読み上げない）。"""
    if "次のレッスン" in heading:
        return {
            "heading": "次のレッスン",
            "narration": "次のレッスンの予告です。今回の内容を土台にして、次は、もう一歩進んだ使い方を扱います。今回の構成を残しておくと、そのまま続きが作れます。",
            "points": ["次の学びにつなげる"],
        }
    if "前提" in heading:
        return {
            "heading": "始める前に",
            "narration": "始める前に、前提条件を確認します。どんなことを知っていると進めやすいか、何を用意しておくとよいかを、先に見ておきましょう。"
                         "すでに知っている内容があれば、飛ばして進んでも構いません。",
            "points": ["前提を確認する", "知っていることは飛ばしてよい"],
        }
    if "場面" in heading:
        return {
            "heading": "どんな場面で使うか",
            "narration": "この技法が、実際の制作のどんな場面で役に立つのかを確認します。使いどころが分かると、あとの手順の意味がつかみやすくなります。",
            "points": ["使う場面をイメージする"],
        }
    if "作る前" in heading or "段取り" in heading:
        return {
            "heading": "使うノードと段取り",
            "narration": "作り始める前に、使うノードと、その順番を確認します。それぞれのノードで何ができるのかを知っておくと、手順の流れが追いやすくなります。",
            "points": ["使うノードと順番を確認する"],
        }
    if "TIPS" in heading.upper():
        return {
            "heading": "TIPS",
            "narration": "ここでは、作業が楽になるコツを紹介します。確かめ方や、うまくいかないときの切り分け方も、覚えておくと便利です。",
            "points": ["コツを覚えておく"],
        }
    if "自分で" in heading or "挑戦" in heading:
        return {
            "heading": "自分でやってみよう",
            "narration": "最後に、手本を見ずに、自分で作ってみましょう。やり方は自由です。結果の条件を満たせたかどうかで、確かめてみてください。",
            "points": ["手本を見ずに作ってみる", "条件を満たせたか確かめる"],
        }
    if any(k in heading for k in ("ハマ", "つまず", "注意", "エラー")):
        return {
            "heading": "つまずきやすいところ",
            "narration": "ここからは、つまずきやすいところの紹介です。エラーが出たときは、あわてずに、メッセージを読んでみてください。"
                         "どのノードの、どの設定で止まっているのかが、たいてい書いてあります。",
            "points": ["エラーが出たら、メッセージを読む", "止まっているノードと設定を探す"],
        }
    if "学ぶ" in heading or "身につ" in heading:
        return {
            "heading": "この動画で身につくこと",
            "narration": "まず、この動画で身につくことを確認します。作り方を覚えるだけでなく、それぞれのノードが何を担当しているのかを、一緒に理解していきましょう。",
            "points": ["ノードの役割を理解する"],
        }
    if "考え方" in heading or "とは" in heading:
        return {
            "heading": "先に、考え方を知ろう",
            "narration": "ノードを触る前に、仕組みの考え方を知っておきましょう。全体のイメージがあると、あとの手順で、いま何をしているのかが分かりやすくなります。",
            "points": ["まず、全体の仕組みをつかむ"],
        }
    if "パラメータ" in heading or "確かめ" in heading or "実験" in heading:
        return {
            "heading": "数字を動かして確かめよう",
            "narration": "ここからは、数字を動かして、結果がどう変わるかを確かめます。1つの数字だけを変えて、前と後を見比べると、その数字の役目がよく分かります。"
                         "試したあとは、数字を元に戻しておきましょう。",
            "points": ["1つだけ変えて、前と後を見比べる", "確かめたら、元に戻す"],
        }
    if "仕上げ" in heading:
        return {
            "heading": "仕上げ",
            "narration": "最後に、見た目を整えます。色や大きさを少し調整するだけで、ぐっと完成品らしくなります。",
            "points": ["色や大きさを整える"],
        }
    if any(k in heading for k in ("応用", "発展", "ヒント", "次")):
        return {
            "heading": "もっと試してみよう",
            "narration": "最後に、もっと試してみたい人へのヒントです。数字を少し変えたり、ノードを足したりして、見た目がどう変わるかを確かめてみましょう。"
                         "うまくいかないときは、前の手順に戻って、1つずつ確認すると見つかります。",
            "points": ["数字を少し変えて、試してみる", "ノードを足して、変化を見る"],
        }
    return {
        "heading": heading[:24],
        "narration": f"ここでは、「{to_katakana(heading)}」について、補足します。",
        "points": [_short(heading)],
    }


def _template_intro(title: str, summary: str, compact: bool = False) -> dict:
    first = ""
    if summary:
        sentence = summary.replace("\n", " ").split("。", 1)[0].strip()
        if sentence and not looks_like_code(sentence) and len(sentence) <= 120:
            first = to_katakana(sentence) + "。"
    narration = f"この動画では、「{to_katakana(title)}」を作ります。" if title else "この動画では、チュートリアルの手順を追っていきます。"
    if compact:
        narration += first + "操作を1つずつ、何をしているのかと、その理由を説明しながら進めます。"
    else:
        narration += first + "操作を1つずつ、何をしているのかを説明しながら進めるので、はじめての方も、画面を見ながらついてきてください。"
    return {"narration": narration, "points": ([title[:POINT_MAX_CHARS]] if title else [])}


def _template_outro() -> dict:
    return {
        "narration": "お疲れさまでした。これで、一通りの流れができました。"
                     "次は、数字を変えたり、ノードを足したりして、結果がどう変わるかを試してみてください。",
        "points": ["数字を変えて試してみる"],
    }


# ── 手順の事実（対象・場所・変更前→後）と、字幕に対象を入れる（2026-11-17） ────────────────────────────────
# 実験の結果: 字幕「4にすると、最大値は約0.998になりました。」のように、何を 4 にしたのかが、字幕に無い手順があった。
# 手順の操作文（result）と、ツールの結果（tool_result）から、「どのノードの・どのパラメータを・いくつからいくつに」を取り出し、
#   ・ナレーション／字幕に、対象の名前が入っているかを確かめる（足りなければ、先頭に 1 文を足す）
#   ・スライドの短い文（points）と、詳細（detail）に、ノードのパス・タブ・変更前→後を入れる
# 手順の記録（step_screenshots の 1 件）に "changes"（label / name / old / new / code / tab / kind / menu_labels の一覧）が
# あれば、それを使う。無ければ、操作文から読み取る（変更前の値は、操作文に無いので、空になる）。

_REL_SET_RE = re.compile(r"^(\S+?)\.(\w+) = ")
_REL_CREATE_RE = re.compile(r"^作成しました: (\S+)（タイプ")
_CREATE_ANY_RE = re.compile(r"「(.+?)」ノード(?:（(\w+)）)?を作り、名前を (\S+) にする")
_DELETE_RE = re.compile(r"不要になった (\S+) を削除する")
_COOK_RE = re.compile(r"^(\S+) を評価")
_MORE_RE = re.compile(r"\s*ほか(\d+)件$")
_CHANGE_ITEM_RE = re.compile(r"^(.+?) を (.+)$")


def _clean_change(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label") or raw.get("name") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not label and not name:
        return None
    labels = raw.get("menu_labels")
    return {
        "label": label or name, "name": name, "old": str(raw.get("old") if raw.get("old") is not None else "").strip(),
        "new": str(raw.get("new") if raw.get("new") is not None else "").strip(), "code": bool(raw.get("code")),
        "tab": str(raw.get("tab") or "").strip(), "kind": str(raw.get("kind") or "").strip(),
        "menu_labels": [str(x) for x in labels] if isinstance(labels, list) else [],
    }


def display_value(change: dict, which: str = "new") -> str:
    """値を、画面に出る言い方にする。チェックボックスは「オン／オフ」、メニューは表示名（数字のままにしない）。
    同じ値の並び（「0.8 0.8 0.8」）は「すべて0.8」。"""
    value = str(change.get(which, "")).strip()
    kind = change.get("kind")
    if kind == "toggle":
        if value.lower() in ("1", "true", "on"):
            return "オン"
        if value.lower() in ("0", "false", "off"):
            return "オフ"
    if kind == "menu":
        labels = change.get("menu_labels") or []
        if value.isdigit() and int(value) < len(labels):
            return str(labels[int(value)])
    parts = value.split()
    if len(parts) > 1 and len(set(parts)) == 1:
        return f"すべて{parts[0]}"
    return value


def step_facts(entry: dict) -> dict:
    """手順（step_screenshots の 1 件）から、何を・どこで・どう変えたかを取り出す。Houdini に依存しない。
    戻り値: {"tool", "action"（create / set / code / connect / delete / cook / other）, "node"（葉の名前）,
    "node_path"（サンドボックスからの相対パス。分かる範囲）, "changes": [...], "more": 省略された件数,
    "is_code", "connect": (入力元, 出力先, 入力の番号) or None, "created": (表示名, タイプ, 名前) or None}。"""
    tool = str(entry.get("tool") or "")
    result = str(entry.get("result") or "").strip()
    first = result.split("\n", 1)[0].strip()
    tool_result = str(entry.get("tool_result") or "").strip()
    facts: dict = {
        "tool": tool, "action": "other", "node": "", "node_path": "", "changes": [], "more": 0,
        "is_code": False, "connect": None, "created": None,
    }
    if tool == "create_node":
        m = _CREATE_ANY_RE.search(first)
        if m:
            facts.update(action="create", node=m.group(3), created=(m.group(1), m.group(2) or "", m.group(3)))
        rel = _REL_CREATE_RE.match(tool_result)
        facts["node_path"] = rel.group(1) if rel else facts["node"]
    elif tool == "set_parameter":
        listed = [c for c in (_clean_change(x) for x in (entry.get("changes") or [])) if c]
        rel = _REL_SET_RE.match(tool_result)
        pm = _PARAM_RE.search(first)
        cm = _CODE_INPUT_RE.search(first or result)
        node = (pm.group(1) if pm else cm.group(1) if cm else (rel.group(1).split("/")[-1] if rel else ""))
        if not node and " のパラメータ" in result:
            node = result.split(" のパラメータ", 1)[0].strip()
        changes = listed
        if not changes and cm:
            changes = [{"label": cm.group(2), "name": "", "old": "", "new": "", "code": True, "tab": "", "kind": "", "menu_labels": []}]
        elif not changes and pm:
            body = pm.group(2)
            more = _MORE_RE.search(body)
            if more:
                facts["more"] = int(more.group(1))
                body = body[: more.start()]
            for chunk in body.split("、"):
                item = _CHANGE_ITEM_RE.match(chunk.strip())
                if item:
                    changes.append({"label": item.group(1).strip(), "name": "", "old": "", "new": item.group(2).strip(),
                                    "code": False, "tab": "", "kind": "", "menu_labels": []})
        if node or changes:
            facts.update(action="code" if any(c["code"] for c in changes) else "set", node=node, changes=changes)
            facts["is_code"] = facts["action"] == "code"
            facts["node_path"] = rel.group(1) if rel else node
    elif tool == "connect_nodes":
        g = _CONNECT_GROUP_RE.match(first)
        m = _CONNECT_RE.search(first)
        if m:
            facts.update(action="connect", connect=(m.group(1), m.group(2), m.group(3).strip()))
        elif g:
            facts.update(action="connect")
    elif tool == "delete_node":
        m = _DELETE_RE.search(first)
        facts.update(action="delete", node=m.group(1) if m else "")
        facts["node_path"] = facts["node"]
    elif tool == "cook_node":
        m = _COOK_RE.match(first)
        facts.update(action="cook", node=m.group(1) if m else "")
        facts["node_path"] = facts["node"]
    return facts


def _mentions(text: str, term: str) -> bool:
    """text に term（またはそのカタカナの読み）が入っているか。大文字・小文字は区別しない。"""
    if not term or not text:
        return False
    low = text.casefold()
    return term.casefold() in low or to_katakana(term).casefold() in low


def target_terms(facts: dict) -> tuple[list[str], list[str]]:
    """解説に必ず入れる語。戻り値: (全部が必要な語, どれか 1 つでよい語)。"""
    action = facts["action"]
    node = facts["node"]
    if action in ("set", "code"):
        names = [t for c in facts["changes"][:3] for t in (c["label"], c["name"]) if t]
        return ([node] if node else []), names
    if action == "create" and facts["created"]:
        desc, ntype, name = facts["created"]
        return [], [t for t in (name, desc, ntype) if t]
    if action == "connect" and facts["connect"]:
        return [facts["connect"][0], facts["connect"][1]], []
    if action in ("delete", "cook") and node:
        return [node], []
    return [], []


def missing_targets(facts: dict, *texts: str) -> list[str]:
    """texts（ナレーション・字幕）のどれにも入っていない、必須の語。"""
    required, any_of = target_terms(facts)
    missing = [t for t in required if not any(_mentions(x, t) for x in texts)]
    if any_of and not any(_mentions(x, t) for x in texts for t in any_of):
        missing.append(any_of[0])
    return missing


def target_sentence(facts: dict) -> tuple[str, str] | None:
    """対象を言う 1 文。戻り値: (読み上げる文, 字幕の文)。作れない手順は None。
    チェックボックス・メニューは表示名で言う。消す手順は「消します」と言う。"""
    action, node = facts["action"], facts["node"]
    shown = ""
    if action == "set" and node and facts["changes"]:
        changes = facts["changes"]
        c = changes[0]
        if len(changes) == 1 and not facts["more"]:
            new, old = display_value(c, "new"), display_value(c, "old")
            if not new or len(new) > 24:
                shown = f"{node}の「{c['label']}」を設定します。"
            elif old and old != new and len(old) <= 24:
                shown = f"{node}の「{c['label']}」を、{old}から{new}に変えます。"
            else:
                shown = f"{node}の「{c['label']}」を、{new}にします。"
        else:
            labels = "」と「".join(x["label"] for x in changes[:3])
            rest = len(changes) - 3 + facts["more"]
            shown = f"{node}の「{labels}」を変えます。" + (f"ほか{rest}件も変えます。" if rest > 0 else "")
    elif action == "code" and node and facts["changes"]:
        shown = f"{node}の「{facts['changes'][0]['label']}」に、コードを入力します。"
    elif action == "delete" and node:
        shown = f"{node}を消します。"
    elif action == "create" and facts["created"]:
        desc, _ntype, name = facts["created"]
        shown = f"{desc}ノード、{name}を作ります。"
    elif action == "connect" and facts["connect"]:
        src, dst, nth = facts["connect"]
        shown = f"{src}の出力を、{dst}の{nth}入力につなぎます。" if nth else f"{src}の出力を、{dst}につなぎます。"
    elif action == "cook" and node:
        shown = f"{node}をクックして、結果を確認します。"
    if not shown:
        return None
    return to_katakana(shown), shown


def ensure_target(spoken: str, shown: str, facts: dict, max_chars: int) -> tuple[str, str, bool]:
    """解説に対象の名前が無ければ、先頭に、対象を言う 1 文を足す。戻り値: (読み上げる文, 字幕, 足したか)。
    長さの上限を超えるときは、末尾の文を落とす（足した文は残す）。"""
    if not missing_targets(facts, spoken, shown):
        return spoken, shown, False
    sentence = target_sentence(facts)
    if sentence is None:
        return spoken, shown, False
    head_spoken, head_shown = sentence
    new_spoken, new_shown = head_spoken + spoken, head_shown + shown
    while len(new_spoken) > max_chars and new_spoken.count("。") > 1:
        cut = new_spoken.rfind("。", 0, len(new_spoken) - 1)
        if cut <= len(head_spoken):
            break
        new_spoken = new_spoken[: cut + 1]
        new_shown = _first_sentences(new_shown, new_spoken.count("。"))
    return new_spoken, new_shown, True


_DANGLING_RE = re.compile(
    r"^(?:ここで|すると|では|次に|そして|また)?[、,]?\s*[-+]?\d+(?:\.\d+)?\s*(?:倍|度|個|%|％|px|フレーム)?\s*(?:に|へ)"
    r"(?:すると|したら|して|変える|変えると|変えて|します|した|なります)"
)


def dangling_value_sentences(text: str, known_terms: list[str] | None = None) -> list[str]:
    """「4にすると、…」のように、何の値か分からない文（数字から始まる）。
    known_terms（対象のノード名・パラメータ名）が、それより前の文に出ていれば、何の値かは分かるので、数えない。"""
    sentences = [x.strip() for x in text.split("。") if x.strip()]
    out = []
    for i, sentence in enumerate(sentences):
        if not _DANGLING_RE.match(sentence):
            continue
        named_before = any(_mentions(prev, t) for prev in sentences[:i] for t in (known_terms or []))
        if not named_before:
            out.append(sentence)
    return out


def _fit_path_line(parts: list[str], limit: int = POINT_MAX_CHARS) -> str:
    """「geo1/emit › Code › Run Over」の形の 1 行。長いときは、先頭のパスの前のほうを「…/」にして、項目名を残す。"""
    parts = [p for p in parts if p]
    if not parts:
        return ""
    head, tail = parts[0], parts[1:]
    prefix = ""
    while len(prefix + " › ".join([head] + tail)) > limit and "/" in head:
        head, prefix = head.split("/", 1)[1], "…/"
    line = prefix + " › ".join([head] + tail)
    if len(line) <= limit:
        return line
    keep = limit - len(" › ".join([""] + tail)) - 1  # ノード名も長いときは、ノード名の前を「…」にして、項目名を残す
    if keep >= 4:
        return "…" + head[-keep:] + " › " + " › ".join(tail)
    return _short(line)


def facts_points(facts: dict) -> list[str]:
    """スライドに出す短い 2 行（場所と、変更前→後）。事実が足りないときは空。"""
    action = facts["action"]
    path = facts["node_path"] or facts["node"]
    if action in ("set", "code") and path and facts["changes"]:
        c = facts["changes"][0]
        first = _fit_path_line([path, c["tab"], c["label"]] if len(facts["changes"]) == 1 else [path, c["tab"]])
        if action == "code":
            return [first, "コードを入力する"]
        if len(facts["changes"]) > 1 or facts["more"]:
            return [first, _short(f"{len(facts['changes']) + facts['more']}件のパラメータを変更")]
        new, old = display_value(c, "new"), display_value(c, "old")
        return [first, _short(f"{old} → {new}" if old and old != new else f"{c['label']} = {new}")]
    if action == "delete" and path:
        return [_short(f"{path} を消す"), "このノードを削除する"]
    if action == "connect" and facts["connect"]:
        src, dst, nth = facts["connect"]
        return [_short(f"{src} → {dst}" + (f"（{nth}入力）" if nth else ""))]
    if action == "cook" and path:
        return [_short(f"{path} を評価（cook）する")]
    return []


def _help_purpose(node_type: str) -> str:
    """定型の説明（_NODE_HELP）から、ノードを使う目的を取る。「スフィアは、球の形を作るノードです」→「球の形を作るノードです」。
    前は「、」の手前を取っていたため、「スフィアは」だけになっていた。"""
    first = _NODE_HELP.get(str(node_type).lower(), "").split("。", 1)[0]
    _topic, sep, rest = first.partition("は、")
    return (rest if sep else first)[:40].strip()


RECORDED_PURPOSE_MAX = 60  # houdini_tools.HoudiniTools._PURPOSE_CHARS と同じ（記録側が、この長さに切って書く）


def recorded_purpose(entry: dict) -> str:
    """手順の記録（step_screenshots の 1 件）の "purpose"（ノードを使う目的の 1 文）。文字列でない・空・コードのような文は ""。"""
    raw = entry.get("purpose")
    if not isinstance(raw, str):
        return ""
    text = " ".join(re.sub(r"[`*#]+", "", raw).split())[:RECORDED_PURPOSE_MAX]
    return "" if looks_like_code(text) else text


def step_detail(facts: dict, purpose: str = "") -> dict:
    """台本の手順に付ける詳細（動画エンジンが、スライドに出せる形）。キー: action / node / node_path / location / changes / purpose / remove。"""
    detail: dict = {"action": facts["action"]}
    if facts["node"]:
        detail["node"] = facts["node"]
    if facts["node_path"]:
        detail["node_path"] = facts["node_path"]
    if facts["changes"]:
        detail["changes"] = [
            {"label": c["label"], "name": c["name"], "tab": c["tab"], "old": display_value(c, "old") if c["old"] else "",
             "new": display_value(c, "new"), "code": c["code"]}
            for c in facts["changes"][:6]
        ]
        c0 = facts["changes"][0]
        detail["location"] = " › ".join(x for x in (c0["tab"], c0["label"]) if x)
    if facts["more"]:
        detail["more"] = facts["more"]
    if facts["action"] == "delete":
        detail["remove"] = True
    if purpose:
        detail["purpose"] = purpose
    return detail


# ── 参照した情報源（出典）。同じ資料が複数の断片で出る（Shelf tools が 2 件、など）ので、重複を除く（2026-11-17） ─────────

_SOURCE_LINE_RE = re.compile(r"^-\s*\[(\d+)\]\s*(?:(✅|⬜)\s*(?:引用済み|未引用)?\s*)?(.+?)(?:（([^）]*)）)?\s*$", re.M)


def dedupe_sources(items: list[dict]) -> list[dict]:
    """出典の重複を除く（資料の名前と、ナレッジの名前が同じものを 1 件にする）。順番は最初に出た順。
    items: [{"title" or "file", "db" or "namespace", "cited"（任意）}]。
    戻り値: ギャラリーの metadata.json の rag_sources と同じキーの一覧
    [{"file", "namespace", "cited"（True / False。分からなければ書かない）, "similarity": 0, "excerpt": "", "numbers": [元の番号]}]。
    1 件でも引用されていれば、cited は True（引用された資料を、「検索のみ」にしない）。"""
    merged: dict[tuple[str, str], dict] = {}
    for n, item in enumerate(items or [], start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("file") or "").strip()
        if not title:
            continue
        db = str(item.get("db") or item.get("namespace") or "").strip()
        key = (title.casefold(), db.casefold())
        number = item.get("number") if isinstance(item.get("number"), int) else n
        if key not in merged:
            entry = {"file": title, "namespace": db, "similarity": 0, "excerpt": "", "numbers": [number]}
            if "cited" in item:
                entry["cited"] = bool(item["cited"])
            merged[key] = entry
        else:
            entry = merged[key]
            entry["numbers"].append(number)
            if "cited" in item:
                entry["cited"] = bool(entry.get("cited")) or bool(item["cited"])
    return list(merged.values())


def parse_md_sources(md_text: str) -> list[dict]:
    """チュートリアル(.md)の「## 参考」の出典の行を読む（tutorial_agent の source_lines の形）。
    戻り値: [{"title", "db", "cited"（バッジが無い=打ち切りの生成では書かない）, "number"}]。"""
    text = md_text.replace("\r\n", "\n")
    start = re.search(r"^## 参考\s*$", text, re.M)
    if not start:
        return []
    body = text[start.end():]
    nxt = re.search(r"^## ", body, re.M)
    if nxt:
        body = body[: nxt.start()]
    out = []
    for m in _SOURCE_LINE_RE.finditer(body):
        item: dict = {"title": m.group(3).strip(), "db": (m.group(4) or "").strip(), "number": int(m.group(1))}
        if m.group(2):
            item["cited"] = m.group(2) == "✅"
        out.append(item)
    return out


# ── 動画の品質チェッカー（2026-11-17）。書き出す前に、台本と素材が最低限の基準を満たすかを調べる ─────────────────────────
# 実験の結果: 動画の品質に差がありすぎた（対象が見えない・字幕に対象が無い・文字がつぶれる・ノード図が読めない、など）。
# check_video_quality() は、手順ごとに次を調べ、満たさない手順を一覧にする（level: error=直すべき / warn=注意 / info=参考）。
#   no_visual            画面の素材（ビューポート・ノード画面）が 1 枚も無い                                   error
#   no_target_view       パラメータを変える手順で、変更した項目の画面が無い                                      warn
#   image_small          画像の幅が MIN_IMAGE_WIDTH 未満（文字がつぶれる）                                     warn
#   diagram_unreadable   ノード図のノード名が MIN_NAME_PT 未満、または図が画面に収まっていない                     error
#   code_hidden          長いコードが、カードに入りきらずに省かれている                                         warn
#   code_not_enlarged    コードを入れる手順なのに、読める大きさのカード（code_card）の画像が無い                  warn
#   target_not_named     ナレーション・字幕に、対象（ノード名・パラメータ名）が無い                              error
#   dangling_value       「4にすると、…」のように、何の値か分からない文がある                                    error
#   delete_wording       消す手順なのに、「消す」「削除」と言っていない                                          error
#   numeric_choice       チェックボックス・メニューを、数字で言っている                                          warn
#   subtitle_long        字幕の 1 文が SUBTITLE_SENTENCE_MAX 文字を超える（画面からはみ出す・読み切れない）       warn
#   detail_missing       パラメータを変える手順に、変更前→後・場所の情報が無い                                  info
#   template_fallback    Claude の解説が基準を満たさず、定型の解説になった                                       info
#   sources_empty / sources_duplicate  出典が空（ギャラリーで「出典なし」になる）／重複                         warn
# 画像の文字の大きさは、撮影側が画像のとなりに書く <画像>.meta.json（screen_capture.write_capture_meta）を読む。無ければ、幅だけで判断する。

MIN_IMAGE_WIDTH = 1280
MIN_NAME_PT = 12.0  # screen_capture.MIN_NAME_PT と同じ値（このモジュールは hou を読み込まないので、複製している。テストで一致を確かめる）
SUBTITLE_SENTENCE_MAX = 60
_LEVEL_ORDER = {"error": 0, "warn": 1, "info": 2}


def _png_size(path: Path) -> tuple[int, int] | None:
    """PNG の幅・高さ（ヘッダだけ読む）。PNG でない・読めないときは None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
            return None
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    except OSError:
        return None


def _read_capture_meta(path: Path) -> dict:
    try:
        data = json.loads(path.with_name(path.name + ".meta.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _number(value: object, default: float = 0.0) -> float:
    """補足情報の数値を読む。壊れた値（None・文字列）のときは default（品質チェックで、台本の生成を止めない）。"""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _issue(step: int | None, level: str, code: str, message: str) -> dict:
    return {"step": step, "level": level, "code": code, "message": message}


def check_step_quality(entry: dict, script_step: dict | None) -> list[dict]:
    """1 手順の品質チェック。entry: 撮影した手順の記録。script_step: 台本の手順（無ければ None）。"""
    n = entry.get("step")
    issues: list[dict] = []
    facts = step_facts(entry)
    images = {k: Path(str(entry[k])) for k in ("viewport", "network") if entry.get(k)}
    existing = {k: p for k, p in images.items() if p.exists()}
    if not existing:
        issues.append(_issue(n, "error", "no_visual", "画面の素材（ビューポート・ノード画面）がありません"))
    if facts["action"] in ("set", "code") and not ("network" in existing and entry.get("network_kind") in ("parameter", None, "")):
        issues.append(_issue(n, "warn", "no_target_view", "変更したパラメータの画面がありません"))
    for kind, path in existing.items():
        size = _png_size(path)
        if size and size[0] < MIN_IMAGE_WIDTH:
            issues.append(_issue(n, "warn", "image_small", f"{kind} の画像が小さい（幅{size[0]}px。{MIN_IMAGE_WIDTH}px以上にする）"))
        meta = _read_capture_meta(path)
        if meta.get("kind") == "node_diagram" and not meta.get("overview"):
            if meta.get("fits") is False or _number(meta.get("name_pt"), MIN_NAME_PT) < MIN_NAME_PT:
                issues.append(_issue(n, "error", "diagram_unreadable",
                                     f"ノード図のノード名が小さい（{meta.get('name_pt', '?')}pt。{MIN_NAME_PT}pt以上にする）"))
        hidden = int(_number(meta.get("lines_hidden")))
        if meta.get("kind") == "code_card" and hidden > 0:
            issues.append(_issue(n, "warn", "code_hidden", f"コードが {hidden} 行、カードに入りきらず省かれています"))
    if facts["action"] == "code" and "network" in existing and _read_capture_meta(existing["network"]).get("kind") != "code_card":
        issues.append(_issue(n, "warn", "code_not_enlarged", "コードを、読める大きさのカードで出していません（小さい画面のままです）"))
    if facts["action"] in ("set", "code") and not facts["changes"]:
        issues.append(_issue(n, "info", "detail_missing", "変更したパラメータが読み取れません（場所・変更前→後を出せません）"))
    if script_step is not None:
        spoken = str(script_step.get("narration") or "")
        shown = str(script_step.get("subtitle") or spoken)
        missing = missing_targets(facts, spoken, shown)
        if missing:
            issues.append(_issue(n, "error", "target_not_named", f"解説・字幕に対象の名前がありません: {'、'.join(missing)}"))
        required, any_of = target_terms(facts)
        for sentence in dangling_value_sentences(spoken, required + any_of) + dangling_value_sentences(shown, required + any_of):
            issues.append(_issue(n, "error", "dangling_value", f"何の値か分からない文があります: 「{sentence[:30]}」"))
            break
        if facts["action"] == "delete" and not any(w in spoken + shown for w in ("消", "削除")):
            issues.append(_issue(n, "error", "delete_wording", "消す手順なのに、「消す」と言っていません"))
        for c in facts["changes"]:
            if c["kind"] in ("toggle", "menu") and display_value(c) != c["new"] and c["new"].isdigit():
                if re.search(rf"{re.escape(c['label'])}[^。]{{0,6}}を\s*{re.escape(c['new'])}\s*に", spoken + shown):
                    issues.append(_issue(n, "warn", "numeric_choice", f"「{c['label']}」を数字で言っています（表示名: {display_value(c)}）"))
        longest = max((len(x) for x in shown.split("。")), default=0)
        if longest > SUBTITLE_SENTENCE_MAX:
            issues.append(_issue(n, "warn", "subtitle_long", f"字幕の 1 文が長い（{longest}文字。{SUBTITLE_SENTENCE_MAX}文字まで）"))
        if script_step.get("source") == "template":
            issues.append(_issue(n, "info", "template_fallback", "Claude の解説が基準を満たさず、定型の解説になっています"))
    return issues


def check_video_quality(script: dict | None, steps: list[dict]) -> dict:
    """台本（build_script の出力）と、手順の素材（step_screenshots）が、最低限の基準を満たすかを調べる。
    戻り値: {"ok": error が 0 件か, "errors", "warnings", "infos", "issues": [{"step", "level", "code", "message"}…（重い順）]}。
    Houdini・Claude に依存しない。台本の段階で直す・警告するために使う（書き出す前に呼ぶ）。"""
    script = script if isinstance(script, dict) else {}
    script_steps = script.get("steps") if isinstance(script.get("steps"), list) else []
    by_step = {e.get("step"): e for e in script_steps if isinstance(e, dict) and isinstance(e.get("step"), (int, str))}
    issues: list[dict] = []
    for entry in steps or []:
        if not isinstance(entry, dict):
            continue
        step_key = entry.get("step")
        issues.extend(check_step_quality(entry, by_step.get(step_key) if isinstance(step_key, (int, str)) else None))
    for section in script.get("sections") or []:  # その他の節（パラメータを動かして確かめる、など）。自動では直せないので、注意にとどめる
        if isinstance(section, dict) and dangling_value_sentences(str(section.get("narration") or "")):
            issues.append(_issue(None, "warn", "dangling_value", f"節「{section.get('heading') or section.get('match', '')}」に、何の値か分からない文があります"))
    sources = script.get("sources")
    if isinstance(sources, list) and not sources:
        issues.append(_issue(None, "warn", "sources_empty", "出典が空です（ギャラリーで「出典なし」になります）"))
    elif isinstance(sources, list):
        keys = [(str(s.get("file", "")).casefold(), str(s.get("namespace", "")).casefold()) for s in sources if isinstance(s, dict)]
        if len(keys) != len(set(keys)):
            issues.append(_issue(None, "warn", "sources_duplicate", "出典に同じ資料が複数あります"))
    images = script.get("images") if isinstance(script.get("images"), dict) else {}
    diagram = images.get("node_diagram")
    if diagram and Path(str(diagram)).exists():
        meta = _read_capture_meta(Path(str(diagram)))
        if meta.get("readable") is False:
            issues.append(_issue(None, "info", "overview_dense", "全体図のノードが多く、名前は小さくなっています（構成の確認用）"))
    issues.sort(key=lambda i: (_LEVEL_ORDER.get(i["level"], 9), i["step"] if isinstance(i["step"], int) else -1))
    count = lambda level: sum(1 for i in issues if i["level"] == level)  # noqa: E731
    return {"ok": count("error") == 0, "errors": count("error"), "warnings": count("warn"), "infos": count("info"), "issues": issues}


def format_quality_report(report: dict, limit: int = 12) -> list[str]:
    """品質チェックの結果を、画面に出す行にする。error と warn を重い順に limit 件まで（info は出さない）。"""
    marks = {"error": "要修正", "warn": "注意"}
    lines = []
    for i in report.get("issues", []):
        if i["level"] not in marks:
            continue
        where = f"手順{i['step']}" if i["step"] is not None else "全体"
        lines.append(f"[{marks[i['level']]}] {where}: {i['message']}")
    if len(lines) > limit:
        lines = lines[:limit] + [f"…ほか {len(lines) - limit} 件"]
    return lines


# ── 入力の用意・出力の検証 ─────────────────────────────────────────────────

def tutorial_excerpt(md_text: str, limit: int = 7000) -> tuple[str, str, str]:
    """(タイトル, 概要の文, Claudeに渡す本文の抜粋)。フロントマターと、ノードの全ダンプ（コード・ノード構成以降）は除く。"""
    text = md_text.replace("\r\n", "\n")
    title = ""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        t = re.search(r"^title:\s*(.+)$", m.group(1), re.M)
        title = t.group(1).strip().strip("\"'") if t else ""
        text = text[m.end():]
    cut = text.find("\n## コード・ノード構成")
    if cut >= 0:
        text = text[:cut]
    summary = ""
    s = re.search(r"^## 概要\n+(.+?)(?:\n\n|\n## |\Z)", text, re.S | re.M)
    if s:
        summary = s.group(1).strip()
    return title, summary, text.strip()[:limit]


# 動画エンジンが別に扱う節。これ以外の「## 見出し」が、「その他の節」（つまずきやすい点・応用のヒントなど）
_HANDLED_SECTIONS = ("概要", "手順", "コード・ノード構成", "参考", "図解")


def extra_sections(md_text: str) -> list[tuple[str, str]]:
    """チュートリアルの「その他の節」を [(見出し, 本文)] で返す。動画では、これらもスライドになり、
    台本が無いと、専門家向けの文章がそのまま読み上げられる（2026-10-19に実データで確認）。"""
    text = md_text.replace("\r\n", "\n")
    m = re.match(r"^---\n.*?\n---\n", text, re.S)
    if m:
        text = text[m.end():]
    out: list[tuple[str, str]] = []
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        heading, _, body = part.partition("\n")
        heading = heading.strip()
        if heading and heading not in _HANDLED_SECTIONS and body.strip():
            out.append((heading, body.strip()))
    return out


def build_user_prompt(
    title: str, excerpt: str, steps: list[dict], sections: list[tuple[str, str]] | None = None, level: str = ""
) -> str:
    audience = _AUDIENCE.get(level, _AUDIENCE["basic"])
    lines = []
    for s in steps:
        result = str(s.get("result") or "").strip()
        tool_result = str(s.get("tool_result") or "").strip()
        item = {"step": s.get("step"), "tool": s.get("tool"), "操作": result.split("\n", 1)[0][:200]}
        facts = step_facts(s)
        if facts["node_path"]:
            item["対象ノード"] = facts["node_path"]
        if facts["changes"]:
            item["変更"] = [
                {k: v for k, v in (("パラメータ", c["label"]), ("タブ", c["tab"]), ("前", display_value(c, "old") if c["old"] else ""),
                                   ("後", "（コード）" if c["code"] else display_value(c, "new"))) if v}
                for c in facts["changes"][:6]
            ]
        frames, fps = s.get("viewport_clip_frames") or [], s.get("viewport_clip_fps") or 0
        if fps and len(frames) / fps >= 5:
            item["動く映像"] = f"この手順の画面で、約{round(len(frames) / fps)}秒の動く映像が再生される"
        # コードを入れる手順は、コードそのものは説明の材料としてだけ渡す（読み上げ禁止）
        if "\n" in result or ";" in result or "\n" in tool_result:
            item["コード（説明の材料。読み上げ・転記は禁止）"] = (tool_result or result)[:600]
        lines.append(json.dumps(item, ensure_ascii=False))
    section_block = ""
    if sections:
        section_block = f"【その他の節（{audience}に言い直すこと。idに節の番号、matchに見出しをそのまま入れる）】\n" + "\n\n".join(
            f"【節{n}】## {h}\n{b[:900]}" for n, (h, b) in enumerate(sections, start=1)
        ) + "\n\n"
    return (
        f"【チュートリアルのタイトル】{title}\n\n"
        f"【チュートリアル本文（作った人の下書き。読むための文章なので、{audience}の話し言葉の台本に言い直すこと）】\n{excerpt}\n\n"
        f"【動画に出る手順（この順番。stepの数字をそのまま使うこと）】\n" + "\n".join(lines) + "\n\n"
        + section_block + f"上のルールに従って、{audience}の台本をJSONで出力してください。"
    )


def parse_model_json(text: str) -> dict | None:
    """モデルの出力から、JSONの本体を取り出す（前後の説明やコードブロックがあっても読む）。"""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def apply_chapters(model: dict, out_steps: list[dict]) -> list[dict]:
    """モデルの chapters を検証して、手順に章の印とつなぎの文を付ける。戻り値: 台本に書く章の一覧（2つ未満なら付けず、空）。
    つなぎの文（bridge）は、章の最初の手順のナレーションの頭に足す（1つ目の章は導入があるので足さない）。
    動画エンジンが対応すれば、step["chapter_start"] で場面転換の画面を出せる（対応していなくても、つなぎの文は声で伝わる）。"""
    order = [e["step"] for e in out_steps]
    chosen: list[dict] = []
    for item in model.get("chapters") or []:
        if not isinstance(item, dict):
            continue
        n = item.get("from_step")
        title = clean_heading(item.get("title"))
        if not isinstance(n, int) or n not in order or not title or any(c["from_step"] == n for c in chosen):
            continue
        bridge, bridge_shown = clean_narration_pair(item.get("bridge"), 160, 10) or ("", "")
        chosen.append({"from_step": n, "title": title, "bridge": bridge, "bridge_shown": bridge_shown})
    chosen.sort(key=lambda c: order.index(c["from_step"]))
    if len(chosen) < 2:
        return []
    starts = {c["from_step"]: c for c in chosen}
    current = None
    for entry in out_steps:
        if entry["step"] in starts:
            current = starts[entry["step"]]
            entry["chapter_start"] = True
            if current["bridge"] and entry["step"] != order[0]:
                shown = entry.get("subtitle") or entry["narration"]
                with_subtitle(entry, current["bridge"] + entry["narration"], current["bridge_shown"] + shown)
        if current is not None:
            entry["chapter"] = current["title"]
    return [{"from_step": c["from_step"], "title": c["title"]} for c in chosen]


def _norm_heading(text: object) -> str:
    """見出しの比較用: 空白・記号・全角半角の違いを除く。"""
    return re.sub(r"[\s:：、。・「」『』()（）\-_/／]+", "", str(text or "")).lower()


def match_sections(raw: object, headings: list[str]) -> dict[str, dict]:
    """モデルの sections を、入力の見出しに対応づける。戻り値: {見出し: 項目}。
    以前は「見出しの完全一致」だけで、1つでもずれると定型の文に落ち、内容のない12節になった（2026-11-06）。
    番号（id。1始まり）→ 完全一致 → 記号を除いた一致 → 数が同じなら出てきた順、の順に試す。"""
    items = [i for i in (raw if isinstance(raw, list) else []) if isinstance(i, dict)]
    out: dict[str, dict] = {}
    used: set[int] = set()
    for n, heading in enumerate(headings, start=1):
        for k, item in enumerate(items):
            if k in used:
                continue
            if isinstance(item.get("id"), int) and item["id"] == n:
                out[heading] = item
                used.add(k)
                break
    for heading in headings:
        if heading in out:
            continue
        for k, item in enumerate(items):
            if k not in used and isinstance(item.get("match"), str) and item["match"].strip() == heading:
                out[heading] = item
                used.add(k)
                break
    for heading in headings:
        if heading in out:
            continue
        for k, item in enumerate(items):
            if k not in used and _norm_heading(item.get("match")) == _norm_heading(heading) and _norm_heading(heading):
                out[heading] = item
                used.add(k)
                break
    if len(items) == len(headings):
        for heading, (k, item) in zip(headings, enumerate(items)):
            if heading not in out and k not in used:
                out[heading] = item
                used.add(k)
    return out


def assemble_script(
    model: dict | None, steps: list[dict], title: str, summary: str, sections: list[tuple[str, str]] | None = None,
    level: str = "",
) -> tuple[dict, str, list[str]]:
    """モデルの出力を検証して台本にする。不合格の部分は定型の解説で補う。
    戻り値: (台本, source, 注意書き)。source は claude / claude+template / template。"""
    notes: list[str] = []
    model = model or {}
    from_model = 0
    lim = limits_for(level)
    compact = level in LEVELS

    out_steps: list[dict] = []
    seen: set[str] = set()  # 定型の解説で、説明済みの話題（同じ説明の繰り返しを避ける）
    by_step = {}
    for item in model.get("steps") or []:
        if isinstance(item, dict) and isinstance(item.get("step"), int):
            by_step[item["step"]] = item
    for entry in steps:
        n = entry.get("step")
        item = by_step.get(n)
        facts = step_facts(entry)
        step_min = SHORT_STEP_MIN if entry.get("tool") in ("connect_nodes", "delete_node") else STEP_NARRATION_MIN
        pair = clean_narration_pair(item.get("narration"), lim["step"], step_min) if item else None
        if pair:
            from_model += 1
            spoken, shown, added = ensure_target(pair[0], pair[1], facts, lim["step"])
            if added:
                notes.append(f"手順{n}: 解説に対象の名前（ノード・パラメータ）が無かったため、対象を言う文を先頭に足しました")
            template = _template_step(entry, set(), compact)
            purpose = clean_heading(item.get("purpose"))
            out = with_subtitle({
                "step": n,
                "heading": clean_heading(item.get("heading")) or template["heading"],
                "points": _merge_points(facts_points(facts), clean_points(item.get("points")) or template["points"]),
            }, spoken, shown)
            out["source"] = "claude"
        else:
            if item:
                notes.append(f"手順{n}: 解説が基準を満たさなかったため、定型の解説にしました")
            t = _template_step(entry, seen, compact)
            spoken, shown, _added = ensure_target(t["narration"], t["narration"], facts, lim["step"])  # 定型の解説への追加は、注意書きにしない
            purpose = ""
            out = with_subtitle({"step": n, "heading": t["heading"], "points": _merge_points(facts_points(facts), t["points"])}, spoken, shown)
            out["source"] = "template"
        if facts["action"] == "create":
            # 目的の優先順: 手順の記録（houdini_tools が entry["purpose"] に書く。ノードを作った時にモデルが書いた目的）→ 台本のモデルの出力 → 定型文
            purpose = recorded_purpose(entry) or purpose
        if facts["action"] == "create" and not purpose and facts["created"]:
            purpose = _help_purpose(facts["created"][1])
        if facts["action"] != "other":
            out["detail"] = step_detail(facts, purpose)
        out_steps.append(out)

    def section(key: str, max_chars: int, fallback: dict | None) -> dict | None:
        raw = model.get(key) if isinstance(model.get(key), dict) else {}
        pair = clean_narration_pair(raw.get("narration"), max_chars, 20)
        if pair:
            return with_subtitle({"points": clean_points(raw.get("points"))}, *pair)
        if key in ("intro", "outro") and raw:
            notes.append(f"{key}: 基準を満たさなかったため、定型の文にしました")
        return fallback

    intro = section("intro", lim["intro"], _template_intro(title, summary, compact))
    structure = section("structure", lim["structure"], None)
    outro = section("outro", lim["outro"], _template_outro())

    if not model:
        source = "template"
    elif from_model == len(steps):
        source = "claude"
    elif from_model == 0:
        source = "template"
    else:
        source = "claude+template"
    chapters = apply_chapters(model, out_steps)
    script: dict = {"version": SCRIPT_VERSION, "source": source, "title": title, "intro": intro, "steps": out_steps, "outro": outro}
    if chapters:
        script["chapters"] = chapters
    if level in LEVELS:
        script["level"] = level  # どのレベル向けの台本か（動画エンジンは読まない。確認・集計用）
    if structure:
        script["structure"] = structure

    # その他の節（つまずきやすい点・応用のヒントなど）。モデルの言い直しが基準を満たさなければ、定型の文にする。
    out_sections: list[dict] = []
    matched_items = match_sections(model.get("sections"), [h for h, _b in sections or []])
    for heading, _body in sections or []:
        item = matched_items.get(heading)
        pair = clean_narration_pair(item.get("narration"), lim["section"], STEP_NARRATION_MIN) if item else None
        if pair:
            out_sections.append(with_subtitle({
                "match": heading,
                "heading": clean_heading(item.get("heading")) or _template_section(heading)["heading"],
                "points": clean_points(item.get("points")) or _template_section(heading)["points"],
            }, *pair))
        else:
            if item:
                notes.append(f"節「{heading}」: 基準を満たさなかったため、定型の文にしました")
            out_sections.append({"match": heading, **_template_section(heading)})
    if out_sections:
        script["sections"] = out_sections
    script["notes"] = notes[:40]  # 基準を満たさず、定型の文に差し替えた部分（動画の内容を調べるとき用。動画エンジンは読まない）
    return script, source, notes


# ── 入口 ─────────────────────────────────────────────────────────────────

def build_script(
    md_text: str, step_screenshots: list[dict], complete: CompleteFn | None, images: dict | None = None, level: str = ""
) -> tuple[dict | None, str, dict]:
    """台本を作る。戻り値: (台本 or None, 状態の説明, usage)。例外は投げない。
    images（任意）: 動画の説明スライドに使う画像のパス。{"node_diagram": "<ノードの関係図のPNG>"}。
    台本の "images" として書き、動画エンジンが、画像の無いスライド（空のぼやけた板になっていた）に出す。"""
    steps = usable_steps(step_screenshots)
    if not steps:
        return None, "台本: 動画に出る手順が無いため、台本は作りませんでした", {}
    title, summary, excerpt = tutorial_excerpt(md_text)
    sections = extra_sections(md_text)
    level = level if level in LEVELS else level_from_md(md_text)  # 引数が無ければ、.md の difficulty から
    model: dict | None = None
    usage: dict = {}
    detail = ""
    if complete is None:
        detail = "Claudeに接続できないため"
    else:
        for attempt in (1, 2):
            try:
                text, usage = complete(system_prompt(level), build_user_prompt(title, excerpt, steps, sections, level))
                model = parse_model_json(text)
                if model:
                    break
                detail = "Claudeの出力を読み取れなかったため"
            except Exception as exc:  # noqa: BLE001 -- best-effort
                detail = f"Claudeの呼び出しに失敗したため（{str(exc)[:60]}）"
                break
    script, source, notes = assemble_script(model, steps, title, summary, sections, level)
    clean_images = {k: str(v) for k, v in (images or {}).items() if v}
    if clean_images:
        script["images"] = clean_images
    # 参照した情報源。重複（同じ資料の別の断片）を除く。キーは、ギャラリーの metadata.json の rag_sources と同じ
    # （file / namespace / cited / similarity / excerpt）。動画エンジンが、ここから metadata を作れる。
    script["sources"] = dedupe_sources(parse_md_sources(md_text))
    report = check_video_quality(script, steps)
    script["quality"] = {k: report[k] for k in ("ok", "errors", "warnings", "infos")}
    script["quality"]["issues"] = report["issues"][:60]
    label ={"claude": "Claudeが書いた台本", "claude+template": "Claudeの台本（一部は定型の解説）", "template": "定型の解説"}[source]
    message = f"台本: {label}（{len(steps)}手順）"
    if source == "template" and detail:
        message += f" — {detail}"
    if notes:
        message += f" / 注意: {len(notes)}件"
    if report["errors"] or report["warnings"]:
        message += f" / 品質チェック: 要修正{report['errors']}件・注意{report['warnings']}件"
    return script, message, usage


def save_script(path: Path, script: dict) -> None:
    path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_script_file(
    md_path: Path, step_screenshots: list[dict], complete: CompleteFn | None, images: dict | None = None, level: str = ""
) -> tuple[Path | None, str]:
    """保存済みの .md から台本を作り、`<slug>_video_script.json` に書く。戻り値: (パス or None, 状態)。"""
    try:
        md_text = md_path.read_text(encoding="utf-8")
        script, message, usage = build_script(md_text, step_screenshots, complete, images, level)
        if script is None:
            return None, message
        if usage:
            # 台本づくりで使ったトークン（コストの集計用。動画エンジンは読まない）
            script["usage"] = {k: int(v) for k, v in usage.items() if isinstance(v, (int, float))}
        out = md_path.with_name(md_path.stem + "_video_script.json")
        save_script(out, script)
        return out, message
    except Exception as exc:  # noqa: BLE001 -- 台本が作れなくても、従来の動画は作れる
        return None, f"台本: 作成に失敗しました（{exc}）。従来の動画になります"
