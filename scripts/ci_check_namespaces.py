#!/usr/bin/env python3
"""
ci_check_namespaces.py — localRAG/ 配下の未知な namespace を検知する（CI用）

IMPROVEMENT_PLAN.md Phase5:「NAMESPACE_PERMISSIONSに定義のない名前空間への
ドキュメント追加を検知したら失敗させる」という設計だったが、実際に
pep.py の `NAMESPACE_PERMISSIONS`（tool_docs/game_info/research/team_notes/
personal_notes/houdini21）と `localRAG/` の実フォルダ構成を突き合わせたところ、
既存の正当なフォルダ（chat_logs/private_docs/tutorials）がそもそも
NAMESPACE_PERMISSIONS に含まれておらず、pep.py のマップをそのまま基準にすると
初回CI実行時点で既存の正常な構成を誤検知（false positive）することが判明した。

pep.py の NAMESPACE_PERMISSIONS は Cloud RAG 寄りのアクセス制御用途のマップで
あり、「どのローカルフォルダが有効な namespace か」の正とは別物。その正は
auto_index.py の `NAMESPACES` 定数（watchdog が実際にインデックス対象とする
フォルダ一覧）である。本スクリプトはそちらを基準に、`localRAG/` 直下の
フォルダ・ファイルを検証する。

検知対象:
  1. `localRAG/` 直下にあり、`_`/`.` で始まらず、auto_index.NAMESPACES に
     含まれないフォルダ（新しい namespace を追加したのに auto_index.py の
     登録を忘れたケース）
  2. `localRAG/` 直下に直接置かれた `.md` ファイル（namespace フォルダに
     属さない）。vector_database.py の `_namespace_from_path()` はこれを
     `"default"` コレクションに入れてしまい、governance の対象外になる
     抜け道になりうるため、これも検知対象にする。

Usage:
    uv run python scripts/ci_check_namespaces.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))


def main() -> int:
    from auto_index import NAMESPACES

    vault = _REPO_ROOT / "localRAG"
    if not vault.exists():
        print(f"[ci_check_namespaces] localRAG/ が見つかりません（スキップ）: {vault}")
        return 0

    known = set(NAMESPACES)
    unknown_dirs: list[str] = []
    unknown_files: list[str] = []

    for entry in sorted(vault.iterdir()):
        if entry.name.startswith(("_", ".")):
            continue
        if entry.is_dir():
            if entry.name not in known:
                unknown_dirs.append(entry.name)
        elif entry.is_file() and entry.suffix == ".md":
            unknown_files.append(entry.name)

    ok = True
    if unknown_dirs:
        ok = False
        print(f"[ci_check_namespaces] 未知の namespace フォルダを検知: {unknown_dirs}")
        print(f"  既知の namespace（auto_index.NAMESPACES）: {sorted(known)}")
        print("  新しい namespace を追加する場合は auto_index.py の NAMESPACES に登録してください。")
    if unknown_files:
        ok = False
        print(f"[ci_check_namespaces] localRAG/ 直下に namespace フォルダ無しの .md ファイルを検知: {unknown_files}")
        print("  いずれかの namespace フォルダの下に移動してください（'default' namespace への意図しない混入を防ぐため）。")

    if not ok:
        return 1

    print(f"[ci_check_namespaces] OK（{len(known)} namespace すべて既知）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
