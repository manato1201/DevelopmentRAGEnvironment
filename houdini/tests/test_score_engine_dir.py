"""ScoreEngine が、DB の置き場所(data/)が無い環境でも動くことの検査。

2026-11-18: クリーンな環境(CI)で `data/` が無く、rag_local_bridge を import しただけで
sqlite3.OperationalError になり、test_prompt_guard・test_namespace_isolation が読み込めなかった。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from score_engine import UnderstandingScoreEngine  # noqa: E402


class ScoreEngineCreatesItsDirectoryTest(unittest.TestCase):
    # Windows では、sqlite の接続(with conn: は閉じない)が残り、一時フォルダを消せないので、後片付けの失敗は無視する。
    def test_missing_parent_directory_is_created(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = Path(tmp) / "data" / "nested" / "auth.db"
            self.assertFalse(db.parent.exists())
            engine = UnderstandingScoreEngine(db)
            self.assertTrue(db.exists())
            self.assertEqual(engine.get_score("u1", "topic"), 0.5)  # 新しい利用者・話題の初期値

    def test_existing_directory_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = Path(tmp) / "auth.db"
            UnderstandingScoreEngine(db)
            UnderstandingScoreEngine(db)  # 2 回作っても、エラーにならない
            self.assertTrue(db.exists())


if __name__ == "__main__":
    unittest.main()
