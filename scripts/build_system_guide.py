"""
build_system_guide.py — docs/system-guide.html を生成する（2026-10-08追加）

使い方:  python scripts/build_system_guide.py
出力:    docs/system-guide.html（単体で開ける。外部ライブラリなし、フォントだけGoogle Fonts）

左の目次・層ごとの色分け・手書きSVGの構成図/フロー図/状態遷移図・表・手順・運用の構成で、このリポジトリ（Houdiniチュートリアル生成、Cloudflare RAG、
公式MCP連携、ナレッジ追加、評価と学習）をまとめたガイド。図は guide_svg.py の部品で組み、
内容を変えたらこのスクリプトを直して再生成する（HTMLを手で直さない）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guide_svg import LEGEND, STYLE, Svg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "system-guide.html"


# ═══════════════════════════════════════════════════════════════════════════════
# 図
# ═══════════════════════════════════════════════════════════════════════════════

def diagram_architecture() -> str:
    s = Svg(1240, 900, "arch", "システム構成図",
            "Houdiniパネルとブラウザから、Cloudflare Worker（検索・Claudeプロキシ・管理・MCPクライアント・評価）を通って、Gemini・Claude・公式MCP・各社REST、D1・Vectorizeにつながる構成")
    # ブラウザ
    s.group(20, 50, 380, 240, "ブラウザ（Webチャット・管理画面）", "ui")
    for i, (t, sub) in enumerate([
        ("チャット", "「外部サービスも使う」・回答の評価"),
        ("ナレッジを追加（ポップアップ）", "ファイル・URL・Q&Aを3ステップで登録"),
        ("公式MCP連携（ポップアップ）", "接続・ツール選択・チャット利用"),
        ("評価の閲覧（adminのみ）", "集計・一覧・CSV"),
    ]):
        s.box(40, 84 + i * 48, 340, 40, t, "", "ui" if i != 3 else "safe", size=13)
    # Houdini
    s.group(20, 310, 380, 560, "Houdini（利用者のPC）", "ui")
    s.box(40, 350, 340, 110, "", "", "ui")
    s.text(210, 376, "Houdini Python パネル（PySide6）", 14, 700)
    for i, name in enumerate(["はじめに", "Chat", "Graph", "Tutorial"]):
        s.chip(54 + i * 80, 392, 72, 24, name)
    for i, name in enumerate(["History", "動画", "Settings"]):
        s.chip(54 + i * 80, 424, 72, 24, name)
    s.box(40, 480, 340, 56, "tutorial_agent.py", "Claudeのツールループ（最大80回・$5上限）", "core", size=13)
    s.box(40, 556, 340, 56, "houdini_tools.py", "HoudiniToolExecutor：サンドボックス・10ツール", "core", size=13)
    s.box(40, 632, 340, 56, "tutorial_feedback.py", "指標・評価・教訓・成功例（Qt/hou非依存）", "safe", size=13)
    s.box(40, 708, 340, 66, "localRAG/tutorials/", ".md .json _metrics.json _feedback.json\n＋ tutorial_lessons.json", "store", size=13)
    s.box(40, 794, 340, 56, "RAGReel（C++/Qt）", "解説動画の生成（VP9）", "ui", size=13)
    s.arrow([(210, 536), (210, 556)], "core")
    s.arrow([(210, 688), (210, 708)], "store")
    # Worker
    s.group(470, 50, 330, 500, "Cloudflare Worker（rag-poc）", "core")
    for i, (t, sub, acc) in enumerate([
        ("検索・回答  /search /query", "HyDE・ハイブリッド検索・引用率・useMcp", "core"),
        ("Claude プロキシ  /claude/messages", "トークン予算・effort", "core"),
        ("管理 API  /admin/*", "KB登録・クロール・同期・利用統計", "core"),
        ("MCPクライアント  src/mcp/", "OAuth 2.1・ツール方針・チャット連携", "safe"),
        ("評価  /tutorial-feedback/*", "送信は本人・閲覧はadminのみ", "safe"),
    ]):
        s.box(490, 90 + i * 80, 290, 64, t, sub, acc, size=13)
    # 保存
    s.group(470, 580, 330, 290, "保存（Cloudflare）", "store")
    s.box(490, 620, 290, 150, "D1（SQLite）", "users・memory・audit_log・kb_log\ncrawl_jobs・oauth_connections\nmcp_connections・mcp_audit\ntutorial_feedback", "store", mono_sub=True, size=13)
    s.box(490, 786, 290, 64, "Vectorize", "shared / personal（768次元）", "store", size=13)
    s.arrow([(635, 552), (635, 620)], "store", "読み書き", 650, 570, anchor="start")
    # 外部
    s.group(870, 50, 350, 360, "外部サービス", "rest")
    for i, (t, sub) in enumerate([
        ("Gemini API", "埋め込み・回答生成・関数呼び出し"),
        ("Anthropic Claude API", "チュートリアル生成（Sonnet / Opus）"),
        ("各社 REST・同期元", "Notion・Drive・Jira・Backlog・Google・Slack"),
        ("公式MCPサーバー", "Notion／Atlassian（OAuth 2.1）"),
    ]):
        s.box(890, 90 + i * 80, 310, 64, t, sub, "rest", size=13)
    for i, color in enumerate(["core", "core", "rest", "safe"]):
        s.arrow([(780, 122 + i * 80), (890, 122 + i * 80)], color)
    # 検討中
    s.group(870, 440, 350, 200, "未対応・検討中", "plan", dashed=True)
    s.plan(890, 478, 310, 44, "書き込みツールのチャット利用", "確認ダイアログが必要")
    s.plan(890, 532, 310, 44, "Google公式MCP", "Developer Preview参加が必要")
    s.plan(890, 586, 310, 44, "トークンの暗号化", "現在はD1に平文（PoC水準）")
    # クライアント → Worker
    s.arrow([(400, 170), (470, 170)], "ui", "HTTPS", 435, 160)
    s.arrow([(400, 520), (470, 520)], "core")
    s.note(490, 524, "Houdiniパネルは /search・/claude/messages・/tutorial-feedback を呼ぶ", "start", "var(--muted)", 11.5)
    return s.render()


def diagram_generation_flow() -> str:
    s = Svg(1240, 1080, "gen", "チュートリアル生成の流れ",
            "入力から領域判定、RAG検索、プロンプト組み立て、Claudeのツールループ、仕上げ、保存、評価、Cloudflareでの閲覧までの流れ")
    lanes = [(0, 300, "利用者・Tutorialタブ", True), (300, 320, "tutorial_agent（Houdini内）", False),
             (620, 310, "Cloudflare Worker", True), (930, 310, "Houdini 実機（サンドボックス）", False)]
    for x, w, label, alt in lanes:
        s.lane(x, 0, w, 1080, label, alt)
    cx = [150, 460, 775, 1085]

    def step(lane, y, title, sub, acc, h=64):
        s.box(cx[lane] - 130, y, 260, h, title, sub, acc, size=13)

    step(0, 60, "① 入力", "トピック・生成条件\n対象モデル・参考画像", "ui", 72)
    step(1, 160, "② 領域を判定して節を選ぶ", "GSplat／アニメ・リグ／H22\n条件・教訓・成功例", "core", 72)
    step(2, 260, "③ RAG検索", "/search（houdini22）", "core")
    step(1, 360, "④ プロンプトを組み立てる", "共通ノード一覧・知識の節・画像", "core")
    step(2, 460, "⑤ Claudeに依頼", "/claude/messages → tool_use", "core")
    step(3, 560, "⑥ ツールを実行", "create／set／connect／cook\ninspect_geometry", "core", 72)
    step(3, 670, "⑦ 手順ごとに撮影", "ビューポート・ネットワーク図\nパラメータカード", "ui", 72)
    step(1, 770, "⑧ 仕上げ", "finish → 自己確認画像 → confirm", "core")
    step(0, 880, "⑨ プレビュー・保存", ".md .json _metrics.json\n（動画の生成も起動）", "store", 72)
    step(0, 990, "⑩ 評価", "👍👎・タグ・メモ", "safe", 56)
    step(2, 990, "⑪ D1に保存", "管理者が管理画面で閲覧", "store", 56)
    s.arrow([(280, 96), (305, 96), (305, 196), (330, 196)], "ui")
    s.arrow([(590, 196), (612, 196), (612, 292), (645, 292)], "core")
    s.arrow([(645, 310), (618, 310), (618, 392), (590, 392)], "core", "検索結果", 636, 358, anchor="end")
    s.arrow([(590, 400), (624, 400), (624, 492), (645, 492)], "core")
    s.arrow([(905, 478), (940, 478), (940, 590), (955, 590)], "rest", "ツール呼び出し", 948, 536, anchor="start")
    s.arrow([(1085, 632), (1085, 670)], "core")
    s.arrow([(955, 712), (922, 712), (922, 520), (905, 520)], "core", "結果を返す", 914, 640, anchor="end", dashed=True)
    s.note(792, 590, "完了まで最大80回\n（コスト$5・反復の上限）", "start", "var(--muted)", 12)
    s.arrow([(775, 524), (775, 802), (590, 802)], "safe", "finish_tutorial", 782, 700, anchor="start")
    s.arrow([(330, 802), (305, 802), (305, 916), (280, 916)], "store")
    s.arrow([(150, 952), (150, 990)], "safe")
    s.arrow([(280, 1018), (645, 1018)], "safe", "POST /tutorial-feedback/submit", 462, 1008)
    return s.render()


def diagram_agent_logic() -> str:
    s = Svg(1240, 780, "loop", "エージェントループの判断",
            "RAG検索とプロンプト組み立ての後、Claudeの応答の種類で分岐し、ツール実行、上限判定、救済、打ち切り、成果物の組み立てへ進む")
    s.terminal(520, 14, 200, 36, "生成開始")
    s.box(470, 72, 300, 48, "① RAG検索", "失敗しても続行", size=13)
    s.box(470, 140, 300, 56, "② プロンプトを組み立てる", "教訓・成功例・知識の節・参考画像", size=13)
    s.arrow([(620, 50), (620, 72)], "muted")
    s.arrow([(620, 120), (620, 140)], "muted")
    s.arrow([(620, 196), (620, 235)], "muted")
    s.diamond(620, 290, 300, 110, "③ Claudeの応答は？")
    # 左: テキストのみ→救済
    s.box(60, 246, 340, 88, "救済ロジック", "ノード未作成→催促（最大2回）\nfinish未呼出→催促（1回）\nconfirm未呼出→催促（最大2回）", "safe", size=13)
    s.arrow([(470, 290), (400, 290)], "safe", "テキストのみ", 435, 278)
    s.line([(60, 290), (20, 290)], "safe", dashed=False)
    # 右: refusal
    s.parts.append('<rect x="900" y="262" width="300" height="56" rx="10" class="d-step" style="stroke:var(--warn)"/>')
    s.text(1050, 286, "打ち切り（安全分類器の拒否）", 13.5, 700)
    s.text(1050, 304, "分類つきで理由を表示", 12.5, 400, "var(--muted)")
    s.arrow([(770, 290), (900, 290)], "warn", "refusal", 835, 278)
    # ④ ツール
    s.box(470, 372, 300, 60, "④ ツールを実行", "結果を履歴へ（画像は1回だけ添付）", "core", size=13)
    s.arrow([(620, 345), (620, 372)], "core", "tool_use", 630, 364, anchor="start")
    s.box(900, 374, 300, 56, "完了（confirm_tutorial=true）", "自己確認の画像を見て確定", "core", size=13)
    s.arrow([(770, 402), (900, 402)], "core", "confirm", 835, 392)
    # ⑤ 上限
    s.diamond(620, 520, 320, 104, "⑤ 上限を超えた？\n反復>80／コスト>$5")
    s.arrow([(620, 432), (620, 468)], "muted")
    s.parts.append('<rect x="900" y="492" width="300" height="56" rx="10" class="d-step" style="stroke:var(--warn)"/>')
    s.text(1050, 516, "打ち切り（反復／コスト上限）", 13.5, 700)
    s.text(1050, 534, "途中経過を提示して保存可能", 12.5, 400, "var(--muted)")
    s.arrow([(780, 520), (900, 520)], "warn", "はい", 840, 508)
    s.box(470, 612, 300, 60, "⑥ 次の反復へ", "残り5回／コスト85%超で仕上げ促し（1回）", "core", size=13)
    s.arrow([(620, 572), (620, 612)], "muted", "いいえ", 632, 596, anchor="start")
    s.arrow([(470, 642), (20, 642), (20, 214), (614, 214)], "core", "繰り返す（最大80回）", 245, 632)
    # ⑦ 成果物
    s.box(900, 640, 300, 64, "⑦ 成果物を組み立てる", "best_unconfirmed_draft・グラフ・撮影・metrics", "store", size=13)
    s.arrow([(1200, 290), (1225, 290), (1225, 672), (1200, 672)], "store")
    s.line([(1200, 402), (1225, 402)], "store", dashed=False)
    s.line([(1200, 520), (1225, 520)], "store", dashed=False)
    s.note(60, 720, "救済の上限を超えて、なお終わらないときは「打ち切り」になります。下書き（finish_tutorial）が1件でもあれば、\n本文量が最大のものを採用します（タイトルだけのプレースホルダーは棄却）。", "start", "var(--muted)", 12.5)
    return s.render()


def diagram_feedback() -> str:
    s = Svg(1240, 680, "fb", "評価と学習のループ",
            "生成時の自動指標と手動評価をサイドカーに保存し、集計・教訓・成功例として次の生成に反映する。評価はCloudflareにも送られ、管理者だけが閲覧できる")
    s.box(30, 70, 200, 84, "① 生成", "metricsを自動記録\n反復・コスト・cookエラー…", "core", size=13)
    s.box(290, 70, 200, 84, "② 保存", ".md .json\n_metrics.json", "store", size=13)
    s.box(550, 70, 200, 84, "③ 評価", "👍👎・理由タグ・メモ\n→ _feedback.json", "safe", size=13)
    s.arrow([(230, 112), (290, 112)], "muted")
    s.arrow([(490, 112), (550, 112)], "muted")
    s.box(830, 36, 380, 70, "集計", "モデル・レベル・領域・理由タグ別の好評率・コスト", "core", size=13)
    s.box(830, 136, 380, 70, "教訓（承認制）", "👎のメモをClaudeが要約 → 承認した最大10件", "safe", size=13)
    s.box(830, 236, 380, 70, "成功例", "似た題材で👍かつ完走した構成を最大2件", "core", size=13)
    s.arrow([(750, 112), (790, 112), (790, 71), (830, 71)], "core")
    s.arrow([(750, 112), (790, 112), (790, 171), (830, 171)], "safe")
    s.arrow([(750, 112), (790, 112), (790, 271), (830, 271)], "core")
    s.box(830, 380, 380, 70, "④ 次の生成のプロンプト", "システムプロンプトに「教訓」「参考例」の節を追加", "core", size=13)
    s.arrow([(1020, 306), (1020, 380)], "core")
    s.box(830, 490, 380, 56, "設定を選ぶ（人が判断）", "集計を見て、モデル・レベル・effortを決める", "ui", size=13)
    s.arrow([(1210, 71), (1228, 71), (1228, 518), (1210, 518)], "ui", dashed=True)
    s.arrow([(830, 415), (130, 415), (130, 154)], "core", "次の生成へ（教訓・成功例の件数を指標に記録）", 330, 405)
    # Cloudflare
    s.box(480, 186, 300, 52, "POST /tutorial-feedback/submit", "本人の行だけ書ける（rating=0で取り消し）", "rest", size=13)
    s.box(480, 258, 300, 52, "D1  tutorial_feedback", "1ユーザー×1チュートリアルで1行（upsert）", "store", size=13)
    s.box(480, 330, 300, 52, "管理画面（adminのみ）", "集計・一覧・CSV／非adminは403", "safe", size=13)
    s.arrow([(650, 154), (650, 186)], "rest")
    s.arrow([(650, 238), (650, 258)], "store")
    s.arrow([(650, 310), (650, 330)], "safe", "requireAdmin", 662, 324, anchor="start")
    s.note(480, 580, "送るのは題名・トピック・概要の抜粋・評価・タグ・メモ・数値の指標だけ。チュートリアル本文は送らない。", "start", "var(--muted)", 12.5)
    return s.render()


def diagram_mcp_connect() -> str:
    s = Svg(1240, 900, "mcpc", "MCP連携の接続フロー",
            "管理者のブラウザ、Worker、D1、認可サーバーと公式MCPサーバーの間で、探索・自動登録・PKCE・コード交換・保存を行う順序")
    lanes = [(0, 300, "管理者（ブラウザ）", True), (300, 320, "Worker（src/mcp）", False),
             (620, 250, "D1", True), (870, 370, "認可サーバー・公式MCP", False)]
    for x, w, label, alt in lanes:
        s.lane(x, 0, w, 900, label, alt)
    cx = [150, 460, 745, 1055]

    def step(lane, y, title, sub, acc, h=60, w=250):
        s.box(cx[lane] - w / 2, y, w, h, title, sub, acc, size=13)

    step(0, 56, "① 「認証する」を押す", "GET /admin/oauth/mcp/<id>/start", "ui", 64, 270)
    step(1, 130, "② 管理者か確認", "requireAdmin／登録簿のURLだけ", "safe", 56, 260)
    step(3, 200, "③ 探索", ".well-known（RFC 9728 / 8414）", "rest", 56, 310)
    step(3, 276, "④ クライアントを自動登録", "RFC 7591（初回だけ）", "rest", 56, 310)
    step(2, 276, "mcp_clients", "登録結果をキャッシュ", "store", 56, 220)
    step(2, 356, "⑤ state・verifierを保存", "oauth_pending_state（10分・単発）", "store", 64, 230)
    step(0, 440, "⑥ 同意画面へ移動", "302（PKCE S256・resource付き）", "ui", 60, 270)
    step(3, 440, "⑦ 利用者が許可", "→ /admin/oauth/mcp/callback", "rest", 60, 320)
    step(1, 530, "⑧ stateを検証・コード交換", "code_verifier＋resourceを送る", "core", 64, 270)
    step(3, 530, "トークンを発行", "access＋refresh", "rest", 56, 240)
    step(2, 620, "⑨ mcp_connectionsに保存", "connected／設定は引き継ぎ", "store", 64, 230)
    step(0, 710, "⑩ 「接続完了」ページ", "自動で管理画面へ戻る", "ui", 56, 260)
    step(1, 790, "⑪ ツール一覧を取得", "tools/list → ポリシー → 選択", "core", 60, 270)
    step(3, 790, "公式MCPサーバー", "initialize／tools/list", "rest", 56, 240)
    s.arrow([(285, 88), (310, 88), (310, 158), (330, 158)], "ui")
    s.arrow([(590, 158), (612, 158), (612, 228), (900, 228)], "rest", "探索", 760, 218)
    s.arrow([(1055, 256), (1055, 276)], "rest")
    s.arrow([(900, 304), (855, 304)], "store", dashed=True)
    s.arrow([(460, 186), (460, 388), (630, 388)], "store", "state保存", 470, 300, anchor="start")
    s.arrow([(460, 390), (460, 470), (285, 470)], "ui", "302 認可URL", 372, 462)
    s.arrow([(285, 492), (895, 492)], "rest", "同意画面へ", 760, 510)
    s.arrow([(895, 455), (520, 455), (520, 530)], "rest", "callback?code&state", 705, 447)
    s.arrow([(595, 560), (935, 560)], "rest", "コード交換", 765, 550)
    s.arrow([(595, 590), (612, 590), (612, 652), (630, 652)], "store")
    s.arrow([(630, 680), (310, 680), (310, 738), (285, 738)], "ui", "完了", 470, 672)
    s.arrow([(150, 766), (150, 820), (325, 820)], "ui", "ツールを選ぶ", 238, 812)
    s.arrow([(595, 818), (935, 818)], "rest", "", 0, 0)
    s.note(40, 870, "①〜⑪は管理者だけ。接続・解除・再認証は mcp_audit に記録（connect／disconnect／reauth_required）。", "start", "var(--muted)", 12.5)
    return s.render()


def diagram_mcp_chat() -> str:
    s = Svg(1240, 900, "mcpt", "チャットでのツール呼び出しループ",
            "useMcpが有効なとき、Geminiの関数呼び出しで読み取り専用のMCPツールを最大4往復・6回まで実行し、最後はツール無しで回答を書かせる")
    s.terminal(430, 14, 240, 36, "POST /query（useMcp=true）")
    s.box(380, 72, 340, 48, "RAG検索（HyDE・ハイブリッド）", "", size=13)
    s.arrow([(550, 50), (550, 72)], "muted")
    s.box(380, 140, 340, 60, "使えるツールを集める", "chat_enabled＆接続中の有効な読み取り専用ツール", "safe", size=13)
    s.arrow([(550, 120), (550, 140)], "muted")
    s.diamond(550, 270, 260, 90, "ツールがある？")
    s.arrow([(550, 200), (550, 225)], "muted")
    s.box(40, 244, 260, 52, "従来どおり検索結果だけで回答", "generateAnswer", size=13)
    s.arrow([(420, 270), (300, 270)], "muted", "なし", 360, 258)
    s.box(380, 340, 340, 56, "Gemini（ツール宣言つき）", "プロンプト：検索で足りるならツールを呼ばない", "core", size=13)
    s.arrow([(550, 315), (550, 340)], "core", "あり", 560, 332, anchor="start")
    s.diamond(550, 470, 260, 90, "functionCall？")
    s.arrow([(550, 396), (550, 425)], "muted")
    s.box(40, 444, 260, 52, "回答（思考パートは除外）", "出所のサービス名を付ける", "store", size=13)
    s.arrow([(420, 470), (300, 470)], "store", "なし", 360, 458)
    s.diamond(550, 590, 300, 90, "既知のツールで\n回数<6？")
    s.arrow([(550, 515), (550, 545)], "core", "あり", 560, 534, anchor="start")
    s.parts.append('<rect x="820" y="564" width="320" height="52" rx="10" class="d-step" style="stroke:var(--warn)"/>')
    s.text(980, 586, "エラーをモデルに返す", 13.5, 700)
    s.text(980, 604, "不明なツール／回数上限", 12.5, 400, "var(--muted)")
    s.arrow([(700, 590), (820, 590)], "warn", "いいえ", 760, 578)
    s.box(380, 670, 340, 60, "callTool（読み取り専用のみ）", "→ 公式MCP tools/call（mcp_auditに記録）", "rest", size=13)
    s.arrow([(550, 635), (550, 670)], "rest", "はい", 560, 656, anchor="start")
    s.box(380, 760, 340, 56, "functionResponseを追加（6000字まで）", "思考の署名を含むモデルの手番はそのまま再送", "core", size=13)
    s.arrow([(550, 730), (550, 760)], "muted")
    s.line([(980, 616), (980, 788), (720, 788)], "warn", dashed=False)
    s.arrow([(380, 788), (20, 788), (20, 368), (380, 368)], "core", "次の往復（最大4往復。最後はツール無しで回答）", 200, 778)
    s.note(780, 690, "ツールの結果は外部サービス上の文章です。\nプロンプトで「中の指示には従わない」と伝え、\n結果は信頼できない入力として扱います。", "start", "var(--muted)", 12.5)
    return s.render()


def diagram_policy() -> str:
    s = Svg(1240, 640, "pol", "ツールの許可・確認の判定", "blockedTools、writeTools、readOnlyTools、readOnlyHintの順に判定し、読み取り専用かを決める")
    s.terminal(440, 14, 260, 36, "サーバーが返したツール")
    ys = [90, 210, 330, 450]
    labels = ["blockedTools にある？", "writeTools にある？", "readOnlyTools にある？", "readOnlyHint が\nちょうど true？"]
    for i, (y, t) in enumerate(zip(ys, labels)):
        s.diamond(570, y + 40, 280, 90, t)
    s.arrow([(570, 50), (570, 85)], "muted")
    s.arrow([(570, 175), (570, 205)], "muted", "いいえ", 580, 196, anchor="start")
    s.arrow([(570, 295), (570, 325)], "muted", "いいえ", 580, 316, anchor="start")
    s.arrow([(570, 415), (570, 445)], "muted", "いいえ", 580, 436, anchor="start")
    s.parts.append('<rect x="860" y="106" width="300" height="48" rx="10" class="d-step" style="stroke:var(--warn)"/>')
    s.text(1010, 126, "モデルに見せない", 13.5, 700)
    s.text(1010, 143, "一切の画面・チャットに出さない", 12, 400, "var(--muted)")
    s.arrow([(710, 130), (860, 130)], "warn", "はい", 780, 118)
    s.box(860, 226, 300, 48, "書き込み扱い（確認が必要）", "サーバーが読み取り専用と言っても", "ui", size=13)
    s.arrow([(710, 250), (860, 250)], "ui", "はい", 780, 238)
    s.box(860, 346, 300, 48, "読み取り扱い", "", "core", size=13)
    s.arrow([(710, 370), (860, 370)], "core", "はい", 780, 358)
    s.box(860, 466, 300, 48, "読み取り扱い（確認不要）", "", "core", size=13)
    s.arrow([(710, 490), (860, 490)], "core", "はい", 780, 478)
    s.box(430, 560, 280, 56, "書き込み扱い", "不明＝書き込みかもしれない", "ui", size=13)
    s.arrow([(570, 535), (570, 560)], "ui", "いいえ", 580, 552, anchor="start")
    s.note(760, 560, "使い道：\n・RAGチャット … 読み取りで、管理者が有効化したものだけ\n・試し実行（管理者） … 書き込みは confirmed:true が必須", "start", "var(--muted)", 12.5)
    return s.render()


def diagram_states() -> str:
    s = Svg(1000, 330, "st", "MCP接続の状態遷移", "未接続、接続済み、要再認証の3状態と、遷移の条件")
    s.state(60, 110, 200, 90, "未接続", "disconnected", "ink")
    s.state(400, 110, 200, 90, "接続済み", "connected", "core")
    s.state(740, 110, 200, 90, "再認証が必要", "reauth_required", "ui")
    s.arrow([(262, 140), (398, 140)], "core", "認証が完了", 330, 124)
    s.arrow([(602, 140), (738, 140)], "warn", "401・更新失敗", 670, 124)
    s.arrow([(840, 202), (840, 250), (540, 250), (540, 204)], "ui", "もう一度認証する（設定は引き継ぐ）", 690, 270)
    s.arrow([(500, 112), (500, 60), (160, 60), (160, 108)], "muted", "連携を解除", 330, 50)
    return s.render()


def diagram_wizard() -> str:
    s = Svg(1280, 400, "wiz", "ナレッジ追加ポップアップの画面遷移", "入力、確認、登録中、結果の4画面と、戻る・再実行・続けて追加の遷移")
    xs = [20, 350, 680, 1010]
    w = 250
    names = [("① 入力", "方法と内容を決める"), ("② 確認", "登録内容を一覧で確認"), ("③ 登録中", "1件ずつ実行・閉じられない"), ("④ 結果", "成功／失敗を1件ずつ表示")]
    accs = ["ui", "ui", "core", "store"]
    for x, (t, sub), a in zip(xs, names, accs):
        s.state(x, 130, w, 96, t, sub, a)
    s.arrow([(272, 160), (348, 160)], "ui", "次へ", 310, 148)
    s.arrow([(348, 198), (272, 198)], "muted", "戻る", 310, 218)
    s.arrow([(602, 160), (678, 160)], "core", "登録開始", 640, 148)
    s.arrow([(932, 178), (1008, 178)], "core", "完了", 970, 166)
    s.arrow([(805, 128), (805, 76), (1135, 76), (1135, 128)], "warn", "残りを中断", 970, 66)
    s.arrow([(1135, 228), (1135, 296), (805, 296), (805, 228)], "ui", "失敗・中断した分だけ再実行", 970, 316)
    s.arrow([(1250, 228), (1250, 360), (145, 360), (145, 228)], "muted", "続けて追加（登録先は維持）", 700, 350)
    return s.render()


# ═══════════════════════════════════════════════════════════════════════════════
# 本文
# ═══════════════════════════════════════════════════════════════════════════════

NAV = [
    ("概要", [("overview", "システムの要点"), ("arch", "システム構成図"), ("changes", "今回の変更（2026-10）")]),
    ("Houdini チュートリアル生成", [("gen", "生成の流れ"), ("loop", "エージェントのロジック"), ("tools", "エージェントのツール"),
                                      ("domains", "対応範囲"), ("inputs", "生成条件・対象モデル"), ("feedback", "評価と学習")]),
    ("Cloudflare RAG", [("knowledge", "ナレッジ追加"), ("mcp", "公式MCP連携"), ("mcp-flow", "接続フロー"), ("mcp-chat", "チャットでの利用"),
                         ("mcp-policy", "ツールの方針"), ("mcp-layers", "共通層と固有層")]),
    ("リファレンス", [("api", "エンドポイント"), ("security", "権限と安全性"), ("files", "コードの置き場所"), ("add", "サービスを足す")]),
    ("運用", [("ops", "デプロイと設定"), ("verify", "検証した内容"), ("limits", "未対応・制約"), ("trouble", "困ったとき")]),
]


def nav_html() -> str:
    out = ['<nav class="index" aria-label="目次"><p>Contents</p>']
    for group, items in NAV:
        out.append(f'<span class="group">{group}</span>')
        out.extend(f'<a href="#{i}">{t}</a>' for i, t in items)
    out.append("</nav>")
    return "".join(out)


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def pill(kind: str, text: str) -> str:
    return f'<span class="pill {kind}">{text}</span>'


OK, WAIT, OFF, WARN = (lambda t: pill("ok", t)), (lambda t: pill("wait", t)), (lambda t: pill("off", t)), (lambda t: pill("warn", t))


def body() -> str:
    parts: list[str] = []
    add = parts.append

    add('<h2 id="overview">システムの要点<small>OVERVIEW</small></h2>')
    add("""<ul>
<li><strong>Houdiniパネル</strong>（PySide6）から、自然言語の依頼でHoudiniのノードグラフを<strong>実際に組み立て</strong>、cookエラーなしを確認したチュートリアル（Markdown＋ノードグラフ＋手順ごとの画像）を作ります。保存後は解説動画の生成も起動できます。</li>
<li><strong>Cloudflare Worker</strong>（rag-poc）が、RAG検索・回答（Gemini）、Claude APIプロキシ、ナレッジ管理（登録・同期・クロール）、公式MCPクライアント、評価の受付を担います。</li>
<li>知識は<strong>houdini21／houdini22</strong>などのnamespaceごとに検索します。ライセンス上、検索対象はHoudiniのドキュメントに限っています。</li>
<li>生成は<strong>モデルの知識＋ツールからの実機の返答</strong>が主役で、RAGは補助です（参考ドキュメントの利用率はMarkdownに記録されます）。</li>
<li>過去の評価（👍👎・タグ・メモ）と生成時の自動指標は、<strong>集計・教訓・成功例</strong>として次の生成に反映できます。モデルの重みを学習するのではなく、プロンプトと設定選びの根拠にします。</li>
</ul>""")

    add('<h2 id="arch">システム構成図<small>ARCHITECTURE</small></h2>')
    add("<p>利用者はブラウザの管理画面・Webチャットと、Houdiniのパネルを使います。どちらもCloudflare Workerを通って、GeminiやClaude、公式MCPサーバーなどの外部サービスにつながります。</p>")
    add(diagram_architecture() + LEGEND)

    add('<h2 id="changes">今回の変更（2026-10）<small>CHANGES</small></h2>')
    add(table(["領域", "変更", "状態"], [
        ["Houdini", "反復上限を40→<strong>80回</strong>（パーティクル系で打ち切られやすかったため）。動画タブの右ペインを撤去し、一覧を全幅・大サムネイルに", OK("反映済み")],
        ["Houdini", "<strong>生成条件</strong>（必須条件の自由記述）と<strong>対象モデル</strong>（fbx/glb/usd/obj/bgeo/abc/ply）の指定。ガウシアンスプラットを「風」ではなく本物で扱う知識の節", OK("反映済み")],
        ["Houdini", "ツール強化：<code>inspect_geometry</code>、キーフレーム・式・ランプ、入力名での接続、TOPの作業項目生成、Cop／Lop／Chopの一覧。Houdini 22の新機能（241ノードを実機で確認）をプロンプトに", OK("反映済み")],
        ["Houdini", "<strong>評価と学習</strong>：👍👎・理由タグ・メモ、自動指標、集計、教訓（承認制）、成功例", OK("反映済み")],
        ["Cloudflare", "評価の受け付けと<strong>管理者限定の閲覧</strong>（集計・一覧・CSV）", OK("本番反映済み")],
        ["Cloudflare", "クロールの最大ページ数の上限（50）を撤廃（状態サイズで安全に停止）", OK("本番反映済み")],
        ["Cloudflare", "<strong>ナレッジ追加</strong>を3ステップのポップアップに統合", OK("本番反映済み")],
        ["Cloudflare", "<strong>公式MCP連携</strong>（Notion・Atlassian）。管理画面で接続・ツール選択、RAGチャットで読み取り専用ツールを利用", OK("本番反映済み")],
        ["不具合修正", "参考欄の題名が空になる／OAuth結果ページの未エスケープ／ランプが1点に潰れる／TOPが「cook成功」でも何もしない", OK("修正済み")],
    ]))

    # ── Houdini ──
    add('<h2 id="gen">生成の流れ<small>FLOW</small></h2>')
    add("<p>Tutorialタブで依頼を入力してから、保存・評価までの流れです。左から利用者、エージェント（Houdini内）、Cloudflare、Houdini実機のレーンです。</p>")
    add(diagram_generation_flow() + LEGEND)

    add('<h2 id="loop">エージェントのロジック<small>LOGIC</small></h2>')
    add("<p>Claudeの応答の種類（拒否・ツール呼び出し・テキストのみ）と、反復・コストの上限で分岐します。完了・打ち切りのどちらでも、成果物と指標は必ず組み立てます。</p>")
    add(diagram_agent_logic())
    add("<h3>救済ロジック（テキストのみで終わろうとしたとき）</h3>")
    add(table(["状況", "催促の内容", "上限"], [
        ["ノードを1つも作っていない", "create_nodeから始める。2回目は「基本形状の組み合わせで妥協してよい」", "2回"],
        ["ノードはあるがfinish_tutorial未呼出", "cookエラーを確認してfinish_tutorialを提出する", "1回"],
        ["finish_tutorialは呼んだがconfirm未呼出", "画像を見て確定する。2回目は「今すぐconfirmだけ呼ぶ」", "2回"],
        ["残り5回以内／コスト85%超", "新しい作業を始めず、今の状態で仕上げる（1回だけ差し込む）", "1回"],
    ]))
    add("<h3>モデルとコスト</h3>")
    add("<ul><li>既定は <code>claude-sonnet-5</code>。<code>claude-sonnet-5-5</code>・<code>claude-opus-5-5</code>・<code>claude-haiku-4-5</code>も選べます。5.5系は<strong>effort=medium</strong>、1ターンの出力上限16000（思考もmax_tokensに数えられるため）。</li>"
        "<li>反復上限<strong>80回</strong>、コスト上限<strong>$5</strong>（クライアント側のフェイルセーフ。実際の上限はWorkerのClaude予算が強制）。拒否（stop_reason=refusal）は分類つきで打ち切ります。</li></ul>")

    add('<h2 id="tools">エージェントのツール<small>TOOLS</small></h2>')
    add("<p>モデルが呼べるのは次の10個だけです。ノードの操作はすべてサンドボックス（<code>/obj/ai_tutorial_&lt;時刻&gt;</code>のsubnet）の中に限られ、サンドボックス外のパスは実行前に拒否・監査ログに記録されます。</p>")
    add(table(["ツール", "役割", "2026-10の変更"], [
        ["<code>create_node</code>", "ノードを作る（parentで階層を指定）", "—"],
        ["<code>set_parameter</code>", "パラメータを設定", "<code>expression</code>（Hscript式）・<code>keyframes</code>・<code>ramp</code>を追加。ランプに<code>value</code>を渡すと拒否して案内（以前は1点に潰れた）。不正な式は<code>node.errors()</code>から報告"],
        ["<code>connect_nodes</code>", "ノードを接続する", "<code>input_name</code>／<code>output_name</code>で指定でき、結果に入出力名を返す（<code>in:0 type</code>のように取り違えが見える）"],
        ["<code>cook_node</code>", "評価してエラーを取得", "時間依存ノードは10フレーム評価。<strong>TOP</strong>は作業項目の生成まで（実行はしない）"],
        ["<code>list_available_node_types</code>", "ノードタイプを検索", "<code>Cop</code>（Copernicus）・<code>Lop</code>・<code>Chop</code>を追加。<code>Cop2</code>は旧COP"],
        ["<code>get_node_info</code>", "状態・パラメータ・接続を取得", "入力名（番号と名前）と出力名を表示"],
        ["<code>inspect_geometry</code>", "<strong>中身を数値で確認</strong>", "<strong>新規</strong>。SOP：点/プリム数・範囲・属性・グループ・GSplat判定。COP：解像度・値の範囲・一定値の検出。LOP：プリム一覧"],
        ["<code>delete_node</code>", "不要なノードを削除", "—"],
        ["<code>finish_tutorial</code>", "手順・概要などを提出", "—"],
        ["<code>confirm_tutorial</code>", "自己確認画像を見て確定", "—"],
    ]))

    add('<h2 id="domains">対応範囲<small>COVERAGE</small></h2>')
    add("<p>Houdini 22.0.459（hython）で、実際のツール経路から作成・接続・設定・cookを確認した結果です。Houdini 21は未確認です。</p>")
    add(table(["領域", "状態", "できること・注意"], [
        ["ジオメトリ（SOP）", OK("可"), "作成・接続・cook・<code>inspect_geometry</code>"],
        ["UV", OK("可"), "uvunwrap／uvlayout／uvproject、H22のuvrelax・labs::autouv"],
        ["マテリアル", OK("可"), "matnet＋principledshader::2.0、materialのshop_materialpath1。MaterialXはLOPのmateriallibrary内にsubnetを作ってその中に（<code>mtlxbuilder</code>というタイプは無い）"],
        ["Copernicus（COP）", OK("可"), "<code>copnet</code>の中に385種。<code>noise</code>は旧COPの名前で存在しない（cellularnoise等）。出力画像は<code>inspect_geometry</code>で数値確認（ビューポートには映らない）"],
        ["ガウシアンスプラット", OK("可"), "3DGS属性のポイント。.plyはFile SOPで読み込み、手続き生成は<code>attribwrangle</code>→<code>bakegsplat</code>。変換結果（orient／scale／Cd／GS_Alpha）を実機で確認"],
        ["アニメーション", OK("可"), "式・キーフレーム（bezier／linear／constant／ease）。設定後に3フレームの評価値を返す"],
        ["KineFX・APEX", WAIT("一部"), "SOPのノード（kinefx::／apex::）は作成・接続できる。<strong>APEXグラフの中身は編集できない</strong>"],
        ["DOP（シミュレーション）", OK("可"), "dopnetの中。cookは自動で10フレーム評価。POPはDOPなのでdopnet内に作る"],
        ["VOP", OK("可"), "attribvopの中。接続は<code>input_name</code>で（<code>turbnoise</code>の入力0は<code>pos</code>ではなく<code>type</code>）"],
        ["CHOP", OK("可"), "chopnetの中（wave・math・null）"],
        ["Solaris（LOP）", WAIT("ノード操作のみ"), "lopnetの中のノードは作成・cookできる。レンダリングは未対応"],
        ["TOP（PDG）", WAIT("生成のみ"), "作業項目を<strong>生成</strong>して件数を返す。実行はしない（ファイル出力・プロセス起動の副作用はサンドボックスで防げないため）"],
        ["レンダリング・画像書き出し", OFF("未対応"), "ツールが無い。フレーム範囲の設定・ノードのフラグ・HDA化も未対応"],
    ]))
    add("<h3>Houdini 22の新機能</h3>")
    add("<p>21と22の全ノードタイプを実機で比較し、<strong>22で増えた241ノード</strong>（COP 123／SOP 75／LOP 21／VOP 11／TOP 8／ROP 2／DOP 1）を、ツール経由で作成・cookして確認しました（COPのレシピ245個はノードではないので対象外）。作成は全て成功し、cookのエラーは入力未接続が原因でした。主要な19構成は配線してcookまで通しています。実機で名前を確認できたものだけを、Houdini 22で動いているときにプロンプトへ足します（<code>build_houdini22_section</code>）。</p>")

    add('<h2 id="inputs">生成条件・対象モデル<small>INPUTS</small></h2>')
    add('<div class="methods">'
        "<div><h3>生成条件</h3><p>必ず守ってほしい条件の自由記述（例：ガウシアンスプラットを実際に使う）。トピックより優先され、満たせなかった場合は「ハマりポイント」に理由を書かせます。</p><span class=\"tag\">frontmatter: requirements</span></div>"
        "<div><h3>対象モデル</h3><p>アニメーション・リギング用のモデルファイル。拡張子に応じた読み込みノード（fbxcharacterimport／gltfcharacterimport／usdcharacterimport／File SOP）を指示します。読み取り専用です。</p><span class=\"tag\">frontmatter: target_model</span></div>"
        "<div><h3>参考画像</h3><p>完成イメージのスクショ・写真（最大4枚）。長辺1280pxに縮小してClaudeに添付し、自己確認で見比べさせます。</p><span class=\"tag\">frontmatter: reference_images</span></div>"
        "<div><h3>知識の節（自動）</h3><p>トピック・条件・対象モデルから、GSplat／アニメーション・リギング／Houdini 22の節を必要なときだけ足します。</p><span class=\"tag\">build_domain_sections</span></div>"
        "</div>")

    add('<h2 id="feedback">評価と学習<small>FEEDBACK</small></h2>')
    add("<p>生成物の隣に2つのサイドカーを置きます。自動で残す指標（<code>_metrics.json</code>）と、履歴タブで付けた評価（<code>_feedback.json</code>）です。評価はCloudflareにも送られ、<strong>管理者だけ</strong>が閲覧できます。</p>")
    add(diagram_feedback() + LEGEND)
    add(table(["反映の方法", "中身", "注意"], [
        ["集計", "モデル・レベル・領域・理由タグ別の好評率、平均反復・コスト・cookエラー、打ち切り率", "評価が少ないうちは参考程度（数十件を超えてから判断）"],
        ["教訓（承認制）", "👎のメモからClaudeが「避けること」を数行に要約。<strong>承認したものだけ</strong>、システムプロンプトに最大10件", "生の失敗例をそのまま渡すと真似るため、一般化したルールにする"],
        ["成功例", "似た題材で👍かつ完走した構成を最大2件、構成の参考として渡す（題名・概要・使ったノード）", "文字・単語の重なりで選ぶ軽い方式"],
    ]))
    add("<p>自動指標には、モデル・レベル・領域（general／gsplat／animation／particles／simulation／copernicus／solaris／material／uv）・反復回数・cookエラー数・差し戻し回数・ノード数・コスト・所要時間・打ち切りか、に加えて、反映した教訓と成功例の件数が入ります。<strong>「教訓あり」と「なし」を同じ題材で比べて</strong>、効果を測れます。評価者が1人だと自分の好みへの最適化になるため、cookエラーや打ち切り率といった客観指標と併せて見ます。</p>")

    # ── Cloudflare ──
    add('<h2 id="knowledge">ナレッジ追加<small>KNOWLEDGE</small></h2>')
    add("<p>以前は、URL・クロール・YouTube・ファイル・FAQ・QA CSVの6つの入力欄が縦に並び、どれもnamespaceを毎回手入力していました。<strong>3ステップのポップアップ</strong>に統合しました。</p>")
    add(diagram_wizard())
    add(table(["方法", "できること"], [
        ["ファイル", "複数同時・ドラッグ＆ドロップ。PDF・Word（.docx）・PowerPoint（.pptx）・音声・動画。対応外の形式はその場で弾く"],
        ["URL", "1行1件で複数登録。YouTubeは自動判定（字幕を取得）。<strong>配下ページも含む</strong>を選ぶと、深さ・<strong>最大ページ数（上限なし）</strong>・パス絞り込み・除外パターン・既存スキップを指定できる"],
        ["Q&A", "質問・回答を複数件入力（未入力行は警告）。CSVの読み込み・貼り付け（ヘッダー行にquestion・answer）。Notion DBへの同時作成も選べる"],
    ]))
    add("<ul><li>登録先namespaceは選択式（前回の選択を記憶）。一覧に無いものは「その他（手入力）」。</li>"
        "<li>登録は1件ずつ実行して結果を表示。失敗した分・中断した分だけ再実行できる。登録中は閉じられない。</li>"
        "<li>クロールは1リクエストで1〜5ページずつ処理するバッチ方式（Workers Freeプランの制限対策）。進行状態はD1の1行（<code>crawl_jobs</code>）に保存するため、<strong>状態が約1.5MB（訪問済み約1万ページ分）を超えたら、そこまでを正常終了</strong>して案内する。待ち行列は3000件で頭打ち。</li></ul>")

    add('<h2 id="mcp">公式MCP連携<small>MCP</small></h2>')
    add("<p>Workerを<strong>MCPクライアント</strong>にして、各社が公開する公式のリモートMCPサーバーにつなぎ、そのツールをRAGチャットから使えるようにしました。</p>")
    add(table(["サービス", "MCPサーバー", "自動登録", "PKCE S256", "公開クライアント"], [
        ["Notion", "<code>https://mcp.notion.com/mcp</code>", OK("対応"), OK("対応"), OK("対応")],
        ["Atlassian（Jira／Confluence）", "<code>https://mcp.atlassian.com/v1/mcp</code>", OK("対応"), OK("対応"), OK("対応")],
    ]))
    add('<div class="note"><strong>OAuthアプリの登録・secretの設定は要りません</strong>認証は探索（RFC 9728／8414）、クライアントの自動登録（RFC 7591）、PKCE（S256）、リソース指定（RFC 8707）をWorkerが行います。公式サーバーの公開メタデータで対応を確認済みです。</div>')
    add('<div class="note warn"><strong>Atlassianの注意</strong>無効なトークンでもツール一覧（tools/list）を返します。認証が効くのは実行側なので、トークンの失効に気づくのは実行時になることがあります。</div>')
    add("<h3>連携の状態</h3>")
    add(diagram_states())

    add('<h2 id="mcp-flow">接続フロー<small>CONNECT</small></h2>')
    add("<p>管理者がボタンを押してから、ツールを選べるようになるまでです。途中の状態（code_verifier等）はD1に置きます。コールバックは別のisolateで処理されうるため、メモリには持ちません。</p>")
    add(diagram_mcp_connect() + LEGEND)

    add('<h2 id="mcp-chat">チャットでの利用<small>CHAT</small></h2>')
    add("<p>チャット画面に「外部サービスも使う」が出るのは、管理者が「チャットで使う」をオンにした接続があるときだけです。オンで質問すると、検索結果で足りないときに限り、Geminiが読み取り専用のツールを呼びます。回答の下に、使ったサービスとツール名が出ます。</p>")
    add(diagram_mcp_chat() + LEGEND)
    add("<ul><li>書き込み系のツールは、利用者の確認を挟む手段がまだ無いので、チャットには出しません（このWorkerのチャットはサーバー側で回答を作るため、確認ダイアログを挟めません）。</li>"
        "<li>Geminiの関数名は <code>mcp_&lt;サービス&gt;_&lt;ツール&gt;</code>。MCPの引数スキーマ（JSON Schema全体）は、Geminiが受け付ける部分集合（type・properties・required・items・enum・description）に変換します。</li></ul>")

    add('<h2 id="mcp-policy">ツールの方針<small>POLICY</small></h2>')
    add("<p>「モデルにどのツールを見せるか」と「確認が要るか」を、全サービス共通でここだけが決めます。</p>")
    add(diagram_policy())

    add('<h2 id="mcp-layers">共通層と固有層<small>LAYERS</small></h2>')
    add(table(["層", "担当", "場所"], [
        ["固有層（宣言＝データ）", "サービスごとのURL・ラベル・ツール方針（readOnlyTools／writeTools／blockedTools／toolHints）", "<code>src/mcp/providers.ts</code>"],
        ["共通層", "プロトコル（initialize・tools/list・tools/call、JSONとSSE）", "<code>src/mcp/protocol.ts</code>"],
        ["共通層", "OAuth 2.1（探索・自動登録・PKCE・コード交換・更新）", "<code>src/mcp/auth.ts</code>"],
        ["共通層", "ツールの許可・読み取り専用の判定", "<code>src/mcp/permissions.ts</code>"],
        ["共通層", "入口：保存（D1）・トークン更新・状態・ツール・実行・監査", "<code>src/mcp/service.ts</code>"],
        ["共通層", "Geminiの関数宣言への変換／関数呼び出しループ", "<code>src/mcp/schema.ts</code>・<code>chat.ts</code>"],
        ["共通層", "HTTPハンドラ（検証と権限判定だけ。処理はservice.ts）", "<code>src/mcp/routes.ts</code>"],
    ]))
    add("<p>サービスごとの違いは「宣言」だけで表し、通信・認可・保存・確認の判定は共通層に1つだけ置きます。ルーターはservice.tsの関数だけを呼びます。</p>")

    # ── リファレンス ──
    add('<h2 id="api">エンドポイント<small>API</small></h2>')
    add(table(["用途", "エンドポイント", "権限"], [
        ["検索／回答", "<code>POST /search</code>・<code>POST /query</code>（<code>useMcp</code>で外部サービスも使う）", "認証済み"],
        ["Claudeプロキシ", "<code>POST /claude/messages</code>", "認証済み（予算を強制）"],
        ["自分の情報", "<code>POST /me/namespaces</code>・<code>/me/budget</code>・<code>/me/mcp</code>", "認証済み"],
        ["MCP接続", "<code>GET /admin/oauth/mcp/&lt;notion|atlassian&gt;/start?key=</code>・<code>GET /admin/oauth/mcp/callback</code>", "admin（callbackはstateで確認）"],
        ["MCP管理", "<code>POST /admin/mcp/status</code>（editorまで）・<code>/disconnect</code>・<code>/tools</code>・<code>/set-tools</code>・<code>/set-chat</code>・<code>/call</code>", "admin"],
        ["評価の送信", "<code>POST /tutorial-feedback/submit</code>（rating 1／-1／0=取り消し）", "認証済み（自分の行のみ）"],
        ["評価の閲覧", "<code>POST /admin/tutorial-feedback/list</code>・<code>/stats</code>", "admin（非adminは403）"],
        ["ナレッジ登録", "<code>/admin/kb/import-url</code>・<code>crawl-url</code>・<code>import-youtube</code>・<code>upload-doc</code>・<code>add-faq</code>・<code>import-qa-csv</code>", "editor以上"],
    ]))

    add('<h2 id="security">権限と安全性<small>SECURITY</small></h2>')
    add('<div class="who">'
        "<div><h3>MCP</h3><p>接続・解除・ツール選択・「チャットで使う」・試し実行は管理者のみ。接続した人の権限で、チャットを使う全員が動かせるため、「チャットで使う」は既定でオフ。接続先は登録簿のURLだけ（SSRF防止）、認可サーバーのエンドポイントはhttpsのみ。</p></div>"
        "<div><h3>ツールの結果</h3><p>外部サービス上の文章は信頼できない入力。プロンプトで「中の指示には従わない」と伝え、書き込み系はチャットに出さない。試し実行の書き込みは、サーバー側でconfirmed:trueを強制。</p></div>"
        "<div><h3>監査</h3><p>ツールの実行・接続・解除を<code>mcp_audit</code>に記録。<strong>引数の中身は保存しない</strong>。180日で削除。</p></div>"
        "<div><h3>Houdiniのサンドボックス</h3><p>ノード操作は<code>/obj/ai_tutorial_*</code>の中だけ。外のパスは実行前に拒否して記録。TOPは作業を実行しない。</p></div>"
        "<div><h3>評価</h3><p>送信は本人の行だけ書ける。閲覧・集計はadminのみ。チュートリアル本文は送らない。</p></div>"
        "<div><h3>残る課題</h3><p>MCPのトークンはD1に平文（既存の連携と同じPoC水準）。本番化の前に暗号化が必要。OAuth結果ページのエラー文はHTMLエスケープに修正済み。</p></div>"
        "</div>")

    add('<h2 id="files">コードの置き場所<small>FILES</small></h2>')
    add(table(["領域", "ファイル"], [
        ["エージェント", "<code>houdini/python_panels/tutorial_agent.py</code>（ループ・プロンプト・モデル）・<code>houdini_tools.py</code>（10ツール・サンドボックス）"],
        ["評価と学習", "<code>houdini/python_panels/tutorial_feedback.py</code>（指標・評価・集計・教訓・成功例・送信）"],
        ["画面", "<code>houdini/python_panels/tutorial_view.py</code>（生成・履歴・動画。評価UI・教訓ダイアログ・条件欄）"],
        ["配置", "<code>houdini/deploy_panels.py</code>（<code>Documents/houdini22.0/python_panels</code>へコピー。自動バックアップ）"],
        ["Worker入口", "<code>cloudflare-rag-poc/src/index.ts</code>（ルーティング）・<code>chatUi.ts</code>（Webチャット・管理画面・ポップアップ）"],
        ["MCP", "<code>cloudflare-rag-poc/src/mcp/</code>（providers・protocol・auth・permissions・service・schema・chat・routes）"],
        ["評価（サーバー）", "<code>cloudflare-rag-poc/src/tutorialFeedback.ts</code>"],
        ["クロール", "<code>cloudflare-rag-poc/src/urlImport.ts</code>"],
        ["DB", "<code>cloudflare-rag-poc/migrations/0017_tutorial_feedback.sql</code>・<code>0018_mcp_connections.sql</code>"],
        ["このガイド", "<code>scripts/build_system_guide.py</code>＋<code>guide_svg.py</code>（図の部品）。<code>python scripts/build_system_guide.py</code>で再生成"],
    ]))

    add('<h2 id="add">サービスを足す<small>NEW PROVIDER</small></h2>')
    add('<ol class="steps"><li><code>src/mcp/providers.ts</code>の<code>MCP_PROVIDERS</code>に1件足す（公式のリモートMCPサーバーのURL、必要ならツール方針）。</li>'
        "<li>認可・保存・確認は共通層が行うので、他のコードは変えない。</li>"
        "<li>公開メタデータで自動登録（<code>registration_endpoint</code>）とPKCE S256に対応しているかを先に確認する。<strong>対応していないサーバー</strong>（例：GitHub）は、OAuthアプリの登録とsecret設定が別途要るため対象外。</li>"
        "<li>管理画面のポップアップは<code>/admin/mcp/status</code>の一覧から自動で組まれる。</li></ol>")

    # ── 運用 ──
    add('<h2 id="ops">デプロイと設定<small>OPERATIONS</small></h2>')
    add("<h3>Worker</h3>")
    add("<pre><code>cd cloudflare-rag-poc\nnpm run db:migrate:remote   # 0017（評価）・0018（MCP）を適用\nnpm run deploy</code></pre>")
    add("<h3>Houdiniパネル</h3>")
    add("<pre><code>python houdini/deploy_panels.py 22.0          # モジュールを配置（上書き前に自動バックアップ）\npython houdini/deploy_panels.py 22.0 --check  # 差分だけ表示\n# 配置後はHoudiniを再起動（起動中はモジュールがキャッシュされる）</code></pre>")
    add('<ol class="steps"><li>管理画面「ナレッジ登録」→「🔗 ＋ 連携するシステムを追加」。</li><li>Notion / Atlassian のカードを選び、詳細画面で「…で認証する（公式MCP）」。各社の画面で許可すると管理画面へ戻る。</li>'
        "<li>ツール一覧が出るので、使うものにチェックして「ツールの選択を保存」。</li><li>「RAGチャットでこのサービスのツールを使う」をオンにする。</li>"
        "<li>チャット画面で「外部サービスも使う」にチェックして質問する。</li></ol>")

    add('<h2 id="verify">検証した内容<small>VERIFY</small></h2>')
    add(table(["対象", "方法", "結果"], [
        ["Houdiniのツール・プロンプト", "hython 22.0.459で実ツール経路（作成・接続・設定・cook・検査）。回帰テスト一式", OK("通過")],
        ["Houdini 22の新ノード241個", "ツール経由で作成・cook。主要19構成は配線して確認", OK("作成は全て成功")],
        ["評価（クライアント）", "記録・送信（擬似サーバーで成功／401／未設定／接続不可）・集計・教訓・成功例・UI", OK("通過")],
        ["評価（Worker）", "実SQLiteでの権限（非admin拒否）・upsert・取り消し・集計", OK("通過")],
        ["MCP", "偽のOAuth／MCP／Geminiサーバー＋実SQLiteで、接続→ツール→実行→更新→再認証→解除、チャットのツールループ、権限、HTMLエスケープ", OK("通過")],
        ["公式サーバー", "Notion・Atlassianの公開メタデータを読み取り（自動登録・PKCE・公開クライアント）", OK("確認")],
        ["ポップアップ・MCPモーダル・チャットのスイッチ", "実ブラウザ（擬似APIサーバー経由）で操作。URL・クロール・YouTube・ファイル（失敗行の再実行）・Q&A・CSV", OK("通過")],
        ["本番", "マイグレーション適用・デプロイ後の疎通（読み取りのみ）", OK("確認")],
        ["本物の同意画面を通した接続", "ブラウザでの操作が必要なため未実施", WAIT("未確認")],
    ]))

    add('<h2 id="limits">未対応・制約<small>LIMITS</small></h2>')
    add("<ul><li>APEXグラフの中身の編集、TOPの作業の実行、レンダリング・画像書き出し、フレーム範囲の設定、ノードのフラグ（バイパス等）、HDA化は未対応。</li>"
        "<li>MCPの書き込みツールのチャット利用（確認ダイアログが必要）、Google公式MCP（Developer Preview参加が必要）、MCPトークンの暗号化は未対応。</li>"
        "<li>Houdiniパネルのチャットには、まだ「外部サービスも使う」が無い。</li>"
        "<li>実際のLLMでの生成（スプラット・リグ・Copernicus）、GUIでのビューポート確認、Houdini 21への配置は未確認。</li>"
        "<li>クロールは極端に大きいサイトでは状態サイズの上限で止まる（続きはパス絞り込みを変えて別のクロールで）。</li></ul>")

    add('<h2 id="trouble">困ったとき<small>TROUBLESHOOTING</small></h2>')
    add(table(["症状", "原因と対処"], [
        ["評価を付けたのに管理画面に出ない", "履歴タブの状態欄を確認（「送信に失敗」の文言）。Cloudflare未設定・APIキーの権限・Worker未デプロイのいずれか。ローカルの評価は残る"],
        ["MCPの接続後に「要再認証」", "トークンの失効・取り消し。管理画面で「再認証する」（ツール選択・チャット設定は引き継がれる）"],
        ["チャットに「外部サービスも使う」が出ない", "「チャットで使う」がオフ、または接続が要再認証。<code>POST /me/mcp</code>の<code>available</code>で確認"],
        ["Atlassianで失効に気づけない", "tools/listは無効トークンでも通る。実行時のエラーで判明する"],
        ["ポップアップのクロールが途中で止まる", "進行状態が上限を超えた案内が出る。パス絞り込みを変えて別のクロールで続ける"],
        ["Houdiniを再起動しても新機能が出ない", "<code>deploy_panels.py 22.0 --check</code>で差分を確認（Houdiniは<code>Documents/houdini22.0/python_panels</code>のコピーを読む）"],
        ["wranglerのD1が7403で失敗", "一時的なAPIエラーのことがある。再実行する"],
    ]))
    return "\n".join(parts)


def build() -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>システムガイド（Houdiniチュートリアル生成・Cloudflare RAG・公式MCP）</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Noto+Sans+JP:wght@400;500;700&family=Zen+Kaku+Gothic+New:wght@700;900&display=swap">
<style>{STYLE}</style>
</head>
<body>
<div class="page">
{nav_html()}
<main>
<header class="top">
<p class="kicker">DevelopmentRAGEnvironment</p>
<h1>システムガイド</h1>
<p class="lead">Houdiniチュートリアル自動生成・Cloudflare RAG・公式MCP連携・ナレッジ追加・評価と学習の、構成・ロジック・運用をまとめたガイドです。左の目次・層ごとの色分け・図中心の構成にしています。最終更新 2026-10-08。</p>
</header>
{body()}
<footer>このページは <code>scripts/build_system_guide.py</code> で生成しています。内容を変えるときはスクリプトを直して再生成してください。</footer>
</main>
</div>
<button class="theme" id="theme-toggle" type="button">ライト／ダーク</button>
<script>
document.getElementById("theme-toggle").addEventListener("click", function () {{
  var root = document.documentElement;
  var dark = root.getAttribute("data-theme") === "dark" || (!root.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.setAttribute("data-theme", dark ? "light" : "dark");
}});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
