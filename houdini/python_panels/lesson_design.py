"""
lesson_design.py — ノードを組む前に「レッスンの設計」を作る（2026-10-20）

プロの解説（Indyzone / houdini3d / Studio Satsuki 等のチャプター構成）に共通する型:
  「〜とは？」で考え方を先に → 最小構成を作る → 各段階で「こう見えれば正しい」を確認
  → パラメータを動かして効果を見せる → 仕上げ → つまずきやすい点 → 次のレッスン
これまでのエージェントは、いきなりノードを組み始めて、あとから手順を文章にしていた。
そのため文章は「操作の記録」になり、考え方・確認・実験が抜けていた。

ここでは、ツールを使わない1回の呼び出し（TutorialAgent.complete_text）で設計 JSON を作り、
検証して、エージェントのシステムプロンプトに差し込む。失敗しても生成は止めない（設計なしで続ける）。
"""

from __future__ import annotations

import json
import re
from typing import Callable

CompleteFn = Callable[[str, str], "tuple[str, dict]"]

PLAN_VERSION = 1
MAX_CONCEPTS = 4
MAX_CHAPTERS = 6
MAX_EXPERIMENTS = 3
MAX_DECISIONS = 3
MAX_ROADMAP = 8
MAX_FIELD_CHARS = 200

# basic → applied → advanced は、1つの学習の道すじ（レッスン1→2→3）。
# 2026-11-01: 水準を一段ずつ引き上げた。以前のレッスン1（「〜とは？」と最小の作り方）は、使う人にとって低すぎたため、
#   旧レッスン2（動かして理解する）を新レッスン1に、旧レッスン3（実務で使える形）を新レッスン2にし、
#   新レッスン3は「設計を判断する（比較・規模・壊れにくさ）」とした。
# キー名（basic/applied/advanced）は、保存済みのファイル・指標との互換のため変えない。
LESSON_PATH: dict[str, tuple[str, str]] = {
    "basic": (
        "レッスン1: 動かして理解する（仕組みとパラメータ）",
        "Houdiniの基本操作（ノードを置く・つなぐ・パラメータを変える）は分かる人が、このトピックの仕組みを、"
        "パラメータを動かして理解することが目的です。"
        "冒頭の「それは何か」は1〜2文にとどめ、4〜8ノードの構成を、1つずつ足しては確かめてください。"
        "効果の大きいパラメータを選んで実際に値を変え、前と後の違いを数値と見た目で見せます。"
        "ノイズの重ね掛け・条件による分岐・ランダム化など、見た目を自分でコントロールする技を1〜2個足します。",
    ),
    "applied": (
        "レッスン2: 実務で使える形にする（再利用・バリエーション・書き出し）",
        "レッスン1の構成を前提に、仕事で再利用できる形にすることが目的です。"
        "調整したいパラメータをまとめる／バリエーションを出せるようにする／"
        "ゲームエンジンなど外部へ渡すときの注意点を入れる、のうち2つ以上を扱ってください。"
        "「なぜその構成にしたか」を、代わりの方法と比べて示します。"
        "VEXや式を使う場合は、1行ずつの解説ではなく「何をするコードか」を先に説明します。",
    ),
    "advanced": (
        "レッスン3: 設計を判断する（比較・規模・壊れにくさ）",
        "レッスン2までの構成を、「なぜそれを選ぶか」を数値で示せる設計にすることが目的です。"
        "次のうち2つ以上を、実際に試して数値で示してください。"
        "①同じ結果を出す別の構成と並べて比べ、選ぶ基準を示す／"
        "②規模（点数・密度・フレーム数）を上げたときに何が重くなるかを測る／"
        "③極端な値・空の入力・シードの違いでも壊れないかを確かめ、壊れる条件を示す／"
        "④HDAやパイプラインに載せるときの設計（公開するパラメータの絞り込み、アトリビュートの取り決め、受け渡しの形式）。"
        "確かめていない性能の話は断定しません。",
    ),
}

# 説明の書き方（2026-10-27、2026-11-01に一段引き上げ）。LESSON_PATH は「何を作るか（構成）」の段階、こちらは「どう説明するか（言葉の難しさ・深さ）」の段階。
# 段階が上がるほど、基本の説明を省き、専門用語をそのまま使い、「なぜその構成か」「他の方法と何が違うか」へ文字数を使う。
EXPLANATION_STYLE: dict[str, str] = {
    "basic": (
        "【説明の書き方（レッスン1）】\n"
        "- 読者は Houdini の基本操作（ノードを置く・つなぐ・パラメータを変える・ビューポートを見る）を知っている人です。"
        "SOP・パラメータ・ノードの接続などの基本用語は、説明せずに使ってください。\n"
        "- 手順だけでなく、パラメータを変えると何がなぜ変わるか（仕組み）を説明します。値を変える前後の違いを、数値や見た目で具体的に書いてください。\n"
        "- 新しい専門用語（アトリビュート・パックド・ランプ・ForEach など）は、初出で1文だけ説明します。\n"
        "- 簡単な式やVEXを使うときは、1行ごとの解説ではなく「何をするコードか」を先に書きます。\n"
        "- 各ステップは「何をするか」「なぜそうするか」「結果がどう見えるか」を書き、つまずきやすい点を1〜2個、先回りして書いてください。"
    ),
    "applied": (
        "【説明の書き方（レッスン2）】\n"
        "- 読者は仕事で Houdini を使う人です。基本用語（SOP・アトリビュート・ノードの接続など）は説明せず、"
        "専門用語（VEX・HDA・マルチパーム・パックド・キャッシュ・PDG など）をそのまま使ってください。\n"
        "- 「なぜこの構成か」の設計判断を、代わりの方法と選ぶ基準を添えて説明します。"
        "パフォーマンスや再利用性への影響、ゲームエンジンなど外部へ渡すときの注意も入れます。\n"
        "- 手順の説明は短くし、判断の理由と落とし穴に文字数を使います。VEX・式は「意図 → ハマりどころ → 代替」の順に書きます。\n"
        "- finish_tutorial の concepts には、用語の説明ではなく、設計判断（選んだ構成・代わりの方法・選ぶ基準）を書いてください。\n"
        "- 前のレッスンの内容は繰り返しません。"
    ),
    "advanced": (
        "【説明の書き方（レッスン3）】\n"
        "- 読者は複数の案件で Houdini を使ってきた人です。ノードの役割や、レッスン1・2で扱った手法は説明せず、"
        "手順は「ノード名と設定値」だけで簡潔に書きます。\n"
        "- 文字数は、設計の判断・トレードオフ・失敗の条件に使います。"
        "「A案とB案を比べると、〇〇が△△になる。だから□□のときはA案」の形で、選ぶ基準を数値つきで書いてください"
        "（数値は inspect_geometry / try_parameter で実際に得たものだけ）。\n"
        "- 規模を上げたとき・極端な値のとき・他のパイプライン（ゲームエンジン、他のDCC、キャッシュ）へ渡すときに何が起きるか、"
        "壊れる条件と、気づく方法（確認の手段）を説明します。\n"
        "- 一般論ではなく、今回の構成で確かめた根拠を書いてください。確かめていないことは「この環境では確かめていません」と書きます。\n"
        "- finish_tutorial の concepts には設計判断と代替案の比較を、pitfalls には壊れる条件と診断方法を書いてください。\n"
        "- 前のレッスンの内容は繰り返しません。"
    ),
}


def explanation_style(level: str) -> str:
    """段階（basic / applied / advanced）に合わせた、説明の書き方の指示。未知の段階は basic。"""
    return EXPLANATION_STYLE.get(level, EXPLANATION_STYLE["basic"])


_PLAN_TEMPLATE = """あなたは、Houdini（フーディニ）の解説動画・チュートリアルを作る、経験豊富な講師です。
これから、与えられたトピックの「レッスンの設計」だけを作ります（ノードはまだ組みません）。

【型】プロの解説は、次の順で進みます。この順に沿って設計してください。
@@FLOW@@

【ルール】
- @@READER@@
- 章（chapters）は3〜6個。1章は「1〜3ノードを足して、結果を確認する」まで。各章に、ノードを足す理由（why）と、確認の方法を入れる。
- 確認は、画面の見た目か、cook_node / inspect_geometry で分かる数値（点の数、範囲、属性の有無）で書く。
- 実験（experiments）は2〜3個。「どのノードのどのパラメータを、どの値からどの値に変えると、何がどう変わるか」を具体的に。
- @@DECISIONS@@
- 読む前の準備を設計に入れる。前提（prerequisites）は、読者が持っているべき知識と用意するもの。場面（use_cases）は、読む人が「自分の仕事のここで使える」と分かる具体例。段取り（roadmap）は、使うノードを使う順に並べ、各ノードで何ができるか。
- 読んだあとの手がかりも入れる。TIPS（tips）は、確かめ方（Geometry Spreadsheetで属性を見る等）や、うまくいかないときに効いている要素を1つずつ切って原因を探す方法。挑戦（challenge）は、結果の条件だけを書く。
- ノード名・パラメータ名は、確かでないものは書かない（作りながら確認する）。曖昧なら「〇〇を担当するノード」のように役割で書く。
- 与えられた「参考ドキュメント」にある内容を優先し、ないことを断定しない。

【出力】JSONだけを出力する（前後に説明やコードブロックを付けない）。形式:
{
  "goal": "完成したときに何ができているか（1文）",
  "learn": ["このレッスンで身につくこと（2〜4個、短く）"],
  "concepts": [{"term": "用語", "plain": "一言の説明"}],
  "mental_model": "仕組み全体の見取り図（2〜3文。レッスン1は日常のたとえ、レッスン2・3は設計の要点）",
  "decisions": [{"choice": "選ぶ構成", "alternative": "代わりの方法", "criterion": "選ぶ基準（できれば数値で確かめられる形）"}],
  "prerequisites": ["前提条件（2〜4個）: この水準の読者が知っているべきこと、Houdiniのバージョン、用意するもの。最後に「知っている人は〇章から」「分からなければ先に△△」"],
  "use_cases": ["どんな場面で使うか（2〜3個）: 「〇〇のとき、これを使う」の形で、ゲーム・映像などの具体的な場面"],
  "roadmap": [{"node": "使うノード（役割で書いてもよい）", "does": "このノードで何ができるか（1行）"}],
  "tips": ["TIPS（3〜5個）: 作業が楽になるコツ、確かめ方、うまくいかないときの切り分け方"],
  "challenge": "自分でやってみよう: 手本を見ずに作る課題。やり方ではなく「結果の条件」だけを書く（1〜2文）",
  "chapters": [{"title": "章の名前", "why": "なぜこの章が必要か", "build": "足すノード・操作", "checkpoint": "ここで何が見えれば正しいか", "check_with": "viewport または cook_node または inspect_geometry"}],
  "experiments": [{"target": "ノード.パラメータ（役割で書いてもよい）", "change": "値A → 値B", "effect": "何がどう変わるか"}],
  "polish": "仕上げの操作と効果（1〜2文）",
  "mistakes": ["この水準の読者がやりがちな間違いと、見分け方（1〜3個）"],
  "next_lesson": "次のレッスンで学ぶこと（1〜2文）"
}"""

_PLAN_READER: dict[str, str] = {
    "basic": "視聴者は、Houdiniの基本操作は分かるが、このトピックの仕組みは知らない人。基本用語は説明しない。新しい専門用語は、初めて出たときに一言で説明する。",
    "applied": "視聴者は、仕事でHoudiniを使う人。基本用語は説明しない。構成の「なぜ」を、代わりの方法と選ぶ基準つきで設計する。",
    "advanced": "視聴者は、複数の案件でHoudiniを使ってきた人。手法そのものの説明は省き、比較・規模・壊れる条件・パイプラインへの載せ方を中心に設計する。",
}

_PLAN_FLOW: dict[str, str] = {
    "basic": (
        "  1. 位置づけ: 何の仕組みを、なぜ動かして理解するのかを、1〜2文で示す\n"
        "  2. 考え方: 仕組み全体を、日常のたとえで1つ説明する\n"
        "  3. 構成を作る: 1つずつ足し、各段階で「ここでこう見えれば正しい」を確かめる\n"
        "  4. パラメータを動かす: 効果が分かりやすいものを選び、値を変えたときの違いを見せる\n"
        "  5. 仕上げ: 見た目を整える\n"
        "  6. つまずきやすい点と、次のレッスン"
    ),
    "applied": (
        "  1. 位置づけ: レッスン1の構成を、どう再利用できる形にするのかを示す\n"
        "  2. 設計判断: なぜその構成か。代わりの方法と、選ぶ基準を示す\n"
        "  3. 構成を整える: パラメータをまとめる・バリエーションを出す・外部へ渡す形にする、を1つずつ確かめる\n"
        "  4. パラメータを動かす: バリエーションを出すときに効くものを選び、違いを見せる\n"
        "  5. 仕上げ: 見た目と使いやすさを整える\n"
        "  6. 落とし穴と、次のレッスン"
    ),
    "advanced": (
        "  1. 位置づけ: 何を比べ、何を測るのかを示す\n"
        "  2. 比べる: 同じ結果を出す別の構成を並べ、選ぶ基準を決める\n"
        "  3. 測る: 規模（点数・密度・フレーム数）を上げたとき、何が重くなるかを数値で見る\n"
        "  4. 壊す: 極端な値・空の入力・シードの違いで、壊れる条件を探す\n"
        "  5. 載せる: HDAやパイプラインに載せるときの設計（公開するパラメータ・アトリビュートの取り決め・受け渡しの形式）\n"
        "  6. 判断のまとめと、次のレッスン"
    ),
}

_PLAN_DECISIONS: dict[str, str] = {
    "basic": "判断（decisions）は、必要なときだけ0〜1個。空の配列でもよい。",
    "applied": "判断（decisions）は1〜3個。「選ぶ構成・代わりの方法・選ぶ基準」を書く。",
    "advanced": "判断（decisions）は2〜3個。選ぶ基準は、実験で数値を取って確かめられる形で書く（点の数、cookの結果、範囲など）。",
}


def plan_system_prompt(level: str) -> str:
    """設計用のシステムプロンプト。段階（basic / applied / advanced）に合わせて、視聴者・型・判断の数を切り替える。未知の段階は basic。"""
    key = level if level in _PLAN_READER else "basic"
    return (
        _PLAN_TEMPLATE.replace("@@FLOW@@", _PLAN_FLOW[key])
        .replace("@@READER@@", _PLAN_READER[key])
        .replace("@@DECISIONS@@", _PLAN_DECISIONS[key])
    )


PLAN_SYSTEM_PROMPT = plan_system_prompt("basic")  # 互換用（段階を指定しない呼び出し）


# ── 入力・検証 ─────────────────────────────────────────────────────────────

def build_plan_prompt(
    topic: str,
    level: str,
    requirements: str = "",
    rag_texts: list[str] | None = None,
    prior_level_summary: str = "",
    has_reference_images: bool = False,
    target_model_name: str = "",
) -> str:
    title, role = LESSON_PATH.get(level, LESSON_PATH["basic"])
    parts = [f"【トピック】{topic}", f"【このレッスンの位置づけ】{title}\n{role}", explanation_style(level)]
    if requirements:
        parts.append(f"【必須条件（最優先）】{requirements[:600]}")
    if target_model_name:
        parts.append(f"【使うモデル】{target_model_name}（これを読み込んで使うレッスンにすること）")
    if has_reference_images:
        parts.append("【参考画像】完成イメージの参考画像が添付されています（設計では、見た目の目標として扱う）。")
    if prior_level_summary:
        parts.append(f"【前のレッスンの要約（ここまでは説明済み。繰り返さず、一段深める）】\n{prior_level_summary[:1200]}")
    if rag_texts:
        docs = "\n\n".join(f"[{i}] {t[:700]}" for i, t in enumerate(rag_texts[:5], start=1))
        parts.append(f"【参考ドキュメント（抜粋）】\n{docs}")
    parts.append("上のルールに従って、レッスンの設計をJSONで出力してください。")
    return "\n\n".join(parts)


def parse_plan_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _s(value: object, limit: int = MAX_FIELD_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _str_list(raw: object, limit: int, max_items: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [t for t in (_s(x, limit) for x in raw) if t][:max_items]


def validate_plan(raw: dict | None) -> dict | None:
    """設計を検証して整える。章が2つ未満など、レッスンとして成り立たないときは None。"""
    if not raw:
        return None
    chapters = []
    for item in (raw.get("chapters") or [])[:MAX_CHAPTERS]:
        if not isinstance(item, dict):
            continue
        chapter = {
            "title": _s(item.get("title"), 40),
            "why": _s(item.get("why")),
            "build": _s(item.get("build")),
            "checkpoint": _s(item.get("checkpoint")),
            "check_with": _s(item.get("check_with"), 30),
        }
        if chapter["title"] and (chapter["build"] or chapter["why"]):
            chapters.append(chapter)
    if len(chapters) < 2:
        return None
    concepts = []
    for item in (raw.get("concepts") or [])[:MAX_CONCEPTS]:
        if isinstance(item, dict) and _s(item.get("term"), 40) and _s(item.get("plain")):
            concepts.append({"term": _s(item.get("term"), 40), "plain": _s(item.get("plain"))})
    experiments = []
    for item in (raw.get("experiments") or [])[:MAX_EXPERIMENTS]:
        if isinstance(item, dict) and _s(item.get("target")) and _s(item.get("effect")):
            experiments.append({
                "target": _s(item.get("target")),
                "change": _s(item.get("change")),
                "effect": _s(item.get("effect")),
            })
    decisions = []
    for item in (raw.get("decisions") or [])[:MAX_DECISIONS]:
        if isinstance(item, dict) and _s(item.get("choice")) and (_s(item.get("alternative")) or _s(item.get("criterion"))):
            decisions.append({
                "choice": _s(item.get("choice")),
                "alternative": _s(item.get("alternative")),
                "criterion": _s(item.get("criterion")),
            })
    roadmap = []
    for item in (raw.get("roadmap") or [])[:MAX_ROADMAP]:
        if isinstance(item, dict) and _s(item.get("node"), 60) and _s(item.get("does")):
            roadmap.append({"node": _s(item.get("node"), 60), "does": _s(item.get("does"))})
    return {
        "version": PLAN_VERSION,
        "goal": _s(raw.get("goal")),
        "learn": _str_list(raw.get("learn"), 60, 4),
        "concepts": concepts,
        "mental_model": _s(raw.get("mental_model"), 400),
        "decisions": decisions,
        "prerequisites": _str_list(raw.get("prerequisites"), 160, 4),
        "use_cases": _str_list(raw.get("use_cases"), 140, 3),
        "roadmap": roadmap,
        "tips": _str_list(raw.get("tips"), 160, 5),
        "challenge": _s(raw.get("challenge"), 300),
        "chapters": chapters,
        "experiments": experiments,
        "polish": _s(raw.get("polish")),
        "mistakes": _str_list(raw.get("mistakes"), 140, 3),
        "next_lesson": _s(raw.get("next_lesson")),
    }


# ── 差し込み・書き戻し ─────────────────────────────────────────────────────

def level_section(level: str) -> tuple[str, str]:
    """(見出し, 指示)。未知のレベルは basic 扱い。"""
    return LESSON_PATH.get(level, LESSON_PATH["basic"])


TEACHING_RULES = """
## 教え方のルール（最優先。ノードを正しく組むだけでは不十分です。「読者が理解できるレッスン」にすること。読者の水準は、上の「説明の書き方」に従う）
- 作る順: ①考え方を決める → ②最小構成を1〜3ノードずつ足す → ③各段階で確かめる → ④パラメータを動かして効果を見る → ⑤仕上げる。
- 各章（1〜3ノードを足した区切り）の終わりに、cook_node で評価し、inspect_geometry で点の数・範囲・属性などを確かめること。finish_tutorial の steps には、各章の終わりに「✅ 確認ポイント: ここで〇〇（数値や見た目）になっていれば正しい」と書く。
- 手順の各行には、操作だけでなく「なぜそうするか」を書く（例: 「Scatter で点を散らす。後で岩を置く位置になるため」）。新しい専門用語は初めて出たときに一言で説明する（基本用語は、水準に応じて説明しない）。
- 組み終えて cook が通ったら、効果が分かりやすいパラメータを2〜3個選び、try_parameter で値を並べて試す（結果が数値の表で返り、元の値に戻る）。式・ランプ・シミュレーション系など try_parameter が使えないものは、set_parameter で値を変えて cook_node（画面が変わる）→ 結果の違いを観察 → 元の値に戻して再 cook、を実際に行うこと。finish_tutorial の experiments には、実際にやって確かめた結果だけを書く。シミュレーション系など重いノードでは、実験を1個に減らしてよい。
- 仕上げとして、見た目を整える1〜2個の操作（色・密度・大きさ・向き）を行い、polish に書く。
- finish_tutorial では、learn（学ぶこと）/ concepts（用語の説明と、仕組み全体のたとえ）/ experiments / polish / next_lesson も必ず書く。
- 読む前に分かるように、prerequisites（前提条件: 対象の読者・前提知識・Houdiniのバージョン・用意するもの。「知っている人は〇から読む」「分からなければ先に△△」も）、use_cases（どんな場面で使うか: 「〇〇のとき、これを使う」を2〜3個）、roadmap（作る前に: 使うノードを使う順に並べ、各ノードで何ができるかを1行ずつ）も必ず書く。
- 読んだあとに自分でできるように、tips（TIPS: 作業が楽になるコツ・確かめ方・うまくいかないときの切り分け方を3〜5個。確かめたことだけ）と、challenge（自分でやってみよう: 手本を見ずに作る課題。やり方ではなく「結果の条件」だけ。例: 「点が500個以上あり、〇〇属性がある」）も必ず書く。steps と pitfalls は「読者が再現でき、つまずきを避けられる」粒度で。
- コード（VEXなど）は、1行ずつ解説しない。「何をするコードか」を先に説明し（レッスン1は日常のたとえで）、そのあと値の意味や落とし穴を説明する。
- finish_tutorial の直後の画像で、作ったものが見えない・枠だけ・空に見える場合は、confirm_tutorial を looks_correct=false にして、見える形に直す（動画の最初の画面になる）。note に「見えていない」と書きながら looks_correct=true にしない。ボリューム（煙・炎）は、ビューポートで枠だけに見えることがあるので、メッシュ化・ポイント化・可視化のノードで見せる。
- 確かめていないことは書かない。分からないことは「この環境では確かめていません」と書く。
"""


def plan_section(plan: dict | None, level: str) -> str:
    """システムプロンプトに差し込む節（設計があれば章立てつき。無くても教え方のルールは入る）。"""
    title, role = level_section(level)
    lines = [f"\n## このレッスンの位置づけ\n{title}\n{role}"]
    if plan:
        lines.append("\n## レッスンの設計（この設計に沿って組み立て、教えること。作りながら不都合があれば直してよい）")
        if plan["goal"]:
            lines.append(f"- 完成の姿: {plan['goal']}")
        if plan["learn"]:
            lines.append("- 身につくこと: " + " / ".join(plan["learn"]))
        for c in plan["concepts"]:
            lines.append(f"- 用語「{c['term']}」: {c['plain']}")
        if plan["mental_model"]:
            lines.append(f"- 仕組みのたとえ: {plan['mental_model']}")
        for text in plan.get("prerequisites", []):
            lines.append(f"- 前提条件: {text}")
        for text in plan.get("use_cases", []):
            lines.append(f"- 使う場面: {text}")
        for r in plan.get("roadmap", []):
            lines.append(f"- 段取り（使うノード）: {r['node']} … {r['does']}")
        for d in plan.get("decisions", []):
            lines.append(f"- 設計判断: {d['choice']}（代わりの方法: {d['alternative'] or '—'} / 選ぶ基準: {d['criterion'] or '—'}）")
        for i, ch in enumerate(plan["chapters"], start=1):
            tail = f" → 確認: {ch['checkpoint']}（{ch['check_with']}）" if ch["checkpoint"] else ""
            lines.append(f"- 章{i}「{ch['title']}」: {ch['build']}（理由: {ch['why']}）{tail}")
        for text in plan.get("tips", []):
            lines.append(f"- TIPS: {text}")
        if plan.get("challenge"):
            lines.append(f"- 自分でやってみよう: {plan['challenge']}")
        for e in plan["experiments"]:
            lines.append(f"- 実験の候補: {e['target']} を {e['change']} → {e['effect']}")
        if plan["polish"]:
            lines.append(f"- 仕上げ: {plan['polish']}")
        for m in plan["mistakes"]:
            lines.append(f"- つまずきやすい点: {m}")
        if plan["next_lesson"]:
            lines.append(f"- 次のレッスン: {plan['next_lesson']}")
    lines.append(TEACHING_RULES)
    return "\n".join(lines)


def fallback_fields(plan: dict | None) -> dict[str, str]:
    """モデルが finish_tutorial に書かなかったレッスン用の項目を、設計で補う（確かめていない旨を添える）。"""
    if not plan:
        return {}
    out: dict[str, str] = {}
    if plan["learn"]:
        out["learn"] = "\n".join(f"- {t}" for t in plan["learn"])
    concepts = [f"- **{c['term']}**: {c['plain']}" for c in plan["concepts"]]
    if plan["mental_model"]:
        concepts.append(f"- **仕組みのたとえ**: {plan['mental_model']}")
    for d in plan.get("decisions", []):
        concepts.append(f"- **設計判断**: {d['choice']}（代わりの方法: {d['alternative'] or '—'} / 選ぶ基準: {d['criterion'] or '—'}）")
    if concepts:
        out["concepts"] = "\n".join(concepts)
    if plan["experiments"]:
        out["experiments"] = (
            "（設計段階の予想です。この生成の中では実際に動かして確かめられなかったため、ご自身で試して確認してください）\n"
            + "\n".join(f"- {e['target']}: {e['change']} → {e['effect']}" for e in plan["experiments"])
        )
    if plan["polish"]:
        out["polish"] = plan["polish"]
    if plan["next_lesson"]:
        out["next_lesson"] = plan["next_lesson"]
    if plan.get("prerequisites"):
        out["prerequisites"] = "\n".join(f"- {t}" for t in plan["prerequisites"])
    if plan.get("use_cases"):
        out["use_cases"] = "\n".join(f"- {t}" for t in plan["use_cases"])
    if plan.get("roadmap"):
        out["roadmap"] = "\n".join(f"{i}. **{r['node']}**: {r['does']}" for i, r in enumerate(plan["roadmap"], start=1))
    if plan.get("tips"):
        out["tips"] = "\n".join(f"- {t}" for t in plan["tips"])
    if plan.get("challenge"):
        out["challenge"] = plan["challenge"]
    return out


# ── 入口 ─────────────────────────────────────────────────────────────────

def design_lesson(
    complete: CompleteFn | None,
    topic: str,
    level: str,
    requirements: str = "",
    rag_texts: list[str] | None = None,
    prior_level_summary: str = "",
    has_reference_images: bool = False,
    target_model_name: str = "",
) -> tuple[dict | None, str, dict]:
    """設計を作る。戻り値: (設計 or None, 状態の説明, usage)。例外は投げない（失敗しても生成は続く）。"""
    if complete is None:
        return None, "レッスン設計: Claudeに接続できないため、設計なしで続けます", {}
    prompt = build_plan_prompt(
        topic, level, requirements, rag_texts, prior_level_summary, has_reference_images, target_model_name
    )
    usage: dict = {}
    detail = ""
    for _attempt in (1, 2):
        try:
            text, usage = complete(plan_system_prompt(level), prompt)
        except Exception as exc:  # noqa: BLE001 -- best-effort
            return None, f"レッスン設計: 呼び出しに失敗したため、設計なしで続けます（{str(exc)[:60]}）", usage
        plan = validate_plan(parse_plan_json(text))
        if plan:
            n = len(plan["chapters"])
            return plan, f"レッスン設計: {n}章 / 用語{len(plan['concepts'])}個 / 実験{len(plan['experiments'])}個", usage
        detail = "出力を読み取れなかった"
    return None, f"レッスン設計: {detail}ため、設計なしで続けます", usage
