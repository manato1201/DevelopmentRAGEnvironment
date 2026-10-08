"""
tutorial_feedback.py — チュートリアル生成への評価（good/bad）と、そこからの「学習」

2026-10-05追加。生成物（localRAG/tutorials/<名前>.md）の隣に、次の2つのサイドカーを置く:

  <名前>_metrics.json   生成時に自動で記録する品質指標（反復回数・コスト・cookエラー数・領域など）。
                        人手の評価が無くても、モデル・レベル・領域別の傾向を集計できる。
  <名前>_feedback.json  ユーザーが付けた評価（rating: 1=良い / -1=悪い、理由タグ、一言メモ）。

評価は「モデルの重みを学習させる」ものではなく、次の3つの形でプロンプトと設定選びに反映する:
  1. 集計（format_report）: モデル・レベル・領域・理由タグ別の好評率と平均コスト等。どの設定が良いかを
     自分のデータで決める。
  2. 教訓（tutorial_lessons.json）: 低評価のメモから「避けること」を数行にまとめ、ユーザーが承認した
     ものだけをシステムプロンプトに入れる。生の失敗例をそのまま渡すとモデルが真似るため、要約した
     ルールの形にする。
  3. 成功例（select_good_examples）: 似たトピックで高評価だったチュートリアルの構成を参考として渡す。

評価はCloudflare Worker（/tutorial-feedback/submit）にも送れる。閲覧・集計は管理者だけ
（cloudflare-rag-poc/src/tutorialFeedback.ts）。このモジュールはQtにもhouに依存しない。
"""

from __future__ import annotations

import datetime
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

_HTTP_USER_AGENT = "HoudiniTutorialAgent/1.0 (+cloudflare-rag-poc)"

# 理由タグ（先頭5つが好評の理由、残りが不評の理由）。UIの選択肢。自由記述はメモ欄に書く。
GOOD_TAGS = ("形が合っている", "手順が分かりやすい", "ノード構成が良い", "条件を守っている", "動画が良い")
BAD_TAGS = ("形が違う", "ノードが多すぎる", "手順が分かりにくい", "エラー・動かない", "条件を守っていない", "動画が悪い", "内容が浅い")
FEEDBACK_TAGS = GOOD_TAGS + BAD_TAGS

MAX_APPROVED_LESSONS = 10   # プロンプトに入れる教訓の最大数（肥大化防止）
MAX_LESSON_CHARS = 120
MAX_GOOD_EXAMPLES = 2

# Cloudflareへ送る自動指標（数値・真偽・短い文字列だけ。Worker側のsanitizeMetricsと同じ方針）。
_UPLOAD_METRIC_KEYS = (
    "iterations", "cost_usd", "cook_calls", "cook_errors", "tool_calls", "node_count", "elapsed_seconds",
    "completed", "used_unconfirmed_draft", "rag_extraction_rate", "input_tokens", "output_tokens",
    "domain", "confirm_rejections", "reference_images", "has_requirements", "has_target_model",
)


# ─── パス・JSON ──────────────────────────────────────────────────────────────────

def feedback_path(md_path: Path) -> Path:
    return md_path.with_name(md_path.stem + "_feedback.json")


def metrics_path(md_path: Path) -> Path:
    return md_path.with_name(md_path.stem + "_metrics.json")


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data) -> bool:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def read_frontmatter(md_path: Path) -> dict[str, str]:
    """frontmatter（先頭の --- で囲まれた key: value）を軽く読む。失敗したら空dict。"""
    result: dict[str, str] = {}
    try:
        with md_path.open("r", encoding="utf-8") as f:
            if f.readline().strip() != "---":
                return result
            for line in f:
                line = line.rstrip("\n")
                if line.strip() == "---":
                    break
                if ":" in line:
                    key, _, value = line.partition(":")
                    result[key.strip()] = value.strip().strip('"')
    except OSError:
        pass
    return result


def read_overview(md_path: Path, limit: int = 600) -> str:
    """「## 概要」節の本文（先頭 limit 文字）。"""
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r"^## 概要\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1).strip()[:limit] if match else ""


def node_types_of(md_path: Path) -> list[str]:
    """同名 .json（ノードグラフ）に含まれるノードタイプ名（重複なし・出現順）。"""
    graph = _read_json(md_path.with_suffix(".json"))
    if not isinstance(graph, dict):
        return []
    seen: dict[str, None] = {}
    for node in graph.get("nodes", []):
        kind = node.get("kind")
        if kind:
            seen[kind] = None
    return list(seen)


# ─── 領域の判定（集計の軸） ──────────────────────────────────────────────────────

_DOMAIN_TOPIC_PATTERNS = (
    ("gsplat", re.compile(r"gaussian|gsplat|splat|3dgs|ガウシアン|スプラット|スプラッド", re.I)),
    ("animation", re.compile(r"animat|アニメ|\brig(ging)?\b|リグ|skelet|スケルトン|kinefx|\bapex\b|キーフレーム|keyframe|モーション|ボーン", re.I)),
    ("particles", re.compile(r"particle|パーティクル|粒子|\bpop", re.I)),
    # 「布」だけは入れない（「散布」に一致してしまう）。クロスは「クロス」「cloth」で拾う。
    ("simulation", re.compile(r"pyro|fire|smoke|flip|cloth|vellum|rbd|シミュレーション|流体|煙|炎|クロス|パイロ", re.I)),
    ("copernicus", re.compile(r"copernicus|コペルニクス|\bcop\b", re.I)),
    ("solaris", re.compile(r"solaris|karma|\blop\b|usd", re.I)),
    ("material", re.compile(r"material|マテリアル|shader|シェーダー", re.I)),
    ("uv", re.compile(r"\buv\b", re.I)),
)


def detect_domain(topic: str, requirements: str = "", node_types: list[str] | tuple[str, ...] = ()) -> str:
    """トピック・条件・使ったノードから領域名を決める。集計の軸にするだけなので大づかみで良い。"""
    kinds = set(node_types)
    if kinds & {"bakegsplat", "rasterizegsplats"}:
        return "gsplat"
    if any(k.startswith(("kinefx::", "apex::")) for k in kinds):
        return "animation"
    if any(k.startswith("pop") or k == "popnet" for k in kinds):
        return "particles"
    if kinds & {"pyrosolver::2.0", "pyrosolver", "vellumsolver", "rbdsolver", "flipsolver", "dopnet"}:
        return "simulation"
    if "copnet" in kinds:
        return "copernicus"
    if "lopnet" in kinds:
        return "solaris"
    text = f"{topic}\n{requirements}"
    for name, pattern in _DOMAIN_TOPIC_PATTERNS:
        if pattern.search(text):
            return name
    if kinds & {"matnet", "material", "materiallibrary"}:
        return "material"
    if kinds & {"uvunwrap", "uvlayout", "uvlayout::3.0", "uvproject"}:
        return "uv"
    return "general"


# ─── 自動指標 ────────────────────────────────────────────────────────────────────

def write_metrics(md_path: Path, metrics: dict) -> bool:
    return _write_json(metrics_path(md_path), metrics)


def read_metrics(md_path: Path) -> dict:
    data = _read_json(metrics_path(md_path))
    return data if isinstance(data, dict) else {}


# ─── 評価 ────────────────────────────────────────────────────────────────────────

def read_feedback(md_path: Path) -> dict | None:
    data = _read_json(feedback_path(md_path))
    return data if isinstance(data, dict) and data.get("rating") in (1, -1) else None


def save_feedback(md_path: Path, rating: int, tags: list[str], note: str) -> dict | None:
    """評価を保存して、保存した内容（アップロードにも使う）を返す。rating=0は取り消し（Noneを返す）。"""
    path = feedback_path(md_path)
    if rating == 0:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    frontmatter = read_frontmatter(md_path)
    metrics = read_metrics(md_path)
    entry = {
        "rating": 1 if rating > 0 else -1,
        "tags": [t for t in dict.fromkeys(tags) if t][:10],
        "note": (note or "").strip()[:2000],
        "rated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        # 後から「どの設定の何を評価したか」を辿れるよう、評価時点の情報を写しておく
        "title": frontmatter.get("title") or md_path.stem,
        "topic": str(metrics.get("topic") or "")[:300],
        "level": frontmatter.get("difficulty", ""),
        "model": str(metrics.get("model") or ""),
        "rag_name": str(metrics.get("rag_name") or ""),
        "houdini_version": str(metrics.get("houdini_version") or ""),
        "overview": read_overview(md_path),
        "node_types": node_types_of(md_path)[:40],
    }
    return entry if _write_json(path, entry) else None


def build_upload_payload(md_path: Path, entry: dict) -> dict:
    """Cloudflare /tutorial-feedback/submit のボディ。本文は送らない（題名・概要の抜粋・指標だけ）。"""
    metrics = read_metrics(md_path)
    return {
        "tutorialKey": md_path.stem,
        "title": entry.get("title", ""),
        "topic": entry.get("topic", ""),
        "level": entry.get("level", ""),
        "model": entry.get("model", ""),
        "ragName": entry.get("rag_name", ""),
        "houdiniVersion": entry.get("houdini_version", ""),
        "rating": entry.get("rating", 0),
        "tags": entry.get("tags", []),
        "note": entry.get("note", ""),
        "overview": entry.get("overview", ""),
        "metrics": {k: metrics[k] for k in _UPLOAD_METRIC_KEYS if k in metrics},
    }


def upload_feedback(cf_url: str, cf_api_key: str, payload: dict, timeout: int = 15) -> tuple[bool, str]:
    """評価をCloudflareへ送る（ベストエフォート）。戻り値は (成功したか, 表示用メッセージ)。"""
    if not cf_url or not cf_api_key:
        return False, "Cloudflare未設定のため送信しませんでした（ローカルには保存済み）"
    request = urllib.request.Request(
        f"{cf_url.rstrip('/')}/tutorial-feedback/submit",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cf_api_key}",
            "User-Agent": _HTTP_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
        return True, "Cloudflareへ送信しました"
    except urllib.error.HTTPError as exc:
        return False, f"Cloudflareへの送信に失敗（HTTP {exc.code}）。ローカルには保存済み"
    except Exception as exc:  # noqa: BLE001 -- 送信失敗で評価そのものは失わない
        return False, f"Cloudflareへの送信に失敗: {exc}。ローカルには保存済み"


# ─── 一覧と集計 ──────────────────────────────────────────────────────────────────

def list_entries(tutorials_dir: Path) -> list[dict]:
    """保存済みチュートリアルごとに、frontmatter・自動指標・評価をまとめたdictを返す。"""
    entries: list[dict] = []
    if not tutorials_dir.exists():
        return entries
    for md in sorted(tutorials_dir.glob("*.md")):
        frontmatter = read_frontmatter(md)
        metrics = read_metrics(md)
        feedback = read_feedback(md) or {}
        entries.append({
            "key": md.stem,
            "path": str(md),
            "title": frontmatter.get("title") or md.stem,
            "level": frontmatter.get("difficulty", ""),
            "model": str(metrics.get("model") or ""),
            "domain": str(metrics.get("domain") or ""),
            "metrics": metrics,
            "rating": feedback.get("rating", 0),
            "tags": feedback.get("tags", []),
            "note": feedback.get("note", ""),
            "status": frontmatter.get("status", ""),
        })
    return entries


def _avg(entries: list[dict], key: str) -> float | None:
    values = [e["metrics"][key] for e in entries if isinstance(e["metrics"].get(key), (int, float))]
    return sum(values) / len(values) if values else None


def summarize(entries: list[dict], keys_of: Callable[[dict], list[str]]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        for key in keys_of(entry):
            groups.setdefault(key or "（不明）", []).append(entry)
    rows = []
    for key, items in groups.items():
        good = sum(1 for e in items if e["rating"] == 1)
        bad = sum(1 for e in items if e["rating"] == -1)
        with_metrics = [e for e in items if e["metrics"]]
        aborted = sum(1 for e in with_metrics if e["metrics"].get("completed") is False)
        rows.append({
            "key": key, "total": len(items), "good": good, "bad": bad,
            "good_rate": good / (good + bad) if good + bad else None,
            "avg_iterations": _avg(with_metrics, "iterations"),
            "avg_cost": _avg(with_metrics, "cost_usd"),
            "avg_cook_errors": _avg(with_metrics, "cook_errors"),
            "abort_rate": aborted / len(with_metrics) if with_metrics else None,
        })
    rows.sort(key=lambda r: -r["total"])
    return rows


def _fmt(value, digits: int = 1, prefix: str = "") -> str:
    return "-" if value is None else f"{prefix}{value:.{digits}f}"


def _fmt_rate(value) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def format_report(entries: list[dict]) -> str:
    """評価と自動指標の集計を、そのまま表示できるテキストにする。"""
    if not entries:
        return "保存されたチュートリアルがありません。"
    rated = [e for e in entries if e["rating"]]
    good = sum(1 for e in rated if e["rating"] == 1)
    bad = len(rated) - good
    lines = [
        f"チュートリアル {len(entries)} 件 / 評価済み {len(rated)} 件（👍 {good} / 👎 {bad}、好評率 {_fmt_rate(good / len(rated) if rated else None)}）",
        "※ 評価が少ないうちは傾向は参考程度です（数十件を超えてから判断してください）。",
    ]
    sections = (
        ("モデル別", lambda e: [e["model"]]),
        ("レベル別", lambda e: [e["level"]]),
        ("領域別", lambda e: [e["domain"]]),
        ("理由タグ別", lambda e: list(e["tags"])),
    )
    for title, keys_of in sections:
        rows = summarize(entries, keys_of)
        if not rows:
            continue
        lines.append("")
        lines.append(f"■ {title}")
        lines.append("  項目 | 件数 | 👍/👎 | 好評率 | 平均反復 | 平均コスト | 平均cookエラー | 打ち切り率")
        for r in rows[:15]:
            lines.append(
                f"  {r['key']} | {r['total']} | {r['good']}/{r['bad']} | {_fmt_rate(r['good_rate'])} | "
                f"{_fmt(r['avg_iterations'])} | {_fmt(r['avg_cost'], 3, '$')} | {_fmt(r['avg_cook_errors'])} | {_fmt_rate(r['abort_rate'])}"
            )
    recent_bad = [e for e in rated if e["rating"] == -1 and (e["note"] or e["tags"])][-5:]
    if recent_bad:
        lines.append("")
        lines.append("■ 最近の👎のメモ")
        for e in recent_bad:
            lines.append(f"  ・{e['title']}: {' '.join(e['tags'])} {e['note']}".rstrip())
    return "\n".join(lines)


# ─── 教訓（承認制） ──────────────────────────────────────────────────────────────

def lessons_file(project_dir: str) -> Path | None:
    if not project_dir:
        return None
    return Path(project_dir) / "localRAG" / "tutorial_lessons.json"


def load_lessons(project_dir: str) -> list[dict]:
    path = lessons_file(project_dir)
    data = _read_json(path) if path else None
    if not isinstance(data, list):
        return []
    return [
        {"text": str(item.get("text", "")).strip()[:MAX_LESSON_CHARS], "approved": bool(item.get("approved")),
         "created": str(item.get("created", ""))}
        for item in data if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]


def save_lessons(project_dir: str, lessons: list[dict]) -> bool:
    path = lessons_file(project_dir)
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return _write_json(path, lessons)


def approved_lessons(project_dir: str) -> list[str]:
    return [l["text"] for l in load_lessons(project_dir) if l["approved"]][:MAX_APPROVED_LESSONS]


def build_lessons_section(project_dir: str) -> str:
    """承認済みの教訓をシステムプロンプトの節にする（無ければ空文字）。"""
    lessons = approved_lessons(project_dir)
    if not lessons:
        return ""
    body = "\n".join(f"- {text}" for text in lessons)
    return (
        "\n## 過去の評価から得た教訓（ユーザーが承認したもの。守ること）\n"
        f"{body}\n"
    )


def build_distill_request(bad_entries: list[dict], existing: list[str], max_new: int = 5) -> tuple[str, list[dict]]:
    """低評価のメモから、生成エージェントへの「避けること」ルールを作らせるリクエスト。"""
    system = (
        "あなたはHoudiniチュートリアル自動生成エージェントの品質改善担当です。"
        "ユーザーが低評価（👎）を付けたチュートリアルの理由タグとメモから、次回以降の生成で守るべき"
        "短いルール（教訓）を作ります。"
    )
    cases = []
    for e in bad_entries[-30:]:
        m = e.get("metrics", {})
        facts = []
        if m.get("domain"):
            facts.append(f"領域={m['domain']}")
        if m.get("cook_errors") is not None:
            facts.append(f"cookエラー={m['cook_errors']}")
        if m.get("completed") is False:
            facts.append("打ち切り")
        cases.append(
            f"- 題名: {e.get('title', '')} / タグ: {', '.join(e.get('tags', [])) or 'なし'} / "
            f"メモ: {e.get('note', '') or 'なし'} / {' '.join(facts)}"
        )
    existing_text = "\n".join(f"- {t}" for t in existing) or "（なし）"
    user = (
        "次の低評価の事例から、共通する改善点を最大"
        f"{max_new}個のルールにまとめてください。\n\n"
        "【低評価の事例】\n" + "\n".join(cases) + "\n\n"
        "【すでにあるルール（重複させないこと）】\n" + existing_text + "\n\n"
        "条件:\n"
        f"- 各ルールは命令形の日本語で{MAX_LESSON_CHARS}文字以内。特定のチュートリアル名を含めず、一般化すること\n"
        "- 1件の事例にしか当てはまらない細かい指摘や、根拠が弱いものは作らない（作れなければ空配列でよい）\n"
        "- 出力はJSONの文字列配列だけ。説明文やコードフェンスは付けない。例: [\"ノード数は5個以内に収める\"]"
    )
    return system, [{"role": "user", "content": user}]


def parse_lessons(text: str, limit: int = 5) -> list[str]:
    """モデルの出力（JSON配列、または箇条書き）からルールを取り出す。"""
    text = (text or "").strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    candidates: list[str] = []
    if match:
        try:
            data = json.loads(match.group(0))
            candidates = [str(x) for x in data if isinstance(x, str)]
        except json.JSONDecodeError:
            candidates = []
    if not candidates:
        candidates = [re.sub(r"^[\-\*・\d\.\)\s]+", "", line).strip() for line in text.splitlines()]
    cleaned = [c.strip().strip('"')[:MAX_LESSON_CHARS] for c in candidates if len(c.strip()) >= 4]
    return list(dict.fromkeys(cleaned))[:limit]


# ─── 成功例の参照 ────────────────────────────────────────────────────────────────

def _grams(text: str) -> set[str]:
    """英単語と、日本語の2文字連続（バイグラム）。トピックの近さを測る軽い目安。"""
    text = (text or "").lower()
    grams = set(re.findall(r"[a-z0-9]{3,}", text))
    jp = re.sub(r"[^぀-ヿ㐀-鿿]", "", text)  # ひらがな・カタカナ・漢字だけ残す
    grams.update(jp[i:i + 2] for i in range(len(jp) - 1))
    return grams


def select_good_examples(tutorials_dir: Path, topic: str, n: int = MAX_GOOD_EXAMPLES) -> list[dict]:
    """似たトピックで高評価だったチュートリアルを最大n件選ぶ（完走したものだけ）。"""
    wanted = _grams(topic)
    if not wanted or not tutorials_dir.exists():
        return []
    scored = []
    for md in tutorials_dir.glob("*.md"):
        feedback = read_feedback(md)
        if not feedback or feedback["rating"] != 1:
            continue
        metrics = read_metrics(md)
        if metrics.get("completed") is False:
            continue
        have = _grams(f"{feedback.get('title', '')} {feedback.get('topic', '')} {' '.join(feedback.get('tags', []))}")
        overlap = len(wanted & have)
        if overlap >= 2:
            scored.append((overlap / (len(wanted) ** 0.5 * max(len(have), 1) ** 0.5), md, feedback))
    scored.sort(key=lambda x: -x[0])
    return [
        {"title": fb.get("title", md.stem), "level": fb.get("level", ""), "overview": fb.get("overview", "")[:200],
         "node_types": fb.get("node_types", [])[:12], "note": fb.get("note", "")}
        for _, md, fb in scored[:n]
    ]


def build_examples_section(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = []
    for ex in examples:
        nodes = ", ".join(ex["node_types"]) or "（不明）"
        lines.append(f"- 「{ex['title']}」（{ex['level'] or 'レベル不明'}）: {ex['overview']} 使ったノード: {nodes}")
    return (
        "\n## 高評価だった過去のチュートリアル（構成の参考。そのまま真似せず、今回の題材に合わせること）\n"
        + "\n".join(lines) + "\n"
    )
