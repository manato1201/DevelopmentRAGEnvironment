"""
pep.py — NIST SP 800-207 Policy Enforcement Point (PEP)

名前空間スコープ制御の実装。
RAG クエリ・インデックス操作の前に authorize() を呼んで
アクセス可否を判定し、監査ログに記録する。

参考: NIST SP 800-207 §3 Zero Trust Architecture
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from audit_logger import RAGAuditLogger


class RAGPolicyEnforcementPoint:
    """
    NIST SP 800-207 §3 Policy Enforcement Point の実装。
    名前空間ごとの read/write/delete 権限を定義し、
    リクエストのスコープを最小権限原則に基づいて絞り込む。
    """

    # 名前空間ごとの操作権限マップ
    # read  : 検索クエリで参照できる
    # write : ドキュメントを追加・更新できる
    # delete: ドキュメントを削除できる
    NAMESPACE_PERMISSIONS: dict[str, dict[str, bool]] = {
        "tool_docs":      {"read": True,  "write": False, "delete": False},
        "game_info":      {"read": True,  "write": False, "delete": False},
        "research":       {"read": True,  "write": False, "delete": False},
        "team_notes":     {"read": True,  "write": True,  "delete": False},
        "personal_notes": {"read": True,  "write": True,  "delete": True},
        "houdini21":      {"read": True,  "write": False, "delete": False},
    }

    # ロール別のアクセス可能名前空間
    # admin     : 全名前空間
    # developer : 読み取り系 + チームノート + Houdini21技術DB
    # user      : 公式・公開情報のみ
    _ROLE_NAMESPACES: dict[str, list[str]] = {
        "admin":     list(NAMESPACE_PERMISSIONS.keys()),
        "developer": ["tool_docs", "game_info", "research", "team_notes", "houdini21"],
        "user":      ["tool_docs", "game_info", "research", "houdini21"],
    }

    def authorize(
        self,
        namespace: str,
        operation: str,
        audit_logger: Optional["RAGAuditLogger"] = None,
        session_id: Optional[str] = None,
        user_role: Optional[str] = None,
    ) -> bool:
        """
        指定された名前空間・操作の許可/拒否を判定する。

        Args:
            namespace : 対象名前空間 ("tool_docs" など)
            operation : 操作種別 ("read" | "write" | "delete")
            audit_logger: 判定結果を audit_logger.log() に記録する場合に渡す
            session_id: 監査ログ用ユーザーセッション ID
            user_role : 監査ログ用ロール文字列

        Returns:
            bool: True なら許可、False なら拒否
        """
        perms = self.NAMESPACE_PERMISSIONS.get(namespace, {})
        allowed = perms.get(operation, False)

        if audit_logger is not None:
            audit_logger.log({
                "session_id": session_id,
                "user_role":  user_role,
                "action":     f"pep_{operation}",
                "namespace":  namespace,
                "allowed":    allowed,
            })

        return allowed

    def filter_namespaces(
        self,
        user_role: str,
        requested: list[str],
    ) -> list[str]:
        """
        リクエストされた名前空間リストからロールで許可されるものだけを返す。

        最小権限の原則に基づき fail-closed で判定する: admin 以外のロールは
        要求が空、または許可される namespace が1つもない場合は「アクセスなし」
        （空リスト）を返す。以前は未指定時にロールの全namespaceへフォール
        バックしていたため、namespace を1つも付与されていないユーザーが
        実質フルアクセスになってしまっていた（fail-open）。

        Args:
            user_role : "admin" | "developer" | "user"
            requested : クライアントが要求する名前空間リスト

        Returns:
            list[str]: 許可された名前空間のみ。admin は常にロールの
                       全namespaceを返す（namespace未設定でも管理者権限は
                       失われない）。admin 以外はフォールバックなし。
        """
        allowed_for_role = self._ROLE_NAMESPACES.get(user_role, self._ROLE_NAMESPACES["user"])

        if user_role == "admin":
            return allowed_for_role

        if not requested:
            return []

        # 要求と許可の積集合。一致するものがなければ空リスト（アクセスなし）。
        return [ns for ns in requested if ns in allowed_for_role]
