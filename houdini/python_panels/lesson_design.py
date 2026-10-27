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
MAX_FIELD_CHARS = 200

# basic → applied → advanced は「難しさ」ではなく、1つの学習の道すじ（レッスン1→2→3）として扱う。
LESSON_PATH: dict[str, tuple[str, str]] = {
    "basic": (
        "レッスン1: 「〜とは？」と、最小の作り方",
        "初めて触る人が、このトピックの考え方をつかみ、3〜6ノードの最小構成を自分で作れるようになることが目的です。"
        "最初に「それは何か・何の役に立つか」を説明し、パラメータはほぼ初期値のまま、1つずつ足しては結果を確認してください。"
        "凝った見た目より、「どのノードが何を担当しているか」が分かることを優先します。",
    ),
    "applied": (
        "レッスン2: 動かして理解する（パラメータとコントロール）",
        "レッスン1の最小構成を前提に、パラメータを動かすと何がどう変わるかを体験して理解することが目的です。"
        "効果の大きいパラメータを選んで実際に値を変え、結果の違いを見せてください。"
        "ノイズの重ね掛け・条件による分岐・ランダム化など、見た目を自分でコントロールする技を1〜2個足します。",
    ),
    "advanced": (
        "レッスン3: 実務で使える形にする（再利用・書き出し）",
        "レッスン2までの内容を、仕事で再利用できる形にすることが目的です。"
        "調整したいパラメータを分かりやすくまとめる／バリエーションを出せるようにする／"
        "ゲームエンジンなど外部へ渡すときの注意点を入れる、のうち2つ以上を扱ってください。"
        "VEXや式を使う場合は、1行ずつの解説ではなく「何をするコードか」を先に説明します。",
    ),
}

# 説明の書き方（2026-10-27）。LESSON_PATH は「何を作るか（構成）」の段階、こちらは「どう説明するか（言葉の難しさ・深さ）」の段階。
# 段階が上がるほど、基本用語の説明を省き、専門用語をそのまま使い、「なぜその構成か」へ文字数を使う。
EXPLANATION_STYLE: dict[str, str] = {
    "basic": (
        "【説明の書き方（レッスン1）】\n"
        "- 読者は Houdini を初めて触る人です。専門用語は最小限にし、使うときは初出で（かっこ書きで）短く説明してください。"
        "略語（SOP・VEX・アトリビュートなど）は、先に正式名か意味を書きます。\n"
        "- 各ステップは「何をするか」と「なぜそうするか」を1〜2文で。手順は1ステップ1操作にします。\n"
        "- たとえ話は短く1つまで。数式・コード（VEX・式）は出しません。\n"
        "- 毎ステップ、結果の見え方（ビューポートで何が変わるか）を書いてください。"
    ),
    "applied": (
        "【説明の書き方（レッスン2）】\n"
        "- 読者は基本のノード操作を知っている人です。SOP・パラメータ・ノードの接続などの基本用語は、説明せずに使ってください。\n"
        "- 手順だけでなく、パラメータを変えると何がなぜ変わるか（仕組み）を説明します。値を変える前後の違いを具体的に書いてください。\n"
        "- 新しい専門用語（アトリビュート・パックド・ランプ・ForEach など）は、初出で1文だけ説明します。\n"
        "- 簡単な式やVEXを使うときは、1行ごとの解説ではなく「何をするコードか」を先に書きます。\n"
        "- つまずきやすい点を、1〜2個、先回りして書いてください。"
    ),
    "advanced": (
        "【説明の書き方（レッスン3）】\n"
        "- 読者は実務で使う人です。基本用語（SOP・アトリビュート・ノードの接続など）は説明せず、"
        "専門用語（VEX・HDA・マルチパーム・パックド・キャッシュ・PDG など）をそのまま使ってください。\n"
        "- 「なぜこの構成か」の設計判断、代わりの方法と選ぶ基準、パフォーマンスや再利用性への影響、"
        "ゲームエンジンなど外部へ渡すときの注意を説明します。\n"
        "- 手順の説明は短くし、判断の理由と落とし穴に文字数を使います。VEX・式は「意図 → ハマりどころ → 代替」の順に書きます。\n"
        "- 前のレッスンの内容は繰り返しません。"
    ),
}


def explanation_style(level: str) -> str:
    """段階（basic / applied / advanced）に合わせた、説明の書き方の指示。未知の段階は basic。"""
    return EXPLANATION_STYLE.get(level, EXPLANATION_STYLE["basic"])


PLAN_SYSTEM_PROMPT = """あなたは、Houdini（フーディニ）の解説動画・チュートリアルを作る、経験豊富な講師です。
これから、与えられたトピックの「レッスンの設計」だけを作ります（ノードはまだ組みません）。

【型】プロの解説は、次の順で進みます。この順に沿って設計してください。
  1. 「〜とは？」: 初めての人に、これが何で・何の役に立つかを先に説明する
  2. 考え方: 仕組み全体を、日常のたとえで1つ説明する
  3. 最小構成を作る: 1つずつ足し、各段階で「ここでこう見えれば正しい」を確かめる
  4. パラメータを動かす: 効果が分かりやすいものを選び、値を変えたときの違いを見せる
  5. 仕上げ: 見た目を整える
  6. つまずきやすい点と、次のレッスン

【ルール】
- 視聴者は、3DCGやゲーム開発に少し触れたが、Houdiniは初めての人。専門用語は、初めて出たときに一言で説明する。
- 章（chapters）は3〜6個。1章は「1〜3ノードを足して、結果を確認する」まで。各章に、ノードを足す理由（why）と、確認の方法を入れる。
- 確認は、画面の見た目か、cook_node / inspect_geometry で分かる数値（点の数、範囲、属性の有無）で書く。
- 実験（experiments）は2〜3個。「どのノードのどのパラメータを、どの値からどの値に変えると、何がどう変わるか」を具体的に。
- ノード名・パラメータ名は、確かでないものは書かない（作りながら確認する）。曖昧なら「〇〇を担当するノード」のように役割で書く。
- 与えられた「参考ドキュメント」にある内容を優先し、ないことを断定しない。

【出力】JSONだけを出力する（前後に説明やコードブロックを付けない）。形式:
{
  "goal": "完成したときに何ができているか（1文）",
  "learn": ["このレッスンで身につくこと（2〜4個、短く）"],
  "concepts": [{"term": "用語", "plain": "一言の説明（初心者向け）"}],
  "mental_model": "仕組み全体を日常のたとえで説明（2〜3文）",
  "chapters": [{"title": "章の名前", "why": "なぜこの章が必要か", "build": "足すノード・操作", "checkpoint": "ここで何が見えれば正しいか", "check_with": "viewport または cook_node または inspect_geometry"}],
  "experiments": [{"target": "ノード.パラメータ（役割で書いてもよい）", "change": "値A → 値B", "effect": "何がどう変わるか"}],
  "polish": "仕上げの操作と効果（1〜2文）",
  "mistakes": ["初心者がやりがちな間違いと、見分け方（1〜3個）"],
  "next_lesson": "次のレッスンで学ぶこと（1〜2文）"
}"""


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
    return {
        "version": PLAN_VERSION,
        "goal": _s(raw.get("goal")),
        "learn": _str_list(raw.get("learn"), 60, 4),
        "concepts": concepts,
        "mental_model": _s(raw.get("mental_model"), 400),
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
## 教え方のルール（最優先。ノードを正しく組むだけでは不十分です。「初心者が理解できるレッスン」にすること）
- 作る順: ①考え方を決める → ②最小構成を1〜3ノードずつ足す → ③各段階で確かめる → ④パラメータを動かして効果を見る → ⑤仕上げる。
- 各章（1〜3ノードを足した区切り）の終わりに、cook_node で評価し、inspect_geometry で点の数・範囲・属性などを確かめること。finish_tutorial の steps には、各章の終わりに「✅ 確認ポイント: ここで〇〇（数値や見た目）になっていれば正しい」と書く。
- 手順の各行には、操作だけでなく「なぜそうするか」を書く（例: 「Scatter で点を散らす。後で岩を置く位置になるため」）。用語は初めて出たときに一言で説明する。
- 組み終えて cook が通ったら、効果が分かりやすいパラメータを2〜3個選び、set_parameter で値を変えて cook_node（画面が変わる）→ 結果の違いを観察 → 元の値に戻して再 cook、を実際に行うこと。finish_tutorial の experiments には、実際にやって確かめた結果だけを書く。シミュレーション系など重いノードでは、実験を1個に減らしてよい。
- 仕上げとして、見た目を整える1〜2個の操作（色・密度・大きさ・向き）を行い、polish に書く。
- finish_tutorial では、learn（学ぶこと）/ concepts（用語の説明と、仕組み全体のたとえ）/ experiments / polish / next_lesson も必ず書く。steps と pitfalls は「初心者が再現でき、つまずきを避けられる」粒度で。
- コード（VEXなど）は、1行ずつ解説しない。「何をするコードか」を先に日常のたとえで説明し、そのあと値の意味を説明する。
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
        for i, ch in enumerate(plan["chapters"], start=1):
            tail = f" → 確認: {ch['checkpoint']}（{ch['check_with']}）" if ch["checkpoint"] else ""
            lines.append(f"- 章{i}「{ch['title']}」: {ch['build']}（理由: {ch['why']}）{tail}")
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
            text, usage = complete(PLAN_SYSTEM_PROMPT, prompt)
        except Exception as exc:  # noqa: BLE001 -- best-effort
            return None, f"レッスン設計: 呼び出しに失敗したため、設計なしで続けます（{str(exc)[:60]}）", usage
        plan = validate_plan(parse_plan_json(text))
        if plan:
            n = len(plan["chapters"])
            return plan, f"レッスン設計: {n}章 / 用語{len(plan['concepts'])}個 / 実験{len(plan['experiments'])}個", usage
        detail = "出力を読み取れなかった"
    return None, f"レッスン設計: {detail}ため、設計なしで続けます", usage
