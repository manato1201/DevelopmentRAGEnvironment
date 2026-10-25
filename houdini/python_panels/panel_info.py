"""
panel_info.py — パネルに出す文面の組み立て（Qt に依存しない純粋な関数。単体テストできる）

  ・summarize_sources … 回答の出典と、採用比率（回答で使った資料／検索で見つかった資料）
  ・format_user       … 「どのユーザーで入っているか」の表示

出典の見方（Slack・local-chat と同じ）:
  回答で使った資料 … 回答の中で [1] [2] と番号で引用された資料（引用回数つき）
  使わなかった資料 … 検索では見つかったが、回答には使われなかった資料
  引用が1つも無い   … 出典を示さずに答えている可能性（知ったかぶりの警戒）
"""
from __future__ import annotations

import html

ROLE_LABELS = {"admin": "管理者", "editor": "編集者", "member": "一般ユーザー", "guest": "ゲスト"}


def _name(source: dict) -> str:
    # Cloudflare は出典を {"file": ...}、Local ブリッジは {"title": ...} で返す
    return str(source.get("file") or source.get("title") or "(名前なし)")


def _namespace_label(namespace: str) -> str:
    if namespace.startswith("personal:"):
        return "自分用"
    return namespace.removeprefix("shared:")


def summarize_sources(sources: list[dict]) -> dict:
    """出典の表示用データを返す。

    {"summary": 1行の見出し, "html": 詳細（リッチテキスト。文字はエスケープ済み）, "state": "cited"|"none"|"plain"|"empty",
     "used": 使った件数, "total": 検索で見つかった件数}
    """
    sources = list(sources or [])
    total = len(sources)
    if total == 0:
        return {"summary": "", "html": "", "state": "empty", "used": 0, "total": 0}

    def line(number: int, s: dict) -> str:
        meta = []
        if s.get("namespace"):
            meta.append(_namespace_label(str(s["namespace"])))
        if int(s.get("citationCount") or 0) > 1:
            meta.append(f"引用{int(s['citationCount'])}回")
        tail = f"（{html.escape('・'.join(meta))}）" if meta else ""
        return f"• [{number}] {html.escape(_name(s))}{tail}"

    # 引用の情報が無い（Local ブリッジなど）: 採用比率は出さず、参照した資料だけ出す
    if not any("cited" in s for s in sources):
        return {
            "summary": f"参照した資料: {total}件",
            "html": "<br>".join(line(i + 1, s) for i, s in enumerate(sources)),
            "state": "plain",
            "used": 0,
            "total": total,
        }

    numbered = list(enumerate(sources, start=1))
    used = [(n, s) for n, s in numbered if s.get("cited")]
    unused = [(n, s) for n, s in numbered if not s.get("cited")]
    if not used:
        return {
            "summary": f"⚠ 出典の番号による引用がありません（検索で見つかった{total}件）",
            "html": (
                "<b style='color:#f59e0b'>回答の中に、資料の番号（[1] など）による引用がありませんでした。"
                "出典を示さずに答えている可能性があります。資料で確認してください。</b><br>"
                + "<br>".join(line(n, s) for n, s in unused)
            ),
            "state": "none",
            "used": 0,
            "total": total,
        }
    parts = [f"<b>回答で使った資料: {len(used)}件（検索で見つかった{total}件のうち）</b>"] + [line(n, s) for n, s in used]
    if unused:
        names = " ／ ".join(f"[{n}] {html.escape(_name(s))}" for n, s in unused[:5])
        more = f" ほか{len(unused) - 5}件" if len(unused) > 5 else ""
        parts.append(f"<span style='color:#94a3b8'>回答では使わなかった資料: {names}{more}</span>")
    percent = round(len(used) / total * 100)
    return {
        "summary": f"出典: 回答で使った資料 {len(used)}件 / 検索で見つかった {total}件（採用 {percent}%）",
        "html": "<br>".join(parts),
        "state": "cited",
        "used": len(used),
        "total": total,
    }


def format_user(info: dict | None, mode: str = "cloudflare") -> dict:
    """「どのユーザーで入っているか」の表示。

    info は /me/namespaces の応答（displayName・role・userIdShort）。None は、まだ取れていない／取れなかった。
    {"text": 表示, "tooltip": 詳細, "role": 役割}
    """
    if mode == "local":
        return {"text": "ローカルモード（ユーザーの区別なし）", "tooltip": "Local モードは、このPCのブリッジに直接つなぐため、ユーザーの区別はありません。", "role": ""}
    if info and info.get("error"):
        return {"text": "ユーザー: 認証できません", "tooltip": f"APIキーを確認してください。（{info['error']}）", "role": ""}
    if not info:
        return {"text": "ユーザー: 未確認", "tooltip": "APIキーを設定して接続すると、どのユーザーで入っているかが表示されます。", "role": ""}
    role = str(info.get("role") or "")
    label = ROLE_LABELS.get(role, role or "?")
    name = str(info.get("displayName") or "") or "（名前なし）"
    short = str(info.get("userIdShort") or "-")
    return {
        "text": f"ユーザー: {name}（{label}）",
        "tooltip": f"キーの名前: {name}\n役割: {label}\nID: {short}…（キーのハッシュの先頭）",
        "role": role,
    }
