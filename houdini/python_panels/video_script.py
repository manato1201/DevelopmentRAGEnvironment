"""
video_script.py — チュートリアル動画の「初心者向け台本」を作る（2026-10-19）

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

SYSTEM_PROMPT = """あなたは、Houdini（フーディニ）の入門講師です。Houdiniを初めて触る人に向けた、解説動画の台本を書きます。

【視聴者】ゲーム開発や3DCGに少し触れたことはあるが、Houdiniは初めて。Houdiniの専門用語は知らない。
【目的】画面に映る操作を「読み上げる」のではなく「説明」する。何をしているか、なぜそうするのか、画面のどこを見ればよいかを、やさしい言葉で伝える。

【手順ごとのナレーションの書き方】
1. 次の順で書く。①と②は必ず入れる。
   ①いま何をするか　②なぜそうするのか（それは何のためのものか）　③画面で見る場所・変わるところ　④つまずきやすい点（あれば）
2. 初めて出てくる用語は、その場で一言で説明する。例:「アトリビュートラングルは、短いプログラムを書いて、点の値をまとめて計算するノードです」。2回目以降は説明しない。
3. コード（VEXなど）は、1行ずつ読まない。「何をするコードか」を、日常のたとえで説明する。変数名・記号・数式は読み上げない。
4. 数字には意味を添える。ただし、与えられた情報から言えることだけにする。
5. 話し言葉の「です・ます」調で、1文は40文字くらいまで。むずかしい漢語は避ける。
6. ナレーションには、英字（アルファベット）を使わない。ノード名・用語はカタカナで書く（例: アトリビュートラングル、スキャッター、ジオメトリ）。数字は算用数字でよい。
7. 画面に出す短い文（points）は、1行30文字くらいまで。ノード名やパラメータ名は、英字のままでよい。コードは入れない。
8. 与えられた手順・値・ノード名にないことは、書かない。分からないことは、書かない。
9. 「それでは始めましょう」のような決まり文句を、手順ごとに繰り返さない。
10. 「その他の節」（つまずきやすい点、応用のヒントなど）は、専門家向けに書かれている。そのまま読まず、初心者が知っておくとよい要点を1〜3つ選び、やさしい言葉で言い直す（2〜4文）。コード・関数名・記号は読み上げない。
11. 本文に「先に知っておく考え方」があるときは、手順の説明でその用語・たとえを使い、考え方と画面の操作を結びつける（「さっきのたとえで言うと、ここが〇〇にあたります」）。
12. 本文の手順に「✅ 確認ポイント」があるときは、その手順（または直前の手順）のナレーションで、「ここで〇〇が見えれば正しいです。見えないときは、△△を確認してください」と、視聴者が自分で確かめられるように伝える。
13. 「パラメータを動かして確かめよう」の節は、「前→後」で話す（「〇〇を△△から□□に変えると、…が変わります」）。数字そのものより、「何がどう変わるか」を伝える。本文にない結果は作らない。

【出力】JSONだけを出力する（前後に説明やコードブロックを付けない）。形式:
{
  "intro": {"narration": "この動画で何を作るか、完成するとどう見えるか、何が身につくかを、はじめての人に向けて話す（3〜5文）", "points": ["作るもの（短く）", "身につくこと（短く）"]},
  "steps": [
    {"step": 手順の番号（入力と同じ数字）, "heading": "手順の見出し（20文字まで。例: スキャッターで点を散らす）",
     "narration": "解説（2〜5文）", "points": ["画面に出す短い文（任意、最大2行）"]}
  ],
  "structure": {"narration": "作ったノード全体の流れを、上から下へ順に説明（2〜3文）", "points": []},
  "sections": [{"match": "その他の節の見出し（入力と同じ文字）", "heading": "見出し（20文字まで。例: つまずきやすいところ）", "narration": "初心者向けの言い直し（2〜4文）", "points": ["要点（短く）"]}],
  "outro": {"narration": "まとめと、次にやってみるとよいこと（2〜3文）", "points": ["次にやってみること（短く）"]}
}
stepsには、入力のすべての手順を、同じ順番で入れること。sectionsには、入力のすべての「その他の節」を入れること（無ければ空の配列）。"""


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
}


def to_katakana(text: str) -> str:
    for term in sorted(READINGS, key=len, reverse=True):
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", READINGS[term], text, flags=re.IGNORECASE)
    return text


def _ascii_letter_ratio(text: str) -> float:
    return sum(1 for c in text if c.isascii() and c.isalpha()) / len(text) if text else 0.0


def clean_narration(raw: object, max_chars: int, min_chars: int = 0) -> str | None:
    """ナレーションとして使える文章に整える。使えないときは None（理由はcheck_narrationで）。"""
    if not isinstance(raw, str):
        return None
    text = re.sub(r"[`*#]+", "", raw)
    text = re.sub(r"\s*\n+\s*", " ", text).strip()
    text = to_katakana(text)
    if len(text) < min_chars or looks_like_code(text):
        return None
    if _ascii_letter_ratio(text) > 0.3:  # 英字だらけ。音声が読めない
        return None
    if len(text) > max_chars:
        # 文の切れ目（。）で切る。切れ目が無いときは使わない。
        cut = text.rfind("。", 0, max_chars)
        if cut < min_chars:
            return None
        text = text[: cut + 1]
    return text


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
_PARAM_RE = re.compile(r"^(\S+) のパラメータを設定: (.+)$")
_PARAM_ONE_RE = re.compile(r"(.+?) を (.+?)(?:、|$)")
_CODE_INPUT_RE = re.compile(r"^(\S+) の「(.+?)」欄に、次のコードを入力する")


def _short(text: str) -> str:
    return text[:POINT_MAX_CHARS] if len(text) <= POINT_MAX_CHARS else text[: POINT_MAX_CHARS - 1] + "…"


def _template_step(entry: dict, seen: set[str] | None = None) -> dict:
    """1手順ぶんの定型の解説。操作文（entry['result']）の最初の行だけを使い、コードは使わない。
    seen: これまでの手順で説明済みの話題。2回目以降は、同じ説明を繰り返さず、短く言う。"""
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
                help_text = _NODE_HELP.get(ntype.lower(), "")
                if help_text:
                    narration += help_text + "。"
            if "tab" not in seen:
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
            "narration": "作業場所になるジオメトリノードを作ります。" + _NODE_HELP["geo"] + "。",
            "points": points,
        }
    if tool == "connect_nodes":
        m = _CONNECT_RE.search(first_line)
        src, dst, nth = (m.group(1), m.group(2), m.group(3).strip()) if m else ("", "", "")
        what = f"{src}の出力を、{dst}につなぎます。" if m else "ノードを線でつなぎます。"
        if m:
            points = [_short(f"{src} → {dst}" + (f"（{nth}入力）" if nth else ""))]
        if nth:
            what = f"{src}の出力を、{dst}の{nth}入力につなぎます。入力が2つ以上あるノードは、つなぐ場所で意味が変わります。"
        if "connect" in seen:
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
        if "param" in seen:
            return {"heading": "パラメータを設定する", "narration": (detail or "もう1つ、設定を変えます。"), "points": points}
        seen.add("param")
        return {
            "heading": "パラメータを設定する",
            "narration": (detail or "ノードの設定を変えます。") + "パラメータは、ノードの動きを決める設定項目です。"
                         "数字を変えると、結果がすぐに変わるので、動かしながら確かめてみてください。",
            "points": points,
        }
    if tool == "cook_node":
        if "cook" in seen:
            return {"heading": "結果を確認する", "narration": "もう一度、クックして、結果を確認します。", "points": ["エラーが出ないか確認する"]}
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


def _template_intro(title: str, summary: str) -> dict:
    first = ""
    if summary:
        sentence = summary.replace("\n", " ").split("。", 1)[0].strip()
        if sentence and not looks_like_code(sentence) and len(sentence) <= 120:
            first = to_katakana(sentence) + "。"
    narration = f"この動画では、「{to_katakana(title)}」を作ります。" if title else "この動画では、チュートリアルの手順を追っていきます。"
    narration += first + "操作を1つずつ、何をしているのかを説明しながら進めるので、はじめての方も、画面を見ながらついてきてください。"
    return {"narration": narration, "points": ([title[:POINT_MAX_CHARS]] if title else [])}


def _template_outro() -> dict:
    return {
        "narration": "お疲れさまでした。これで、一通りの流れができました。"
                     "次は、数字を変えたり、ノードを足したりして、結果がどう変わるかを試してみてください。",
        "points": ["数字を変えて試してみる"],
    }


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


def build_user_prompt(title: str, excerpt: str, steps: list[dict], sections: list[tuple[str, str]] | None = None) -> str:
    lines = []
    for s in steps:
        result = str(s.get("result") or "").strip()
        tool_result = str(s.get("tool_result") or "").strip()
        item = {"step": s.get("step"), "tool": s.get("tool"), "操作": result.split("\n", 1)[0][:200]}
        # コードを入れる手順は、コードそのものは説明の材料としてだけ渡す（読み上げ禁止）
        if "\n" in result or ";" in result or "\n" in tool_result:
            item["コード（説明の材料。読み上げ・転記は禁止）"] = (tool_result or result)[:600]
        lines.append(json.dumps(item, ensure_ascii=False))
    section_block = ""
    if sections:
        section_block = "【その他の節（初心者向けに言い直すこと。matchには見出しをそのまま入れる）】\n" + "\n\n".join(
            f"## {h}\n{b[:900]}" for h, b in sections
        ) + "\n\n"
    return (
        f"【チュートリアルのタイトル】{title}\n\n"
        f"【チュートリアル本文（作った人の下書き。専門家向けの書き方なので、初心者向けに言い直すこと）】\n{excerpt}\n\n"
        f"【動画に出る手順（この順番。stepの数字をそのまま使うこと）】\n" + "\n".join(lines) + "\n\n"
        + section_block + "上のルールに従って、初心者向けの台本をJSONで出力してください。"
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


def assemble_script(
    model: dict | None, steps: list[dict], title: str, summary: str, sections: list[tuple[str, str]] | None = None
) -> tuple[dict, str, list[str]]:
    """モデルの出力を検証して台本にする。不合格の部分は定型の解説で補う。
    戻り値: (台本, source, 注意書き)。source は claude / claude+template / template。"""
    notes: list[str] = []
    model = model or {}
    from_model = 0

    out_steps: list[dict] = []
    seen: set[str] = set()  # 定型の解説で、説明済みの話題（同じ説明の繰り返しを避ける）
    by_step = {}
    for item in model.get("steps") or []:
        if isinstance(item, dict) and isinstance(item.get("step"), int):
            by_step[item["step"]] = item
    for entry in steps:
        n = entry.get("step")
        item = by_step.get(n)
        narration = clean_narration(item.get("narration"), STEP_NARRATION_MAX, STEP_NARRATION_MIN) if item else None
        if narration:
            from_model += 1
            out_steps.append({
                "step": n,
                "heading": clean_heading(item.get("heading")) or _template_step(entry, set())["heading"],
                "narration": narration,
                "points": clean_points(item.get("points")) or _template_step(entry, set())["points"],
            })
        else:
            if item:
                notes.append(f"手順{n}: 解説が基準を満たさなかったため、定型の解説にしました")
            t = _template_step(entry, seen)
            out_steps.append({"step": n, **t})

    def section(key: str, max_chars: int, fallback: dict | None) -> dict | None:
        raw = model.get(key) if isinstance(model.get(key), dict) else {}
        narration = clean_narration(raw.get("narration"), max_chars, 20)
        if narration:
            return {"narration": narration, "points": clean_points(raw.get("points"))}
        if key in ("intro", "outro") and raw:
            notes.append(f"{key}: 基準を満たさなかったため、定型の文にしました")
        return fallback

    intro = section("intro", INTRO_NARRATION_MAX, _template_intro(title, summary))
    structure = section("structure", STRUCTURE_NARRATION_MAX, None)
    outro = section("outro", OUTRO_NARRATION_MAX, _template_outro())

    if not model:
        source = "template"
    elif from_model == len(steps):
        source = "claude"
    elif from_model == 0:
        source = "template"
    else:
        source = "claude+template"
    script: dict = {"version": SCRIPT_VERSION, "source": source, "title": title, "intro": intro, "steps": out_steps, "outro": outro}
    if structure:
        script["structure"] = structure

    # その他の節（つまずきやすい点・応用のヒントなど）。モデルの言い直しが基準を満たさなければ、定型の文にする。
    by_match: dict[str, dict] = {}
    for item in model.get("sections") or []:
        if isinstance(item, dict) and isinstance(item.get("match"), str):
            by_match[item["match"].strip()] = item
    out_sections: list[dict] = []
    for heading, _body in sections or []:
        item = by_match.get(heading)
        narration = clean_narration(item.get("narration"), SECTION_NARRATION_MAX, STEP_NARRATION_MIN) if item else None
        if narration:
            out_sections.append({
                "match": heading,
                "heading": clean_heading(item.get("heading")) or _template_section(heading)["heading"],
                "narration": narration,
                "points": clean_points(item.get("points")) or _template_section(heading)["points"],
            })
        else:
            if item:
                notes.append(f"節「{heading}」: 基準を満たさなかったため、定型の文にしました")
            out_sections.append({"match": heading, **_template_section(heading)})
    if out_sections:
        script["sections"] = out_sections
    return script, source, notes


# ── 入口 ─────────────────────────────────────────────────────────────────

def build_script(
    md_text: str, step_screenshots: list[dict], complete: CompleteFn | None, images: dict | None = None
) -> tuple[dict | None, str, dict]:
    """台本を作る。戻り値: (台本 or None, 状態の説明, usage)。例外は投げない。
    images（任意）: 動画の説明スライドに使う画像のパス。{"node_diagram": "<ノードの関係図のPNG>"}。
    台本の "images" として書き、動画エンジンが、画像の無いスライド（空のぼやけた板になっていた）に出す。"""
    steps = usable_steps(step_screenshots)
    if not steps:
        return None, "台本: 動画に出る手順が無いため、台本は作りませんでした", {}
    title, summary, excerpt = tutorial_excerpt(md_text)
    sections = extra_sections(md_text)
    model: dict | None = None
    usage: dict = {}
    detail = ""
    if complete is None:
        detail = "Claudeに接続できないため"
    else:
        for attempt in (1, 2):
            try:
                text, usage = complete(SYSTEM_PROMPT, build_user_prompt(title, excerpt, steps, sections))
                model = parse_model_json(text)
                if model:
                    break
                detail = "Claudeの出力を読み取れなかったため"
            except Exception as exc:  # noqa: BLE001 -- best-effort
                detail = f"Claudeの呼び出しに失敗したため（{str(exc)[:60]}）"
                break
    script, source, notes = assemble_script(model, steps, title, summary, sections)
    clean_images = {k: str(v) for k, v in (images or {}).items() if v}
    if clean_images:
        script["images"] = clean_images
    label ={"claude": "Claudeが書いた台本", "claude+template": "Claudeの台本（一部は定型の解説）", "template": "定型の解説"}[source]
    message = f"台本: {label}（{len(steps)}手順）"
    if source == "template" and detail:
        message += f" — {detail}"
    if notes:
        message += f" / 注意: {len(notes)}件"
    return script, message, usage


def save_script(path: Path, script: dict) -> None:
    path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_script_file(
    md_path: Path, step_screenshots: list[dict], complete: CompleteFn | None, images: dict | None = None
) -> tuple[Path | None, str]:
    """保存済みの .md から台本を作り、`<slug>_video_script.json` に書く。戻り値: (パス or None, 状態)。"""
    try:
        md_text = md_path.read_text(encoding="utf-8")
        script, message, usage = build_script(md_text, step_screenshots, complete, images)
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
