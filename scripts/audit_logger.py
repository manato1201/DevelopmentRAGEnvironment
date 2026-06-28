"""
audit_logger.py — NIST SP 800-207 準拠 JSONL 監査ログ

全 RAG クエリ・アクセスの監査証跡を JSON Lines 形式で記録する。
NIST SP 800-207 テネット7「可能な限り情報収集」の実装。

クエリ内容はプライバシー保護のため SHA-256 でハッシュ化して記録する。
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class RAGAuditLogger:
    """
    全 RAG クエリ・アクセスの監査証跡を JSON Lines 形式で記録する。

    出力フォーマット (1行 = 1イベント):
      {
        "timestamp":    "2026-06-29T12:00:00.000Z",  # UTC ISO 8601
        "session_id":   "abc12345" | null,
        "user_role":    "admin" | "developer" | "user" | null,
        "action":       "search" | "index" | "delete" | "auth_fail",
        "namespace":    "tool_docs" | ... | null,
        "query_hash":   "a1b2c3d4e5f6a7b8",   # SHA-256 先頭 16 文字
        "result_count": 5 | null,
        "latency_ms":   123 | null,
        "allowed":      true | false
      }
    """

    def __init__(self, log_path: str | Path = "logs/rag_audit.jsonl") -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: dict) -> None:
        """
        監査イベントを JSONL ファイルに追記する。
        event には任意のキーを渡せるが、以下の標準フィールドに正規化する:
          session_id, user_role, action, namespace, query, result_count, latency_ms, allowed
        """
        record = {
            "timestamp":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") +
                            f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
            "session_id":   event.get("session_id"),
            "user_role":    event.get("user_role"),
            "action":       event.get("action", "search"),
            "namespace":    event.get("namespace"),
            "query_hash":   self._hash(event.get("query", "")),
            "result_count": event.get("result_count"),
            "latency_ms":   event.get("latency_ms"),
            "allowed":      event.get("allowed", True),
        }

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _hash(self, text: str) -> str:
        """クエリ内容を SHA-256 でハッシュ化し先頭 16 文字を返す（プライバシー保護）。"""
        if not text:
            return ""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def get_recent(self, limit: int = 100) -> list[dict]:
        """最新 limit 件のログエントリを新しい順で返す（管理 UI 用）。"""
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(records))[-limit:]
