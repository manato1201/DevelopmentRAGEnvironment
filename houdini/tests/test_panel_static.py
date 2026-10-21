"""パネルのコードの静的な検査（標準の unittest。Houdini・Qt は読み込まない）。

2026-10-21: TutorialGeneratePanel が、自分のクラスに無い self._make_agent を呼んでいて、実機で動画生成が
AttributeError で始まらなかった。Houdini の中でしか動かない画面コードは、単体テストが届かないので、
「self._xxx（アンダースコア始まり）で参照しているのに、そのクラス（と、同じファイル内の親クラス）の中で
定義も代入もされていない名前」を、構文木で見つける。Qt の部品が持つ名前にアンダースコア始まりのものは
無いので、誤検出は起きにくい。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PANELS = Path(__file__).resolve().parents[1] / "python_panels"


def _defined_and_used(cls: ast.ClassDef) -> tuple[set[str], dict[str, int]]:
    defined: set[str] = set()
    used: dict[str, int] = {}
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            if isinstance(node.ctx, ast.Store):
                defined.add(node.attr)
            elif node.attr.startswith("_") and not node.attr.startswith("__"):
                used.setdefault(node.attr, node.lineno)
    return defined, used


def undefined_private_attributes(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    problems: list[str] = []

    def inherited(cls: ast.ClassDef, seen: set[str]) -> set[str]:
        defined, _ = _defined_and_used(cls)
        for base in cls.bases:
            if (
                isinstance(base, ast.Name)
                and base.id in classes
                and base.id not in seen
            ):
                seen.add(base.id)
                defined |= inherited(classes[base.id], seen)
        return defined

    for name, cls in classes.items():
        defined = inherited(cls, {name})
        _, used = _defined_and_used(cls)
        for attr, line in sorted(used.items(), key=lambda kv: kv[1]):
            if attr not in defined:
                problems.append(
                    f"{path.name}:{line} {name}.{attr} が、どこにも定義・代入されていません"
                )
    return problems


class PanelStaticTest(unittest.TestCase):
    def test_no_undefined_private_attributes(self) -> None:
        problems: list[str] = []
        for path in sorted(PANELS.glob("*.py")):
            problems += undefined_private_attributes(path)
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_checker_catches_the_original_bug(self) -> None:
        source = (
            "class Panel:\n    def go(self):\n        return Worker(self._make_agent)\n"
        )
        tmp = PANELS.parent / "tests" / "_tmp_static_sample.py"
        tmp.write_text(source, encoding="utf-8")
        try:
            problems = undefined_private_attributes(tmp)
        finally:
            tmp.unlink()
        self.assertEqual(len(problems), 1)
        self.assertIn("Panel._make_agent", problems[0])

    def test_inherited_and_assigned_names_are_not_flagged(self) -> None:
        source = (
            "class Base:\n"
            "    def _helper(self):\n"
            "        return 1\n"
            "class Child(Base):\n"
            "    def __init__(self):\n"
            "        self._x = 1\n"
            "    def go(self):\n"
            "        return self._helper() + self._x\n"
        )
        tmp = PANELS.parent / "tests" / "_tmp_static_sample2.py"
        tmp.write_text(source, encoding="utf-8")
        try:
            problems = undefined_private_attributes(tmp)
        finally:
            tmp.unlink()
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
