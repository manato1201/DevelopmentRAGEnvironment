"""作って消したノードの手順を、動画とガイドから省く（trial_pruning。2026-11-06）のテスト。
実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "python_panels"))

import trial_pruning as tp  # noqa: E402


def create(name): return {"tool": "create_node", "result": f"「X」ノード（x）を作り、名前を {name} にする", "guide": {"node": name}}
def delete(name): return {"tool": "delete_node", "result": f"{name} を削除する", "guide": {"node": name}}
def setp(name): return {"tool": "set_parameter", "result": f"{name} のパラメータを設定: A を 1", "guide": {"node": name}}
def cook(name): return {"tool": "cook_node", "result": f"{name} をクック", "guide": {"node": name}}


def connect(src, dst, index=0):
    text = f"{src} の出力を、{dst} の入力につなぐ" if index == 0 else f"{src} の出力を、{dst} の{index + 1}番目の入力につなぐ"
    return {"tool": "connect_nodes", "result": text, "guide": {"from": src, "to": dst, "input": index}}


def group(pairs):
    shown = "、".join(f"{a} → {b}" for a, b, _ in pairs)
    return {
        "tool": "connect_nodes", "result": f"{len(pairs)}本のノードをつなぐ: {shown}",
        "guide": {"from": pairs[-1][0], "to": pairs[-1][1], "input": pairs[-1][2],
                  "connections": [{"from": a, "to": b, "input": i} for a, b, i in pairs]},
    }


def numbered(steps):
    return [dict(s, step=i) for i, s in enumerate(steps, start=1)]


class PruneTest(unittest.TestCase):
    def tools(self, steps):
        return [(s["tool"], (s.get("guide") or {}).get("node") or s["result"][:12]) for s in steps]

    def test_a_node_that_was_created_and_deleted_leaves_no_steps(self):
        steps = numbered([create("a"), create("tmp"), setp("tmp"), connect("a", "tmp"), cook("tmp"), delete("tmp"), cook("a")])
        kept, dropped = tp.prune_failed_trials(steps)
        self.assertEqual([s["tool"] for s in kept], ["create_node", "cook_node"])
        self.assertEqual(len(dropped), 5)
        self.assertEqual([s["step"] for s in kept], [1, 2], "the numbers start again from 1")

    def test_a_name_that_is_reused_counts_as_a_new_node(self):
        steps = numbered([create("a"), create("pts"), delete("pts"), create("pts"), setp("pts"), connect("a", "pts")])
        kept, dropped = tp.prune_failed_trials(steps)
        self.assertEqual([s["tool"] for s in kept], ["create_node", "create_node", "set_parameter", "connect_nodes"])
        self.assertEqual(len(dropped), 2, "only the first, deleted pts goes")

    def test_nodes_that_stay_are_never_dropped(self):
        steps = numbered([create("a"), setp("a"), create("b"), connect("a", "b"), cook("b")])
        kept, dropped = tp.prune_failed_trials(steps)
        self.assertEqual(len(kept), 5)
        self.assertEqual(dropped, [])

    def test_a_grouped_connection_keeps_only_the_living_pairs(self):
        steps = numbered([
            create("a"), create("b"), create("tmp"),
            group([("a", "b", 0), ("b", "tmp", 0), ("tmp", "b", 1)]),
            delete("tmp"),
        ])
        kept, _ = tp.prune_failed_trials(steps)
        connect_step = [s for s in kept if s["tool"] == "connect_nodes"][0]
        self.assertEqual(connect_step["result"], "a の出力を、b の入力につなぐ", "one pair left: it reads as a single connection")
        self.assertEqual((connect_step["guide"]["from"], connect_step["guide"]["to"]), ("a", "b"))
        self.assertNotIn("connections", connect_step["guide"])

    def test_a_group_with_several_living_pairs_stays_a_group(self):
        steps = numbered([
            create("a"), create("b"), create("c"), create("tmp"),
            group([("a", "b", 0), ("b", "c", 0), ("c", "tmp", 0)]),
            delete("tmp"),
        ])
        kept, _ = tp.prune_failed_trials(steps)
        connect_step = [s for s in kept if s["tool"] == "connect_nodes"][0]
        self.assertEqual(connect_step["result"], "2本のノードをつなぐ: a → b、b → c")
        self.assertEqual(len(connect_step["guide"]["connections"]), 2)

    def test_a_group_whose_pairs_all_die_is_dropped(self):
        steps = numbered([create("a"), create("t1"), create("t2"), group([("a", "t1", 0), ("t1", "t2", 0)]), delete("t1"), delete("t2")])
        kept, _ = tp.prune_failed_trials(steps)
        self.assertEqual([s["tool"] for s in kept], ["create_node"])

    def test_reconnecting_what_is_already_connected_is_dropped(self):
        """検査のために、間に一時ノードを挟み、終わったらつなぎ直した。つなぎ直しだけが残ると、何のことか分からない。"""
        steps = numbered([
            create("paper"), create("params"), connect("paper", "params"),
            create("empty_test"), connect("paper", "empty_test"), connect("empty_test", "params"), cook("params"),
            connect("paper", "params"),  # つなぎ直し
            delete("empty_test"),
        ])
        kept, dropped = tp.prune_failed_trials(steps)
        self.assertEqual([s["tool"] for s in kept], ["create_node", "create_node", "connect_nodes", "cook_node"])
        self.assertEqual(len(dropped), 5)

    def test_rewiring_to_a_different_source_is_kept(self):
        steps = numbered([create("a"), create("b"), create("c"), connect("a", "c"), connect("b", "c")])
        kept, _ = tp.prune_failed_trials(steps)
        self.assertEqual(len(kept), 5)

    def test_a_different_input_of_the_same_node_is_not_a_repeat(self):
        steps = numbered([create("a"), create("m"), connect("a", "m", 0), connect("a", "m", 1)])
        kept, _ = tp.prune_failed_trials(steps)
        self.assertEqual(len(kept), 4)

    def test_steps_without_a_recorded_node_are_kept(self):
        steps = numbered([{"tool": "set_parameter", "result": "どれか", "guide": {}}, {"tool": "cook_node", "result": "x"}, create("a")])
        kept, dropped = tp.prune_failed_trials(steps)
        self.assertEqual(len(kept), 3)
        self.assertEqual(dropped, [])

    def test_connections_are_read_from_the_text_when_the_input_was_not_recorded(self):
        old = {"tool": "connect_nodes", "result": "a の出力を、m の2番目の入力につなぐ", "guide": {"from": "a", "to": "m"}}
        self.assertEqual(tp._connect_pairs(old)[0]["input"], 1)
        named = {"tool": "connect_nodes", "result": "a の出力を、m の「source」入力につなぐ", "guide": {"from": "a", "to": "m"}}
        self.assertEqual(tp._connect_pairs(named)[0]["input"], "source")

    def test_the_input_is_not_changed(self):
        steps = numbered([create("a"), create("tmp"), delete("tmp")])
        snapshot = [dict(s) for s in steps]
        tp.prune_failed_trials(steps)
        self.assertEqual(steps, snapshot)

    def test_empty_and_odd_input(self):
        self.assertEqual(tp.prune_failed_trials([]), ([], []))
        self.assertEqual(tp.prune_failed_trials(None), ([], []))  # type: ignore[arg-type]
        kept, _ = tp.prune_failed_trials([{"tool": "create_node"}, "x"])  # type: ignore[list-item]
        self.assertEqual(len(kept), 1)


class PaperBurnShapeTest(unittest.TestCase):
    """2026-11-06 の紙燃焼と同じ形（ブラスト方式を試して消す → 同じ名前で作り直す。散布の比較用ノードは最後に消す）。"""

    def test_the_failed_blast_trial_and_the_comparison_branch_go(self):
        steps = numbered([
            create("geo1"), create("paper"), create("params"), connect("paper", "params"),
            create("merge_A"), create("ember_wr"),
            create("ember_pts"), setp("ember_pts"), connect("ember_wr", "ember_pts"), connect("ember_pts", "merge_A", 1),
            create("B_scatter"), create("B_emit"), connect("params", "B_scatter"), cook("B_emit"),
            delete("ember_pts"), create("ember_pts"), setp("ember_pts"), connect("ember_wr", "ember_pts"), connect("ember_pts", "merge_A", 1),
            cook("merge_A"),
            delete("B_emit"), delete("B_scatter"),
        ])
        kept, dropped = tp.prune_failed_trials(steps)
        names = [(s["tool"], s["guide"].get("node")) for s in kept if s["tool"] != "connect_nodes"]
        self.assertEqual(names, [
            ("create_node", "geo1"), ("create_node", "paper"), ("create_node", "params"), ("create_node", "merge_A"),
            ("create_node", "ember_wr"), ("create_node", "ember_pts"), ("set_parameter", "ember_pts"), ("cook_node", "merge_A"),
        ])
        # 残る接続は、紙→params と、作り直した ember_pts まわりの2本
        self.assertEqual(sum(1 for s in kept if s["tool"] == "connect_nodes"), 3)
        self.assertEqual(len(dropped), len(steps) - len(kept))
        self.assertEqual([s["step"] for s in kept], list(range(1, len(kept) + 1)))


if __name__ == "__main__":
    unittest.main()
