"""
score_engine.py — 理解度スコアエンジン

RAG_SECURITY_REFERENCE.md の UnderstandingScoreEngine 設計を実装。
ユーザーのトピック別理解度スコアを SQLite で管理し、
スコアに応じて RAG クエリの名前空間と詳細レベルを自動調整する。

スコアの解釈:
  0.0 - 0.29 : 初心者 → 基礎ドキュメント優先
  0.3 - 0.69 : 中級者 → 標準ドキュメント + 研究資料
  0.7 - 1.0  : 上級者 → 研究資料 + チームノート

Track Test のスキルスコアリングパターンを RAG クエリ難易度制御に転用。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class UnderstandingScoreEngine:
    """
    ユーザーのトピック別理解度スコアを管理し、
    RAG クエリの難易度・名前空間を動的に調整する。

    DB: data/auth.db の understanding_scores テーブル
    """

    # スコアの閾値
    _BEGINNER_THRESHOLD    = 0.3   # 以下なら初心者
    _INTERMEDIATE_THRESHOLD = 0.7  # 以下なら中級

    # スコア変動量
    _SUCCESS_DELTA = 0.1    # 正解時の加点
    _FAILURE_DELTA = -0.05  # 不正解時の減点

    def __init__(self, db_path: str | Path = "data/auth.db") -> None:
        self.db_path = Path(db_path)
        self._ensure_table()

    def _ensure_table(self) -> None:
        """understanding_scores テーブルが存在しなければ作成する。"""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS understanding_scores (
                    user_id    TEXT NOT NULL,
                    topic      TEXT NOT NULL,
                    score      REAL NOT NULL DEFAULT 0.5,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, topic)
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_score(self, user_id: str, topic: str) -> float:
        """
        ユーザーのトピック別理解度スコアを返す。
        未記録の場合はデフォルト 0.5（中立）を返す。
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT score FROM understanding_scores WHERE user_id=? AND topic=?",
                (user_id, topic),
            ).fetchone()
        return float(row["score"]) if row else 0.5

    def update_score(self, user_id: str, topic: str, success: bool) -> float:
        """
        操作結果に基づいてトピック別スコアを更新する。

        Args:
            user_id : ユーザー ID
            topic   : トピック名（例: "SOP", "VEX", "Houdini基礎"）
            success : True = 正解・理解できた / False = 失敗・詰まった

        Returns:
            float: 更新後のスコア [0.0, 1.0]
        """
        current = self.get_score(user_id, topic)
        delta   = self._SUCCESS_DELTA if success else self._FAILURE_DELTA
        new_score = max(0.0, min(1.0, current + delta))

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO understanding_scores (user_id, topic, score, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, topic) DO UPDATE SET
                    score      = excluded.score,
                    updated_at = excluded.updated_at
                """,
                (user_id, topic, new_score, now),
            )

        return new_score

    def get_all_scores(self, user_id: str) -> list[dict]:
        """ユーザーの全トピックスコアを返す（管理 UI 用）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT topic, score, updated_at FROM understanding_scores WHERE user_id=? ORDER BY topic",
                (user_id,),
            ).fetchall()
        return [{"topic": r["topic"], "score": r["score"], "updated_at": r["updated_at"]} for r in rows]

    def build_rag_query(self, user_id: str, action_context: dict) -> dict:
        """
        理解度スコアに応じて RAG クエリの名前空間と詳細レベルを決定する。

        Track Test の「理解度スコア → 難易度制御」パターンの転用。

        Args:
            user_id       : ユーザー ID
            action_context: {"topic": "SOP", "query": "このノードの使い方は？", ...}

        Returns:
            dict: {"query": str, "namespaces": list[str], "detail_level": str, "max_results": int}
        """
        topic = action_context.get("topic", "general")
        score = self.get_score(user_id, topic)
        query = action_context.get("query", "")

        if score < self._BEGINNER_THRESHOLD:
            # 初心者: 基礎ドキュメントのみ、ステップバイステップ
            namespaces   = ["tool_docs"]
            detail_level = "step_by_step"
            max_results  = 5
        elif score < self._INTERMEDIATE_THRESHOLD:
            # 中級者: 標準 + 研究資料も含める
            namespaces   = ["tool_docs", "game_info", "research"]
            detail_level = "conceptual"
            max_results  = 5
        else:
            # 上級者: 研究・チームノート中心
            namespaces   = ["research", "team_notes"]
            detail_level = "reference_only"
            max_results  = 3

        return {
            "query":        query,
            "namespaces":   namespaces,
            "detail_level": detail_level,
            "max_results":  max_results,
            "score":        score,
        }
