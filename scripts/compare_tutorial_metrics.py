"""
compare_tutorial_metrics.py — チュートリアル生成の指標（localRAG/tutorials/*_metrics.json）を、条件ごとに集計して比べる。

使い方（リポジトリのルートで）:
  uv run python scripts/compare_tutorial_metrics.py                 # doc_tools の有無で比べる（既定）
  uv run python scripts/compare_tutorial_metrics.py --by domain     # 領域別
  uv run python scripts/compare_tutorial_metrics.py --by model --dir localRAG/tutorials

「ドキュメント検索ツール（search_docs / get_doc）で質が上がったか」を測るための道具。
同じ題材を、環境変数 RAG_TUTORIAL_DOC_TOOLS=0（なし）と、未設定（あり）で生成し、このスクリプトで比べる。
- doc_tools の項目が無い古い指標は「なし(従来)」として扱う。
- 1グループの件数が少ないうちは、平均の差は偶然の範囲に入る。件数（n）を必ず見ること。
- 引用率（rag_extraction_rate）は -1（打ち切りで未計測）を除いて平均する。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

# (表示名, 指標のキー, 小数の桁)。-1 は「未計測」なので平均から除く指標は UNMEASURED_AS_MINUS_ONE に入れる。
COLUMNS = [
    ("完了率", "completed", 2),
    ("反復", "iterations", 1),
    ("cook失敗", "cook_errors", 2),
    ("差し戻し", "confirm_rejections", 2),
    ("費用$", "cost_usd", 3),
    ("秒", "elapsed_seconds", 0),
    ("設計点", "lesson_score", 1),
    ("引用率", "rag_extraction_rate", 2),
    ("最初の引用率", "rag_initial_extraction_rate", 2),
    ("検索", "doc_searches", 1),
    ("全文", "doc_reads", 1),
]
UNMEASURED_AS_MINUS_ONE = {"rag_extraction_rate", "rag_initial_extraction_rate", "lesson_score"}


def load_metrics(directory: Path) -> list[dict]:
    rows = []
    for path in sorted(directory.glob("*_metrics.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            data["_file"] = path.name
            rows.append(data)
    return rows


def group_key(row: dict, by: str) -> str:
    if by == "doc_tools":
        return "あり(doc_tools)" if row.get("doc_tools") else "なし(従来)"
    return str(row.get(by, "-"))


def _numbers(rows: list[dict], key: str) -> list[float]:
    values = []
    for row in rows:
        v = row.get(key)
        if isinstance(v, bool):
            v = 1.0 if v else 0.0
        if not isinstance(v, (int, float)):
            continue
        if key in UNMEASURED_AS_MINUS_ONE and v < 0:
            continue
        values.append(float(v))
    return values


def summarize(rows: list[dict], by: str = "doc_tools") -> dict[str, dict]:
    """グループ名 -> {"n": 件数, キー: 平均 or None}。"""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(group_key(row, by), []).append(row)
    out: dict[str, dict] = {}
    for name, members in sorted(groups.items()):
        entry: dict = {"n": len(members)}
        for _label, key, _digits in COLUMNS:
            values = _numbers(members, key)
            entry[key] = statistics.fmean(values) if values else None
            entry[key + "_n"] = len(values)
        out[name] = entry
    return out


def render(summary: dict[str, dict], by: str) -> str:
    header = [by.ljust(16), "n".rjust(3)] + [label.rjust(8) for label, _k, _d in COLUMNS]
    lines = [" ".join(header)]
    for name, entry in summary.items():
        cells = [name.ljust(16), str(entry["n"]).rjust(3)]
        for _label, key, digits in COLUMNS:
            v = entry.get(key)
            cells.append(("-" if v is None else f"{v:.{digits}f}").rjust(8))
        lines.append(" ".join(cells))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default="localRAG/tutorials", help="指標(*_metrics.json)のあるフォルダ")
    parser.add_argument("--by", default="doc_tools", help="グループ分けのキー（doc_tools / domain / model / level など）")
    args = parser.parse_args(argv)

    rows = load_metrics(Path(args.dir))
    if not rows:
        print(f"指標が見つかりません: {args.dir}", file=sys.stderr)
        return 1
    print(render(summarize(rows, args.by), args.by))
    print(f"\n合計 {len(rows)} 件。件数が少ないグループの平均は、偶然の範囲に入ります。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
