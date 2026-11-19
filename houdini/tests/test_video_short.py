"""video_short（動画の短縮版: 要点の手順を選ぶ）のテスト（2026-11-19）。

実行（リポジトリのルートで）:  uv run python -m unittest houdini/tests/test_video_short.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import video_short as vs  # noqa: E402


def step(n: int, tool: str, changes: int = 0, code: bool = False) -> dict:
    s = {"step": n, "tool": tool, "result": f"手順{n}"}
    if changes:
        s["changes"] = [{"name": f"p{i}"} for i in range(changes)]
    if code:
        s["capture"] = {"kind": "code_card"}
    return s


def energy_like() -> list[dict]:
    """炎のエネルギー（58 手順）に近い形: 作る 19・値を変える 28・つなぐ 3・cook 8 ほか。"""
    out = []
    n = 0
    for _ in range(14):
        n += 1
        out.append(step(n, "create_node"))
    for i in range(13):
        n += 1
        out.append(step(n, "set_parameter", changes=1 + i % 4, code=(i % 3 == 0)))
    n += 1; out.append(step(n, "connect_nodes"))
    n += 1; out.append(step(n, "cook_node"))
    for _ in range(5):
        n += 1
        out.append(step(n, "create_node"))
    for i in range(15):
        n += 1
        out.append(step(n, "set_parameter", changes=1 + i % 3))
    n += 1; out.append(step(n, "connect_nodes"))
    n += 1; out.append(step(n, "cook_node"))
    n += 1; out.append(step(n, "set_parameter", changes=2))
    n += 1; out.append(step(n, "cook_node"))
    return out


class LengthModeTest(unittest.TestCase):
    def test_default_is_short_and_only_full_is_full(self) -> None:
        self.assertEqual(vs.length_mode({}), vs.SHORT)
        self.assertEqual(vs.length_mode(None), vs.SHORT)
        self.assertEqual(vs.length_mode({"video_length": "full"}), vs.FULL)
        self.assertEqual(vs.length_mode({"video_length": " FULL "}), vs.FULL)
        self.assertEqual(vs.length_mode({"video_length": "nonsense"}), vs.SHORT)
        self.assertEqual(vs.length_mode({"video_length": ""}), vs.SHORT)

    def test_engine_args(self) -> None:
        self.assertEqual(vs.engine_args(vs.SHORT), ["--short"])
        self.assertEqual(vs.engine_args(vs.FULL), [])


class SelectStepsTest(unittest.TestCase):
    def test_few_steps_are_all_kept(self) -> None:
        steps = [step(i, "create_node") for i in range(1, 8)]
        self.assertEqual(vs.select_steps(steps), steps)
        self.assertEqual(vs.select_steps([]), [])

    def test_the_result_is_capped_in_order(self) -> None:
        steps = energy_like()
        chosen = vs.select_steps(steps)
        self.assertEqual(len(chosen), vs.SHORT_MAX_STEPS)
        numbers = vs.step_numbers(chosen)
        self.assertEqual(numbers, sorted(numbers))
        self.assertTrue(set(numbers) <= set(vs.step_numbers(steps)))

    def test_first_and_last_steps_are_always_kept(self) -> None:
        steps = energy_like()
        numbers = vs.step_numbers(vs.select_steps(steps))
        self.assertEqual(numbers[0], steps[0]["step"])
        self.assertEqual(numbers[-1], steps[-1]["step"])

    def test_the_last_cook_is_kept_even_when_it_is_not_high_scoring(self) -> None:
        steps = [step(1, "create_node")] + [step(i, "set_parameter", changes=5, code=True) for i in range(2, 25)] + [step(25, "cook_node"), step(26, "create_node")]
        numbers = vs.step_numbers(vs.select_steps(steps, max_steps=6))
        self.assertIn(25, numbers)
        self.assertIn(1, numbers)
        self.assertIn(26, numbers)

    def test_code_and_connect_steps_beat_plain_creates(self) -> None:
        steps = [step(1, "create_node")] + [step(i, "create_node") for i in range(2, 12)] + [step(12, "connect_nodes"), step(13, "set_parameter", changes=2, code=True), step(14, "create_node")]
        numbers = vs.step_numbers(vs.select_steps(steps, max_steps=5))
        self.assertIn(12, numbers)
        self.assertIn(13, numbers)

    def test_code_and_cook_steps_are_capped_so_the_video_is_varied(self) -> None:
        steps = (
            [step(1, "create_node")]
            + [step(i, "set_parameter", changes=4, code=True) for i in range(2, 12)]
            + [step(i, "cook_node") for i in range(12, 20)]
            + [step(i, "set_parameter", changes=1) for i in range(20, 30)]
            + [step(30, "connect_nodes"), step(31, "cook_node")]
        )
        chosen = vs.select_steps(steps, max_steps=10)
        self.assertEqual(len(chosen), 10)
        code = [c for c in chosen if c.get("capture")]
        cooks = [c for c in chosen if c["tool"] == "cook_node"]
        self.assertLessEqual(len(code), vs.SHORT_MAX_CODE_STEPS)
        self.assertLessEqual(len(cooks), vs.SHORT_MAX_COOK_STEPS + 1)  # 最後の手順の cook は、数えない
        self.assertIn(30, vs.step_numbers(chosen))
        self.assertIn(31, vs.step_numbers(chosen))

    def test_when_the_cap_leaves_too_few_the_rest_is_filled_with_code(self) -> None:
        steps = [step(i, "set_parameter", changes=4, code=True) for i in range(1, 16)]
        self.assertEqual(len(vs.select_steps(steps, max_steps=8)), 8)

    def test_ties_prefer_the_earlier_step(self) -> None:
        steps = [step(i, "create_node") for i in range(1, 21)]
        numbers = vs.step_numbers(vs.select_steps(steps, max_steps=4))
        self.assertEqual(numbers, [1, 2, 3, 20])  # 最初・最後 + 同点の前のほう

    def test_zero_or_negative_cap(self) -> None:
        self.assertEqual(vs.select_steps(energy_like(), max_steps=0), [])
        self.assertEqual(vs.select_steps(energy_like(), max_steps=-3), [])

    def test_non_dict_entries_are_ignored(self) -> None:
        self.assertEqual(vs.select_steps([None, "x", step(1, "create_node")]), [step(1, "create_node")])

    def test_the_input_is_not_modified(self) -> None:
        steps = energy_like()
        before = [dict(s) for s in steps]
        vs.select_steps(steps)
        self.assertEqual(steps, before)


class HelpersTest(unittest.TestCase):
    def test_step_numbers_skips_bad_values(self) -> None:
        self.assertEqual(vs.step_numbers([{"step": 3}, {"step": "x"}, {}, {"step": "7"}]), [3, 7])

    def test_describe(self) -> None:
        self.assertIn("58 手順のうち 10 手順", vs.describe(58, 10, vs.SHORT))
        self.assertEqual(vs.describe(8, 8, vs.SHORT), "")
        self.assertEqual(vs.describe(58, 58, vs.FULL), "")


if __name__ == "__main__":
    unittest.main()
