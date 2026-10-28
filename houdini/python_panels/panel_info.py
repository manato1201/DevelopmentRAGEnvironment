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
import re

ROLE_LABELS = {"admin": "管理者", "editor": "編集者", "member": "一般ユーザー", "guest": "ゲスト"}

# 設定者（接続先・モデル・ギャラリーなどの設定と、デバッグ情報を見る人）。一般ユーザーには、これらの画面を出さない。
# サーバー側の権限が正で、これは画面の出し分けだけ。
SETUP_ROLES = ("admin", "editor")


def is_setup_user(role: str, mode: str = "cloudflare") -> bool:
    """設定者の画面（設定・デバッグ）を出すか。Local モードは、自分のPCのブリッジを動かす開発者なので、出す。"""
    return mode == "local" or role in SETUP_ROLES


def friendly_error(raw: str) -> str:
    """利用者に見せる、短く分かりやすい文にする。生の詳細は、デバッグのログ（panel_debug）に残す。"""
    text = str(raw or "")
    low = text.lower()

    def has_status(*codes: str) -> bool:
        # HTTP ステータスは、前後に数字が続かないときだけ（"15000ms" の "500" などに反応しない）
        return any(re.search(rf"(?<!\d){code}(?!\d)", text) for code in codes)

    if has_status("401") or "unauthorized" in low or "認証" in text:
        return "APIキーが無効か、期限が切れています。「接続」タブで、APIキーを確認してください。"
    if has_status("403") or "forbidden" in low:
        return "この操作をする権限がありません。管理者に確認してください。"
    if has_status("429") or "予算" in text or "上限" in text or "budget" in low or ("rate" in low and "limit" in low):
        return "利用の上限に達しました。しばらく待つか、管理者に上限を確認してください。"
    if has_status("404") or "未定義のエンドポイント" in text:
        # パネルが新しく、サーバー（Worker）がまだその機能に対応していないとき
        return "サーバーが、この機能にまだ対応していません。管理者に、サーバーの更新を依頼してください。"
    if "timed out" in low or "timeout" in low or "タイムアウト" in text:
        return "サーバーの応答が遅れています。少し待って、もう一度試してください。"
    if any(w in low for w in ("urlopen error", "connection refused", "connection reset", "name or service", "getaddrinfo", "unreachable", "winerror 10061", "接続できません")):
        return "サーバーに接続できません。ネットワークと、「接続」タブの URL を確認してください。"
    if "url が未設定" in low or "urlが未設定" in low or "未設定" in text:
        return "接続の設定が足りません。「接続」タブで、URL と APIキーを入力してください。"
    if text.startswith("HTTP Error 5") or has_status("500", "502", "503"):
        return "サーバーで問題が起きています。少し待って、もう一度試してください。続く場合は管理者に連絡してください。"
    return "うまくいきませんでした。もう一度試してください。続く場合は、管理者に連絡してください。"


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


EXPLAIN_CHOICES = [
    ("auto", "おまかせ（成長）"),
    ("basic", "basic（やさしく）"),
    ("applied", "applied（仕組みまで）"),
    ("advanced", "advanced（専門的に）"),
]


def format_explain(explain: dict | None) -> str:
    """回答の下に出す、「説明レベル」と「今回紹介した用語」。explain は /query の応答の explain。"""
    if not explain or not explain.get("level"):
        return ""
    text = f"説明レベル: {explain['level']}" + ("（おまかせ）" if explain.get("mode") == "auto" else "")
    introduced = [str(t) for t in (explain.get("introduced") or [])]
    return text + (f" ／ 紹介した用語: {'、'.join(introduced)}" if introduced else "")


def format_growth(growth: dict | None) -> str:
    """接続タブに出す、自分の習熟度。growth は /me/growth の応答。"""
    if not growth or not growth.get("level"):
        return ""
    known = [str(k.get("term")) for k in (growth.get("knownTerms") or [])[:8]]
    lines = [f"習熟度: {growth['level']}（用語 {int(growth.get('termCount') or 0)}個・{growth.get('score', 0)}点）"]
    if growth.get("nextAt") is not None:
        remain = max(0.0, float(growth["nextAt"]) - float(growth.get("score") or 0))
        lines.append(f"次のレベルまで あと {remain:.1f}点（質問で専門用語を使うほど上がります）")
    if growth.get("lowered"):
        lines.append("※「役に立たなかった」が続いたため、一段やさしく説明しています。")
    if known:
        lines.append("使いこなしている用語: " + "、".join(known))
    return "\n".join(lines)


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
