"""Reference の説明の品質を、機械で確かめる（2026-11-24）。開発側の道具。公開の前に、保存してある説明の全部（または一部）を調べる。

  uv run python scripts/check_reference_quality.py [--kind node,vex,apex,shelf] [--only sop/scatter,...] [--parms build/reference_parms.json] [--json build/quality_report.json]

調べること（問題の重さ: error = 公開しない / warn = 目で確かめる）:
  error  欄が足りない（何をする・使いどころが空）／上限（700 文字）を超える／日本語が無い／コードブロック・TODO などが混ざる
  error  本物の Houdini との点検（audit_reference.entry_problems）に通らない（パラメータ・ポート・シェルフの名前、VEX の関数の実在）
  warn   項目の名前（表示名・内部名）が、「何をする」に出てこない（別の項目の資料が混ざった疑い）
  warn   資料が 1 件も見つからなかった（docs_found = 0。AI の知識だけで書いたもの）
  warn   同じ「何をする」が、別の項目にもある（コピー）
  warn   数値・断定（「必ず」「すべて」「100%」）が多い／例（example）が空で、使いどころ（when）も短い（薄い説明）

機械で確かめられるのは、形と名前の実在まで。効き方・使いどころの内容が正しいかは、人が読んで確かめる（docs/design/reference-tab.md §7）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "houdini" / "python_panels"))
sys.path.insert(0, str(ROOT / "scripts"))

import reference_data as rd  # noqa: E402

DEFAULT_CONFIG = Path.home() / ".houdini" / "rag_chatbot_config.json"
_JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
_BAD_MARKS = re.compile(r"```|TODO|\bTBD\b|lorem ipsum|【|】", re.IGNORECASE)
_ABSOLUTE = re.compile(r"必ず|すべての|絶対|100\s*%|完全に")


def _norm(text: str) -> str:
    return re.sub(r"[\s_\-:]+", "", str(text or "")).lower()


def subject_names(kind: str, key: str, label: str) -> list[str]:
    """説明の中に、出てくるはずの名前（表示名・内部名・ページ名）。"""
    page = key.split("/")[-1]
    names = {label, page, page.replace("--", " "), page.split("--")[-1]}
    if kind == "shelf":
        names |= {label.replace("Simple ", "")}
    return [n for n in names if n and len(_norm(n)) >= 2]


def check_entry(kind: str, key: str, entry: dict, meta: dict, problems: list[str] | None = None) -> list[tuple[str, str]]:
    """1 件の説明の点検。[(重さ, 内容), ...]。problems は、audit_reference.entry_problems の結果（呼び出し側が渡す）。"""
    out: list[tuple[str, str]] = []
    for field in ("what", "use", "when"):
        if not str(entry.get(field) or "").strip():
            out.append(("error", f"「{field}」が空です"))
    for field in rd.SECTION_KEYS:
        text = str(entry.get(field) or "")
        if len(text) > rd.MAX_FIELD_CHARS:
            out.append(("error", f"「{field}」が {len(text)} 文字（上限 {rd.MAX_FIELD_CHARS}）"))
        if text and _BAD_MARKS.search(text):
            out.append(("error", f"「{field}」に、コードブロック・TODO・【】などが混ざっています"))
    whole = " ".join(str(entry.get(f) or "") for f in rd.SECTION_KEYS)
    if not _JAPANESE.search(whole):
        out.append(("error", "日本語がありません"))
    for line in problems or []:
        out.append(("error", line))
    what = _norm(entry.get("what"))
    label = str(meta.get("label") or key.split("/")[-1])
    if what and not any(_norm(n) in what for n in subject_names(kind, key, label)):
        out.append(("warn", f"「何をする」に、項目の名前（{label}）が出てきません（別の項目の資料が混ざった疑い）"))
    if int(meta.get("docs_found", 1) or 0) == 0:
        out.append(("warn", "資料が見つかりませんでした（AI の知識だけで書いたもの）"))
    if _ABSOLUTE.search(whole):
        out.append(("warn", "断定の言い方（必ず・すべて・絶対・100%・完全に）があります"))
    if not str(entry.get("example") or "").strip() and len(str(entry.get("when") or "")) < 60:
        out.append(("warn", "例が空で、使いどころも短い（薄い説明）"))
    return out


def load_saved(base_dir: str, kinds: set[str], only: set[str]) -> list[dict]:
    """保存した説明の一覧: [{"kind", "key", "entry", "meta"}]。キーは、ファイルの中身（label）と、一覧データから戻す。"""
    out = []
    for kind in sorted(kinds):
        folder = Path(base_dir) / "localRAG" / "reference" / kind
        if not folder.is_dir():
            continue
        by_slug = {rd.slug(i["key"]): i["key"] for i in rd.catalog(kind)} if kind in ("node", "vex", "apex") else {}
        for path in sorted(folder.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            key = by_slug.get(path.stem) or path.stem.replace("_", "/", 1)
            if only and key not in only:
                continue
            entry = {k: data.get(k, "") for k in rd.SECTION_KEYS}
            out.append({"kind": kind, "key": key, "entry": entry, "meta": {k: v for k, v in data.items() if k not in rd.SECTION_KEYS}})
    return out


def run(items: list[dict], parms: dict | None) -> dict:
    from audit_reference import entry_problems

    report: dict = {"total": len(items), "error": 0, "warn": 0, "items": []}
    seen_what: dict[str, str] = {}
    for item in items:
        kind, key = item["kind"], item["key"]
        problems = entry_problems(kind, key, item["entry"], parms) if parms is not None else []
        found = check_entry(kind, key, item["entry"], item["meta"], problems)
        what = _norm(item["entry"].get("what"))
        if what:
            if what in seen_what and seen_what[what] != key:
                found.append(("warn", f"「何をする」が、{seen_what[what]} と同じです"))
            seen_what.setdefault(what, key)
        if found:
            report["items"].append({"kind": kind, "key": key, "issues": [{"level": lv, "message": msg} for lv, msg in found]})
            report["error"] += sum(1 for lv, _ in found if lv == "error")
            report["warn"] += sum(1 for lv, _ in found if lv == "warn")
    report["errors_in"] = sum(1 for i in report["items"] if any(x["level"] == "error" for x in i["issues"]))
    report["warns_in"] = sum(1 for i in report["items"] if all(x["level"] == "warn" for x in i["issues"]))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kind", default="node,vex,apex,shelf")
    parser.add_argument("--only", default="")
    parser.add_argument("--parms", default=str(ROOT / "build" / "reference_parms.json"), help="audit_reference.py の出力。無ければ、名前の点検を省く")
    parser.add_argument("--json", default="", help="結果を書き出すファイル")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args(argv)
    try:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    base_dir = str(os.environ.get("RAGREEL_BRIDGE_DIR") or cfg.get("local_bridge_dir") or "")
    items = load_saved(base_dir, {k.strip() for k in args.kind.split(",") if k.strip()}, {k.strip() for k in args.only.split(",") if k.strip()})
    from audit_reference import load_parms

    parms = load_parms(Path(args.parms))
    if parms is None:
        print("（本物の Houdini との点検の結果が無いので、名前の点検は省きます。先に audit_reference.py を実行してください）")
    report = run(items, parms)
    for item in report["items"]:
        for issue in item["issues"]:
            print(f"  {'NG  ' if issue['level'] == 'error' else '注意'} {item['key']}: {issue['message']}")
    print(f"点検 {report['total']} 件 / error {report['error']} 件（{report['errors_in']} 項目）/ warn {report['warn']} 件")
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if report["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
