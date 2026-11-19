"""
guide_mode.py — 案内モード: 手順ごとに「見るタブ・操作するノード・変えるパラメータ・使うショートカット」を示す（2026-11-03）

初心者レビューで出た詰まりどころ（ショートカットが大事／操作項目が多くて戸惑う／確認するタブが分からない／
ノードを知らない）への対応。画面の部品を「消す」のではなく、必要な場所を「示す」。Houdini の画面は変えない
（タブを前面に出す・ノードを選んで画面に収める・短い表示を出す、だけ。色や設定は書き換えない）。

  ・生成時に、手順ごとの案内データ（guide）を記録する（houdini_tools.py）。保存時に `<名前>_guide.json` へ書く（tutorial_view.py）。
  ・案内タブ（guide_view.py）が読み込み、手順を1つずつ示す。
  ・Houdini を触る部分（hou）は引数で受け取る。画面の無い環境でも、データの組み立てと検索はテストできる。

ショートカットは、SideFX の公式ドキュメントで確かめたものだけを載せる（guide_shortcuts.py）。
確かめていないもの（例: レイアウトの L）は載せない。

2026-11-17（実証実験の指摘）:
  ・「違うオブジェクトが出る」: 手順が指すノードを、名前だけで探して、ほかの生成のサンドボックスや、同じ種類の別のノードを
    選んでいた。パス（サンドボックス相対 → 自分のネットワークの /obj、またはサンドボックス）で探し、名前・種類が合うものだけを示す
    （resolve_step_target）。見つからないときは、理由を返す。同じ種類の別名のノードは、候補が1つだけのときに限り、そう断って示す。
  ・ノードを選ぶ前にネットワークを切り替える／固定（ピン）されたパラメータ画面を外す、で、選んだノードに画面が追従する。
  ・メニュー・チェックボックスの値を、表示名で言う（describe_parm_change）。取れないときは数字のまま。
  ・手順ごとに、作業する場所・目的・消す操作を、はっきり文にする。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import display_isolation
import guide_shortcuts

GUIDE_VERSION = 2
GUIDE_SUFFIX = "_guide.json"

# 生成が使うサンドボックス（houdini_tools.HoudiniToolExecutor.SANDBOX_PREFIX と同じ値。あちらを import すると hou が要るので写している。
# 値が合っているかは、test_guide_target.py が確かめる）
SANDBOX_PREFIX = "ai_tutorial_"
OWN_ROOT = "/obj"  # 学習者が、手順どおりに作るネットワークの根。手順のパス（サンドボックス相対）は、ここからのパスに当たる

TAB_LABELS: dict[str, str] = {
    "network": "ネットワークエディタ",
    "parm": "パラメータ（Parameters）",
    "viewport": "ビューポート（Scene View）",
    "spreadsheet": "Geometry Spreadsheet",
}
# 手順（ツール）ごとに、まず見るタブ
TOOL_TAB: dict[str, str] = {
    "create_node": "network",
    "connect_nodes": "network",
    "delete_node": "network",
    "set_parameter": "parm",
    "cook_node": "viewport",
}
# Houdini 側の hou.paneTabType の名前（版によって無いものは飛ばす）
_PANE_TYPE_NAMES: dict[str, tuple[str, ...]] = {
    "network": ("NetworkEditor",),
    "parm": ("Parm",),
    "viewport": ("SceneViewer",),
    "spreadsheet": ("DetailsViewer",),
}

# ショートカットの表は guide_shortcuts.py（出典つき。公式ドキュメントで確かめたものだけ）。


# ── 案内データの組み立て ─────────────────────────────────────────────────────

_CREATE_RE = re.compile(r"「(.+?)」ノード（([^）]+)）を作り、名前を (\S+) にする")
_CREATE_TOP_RE = re.compile(r"Object レベルに「(.+?)」ノードを作り、名前を (\S+) にする")
_CONNECT_RE = re.compile(r"^(\S+) の出力を、(\S+) の")
_CONNECT_GROUP_RE = re.compile(r"^(\d+)本のノードをつなぐ: (.+)$")  # 連続した接続を1手順にまとめた操作文
_PARAM_NODE_RE = re.compile(r"^(\S+) の(?:パラメータを設定|「)")
_PARAM_ONE_RE = re.compile(r"(.+?) を (.+?)(?:、|$)")
_COOK_RE = re.compile(r"^(\S+) を評価")
_DELETE_RE = re.compile(r"不要になった (\S+) を削除")


def _parse_instruction(tool: str, text: str) -> dict:
    """案内データの無い古い記録（操作文だけ）から、分かる範囲で読み取る。"""
    first = text.split("\n", 1)[0].strip()
    if tool == "create_node":
        m = _CREATE_RE.search(first)
        if m:
            return {"node": m.group(3), "node_label": m.group(1), "node_type": m.group(2)}
        m = _CREATE_TOP_RE.search(first)
        if m:
            return {"node": m.group(2), "node_label": m.group(1), "node_type": "geo"}
    elif tool == "connect_nodes":
        grouped = _CONNECT_GROUP_RE.match(first)
        if grouped:
            pairs = []
            for chunk in grouped.group(2).split("、"):
                parts = [p.strip() for p in chunk.split("→")]
                if len(parts) == 2 and parts[0] and parts[1] and not parts[1].startswith("ほか"):
                    pairs.append({"from": parts[0], "to": parts[1].split(" ")[0]})
            if pairs:
                return {"node": pairs[-1]["to"], "from": pairs[0]["from"], "to": pairs[-1]["to"], "connections": pairs}
        m = _CONNECT_RE.search(first)
        if m:
            return {"node": m.group(2), "from": m.group(1), "to": m.group(2)}
    elif tool == "set_parameter":
        m = _PARAM_NODE_RE.search(first)
        node = m.group(1) if m else ""
        parms = []
        if "設定:" in first:
            for chunk in first.split("設定:", 1)[1].split("、"):
                one = _PARAM_ONE_RE.match(chunk.strip())
                if one:
                    parms.append({"name": "", "label": one.group(1).strip(), "new": one.group(2).strip()})
        return {"node": node, "parms": parms} if node else {}
    elif tool == "cook_node":
        m = _COOK_RE.search(first)
        if m:
            return {"node": m.group(1)}
    elif tool == "delete_node":
        m = _DELETE_RE.search(first)
        if m:
            return {"node": m.group(1)}
    return {}


def own_path(rel: str) -> str:
    """手順のパス（サンドボックス相対）を、学習者のネットワークでのパス（/obj から）にする。"""
    rel = (rel or "").strip("/")
    return f"{OWN_ROOT}/{rel}" if rel else OWN_ROOT


def _parent_rel(rel: str) -> str:
    rel = (rel or "").strip("/")
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _step_container_rel(step: dict) -> str:
    """手順が作業するネットワーク（ノードを入れている親）の、相対パス。分からなければ ""（Object レベル）。"""
    return _parent_rel(step.get("node_path") or "")


def parm_where_text(where: str) -> str:
    """パラメータのタブの場所の文。where は「Sourcing > Emission」のような、フォルダ（タブ・折りたたみ）の道筋。"""
    where = (where or "").strip()
    return where if where else "タブの外（パラメータ画面のいちばん上）"


def _hint(tool: str, g: dict) -> str:
    """その手順で何をするかの、短い案内（画面に出す）。省略しない（2026-11-17: 「ほか」で切ると、わからない）。"""
    node = g.get("node") or ""
    if tool == "create_node":
        label = g.get("node_label") or g.get("node_type") or "ノード"
        return f"ネットワークエディタで Tab を押し、「{label}」と入力して Enter。名前は {node} にします" if node else f"Tab を押して「{label}」を作ります"
    if tool == "connect_nodes":
        pairs = [c for c in (g.get("connections") or []) if isinstance(c, dict)]
        if len(pairs) > 1:
            return f"{len(pairs)}本つなぎます: " + "、".join(f"{c.get('from')} → {c.get('to')}" for c in pairs)
        return f"{g.get('from') or '上のノード'} の出力から、{g.get('to') or node} の入力へ線を引きます"
    if tool == "set_parameter":
        lines = []
        for p in g.get("parms") or []:
            where = f"（場所: {parm_where_text(p['where'])}）" if p.get("where") else ""
            old = f"{p['old']} → " if p.get("old") not in (None, "") else ""
            lines.append(f"{p.get('label') or p.get('name')}: {old}{p.get('new')}{where}")
        return f"{node} のパラメータを変えます。" + (" / ".join(lines) if lines else "")
    if tool == "cook_node":
        return f"{node} を表示して、ビューポートで形を確認します。点の数や属性の値は、Geometry Spreadsheet で見られます"
    if tool == "delete_node":
        return f"【消す】{node} を選んで、削除します（Delete キー）。残すノードと間違えないように、名前を確かめてから消します"
    return ""


def work_headline(tool: str, g: dict) -> str:
    """手順の冒頭に出す、「どの部分を作業するか」の1文。パスは、学習者のネットワーク（/obj から）の形で、省略しない。"""
    node = g.get("node") or ""
    node_path = g.get("node_path") or ""
    container = own_path(_parent_rel(node_path)) if node_path else ""
    full = own_path(node_path) if node_path else node
    if tool == "create_node":
        label = g.get("node_label") or g.get("node_type") or "ノード"
        place = f"{container} の中に" if container else "いまのネットワークに"
        return f"【作業する部分】{place}、新しいノード「{label}」（名前: {node}）を作る"
    if tool == "connect_nodes":
        place = f"{container} の中で" if container else "同じネットワークの中で"
        return f"【作業する部分】{place}、ノードの線をつなぐ"
    if tool == "set_parameter":
        return f"【作業する部分】{full} のパラメータを変える"
    if tool == "cook_node":
        return f"【作業する部分】{full} の結果を、ビューポートで確かめる"
    if tool == "delete_node":
        return f"【消す】{full} を削除する"
    return ""


def build_guide(step_screenshots: list[dict], title: str = "", level: str = "", extras: dict | None = None,
                purposes: dict | None = None) -> dict:
    """手順の記録（result.step_screenshots）から案内データを作る。画像のパスなどは入れない。
    purposes: {ノード名: 「何のために使うか」の1文}。手順書（.md）の「使うノード」から取る（purposes_from_markdown）。
    記録（guide）に purpose があれば、そちらを優先する。"""
    steps: list[dict] = []
    for i, s in enumerate(step_screenshots or [], start=1):
        if not isinstance(s, dict):
            continue
        tool = str(s.get("tool") or "")
        tab = TOOL_TAB.get(tool)
        if tab is None:
            continue
        recorded = s.get("guide")
        g: dict = recorded if isinstance(recorded, dict) and recorded else _parse_instruction(tool, str(s.get("result") or ""))
        # コードを入れるパラメータの手順には、外部エディタのキーも足す
        has_code = any(isinstance(pm, dict) and str(pm.get("new") or "").startswith("（コード") for pm in (g.get("parms") or []))
        shortcuts = guide_shortcuts.for_step(tool, code=has_code)
        connections = [c for c in (g.get("connections") or []) if isinstance(c, dict)][:12]
        g_view = {**g, "connections": connections}
        instruction = str(s.get("result") or "").split("\n", 1)[0]
        if tool == "connect_nodes" and len(connections) > 1:
            # 記録の文は「ほか○本」で切れていることがある。つなぐ線を、全部書く
            instruction = f"{len(connections)}本のノードをつなぐ: " + "、".join(f"{c.get('from')} → {c.get('to')}" for c in connections)
        node = str(g.get("node") or "")
        purpose = str(g.get("purpose") or (purposes or {}).get(node) or "")
        steps.append({
            "step": s.get("step") if isinstance(s.get("step"), int) else i,
            "tool": tool,
            "instruction": instruction,
            "node": node,
            "node_path": str(g.get("node_path") or ""),
            "node_type": str(g.get("node_type") or ""),
            "node_label": str(g.get("node_label") or ""),
            "parms": [p for p in (g.get("parms") or []) if isinstance(p, dict)][:12],
            "from": str(g.get("from") or ""),
            "to": str(g.get("to") or ""),
            "connections": connections,
            "tab": tab,
            "tab_label": TAB_LABELS[tab],
            "shortcuts": shortcuts,
            "hint": _hint(tool, g_view),
            "work": work_headline(tool, g_view),
            "purpose": purpose,
        })
    guide = {"version": GUIDE_VERSION, "title": title, "level": level, "steps": steps}
    for key, value in (extras or {}).items():
        if value:
            guide[key] = value
    return guide


def guide_from_result(result) -> dict:
    """生成の結果（TutorialResult）から、案内データを作る。保存前（生成直後）にも、保存時にも、同じものを作る。"""
    markdown = getattr(result, "markdown", "") or ""
    extras = dict(sections_from_markdown(markdown))
    sandbox = str(getattr(result, "sandbox_path", "") or "")
    if sandbox:
        extras["sandbox_path"] = sandbox
    return build_guide(
        getattr(result, "step_screenshots", None) or [], getattr(result, "title", "") or "", getattr(result, "level", "") or "",
        extras, purposes_from_markdown(markdown),
    )


# 手順書(.md)の節のうち、案内タブにも出すもの。キー → 見出しに含まれる語
_EXTRA_SECTIONS: dict[str, tuple[str, ...]] = {
    "prerequisites": ("前提",),
    "tips": ("TIPS",),
    "challenge": ("自分でやって",),
}


def sections_from_markdown(md_text: str) -> dict[str, str]:
    """手順書から、前提条件・TIPS・自分でやってみよう の本文を取り出す（案内タブの下に出す）。"""
    try:
        import video_script

        sections = video_script.extra_sections(md_text)
    except Exception:  # noqa: BLE001 -- 取れなくても案内は動く
        return {}
    out: dict[str, str] = {}
    for key, words in _EXTRA_SECTIONS.items():
        for heading, body in sections:
            if any(w.upper() in heading.upper() for w in words):
                out[key] = body[:1500]
                break
    return out


_NODE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SANDBOX_IN_MD_RE = re.compile(r"サンドボックス:\s*`([^`]+)`")


def _split_label_and_purpose(line: str) -> tuple[str, str] | None:
    """「ctrl_seed / ctrl_temp（attribcreate）: 公開値を運ぶ入口」を、(左, 右) に分ける。括弧の中の「:」では分けない。"""
    depth = 0
    for i, ch in enumerate(line):
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        elif ch in ":：" and depth == 0:
            left, right = line[:i].strip(), line[i + 1:].strip()
            return (left, right) if left and right else None
    return None


def purposes_from_markdown(md_text: str) -> dict[str, str]:
    """手順書の「使うノードと、できること」の節から、{ノード名: 何のために使うか} を取る（案内の「目的」に出す）。
    見つからない節・書式のときは空（目的は出さない。足りないことは、報告に書く）。"""
    text = (md_text or "").replace("\r\n", "\n")
    out: dict[str, str] = {}
    for part in re.split(r"^#{2,3} ", text, flags=re.M)[1:]:
        heading, _, body = part.partition("\n")
        if "使うノード" not in heading:
            continue
        for raw in body.split("\n"):
            line = re.sub(r"^\s*(?:\d+[.)]|[-*・])\s*", "", raw).strip()
            if not line:
                continue
            split = _split_label_and_purpose(line)
            if split is None:
                continue
            left, right = split
            for chunk in re.split(r"[/、,]", re.sub(r"[（(][^）)]*[）)]", "", left)):
                name = chunk.strip().strip("`")
                if _NODE_NAME_RE.fullmatch(name):
                    out.setdefault(name, right[:200])
    return out


def sandbox_from_markdown(md_text: str) -> str:
    m = _SANDBOX_IN_MD_RE.search(md_text or "")
    return m.group(1).strip() if m else ""


def guide_path_for(md_path: Path) -> Path:
    return md_path.with_name(md_path.stem + GUIDE_SUFFIX)


def write_guide(path: Path, guide: dict) -> None:
    path.write_text(json.dumps(guide, ensure_ascii=False, indent=2), encoding="utf-8")


def md_path_for(guide_path: Path) -> Path:
    name = guide_path.name
    stem = name[: -len(GUIDE_SUFFIX)] if name.endswith(GUIDE_SUFFIX) else guide_path.stem
    return guide_path.with_name(stem + ".md")


def _fill_from_markdown(data: dict, path: Path) -> None:
    """以前の案内データ（サンドボックスのパス・目的が無い）に、同じ名前の手順書から足りないものを足す。"""
    need_sandbox = not data.get("sandbox_path")
    need_purpose = any(isinstance(s, dict) and not s.get("purpose") for s in data["steps"])
    if not (need_sandbox or need_purpose):
        return
    try:
        md = md_path_for(path).read_text(encoding="utf-8")
    except OSError:
        return
    if need_sandbox:
        sandbox = sandbox_from_markdown(md)
        if sandbox:
            data["sandbox_path"] = sandbox
    if need_purpose:
        purposes = purposes_from_markdown(md)
        for s in data["steps"]:
            if isinstance(s, dict) and not s.get("purpose") and s.get("node") in purposes:
                s["purpose"] = purposes[s["node"]]
                s["work"] = s.get("work") or ""


def load_guide(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list) or not data["steps"]:
        return None
    _fill_from_markdown(data, Path(path))
    return data


def guide_label(data: dict, path: Path | None = None) -> str:
    level = f"［{data['level']}］" if data.get("level") else ""
    fallback = path.name[: -len(GUIDE_SUFFIX)] if path is not None else ""
    return f"{data.get('title') or fallback}{level}（{len(data['steps'])}手順）"


def list_guides(tutorials_dir: Path | None) -> list[tuple[str, Path]]:
    """保存済みの案内データを新しい順に。戻り値: [(表示名, パス)]。"""
    if tutorials_dir is None or not Path(tutorials_dir).is_dir():
        return []
    items: list[tuple[float, str, Path]] = []
    for path in Path(tutorials_dir).glob(f"*{GUIDE_SUFFIX}"):
        data = load_guide(path)
        if data is None:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        items.append((mtime, guide_label(data, path), path))
    items.sort(key=lambda t: t[0], reverse=True)
    return [(name, path) for _m, name, path in items]


# ── パラメータの値を、表示名で言う（メニュー・チェックボックス） ─────────────────────────

_ON = {"1", "true", "on", "yes"}
_OFF = {"0", "false", "off", "no"}


def parm_value_info(template) -> dict:
    """hou.ParmTemplate（またはそれに似たもの）から、値の言い換えに要る情報を取る。取れなければ {}。
    戻り値: {"kind": "toggle" | "menu" | "other", "items": [...], "labels": [...], "int_menu": bool}。
    生成時（ノードが手元にあるとき）に、houdini_tools から呼んで、案内データに入れてもよい。"""
    if template is None:
        return {}
    try:
        kind_obj = template.type()
        kind = str(kind_obj.name() if hasattr(kind_obj, "name") else kind_obj).split(".")[-1]
    except Exception:  # noqa: BLE001
        return {}
    info: dict = {"kind": "other", "items": [], "labels": [], "int_menu": False}
    if kind == "Toggle":
        info["kind"] = "toggle"
        return info
    try:
        items = [str(i) for i in template.menuItems()]
        labels = [str(i) for i in template.menuLabels()]
    except Exception:  # noqa: BLE001 -- メニューを持たないテンプレートは、ここで例外になる
        return info
    if items:
        info.update({"kind": "menu", "items": items, "labels": labels if len(labels) == len(items) else items,
                     "int_menu": kind in ("Menu", "Int")})
    return info


def menu_label_for(info: dict, value) -> str:
    """メニューの値（番号、またはトークン）の、表示名。分からなければ ""。"""
    items, labels = info.get("items") or [], info.get("labels") or []
    text = str(value).strip()
    if not items:
        return ""
    if not info.get("int_menu") and text in items:  # 文字列のメニューは、トークンで持つ
        return labels[items.index(text)]
    try:
        index = int(float(text))
    except ValueError:
        return labels[items.index(text)] if text in items else ""
    if 0 <= index < len(items):
        return labels[index]
    return ""


def _toggle_state(value) -> bool | None:
    text = str(value).strip().lower()
    if text in _ON:
        return True
    if text in _OFF:
        return False
    return None


def describe_parm_change(parm: dict, info: dict | None = None) -> dict:
    """パラメータ1件の変更を、画面に出す文にする。
    戻り値: {"label", "name", "where_text", "action", "old_text", "new_text", "kind"}
      action: 「Run Over を Detail (only once) にする」「X をオフにする（チェックを外す）」「X を空にする（消す）」など、動詞で言う文。
    info（parm_value_info の結果）が無い・合わないときは、数字のまま「X を 2 にする」（メニューかどうかは言わない）。"""
    info = info or {}
    label = str(parm.get("label") or parm.get("name") or "")
    old_raw = "" if parm.get("old") is None else str(parm.get("old"))
    new_raw = "" if parm.get("new") is None else str(parm.get("new"))
    kind = info.get("kind") or "other"
    old_text, new_text = old_raw, new_raw
    if new_raw.startswith("（コード"):
        action = f"{label} の欄に、手順書のコードを入力する（コードは、手順書を見る）"
        kind = "code"
    elif new_raw.strip() == "":
        action = f"{label} を空にする（入っている内容を消す）"
        new_text = "（空）"
    elif kind == "toggle" and _toggle_state(new_raw) is not None:
        on = _toggle_state(new_raw)
        action = f"{label} をオンにする（チェックを入れる）" if on else f"{label} をオフにする（チェックを外す。無効にする）"
        new_text = "オン" if on else "オフ"
        old_state = _toggle_state(old_raw)
        old_text = old_raw if old_state is None else ("オン" if old_state else "オフ")
    elif kind == "menu" and menu_label_for(info, new_raw):
        shown = menu_label_for(info, new_raw)
        action = f"{label} を {shown} にする"
        new_text = f"{shown}（値: {new_raw}）" if shown != new_raw else shown
        old_label = menu_label_for(info, old_raw) if old_raw else ""
        old_text = f"{old_label}（値: {old_raw}）" if old_label and old_label != old_raw else old_raw
    else:
        action = f"{label} を {new_raw} にする"
    if old_raw == "":
        old_text = "（空）" if kind != "code" else ""
    return {
        "label": label, "name": str(parm.get("name") or ""), "where_text": parm_where_text(str(parm.get("where") or "")),
        "action": action, "old_text": old_text, "new_text": new_text, "kind": kind,
    }


def location_status(current_path: str, expected_path: str) -> tuple[str, bool]:
    """「いまのネットワーク」と「この手順の作業場所」を比べた、表示文と、同じかどうか。"""
    if not expected_path:
        return (f"いまのネットワーク: {current_path}" if current_path else "いまのネットワーク: 不明（ネットワークエディタが見つかりません）"), True
    if not current_path:
        return f"この手順の場所: {expected_path}（いまのネットワークは不明）", False
    if current_path.rstrip("/") == expected_path.rstrip("/"):
        return f"いまのネットワーク: {current_path}（この手順の場所と同じ）", True
    return f"いまのネットワーク: {current_path}\nこの手順の場所: {expected_path}（違います）", False


# ── Houdini の画面を動かす（hou は引数。画面を書き換えず、示すだけ） ───────────────

_MAX_SEARCH = 3000
_BASE_LABEL = {"own": "自分のネットワーク", "sandbox": "サンドボックス"}


def _panes_of_type(hou, pane_type) -> list:
    """その種類のペインタブを、順に（最大6つ）。index を受け取らない版・偽物は、最初の1つだけ。"""
    found: list = []
    for index in range(6):
        try:
            pane = hou.ui.paneTabOfType(pane_type, index) if index else hou.ui.paneTabOfType(pane_type)
        except TypeError:
            break
        except Exception:  # noqa: BLE001
            break
        if pane is None or any(pane is f for f in found):
            break
        found.append(pane)
    return found


def _pane(hou, tab: str):
    """指定の種類のペインタブ。複数あるときは、いま前面のものを選ぶ（無ければ最初のもの）。"""
    for name in _PANE_TYPE_NAMES.get(tab, ()):
        try:
            pane_type = getattr(hou.paneTabType, name, None)
        except Exception:  # noqa: BLE001 -- hou が、期待した形でないとき
            return None
        if pane_type is None:
            continue
        found = _panes_of_type(hou, pane_type)
        for pane in found:
            try:
                if pane.isCurrentTab():
                    return pane
            except Exception:  # noqa: BLE001 -- isCurrentTab が無い・失敗したら、最初のものにする
                break
        if found:
            return found[0]
    return None


def show_tab(hou, tab: str) -> tuple[bool, str]:
    """指定のタブを前面に出す。無ければ、追加のしかたを返す。"""
    label = TAB_LABELS.get(tab, tab)
    pane = _pane(hou, tab)
    if pane is None:
        return False, f"{label}のタブが見つかりません。ペイン上部の「＋」から追加してください"
    try:
        pane.setIsCurrentTab()
    except Exception as exc:  # noqa: BLE001
        return False, f"{label}を前面に出せませんでした（{exc}）"
    return True, f"{label}を前面に出しました"


def _base_type_name(type_name: str) -> str:
    """'labs::foo::1.0' → 'foo' / 'scatter::2.0' → 'scatter'。"""
    parts = [p for p in type_name.split("::") if p]
    if len(parts) >= 3:
        return parts[1]
    return parts[0] if parts else ""


def _type_name_of(node) -> str:
    try:
        return str(node.type().name())
    except Exception:  # noqa: BLE001
        return ""


def _type_ok(node, type_name: str) -> bool:
    """手順の種類と、ノードの種類が合うか（種類が分からない手順は、合うとする）。バージョン・名前空間の違いは無視。"""
    if not type_name:
        return True
    return _base_type_name(_type_name_of(node)) == _base_type_name(type_name)


def _node_at(hou, path: str):
    try:
        return hou.node(path)
    except Exception:  # noqa: BLE001
        return None


def _is_sandbox_child(node) -> bool:
    try:
        return node.parent() is not None and node.parent().path() == OWN_ROOT and node.name().startswith(SANDBOX_PREFIX)
    except Exception:  # noqa: BLE001
        return False


def _children_of(node) -> list:
    try:
        if hasattr(node, "children"):
            return list(node.children())
        return [c for c in node.allSubChildren() if c.parent() is not None and c.parent().path() == node.path()]
    except Exception:  # noqa: BLE001
        return []


def _walk(root, skip_sandboxes: bool, budget: list[int]):
    """root の中のノードを、順に返す（root 自身は含めない）。生成のサンドボックスは、自分のネットワークの探索から外す。上限あり。"""
    stack = [root]
    while stack and budget[0] > 0:
        node = stack.pop()
        try:
            children = list(node.children()) if hasattr(node, "children") else list(node.allSubChildren())
        except Exception:  # noqa: BLE001
            continue
        for child in reversed(children):
            if skip_sandboxes and _is_sandbox_child(child):
                continue
            budget[0] -= 1
            yield child
            if hasattr(node, "children"):
                stack.append(child)


def _shared_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a.strip("/").split("/"), b.strip("/").split("/")):
        if x != y:
            break
        n += 1
    return n


@dataclass
class Target:
    """手順が指すノードの探索結果。"""
    node: object = None
    how: str = ""          # "path"（パスが一致）| "name"（名前が一致。場所は少し違う）| "type"（種類が同じ別名。候補が1つだけ）| ""
    where: str = ""        # "own"（自分のネットワーク）| "sandbox"（生成したサンドボックス）| ""
    note: str = ""         # 画面に出す、補足や、見つからない理由
    container: object = None  # 見つからないとき、代わりに開くネットワーク
    expected: str = ""     # 手順が指す、自分のネットワークでのパス


def _bases(mode: str, sandbox_path: str, create: bool) -> list[tuple[str, str]]:
    own = ("own", OWN_ROOT)
    box = ("sandbox", sandbox_path) if sandbox_path else None
    if mode == "own":
        return [own]
    if mode == "sandbox":
        return [box] if box else []
    # 自動: まず学習者のネットワーク。無ければ、サンドボックスの実物（作る手順は、サンドボックスへ飛ばない）
    return [own] + ([box] if box and not create else [])


def _deepest_existing(hou, path: str):
    path = path.rstrip("/")
    while path:
        node = _node_at(hou, path)
        if node is not None:
            return node
        path = path.rsplit("/", 1)[0] if "/" in path.strip("/") else ""
    return _node_at(hou, "/")


def _search_base(hou, root_path: str, label: str, name: str, rel: str, type_name: str, create: bool, default_container=None):
    """1つの根（自分のネットワーク、またはサンドボックス）の中で、手順のノードを探す。戻り値: (Target, 理由の文の一覧)。"""
    notes: list[str] = []
    root = _node_at(hou, root_path)
    if root is None:
        return Target(), [f"{_BASE_LABEL[label]}（{root_path}）が見つかりません"]
    exact_path = ""
    # 1. パスが一致（サンドボックス相対のパスを、根につなぐ）
    if rel:
        exact_path = f"{root_path.rstrip('/')}/{rel}"
        exact = _node_at(hou, exact_path)
        if exact is not None:
            if _type_ok(exact, type_name):
                return Target(node=exact, how="path", where=label), notes
            notes.append(f"{exact_path} はありますが、ノードの種類が違います（いまは {_type_name_of(exact)}、手順は {type_name}）")
    parent_rel = _parent_rel(rel)
    parent_path = f"{root_path.rstrip('/')}/{parent_rel}" if parent_rel else root_path
    if create:  # 作る手順: すでにあるほかのノードを示さない。作る場所（ネットワーク）だけ開く
        return Target(container=_deepest_existing(hou, parent_path), where=label), notes
    # 2. 名前（と種類）が一致するものが、ほかの場所に1つだけある
    budget = [_MAX_SEARCH]
    if name:
        cands = [n for n in _walk(root, label == "own", budget)
                 if n.name() == name and _type_ok(n, type_name) and n.path() != exact_path]
        if budget[0] <= 0 and cands:  # 探索を打ち切ったので、見つかったものが唯一かどうか、言えない
            notes.append(f"ノードが多く、探索の上限（{_MAX_SEARCH} 個）に達しました。同じ名前のノードがほかにもあるかもしれないため、決められません"
                         "（手順のパスのとおりにノードを作ると、案内できます）")
        elif len(cands) == 1:
            return Target(node=cands[0], how="name", where=label,
                          note=f"{exact_path or name} ではなく、{cands[0].path()} にある同じ名前のノードを示しました"), notes
        elif len(cands) > 1:
            scored = sorted(cands, key=lambda n: -_shared_prefix(n.path()[len(root_path):], rel))
            best = _shared_prefix(scored[0].path()[len(root_path):], rel)
            if best > 0 and _shared_prefix(scored[1].path()[len(root_path):], rel) < best:
                return Target(node=scored[0], how="name", where=label,
                              note=f"同じ名前のノードが複数あります。手順のパスに最も近い {scored[0].path()} を示しました"), notes
            notes.append("同じ名前のノードが複数あるため、どれか決められません: " + "、".join(n.path() for n in cands[:5]))
    # 3. 手順のネットワークに、同じ種類のノードが1つだけある（名前だけが違う）
    if type_name:
        container = _node_at(hou, parent_path) if rel else default_container
        if container is not None:
            same = [c for c in _children_of(container) if _type_ok(c, type_name) and not _is_sandbox_child(c)]
            if len(same) == 1 and name:
                return Target(node=same[0], how="type", where=label,
                              note=f"名前が違う同じ種類のノードを示しました: {same[0].path()}（手順の名前は {name}）"), notes
            if len(same) > 1:
                notes.append(f"{container.path()} に同じ種類のノードが複数あります（{'、'.join(c.name() for c in same[:6])}）。名前を {name} にすると、案内できます")
    return Target(container=_deepest_existing(hou, parent_path), where=label), notes


def resolve_step_target(hou, step: dict, sandbox_path: str = "", mode: str = "auto") -> Target:
    """手順が指すノードを探す。
      mode: "auto"（まず自分のネットワーク、無ければサンドボックスの実物）/ "own"（自分のネットワークだけ）/ "sandbox"（サンドボックスだけ）
    探し方: パスが一致 → 名前と種類が一致（1つだけ）→ 種類が同じ別名（手順のネットワークに1つだけ）。当て推量の選択はしない。
    見つからないとき node は None で、note に理由が入る。"""
    tool = str(step.get("tool") or "")
    name = str(step.get("node") or "")
    rel = str(step.get("node_path") or "").strip("/")
    type_name = str(step.get("node_type") or "")
    create = tool == "create_node"
    expected = own_path(rel) if rel else ""
    default_container = None
    if not rel:  # 古い記録: パスが分からない。いま開いているネットワークを、探す場所の目安にする
        editor = _pane(hou, "network")
        try:
            default_container = editor.pwd() if editor is not None else None
        except Exception:  # noqa: BLE001
            default_container = None
    bases = _bases(mode, sandbox_path, create)
    notes: list[str] = []
    container = None
    if mode == "sandbox" and not sandbox_path:
        notes.append("この案内データには、サンドボックスのパスがありません（以前の保存）。「自分のネットワーク」で案内します")
        bases = _bases("own", sandbox_path, create)
    for label, root_path in bases:
        found, why = _search_base(hou, root_path, label, name, rel, type_name, create, default_container)
        notes += why
        if container is None and found.container is not None:
            container = found.container
        if found.node is not None:
            if label == "sandbox" and mode == "auto":
                found.note = (f"自分のネットワークには見つからないので、サンドボックスの実物 {found.node.path()} を示しました（見本です）"
                              + (f"。{found.note}" if found.note else ""))
            elif found.note == "" and label == "sandbox":
                found.note = "サンドボックスの実物を示しました（見本です）"
            found.expected = expected
            return found
    reason = f"「{name or step.get('node_label') or '？'}」" + (f"（{expected}）" if expected else "") + "は見つかりません"
    if create:
        reason = f"「{step.get('node_label') or step.get('node_type') or name}」" + (f"（{expected}）" if expected else "") + "は、まだありません"
    return Target(container=container, expected=expected, note=reason + ("。" + "。".join(notes) if notes else ""))


def find_node(hou, name: str, type_name: str = ""):
    """（以前の関数。互換のため残す）名前（なければ種類）が合うノードを探す。戻り値: (ノード or None, "name"|"type"|"")。
    以前は、同じ種類のノードを、どこからでも拾っていた。いまは、自分のネットワークの中で、名前と種類が合うもの（1つだけ）、
    または、いま開いているネットワークに同じ種類が1つだけあるときに限る。"""
    hit = resolve_step_target(hou, {"tool": "x", "node": name, "node_type": type_name}, mode="own")
    if hit.node is None:
        return None, ""
    return hit.node, ("name" if hit.how in ("path", "name") else "type")


def focus_nodes(hou, nodes: list) -> bool:
    """ノードを選び、ネットワークエディタをそこへ寄せる。順序が大事: ネットワークの切り替え → 選択 → エディタの現在ノード → 追加の選択。
    （以前は、先に選んでから切り替えていたため、パラメータ画面が別のノードのままになることがあった）"""
    if not nodes:
        return False
    first = nodes[0]
    editor = _pane(hou, "network")
    parent = None
    try:
        parent = first.parent()
    except Exception:  # noqa: BLE001
        parent = None
    if editor is not None and parent is not None:
        try:
            if editor.pwd().path() != parent.path():
                editor.setPwd(parent)
        except Exception:  # noqa: BLE001 -- 切り替えられなくても、選択はできる
            pass
    try:
        first.setCurrent(True, clear_all_selected=True)  # 選択 + パラメータ画面がこのノードに追従する
    except Exception:  # noqa: BLE001
        return False
    if editor is not None:
        setter = getattr(editor, "setCurrentNode", None)
        if callable(setter):
            try:
                setter(first)
            except Exception:  # noqa: BLE001
                pass
    try:
        for extra in nodes[1:]:
            if extra.parent() is not None and parent is not None and extra.parent().path() == parent.path():
                extra.setSelected(True)
    except Exception:  # noqa: BLE001
        pass
    if editor is not None:
        try:
            editor.homeToSelection()
            if hasattr(editor, "flashMessage"):
                editor.flashMessage(None, "ここを操作します: " + "、".join(n.name() for n in nodes), 3.0)
        except Exception:  # noqa: BLE001 -- 示せなくても、選択はできている
            pass
    return True


def verify_shown(hou, node) -> str | None:
    """示したノードが、実際に選ばれ、ネットワークエディタもその階層になっているか。合っていれば None、違えば理由の文。"""
    try:
        selected = [n.path() for n in hou.selectedNodes()]
    except Exception:  # noqa: BLE001
        selected = None
    if selected is not None and node.path() not in selected:
        return f"{node.path()} が選ばれていません（いま選んでいるのは: {'、'.join(selected) or 'なし'}）"
    editor = _pane(hou, "network")
    try:
        parent = node.parent()
        if editor is not None and parent is not None and editor.pwd().path() != parent.path():
            return f"ネットワークエディタが {editor.pwd().path()} のままです（{parent.path()} へ切り替えられませんでした）"
    except Exception:  # noqa: BLE001
        pass
    return None


def release_parm_pin(hou) -> str:
    """パラメータ画面が、ピンで固定されていると、選んだノードに追従しない。固定されていたら外す。外したら、その旨の文を返す。"""
    pane = _pane(hou, "parm")
    if pane is None:
        return ""
    try:
        if hasattr(pane, "isPin") and pane.isPin():
            pane.setPin(False)
            return "パラメータ画面の固定（ピン）を外しました（選んだノードに追従させるため）"
    except Exception:  # noqa: BLE001
        pass
    return ""


def show_nodes(hou, wanted: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """（以前の関数。互換のため残す）名前とタイプ名で探して、選ぶ。戻り値: (見つけたノード名, 見つからなかった名前)。"""
    found = []
    missing = []
    for name, type_name in wanted:
        node, _how = find_node(hou, name, type_name)
        if node is None:
            missing.append(name)
        else:
            found.append(node)
    if not found or not focus_nodes(hou, found):
        return [], missing
    return [n.name() for n in found], missing


def isolate_display(hou, node_paths: list[str]) -> str:
    """手順が指すノードのオブジェクト以外の表示を切り、見せたいオブジェクトの表示を入れる（ビューポートに、関係ないものが重ならないように）。
    切ったものがあれば、画面に出す1文を返す（無ければ空）。"""
    keep = [display_isolation.top_object_path(p) for p in node_paths if p]
    keep = [k for k in keep if k]
    if not keep:
        return ""
    turned_off = display_isolation.isolate(hou, keep)
    for path in keep:
        display_isolation.show(hou, path)
    if not turned_off:
        return ""
    return f"ほかのオブジェクトの表示を切りました（{len(turned_off)}個: {'、'.join(p.rsplit('/', 1)[-1] for p in turned_off[:4])}{'…' if len(turned_off) > 4 else ''}）。「表示を元に戻す」で戻せます"


def restore_display(hou) -> str:
    """切ったオブジェクトの表示を、元に戻す。画面に出す1文を返す。"""
    restored = display_isolation.restore(hou)
    return f"{len(restored)}個のオブジェクトの表示を戻しました" if restored else "戻すものはありません"


def _parm_targets(node, names: list[str]) -> list:
    """名前の、実在するパラメータ（無ければ、タプル）。"""
    found = []
    for name in names:
        try:
            parm = node.parm(name)
            if parm is None:
                parm = node.parmTuple(name)
            if parm is not None:
                found.append(parm)
        except Exception:  # noqa: BLE001
            continue
    return found


def highlight_parms(hou, step: dict, node, reveal=None) -> list[str]:
    """パラメータ画面で、この手順の項目を見つけやすくする。Houdini には、パラメータを光らせる API が無いので、
    ① 項目が入っているタブ（フォルダ）を前面にし（reveal）、② その項目がちょうど画面の中央に来るよう、スクロールし
    （ParameterEditor.scrollTo）、③ キーボードの焦点を最初の項目に移す（moveFocusTo）。
    戻り値: 画面に出すメッセージ（できたこと・できなかったこと）。失敗しても、案内は止めない。"""
    names = [str(p.get("name")) for p in (step.get("parms") or []) if isinstance(p, dict) and p.get("name")]
    if node is None or not names:
        return []
    pane = _pane(hou, "parm")
    if pane is None:
        return []
    messages: list[str] = []
    if callable(reveal):
        try:
            reveal(node, names)
        except Exception:  # noqa: BLE001
            pass
    targets = _parm_targets(node, names)
    if not targets:
        return []
    scrolled = False
    scroll = getattr(pane, "scrollTo", None)
    if callable(scroll):
        position = getattr(getattr(hou, "scrollPosition", None), "Center", None)
        try:
            scroll(targets, position) if position is not None else scroll(targets)
            scrolled = True
        except Exception:  # noqa: BLE001 -- 版によって、引数が違う・画面がまだ追従していない
            scrolled = False
    focused = False
    focus = getattr(pane, "moveFocusTo", None)
    if callable(focus):
        try:
            focus(targets[0])
            focused = True
        except Exception:  # noqa: BLE001
            focused = False
    if scrolled or focused:
        messages.append("パラメータ画面を、この手順の項目（" + "、".join(names[:3]) + ("…" if len(names) > 3 else "") + "）の位置に合わせました")
    return messages


def _endpoints(step: dict) -> list[dict]:
    """つなぐ手順の、両端のノード（同じネットワークの中にあるとして、パスを作る）。"""
    parent = _step_container_rel(step)
    names: list[str] = []
    for n in [step.get("from"), step.get("to") or step.get("node")] + [x for pair in (step.get("connections") or []) for x in (pair.get("from"), pair.get("to"))]:
        if n and n not in names:
            names.append(n)
    return [{"tool": "connect_nodes", "node": n, "node_path": f"{parent}/{n}" if parent else n, "node_type": ""} for n in names]


def apply_step(hou, step: dict, sandbox_path: str = "", mode: str = "auto") -> list[str]:
    """1つの手順を案内する: ノードを示し、見るタブを前面に出す。戻り値: 画面に出すメッセージ（1行ずつ）。"""
    messages: list[str] = []
    tool = step.get("tool")
    wanted = _endpoints(step) if tool == "connect_nodes" else ([step] if step.get("node") else [])
    hits = [resolve_step_target(hou, w, sandbox_path, mode) for w in wanted]
    found = [h for h in hits if h.node is not None]
    if found:
        if focus_nodes(hou, [h.node for h in found]):
            for h in found:
                messages.append(f"示したノード: {h.node.path()}（{_BASE_LABEL.get(h.where, '')}）")
            problem = verify_shown(hou, found[0].node)
            if problem:
                messages.append("確認: " + problem)
        else:
            messages.append("ノードを選べませんでした: " + "、".join(h.node.path() for h in found))
    for h in hits:
        if h.note:
            messages.append(h.note)
        if h.node is None and h.container is not None and not found:
            editor = _pane(hou, "network")
            try:
                if editor is not None and editor.pwd().path() != h.container.path():
                    editor.setPwd(h.container)
                if tool == "create_node":
                    messages.append(f"{h.container.path()} を開きました。ここで Tab を押して作ります")
            except Exception:  # noqa: BLE001
                pass
    if found:
        editor = _pane(hou, "network")
        try:
            if editor is not None:
                messages.append(f"いまのネットワーク: {editor.pwd().path()}")
        except Exception:  # noqa: BLE001
            pass
        note = isolate_display(hou, [h.node.path() for h in found])
        if note:
            messages.append(note)
    if tool == "set_parameter":
        pin = release_parm_pin(hou)
        if pin:
            messages.append(pin)
        for p in step.get("parms") or []:
            if isinstance(p, dict):
                messages.append(f"パラメータのタブ: {parm_where_text(str(p.get('where') or ''))}、項目: {p.get('label') or p.get('name')}")
    ok, message = show_tab(hou, step.get("tab") or "network")
    messages.append(message)
    return messages


# ── パラメータの値の言い換えに要る、テンプレートの取得 ──────────────────────────────

_type_cache: dict = {}


def _find_node_type(hou, type_name: str):
    """タイプ名（例: scatter::2.0）から hou.NodeType を探す。カテゴリを順に引く（無ければ None）。"""
    if not type_name:
        return None
    try:
        categories = hou.nodeTypeCategories()
        for category in categories.values():
            found = category.nodeTypes().get(type_name)
            if found is not None:
                return found
    except Exception:  # noqa: BLE001
        return None
    return None


def parm_template_for(hou, step: dict, parm_name: str, sandbox_path: str = "", mode: str = "auto"):
    """手順のノード（無ければ種類）から、パラメータのテンプレートを取る。取れなければ None。"""
    if not parm_name:
        return None
    try:
        target = resolve_step_target(hou, step, sandbox_path, mode)
        node = target.node
        if node is not None:
            parm = node.parm(parm_name)
            if parm is not None:
                return parm.parmTemplate()
            pt = node.parmTuple(parm_name) if hasattr(node, "parmTuple") else None
            if pt is not None:
                return pt.parmTemplate()
    except Exception:  # noqa: BLE001
        pass
    try:
        node_type = _find_node_type(hou, str(step.get("node_type") or ""))
        if node_type is not None:
            return node_type.parmTemplateGroup().find(parm_name)
    except Exception:  # noqa: BLE001
        pass
    return None


def attach_parm_info(hou, step: dict, sandbox_path: str = "", mode: str = "auto") -> dict:
    """手順のコピーを返す。パラメータごとに、値の言い換えに要る情報（_info）を付ける。hou が無い・取れないときは、そのまま。"""
    out = {**step, "parms": [dict(p) for p in (step.get("parms") or []) if isinstance(p, dict)]}
    if hou is None:
        return out
    for p in out["parms"]:
        info = parm_value_info(parm_template_for(hou, step, str(p.get("name") or ""), sandbox_path, mode))
        if info:
            p["_info"] = info
    return out


# ── 選んでいるノードの説明（Docs タブから使う） ──────────────────────────────

def selected_node_info(hou) -> dict | None:
    """Houdini で選んでいるノードの情報。何も選んでいなければ None。"""
    try:
        nodes = hou.selectedNodes()
    except Exception:  # noqa: BLE001
        return None
    if not nodes:
        return None
    node = nodes[0]
    try:
        node_type = node.type()
        return {
            "path": node.path(),
            "name": node.name(),
            "type_name": node_type.name(),
            "label": node_type.description(),
            "category": node_type.category().name(),
            "count": len(nodes),
        }
    except Exception:  # noqa: BLE001
        return None


def doc_query(info: dict) -> str:
    """ドキュメント検索の語。表示名（Scatter）と、タイプ名の本体（scatter）。"""
    label = str(info.get("label") or "").strip()
    base = _base_type_name(str(info.get("type_name") or ""))
    if label and base and label.lower().replace(" ", "") == base.lower():
        return f"{label} node"
    return " ".join(p for p in (label, base, "node") if p)


def open_node_help(hou, info: dict) -> tuple[bool, str]:
    """Houdini 自身のヘルプ（公式マニュアルの、そのノードのページ）を開く。"""
    try:
        node = hou.node(info["path"])
        hou.ui.displayNodeHelp(node.type())
    except Exception as exc:  # noqa: BLE001
        return False, f"ヘルプを開けませんでした（{exc}）"
    return True, "Houdini のヘルプを開きました"


def current_network_path(hou) -> str:
    """ネットワークエディタが、いま開いている階層のパス。取れなければ ""。"""
    editor = _pane(hou, "network")
    try:
        return editor.pwd().path() if editor is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def step_places(step: dict, sandbox_path: str = "") -> dict:
    """手順が指す場所を、省略せずに（画面に出す用）。
    {"network": 手順のネットワーク, "node": ノード, "sandbox_node": サンドボックスでのノード（あれば）}"""
    rel = str(step.get("node_path") or "")
    node = str(step.get("node") or "")
    parent_rel = _parent_rel(rel)
    sandbox_path = sandbox_path.rstrip("/")
    return {
        "network": own_path(parent_rel) if rel else "",
        "node": own_path(rel) if rel else node,
        "sandbox_node": f"{sandbox_path}/{rel}" if sandbox_path and rel else "",
    }
