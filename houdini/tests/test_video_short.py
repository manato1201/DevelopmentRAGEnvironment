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
    n += 1
    out.append(step(n, "connect_nodes"))
    n += 1
    out.append(step(n, "cook_node"))
    for _ in range(5):
        n += 1
        out.append(step(n, "create_node"))
    for i in range(15):
        n += 1
        out.append(step(n, "set_parameter", changes=1 + i % 3))
    n += 1
    out.append(step(n, "connect_nodes"))
    n += 1
    out.append(step(n, "cook_node"))
    n += 1
    out.append(step(n, "set_parameter", changes=2))
    n += 1
    out.append(step(n, "cook_node"))
    return out


class LengthModeTest(unittest.TestCase):
    def test_default_is_full_and_only_short_is_short(self) -> None:
        # 2026-11-22: 既定は完全版（全部の手順を、1 手順ずつ解説する）。短縮版は、1 場面に複数の手順をまとめるので、粗く、短すぎた
        self.assertEqual(vs.length_mode({}), vs.FULL)
        self.assertEqual(vs.length_mode(None), vs.FULL)
        self.assertEqual(vs.length_mode({"video_length": "short"}), vs.SHORT)
        self.assertEqual(vs.length_mode({"video_length": " SHORT "}), vs.SHORT)
        self.assertEqual(vs.length_mode({"video_length": "nonsense"}), vs.FULL)
        self.assertEqual(vs.length_mode({"video_length": ""}), vs.FULL)
        self.assertEqual(vs.engine_args(vs.FULL), [], "the full video does not drop the other chapters")

    def test_engine_args(self) -> None:
        self.assertEqual(vs.engine_args(vs.SHORT), ["--short"])
        self.assertEqual(vs.engine_args(vs.FULL), [])


class GroupStepsTest(unittest.TestCase):
    """全部の手順が、順番を保ったまま、連続した場面に入る（飛ばさない）。2026-11-20: 点数で 10 手順だけ選ぶ方式は、話が飛ぶ動画になった。"""

    def test_few_steps_are_not_grouped(self) -> None:
        steps = [step(i, "create_node") for i in range(1, 8)]
        self.assertEqual(vs.group_steps(steps), steps)
        self.assertEqual(vs.group_steps([]), [])

    def test_every_step_is_in_exactly_one_scene_in_order(self) -> None:
        for steps in (energy_like(), [step(i, "create_node") for i in range(1, 42)], [step(i, "set_parameter", changes=2) for i in range(1, 14)]):
            groups = vs.plan_groups(steps)
            flat = [i for g in groups for i in g]
            self.assertEqual(flat, list(range(len(steps))), "no step is skipped or repeated")
            self.assertLessEqual(len(groups), vs.SHORT_MAX_GROUPS)
            self.assertTrue(all(g == list(range(g[0], g[-1] + 1)) for g in groups), "each scene is a run of consecutive steps")

    def test_the_video_gets_the_last_step_of_each_scene_with_what_it_covers(self) -> None:
        steps = [step(i, "create_node") for i in range(1, 31)]
        scenes = vs.group_steps(steps)
        self.assertEqual(len(scenes), vs.SHORT_MAX_GROUPS)
        covered = [n for s in scenes for n in (s.get("covers") or [s["step"]])]
        self.assertEqual(covered, list(range(1, 31)))
        for scene in scenes:
            if scene.get("covers"):
                self.assertEqual(scene["covers"][-1], scene["step"], "the screen shows the state after the last step")
                self.assertEqual([c["step"] for c in scene["covered"]], scene["covers"])

    def test_the_last_step_is_always_in_the_last_scene_and_the_first_in_the_first(self) -> None:
        steps = energy_like()
        scenes = vs.group_steps(steps)
        self.assertEqual(scenes[-1]["step"], steps[-1]["step"])
        first = scenes[0]
        self.assertEqual((first.get("covers") or [first["step"]])[0], steps[0]["step"])

    def test_the_41_step_case_from_the_real_run(self) -> None:
        """実機の動画（41 手順）: 前の方式は 1・7・12・13・17・19・27・31・34・41 だけで、間が飛んでいた。"""
        tools = ["create_node"] * 6 + ["connect_nodes"] * 6 + ["cook_node"] + ["set_parameter"] * 3 + ["cook_node"] + ["set_parameter"] * 1 + ["cook_node"]
        tools += ["set_parameter"] * 7 + ["connect_nodes"] * 4 + ["set_parameter"] * 6 + ["cook_node"] * 1 + ["set_parameter"] * 3
        steps = [step(i + 1, t) for i, t in enumerate(tools[:41])]
        scenes = vs.group_steps(steps)
        numbers = [n for s in scenes for n in (s.get("covers") or [s["step"]])]
        self.assertEqual(numbers, list(range(1, len(steps) + 1)))
        self.assertLessEqual(len(scenes), vs.SHORT_MAX_GROUPS)

    def test_scene_ends_move_to_a_nearby_cook_so_the_checked_state_is_on_screen(self) -> None:
        steps = [step(i, "set_parameter") for i in range(1, 25)]
        steps[10] = step(11, "cook_node")  # 位置 10。理想の終わりは 11 のそば
        scenes = vs.group_steps(steps, max_groups=2)
        self.assertEqual(scenes[0]["step"], 11)

    def test_covered_is_bounded_and_text_is_short(self) -> None:
        long = {"step": 1, "tool": "create_node", "result": "あ" * 500 + "\n2行目", "tool_result": "い" * 500}
        steps = [long] + [step(i, "create_node") for i in range(2, 40)]
        scenes = vs.group_steps(steps, max_groups=1)
        covered = scenes[0]["covered"]
        self.assertLessEqual(len(covered), vs.COVERED_MAX)
        self.assertLessEqual(len(covered[0]["result"]), vs.COVERED_TEXT_MAX)
        self.assertNotIn("2行目", covered[0]["result"])
        self.assertEqual(len(scenes[0]["covers"]), 39, "covers lists all of them even when covered is bounded")

    def test_zero_or_negative_cap(self) -> None:
        self.assertEqual(vs.group_steps(energy_like(), max_groups=0), [])
        self.assertEqual(vs.group_steps(energy_like(), max_groups=-3), [])

    def test_non_dict_entries_are_ignored(self) -> None:
        self.assertEqual(vs.group_steps([None, "x", step(1, "create_node")]), [step(1, "create_node")])

    def test_the_input_is_not_modified(self) -> None:
        steps = energy_like()
        before = [dict(s) for s in steps]
        vs.group_steps(steps)
        self.assertEqual(steps, before)


class GroupedScriptTest(unittest.TestCase):
    """場面（複数の手順をまとめたもの）の台本: 中の操作を飛ばさず説明させ、見出しに手順書の範囲を出す。"""

    def scene(self) -> dict:
        steps = [
            {"step": 7, "tool": "connect_nodes", "result": "star_base の出力を、star_shape_move の入力につなぐ", "tool_result": "接続しました"},
            {"step": 8, "tool": "connect_nodes", "result": "star_shape_move の出力を、fairy_dust の入力につなぐ", "tool_result": "接続しました"},
            {"step": 9, "tool": "cook_node", "result": "fairy_dust を評価（cook）して、エラーが出ないことを確認する", "tool_result": "cook 成功"},
        ]
        return vs.group_steps(steps, max_groups=1)[0]

    def test_the_prompt_lists_every_operation_of_the_scene(self) -> None:
        import video_script as vsc

        prompt = vsc.build_user_prompt("題", "本文", [self.scene()])
        self.assertIn("この場面にまとめる操作", prompt)
        for n in (7, 8, 9):
            self.assertIn(f"手順{n}:", prompt)
        self.assertIn("1つも飛ばさずに", vsc.system_prompt("basic"))

    def test_a_single_step_has_no_scene_block(self) -> None:
        import video_script as vsc

        prompt = vsc.build_user_prompt("題", "本文", [{"step": 1, "tool": "create_node", "result": "x"}])
        self.assertNotIn("この場面にまとめる操作", prompt)

    def test_the_heading_shows_the_range_in_the_written_tutorial_and_no_target_sentence_is_prepended(self) -> None:
        import video_script as vsc

        scene = self.scene()
        model = {"steps": [{"step": 9, "heading": "発生源を粒子につなぐ",
                            "narration": "スターベースをスターシェイプムーブにつなぎ、さらにフェアリーダストへつなぎます。最後にクックして、エラーが出ないことを確かめます。ここで粒子が見えれば正しいです。"}]}
        script, _source, notes = vsc.assemble_script(model, [scene], "題", "概要")
        entry = script["steps"][0]
        self.assertEqual(entry["heading"], "発生源を粒子につなぐ（手順書の7〜9）")
        self.assertEqual(entry["covers"], [7, 8, 9])
        self.assertTrue(entry["narration"].startswith("スターベース"), "nothing is put in front of the narration")
        self.assertFalse([n for n in notes if "対象の名前" in n])

    def test_a_long_heading_is_cut_before_the_range(self) -> None:
        import video_script as vsc

        model = {"steps": [{"step": 9, "heading": "とても長い見出しで二十字をこえるものです", "narration": "あ" * 60 + "をつなぎます。"}]}
        script, _s, _n = vsc.assemble_script(model, [self.scene()], "題", "概要")
        heading = script["steps"][0]["heading"]
        self.assertTrue(heading.endswith("（手順書の7〜9）"))
        self.assertLessEqual(len(heading), 18 + len("（手順書の7〜9）"))

    def test_the_template_fallback_goes_through_all_the_steps_of_the_scene(self) -> None:
        import video_script as vsc

        script, source, _n = vsc.assemble_script(None, [self.scene()], "題", "概要")
        self.assertEqual(source, "template")
        narration = script["steps"][0]["narration"]
        self.assertIn("star_base", narration)
        self.assertIn("fairy_dust", narration)
        self.assertTrue(script["steps"][0]["heading"].endswith("（手順書の7〜9）"))

    def test_the_quality_check_does_not_demand_the_last_steps_target_in_a_scene(self) -> None:
        import video_script as vsc

        scene = self.scene()
        issues = vsc.check_step_quality(scene, {"narration": "スターベースからフェアリーダストまでをつなぎ、クックで確かめます。", "step": 9})
        self.assertFalse([i for i in issues if i["code"] == "target_not_named"])


class HelpersTest(unittest.TestCase):
    def test_step_numbers_skips_bad_values(self) -> None:
        self.assertEqual(vs.step_numbers([{"step": 3}, {"step": "x"}, {}, {"step": "7"}]), [3, 7])

    def test_describe(self) -> None:
        self.assertIn("58 手順を 10 場面", vs.describe(58, 10, vs.SHORT))
        self.assertEqual(vs.describe(8, 8, vs.SHORT), "")
        self.assertEqual(vs.describe(58, 58, vs.FULL), "")


if __name__ == "__main__":
    unittest.main()
