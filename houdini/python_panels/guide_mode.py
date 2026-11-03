"""
guide_mode.py — 案内モード: 手順ごとに「見るタブ・操作するノード・変えるパラメータ・使うショートカット」を示す（2026-11-03）

初心者レビューで出た詰まりどころ（ショートカットが大事／操作項目が多くて戸惑う／確認するタブが分からない／
ノードを知らない）への対応。画面の部品を「消す」のではなく、必要な場所を「示す」。Houdini の画面は変えない
（タブを前面に出す・ノードを選んで画面に収める・短い表示を出す、だけ。色や設定は書き換えない）。

  ・生成時に、手順ごとの案内データ（guide）を記録する（houdini_tools.py）。保存時に `<名前>_guide.json` へ書く（tutorial_view.py）。
  ・案内タブ（guide_view.py）が読み込み、手順を1つずつ示す。
  ・Houdini を触る部分（hou）は引数で受け取る。画面の無い環境でも、データの組み立てと検索はテストできる。

ショートカットは、SideFX の公式ドキュメント（Network editor shortcuts / Network navigation）で確かめたものだけを載せる。
確かめていないもの（例: レイアウトの L）は載せない。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

GUIDE_VERSION = 1
GUIDE_SUFFIX = "_guide.json"

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

# 出典: https://www.sidefx.com/docs/houdini/network/shortcuts.html / https://www.sidefx.com/docs/houdini/network/navigate.html
# （ここに無いキーは、公式で確かめられなかったもの。足すときは出典を確かめてから）
TOOL_SHORTCUTS: dict[str, list[tuple[str, str]]] = {
    "create_node": [("Tab", "ネットワークエディタの上で押すと、ノードの検索メニューが開く。名前を打って Enter")],
    "connect_nodes": [
        ("ドラッグ", "上のノードの出力（下の丸）から、下のノードの入力（上の丸）へ線を引く"),
        ("Y を押しながらドラッグ", "横切った線を切る（つなぎ間違えたとき）"),
    ],
}
NETWORK_SHORTCUTS: list[tuple[str, str]] = [
    ("G", "選んでいるノードを、画面いっぱいに映す"),
    ("H", "ネットワーク全体を映す"),
]
UNDO_SHORTCUT: tuple[str, str] = ("Ctrl+Z", "直前の操作を取り消す")


# ── 案内データの組み立て ─────────────────────────────────────────────────────

_CREATE_RE = re.compile(r"「(.+?)」ノード（([^）]+)）を作り、名前を (\S+) にする")
_CREATE_TOP_RE = re.compile(r"Object レベルに「(.+?)」ノードを作り、名前を (\S+) にする")
_CONNECT_RE = re.compile(r"^(\S+) の出力を、(\S+) の")
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


def _hint(tool: str, g: dict) -> str:
    """その手順で何をするかの、短い案内（画面に出す）。"""
    node = g.get("node") or ""
    if tool == "create_node":
        label = g.get("node_label") or g.get("node_type") or "ノード"
        return f"ネットワークエディタで Tab を押し、「{label}」と入力して Enter。名前は {node} にします" if node else f"Tab を押して「{label}」を作ります"
    if tool == "connect_nodes":
        return f"{g.get('from') or '上のノード'} の出力から、{g.get('to') or node} の入力へ線を引きます"
    if tool == "set_parameter":
        lines = []
        for p in g.get("parms") or []:
            where = f"（場所: {p['where']}）" if p.get("where") else ""
            old = f"{p['old']} → " if p.get("old") not in (None, "") else ""
            lines.append(f"{p.get('label') or p.get('name')}: {old}{p.get('new')}{where}")
        return f"{node} のパラメータを変えます。" + (" / ".join(lines) if lines else "")
    if tool == "cook_node":
        return f"{node} を表示して、ビューポートで形を確認します。点の数や属性の値は、Geometry Spreadsheet で見られます"
    if tool == "delete_node":
        return f"{node} を選んで Delete キーで削除します"
    return ""


def build_guide(step_screenshots: list[dict], title: str = "", level: str = "", extras: dict | None = None) -> dict:
    """手順の記録（result.step_screenshots）から案内データを作る。画像のパスなどは入れない。"""
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
        shortcuts = list(TOOL_SHORTCUTS.get(tool, []))
        if tab == "network":
            shortcuts += NETWORK_SHORTCUTS
        if tool in ("create_node", "connect_nodes", "delete_node", "set_parameter"):
            shortcuts.append(UNDO_SHORTCUT)
        steps.append({
            "step": s.get("step") if isinstance(s.get("step"), int) else i,
            "tool": tool,
            "instruction": str(s.get("result") or "").split("\n", 1)[0][:200],
            "node": str(g.get("node") or ""),
            "node_path": str(g.get("node_path") or ""),
            "node_type": str(g.get("node_type") or ""),
            "node_label": str(g.get("node_label") or ""),
            "parms": [p for p in (g.get("parms") or []) if isinstance(p, dict)][:12],
            "from": str(g.get("from") or ""),
            "to": str(g.get("to") or ""),
            "tab": tab,
            "tab_label": TAB_LABELS[tab],
            "shortcuts": [{"keys": k, "what": w} for k, w in shortcuts],
            "hint": _hint(tool, g),
        })
    guide = {"version": GUIDE_VERSION, "title": title, "level": level, "steps": steps}
    for key, value in (extras or {}).items():
        if value:
            guide[key] = value
    return guide


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


def guide_path_for(md_path: Path) -> Path:
    return md_path.with_name(md_path.stem + GUIDE_SUFFIX)


def write_guide(path: Path, guide: dict) -> None:
    path.write_text(json.dumps(guide, ensure_ascii=False, indent=2), encoding="utf-8")


def load_guide(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list) or not data["steps"]:
        return None
    return data


def list_guides(tutorials_dir: Path | None) -> list[tuple[str, Path]]:
    """保存済みの案内データを新しい順に。戻り値: [(表示名, パス)]。"""
    if tutorials_dir is None or not Path(tutorials_dir).is_dir():
        return []
    items: list[tuple[float, str, Path]] = []
    for path in Path(tutorials_dir).glob(f"*{GUIDE_SUFFIX}"):
        data = load_guide(path)
        if data is None:
            continue
        level = f"［{data['level']}］" if data.get("level") else ""
        name = f"{data.get('title') or path.name[: -len(GUIDE_SUFFIX)]}{level}（{len(data['steps'])}手順）"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        items.append((mtime, name, path))
    items.sort(key=lambda t: t[0], reverse=True)
    return [(name, path) for _m, name, path in items]


# ── Houdini の画面を動かす（hou は引数。画面を書き換えず、示すだけ） ───────────────

_MAX_SEARCH = 3000


def _pane(hou, tab: str):
    for name in _PANE_TYPE_NAMES.get(tab, ()):
        pane_type = getattr(hou.paneTabType, name, None)
        if pane_type is None:
            continue
        try:
            pane = hou.ui.paneTabOfType(pane_type)
        except Exception:  # noqa: BLE001
            pane = None
        if pane is not None:
            return pane
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


def find_node(hou, name: str, type_name: str = ""):
    """学習者のネットワークから、名前（なければ種類）が合うノードを探す。戻り値: (ノード or None, "name"|"type"|"")。
    探す範囲は、今開いているネットワークとその中身、次に /obj の中。重い探索にならないよう上限がある。"""
    roots = []
    editor = _pane(hou, "network")
    try:
        if editor is not None:
            roots.append(editor.pwd())
    except Exception:  # noqa: BLE001
        pass
    try:
        obj = hou.node("/obj")
        if obj is not None:
            roots.append(obj)
    except Exception:  # noqa: BLE001
        pass
    base = _base_type_name(type_name)
    by_type = None
    seen = 0
    for root in roots:
        if root is None:
            continue
        try:
            candidates = [root] + list(root.allSubChildren())
        except Exception:  # noqa: BLE001
            continue
        for node in candidates:
            seen += 1
            if seen > _MAX_SEARCH:
                break
            try:
                if name and node.name() == name:
                    return node, "name"
                if by_type is None and base and _base_type_name(node.type().name()) == base and node.path() != "/":
                    by_type = node
            except Exception:  # noqa: BLE001
                continue
    return (by_type, "type") if by_type is not None else (None, "")


def show_nodes(hou, wanted: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """ノードを選び、ネットワークエディタをそこへ寄せて、短い表示を出す。
    wanted: [(名前, タイプ名)]。戻り値: (見つけたノード名, 見つからなかった名前)。"""
    found = []
    missing = []
    for name, type_name in wanted:
        node, _how = find_node(hou, name, type_name)
        if node is None:
            missing.append(name)
        else:
            found.append(node)
    if not found:
        return [], missing
    try:
        found[0].setCurrent(True, clear_all_selected=True)  # 選択 + パラメータ画面がこのノードに追従する
        for extra in found[1:]:
            extra.setSelected(True)
    except Exception:  # noqa: BLE001
        return [], missing
    editor = _pane(hou, "network")
    if editor is not None:
        try:
            parent = found[0].parent()
            if parent is not None and editor.pwd().path() != parent.path():
                editor.setPwd(parent)
            editor.homeToSelection()
            if hasattr(editor, "flashMessage"):
                editor.flashMessage(None, "ここを操作します: " + "、".join(n.name() for n in found), 3.0)
        except Exception:  # noqa: BLE001 -- 示せなくても、選択はできている
            pass
    return [n.name() for n in found], missing


def apply_step(hou, step: dict) -> list[str]:
    """1つの手順を案内する: ノードを示し、見るタブを前面に出す。戻り値: 画面に出すメッセージ。"""
    messages: list[str] = []
    tool = step.get("tool")
    wanted: list[tuple[str, str]] = []
    if tool == "connect_nodes":
        wanted = [(step.get("from") or "", ""), (step.get("to") or step.get("node") or "", "")]
    elif step.get("node"):
        wanted = [(step["node"], step.get("node_type") or "")]
    wanted = [(n, t) for n, t in wanted if n]
    if wanted:
        found, missing = show_nodes(hou, wanted)
        if found:
            messages.append("示したノード: " + "、".join(found))
        if missing and tool == "create_node":
            messages.append(f"「{step.get('node_label') or step.get('node_type') or missing[0]}」はまだありません。Tab で作ります")
        elif missing:
            messages.append("見つからないノード: " + "、".join(missing) + "（前の手順で作ります）")
    ok, message = show_tab(hou, step.get("tab") or "network")
    messages.append(message)
    return messages


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
