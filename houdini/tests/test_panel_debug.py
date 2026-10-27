"""panel_debug.py（デバッグの記録・秘密の伏せ字）と、panel_info の friendly_error / is_setup_user のテスト。

実行（リポジトリのルートで）:  uv run python -m unittest discover -s houdini/tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_panels"))

import panel_debug as pd  # noqa: E402
import panel_info as pi  # noqa: E402


class MaskTest(unittest.TestCase):
    def test_secrets_are_masked(self):
        cases = {
            "Authorization: Bearer abcdef123456789": "Bearer ****",
            "key sk-ant-api03-ABCDEFGHIJ was used": "sk-****",
            'cf_api_key": "supersecretvalue123"': "****",
            "token=abcd1234efgh5678": "token=****",
            "hash " + "ab12cd34" * 8: "****",
        }
        for raw, expect in cases.items():
            masked = pd.mask_secrets(raw)
            self.assertIn(expect, masked, raw)
            for leaked in ("abcdef123456789", "ABCDEFGHIJ", "supersecretvalue123", "abcd1234efgh5678", "ab12cd34" * 4):
                self.assertNotIn(leaked, masked)

    def test_plain_text_is_kept(self):
        self.assertEqual(pd.mask_secrets("サーバーに接続できません（URL: https://x.workers.dev）"), "サーバーに接続できません（URL: https://x.workers.dev）")

    def test_mask_key(self):
        self.assertEqual(pd.mask_key(""), "未設定")
        self.assertEqual(pd.mask_key("  "), "未設定")
        self.assertEqual(pd.mask_key("short"), "設定済み")
        shown = pd.mask_key("abcdefghijklmnop1234")
        self.assertIn("1234", shown)
        self.assertNotIn("abcdefghij", shown)


class LogTest(unittest.TestCase):
    def setUp(self):
        pd.clear()

    def test_log_masks_and_trims(self):
        pd.log("質問", "エラー: HTTP 401 Bearer abcdef123456789\n  詳細")
        text = pd.as_text()
        self.assertIn("[質問]", text)
        self.assertNotIn("abcdef123456789", text)
        self.assertEqual(len(text.splitlines()), 1, "one entry is one line")
        pd.log("x", "あ" * 2000)
        self.assertLessEqual(len(pd.entries()[-1][2]), 600)

    def test_ring_buffer_and_clear(self):
        for i in range(700):
            pd.log("k", f"m{i}")
        self.assertEqual(len(pd.entries()), 500)
        self.assertIn("m699", pd.as_text())
        self.assertNotIn("m0\n", pd.as_text() + "\n")
        pd.clear()
        self.assertEqual(pd.as_text(), "")


class FriendlyErrorTest(unittest.TestCase):
    def test_known_failures_get_short_japanese_messages(self):
        cases = {
            "HTTP Error 401: Unauthorized": "APIキー",
            "<urlopen error [WinError 10061] 対象のコンピューターによって拒否されました>": "サーバーに接続できません",
            "<urlopen error [Errno 11001] getaddrinfo failed>": "サーバーに接続できません",
            "HTTP Error 403: Forbidden": "権限",
            "HTTP Error 429: Too Many Requests": "上限",
            "RAG のトークン予算を超えました": "上限",
            "The read operation timed out": "応答が遅れています",
            "Cloudflare モードですが、Worker の URL が未設定です": "接続の設定が足りません",
            "HTTP Error 503: Service Unavailable": "サーバーで問題",
        }
        for raw, expect in cases.items():
            shown = pi.friendly_error(raw)
            self.assertIn(expect, shown, raw)
            self.assertNotIn("Errno", shown)
            self.assertNotIn("urlopen", shown)

    def test_unknown_error_hides_internals(self):
        shown = pi.friendly_error("Traceback (most recent call last): KeyError 'x'")
        self.assertNotIn("Traceback", shown)
        self.assertIn("もう一度", shown)
        self.assertTrue(pi.friendly_error(""))


class SetupUserTest(unittest.TestCase):
    def test_roles(self):
        self.assertTrue(pi.is_setup_user("admin"))
        self.assertTrue(pi.is_setup_user("editor"))
        self.assertFalse(pi.is_setup_user("member"))
        self.assertFalse(pi.is_setup_user("guest"))
        self.assertFalse(pi.is_setup_user(""), "unknown role is treated as a general user")
        self.assertTrue(pi.is_setup_user("", "local"), "local mode is the developer's own bridge")


if __name__ == "__main__":
    unittest.main()
