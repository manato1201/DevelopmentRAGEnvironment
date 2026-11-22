"""
build_diagrams_reference.py — 通信構成図と、Reference の仕組みの図（2026-11-22追加。17・18）

build_diagrams.py から読み込まれる。内容を変えたら、ここを直して  uv run python scripts/build_diagrams.py communication reference  で作り直す。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diagram_kit import Diagram  # noqa: E402


def communication() -> Diagram:
    """各部品が、何で・どの向きに・何の認証でつながっているか。"""
    d = Diagram(1500, 1000, "通信構成図", "どの部品が、どの方式で、誰から誰へつながっているか。矢印は、通信を始める側から出る（常時接続は使わない）",
                legend=["ui", "core", "store", "ext", "safe"])
    d.group(24, 90, 540, 800, "利用者のPC", "Houdini・動画エンジン・ブラウザ。Local モードのブリッジ", "ui")
    d.group(610, 90, 590, 800, "Cloudflare", "rag-poc（Worker）と ragreel-gallery。鍵は Secrets に保管", "core")
    d.group(1246, 90, 234, 800, "外部のサービス", "HTTPS の API・公開ファイル", "ext")

    d.node("panel", 60, 160, "Houdini パネル", "PySide6（Houdini の中）", glyph="Hou", kind="ui")
    d.node("files", 60, 380, "保存フォルダ", "手順書・画像・台本", glyph="FS", kind="store")
    d.node("engine", 400, 380, "RAGReel", "動画エンジン（別の exe）", glyph="RR", kind="ui")
    d.node("bridge", 60, 600, "ローカルブリッジ", "localhost:8766", glyph="Brg", kind="safe", sub2="Local モードだけ")
    d.node("llm", 230, 600, "ローカル LLM の窓口", "127.0.0.1:8800", glyph="LLM", kind="safe", sub2="loopback 以外は拒否")
    d.node("browser", 400, 600, "ブラウザ", "管理画面・チャット・動画一覧", glyph="WEB", kind="ui")

    d.node("worker", 820, 160, "Worker（rag-poc）", "/query /search /claude", glyph="W", kind="core", sub2="/tts /reference /pilot /mcp")
    d.node("d1", 680, 480, "D1", "記録・検索・予算", glyph="D1", kind="store")
    d.node("vec", 820, 480, "Vectorize", "意味検索", glyph="Vec", kind="store")
    d.node("r2ref", 960, 480, "R2", "Reference の画像", glyph="R2", kind="store")
    d.node("gal", 700, 690, "Worker（ギャラリー）", "/api/videos", glyph="W", kind="core")
    d.node("r2g", 960, 690, "R2", "動画・サムネイル", glyph="R2", kind="store")

    d.node("gemini", 1330, 150, "Gemini", "埋め込み・回答", glyph="Gem", kind="ext")
    d.node("claude", 1330, 270, "Claude", "チュートリアル・台本", glyph="Cl", kind="ext")
    d.node("tts", 1330, 390, "Google TTS", "ナレーション", glyph="TTS", kind="ext")
    d.node("mcp", 1330, 510, "公式 MCP", "Notion・GitHub…", glyph="MCP", kind="ext")
    d.node("slack", 1330, 630, "Slack", "Events API", glyph="Sl", kind="ext")
    d.node("github", 1330, 750, "GitHub", "HoudiniReference", glyph="Ref", kind="ext", sub2="data/items.json")

    # ① パネル → Worker（HTTPS・Bearer キー）
    d.line([(116, 188), (820, 188)], "HTTPS の POST（JSON）＋ Bearer キー", kind="core", label_at=(470, 182), step=1)
    d.note(330, 206, "Chat /query・実験 /pilot/*・Reference /reference/*・音声 /tts", "start", 12)
    # ② パネル → 保存フォルダ・動画エンジン
    d.edge("panel", "bb", "files", "t", "書き出す", kind="ui", label_at=(122, 330))
    d.line([(116, 214), (428, 214), (428, 380)], "起動（引数＋ファイル渡し）", kind="ui", label_at=(300, 240), step=2)
    d.edge("files", "r", "engine", "l", "読む", kind="ui", label_at=(255, 400))
    # ③ パネル → ローカルブリッジ（Local モード）
    d.line([(60, 188), (40, 188), (40, 628), (60, 628)], "HTTP（localhost）", kind="safe", label_at=(100, 586), step=3)
    d.edge("bridge", "r", "llm", "l", "", kind="safe")
    d.note(60, 738, "ブリッジは、鍵を環境変数に持ち、Claude・Gemini へ", "start", 12)
    d.note(60, 756, "HTTPS で直接つなぐ（Cloudflare モードでは使わない）", "start", 12)
    # ④⑤ 動画エンジン → Worker・ギャラリー
    d.line([(456, 396), (745, 396), (745, 200), (820, 200)], "HTTPS: 音声 /tts", kind="core", label_at=(620, 390), step=4)
    d.line([(456, 424), (500, 424), (500, 718), (700, 718)], "HTTPS: 動画の送信（トークン）", kind="core", label_at=(590, 744), step=5)
    # ⑥ ブラウザ → Worker・ギャラリー
    d.line([(456, 628), (587, 628), (587, 188)], "HTTPS（管理画面）", kind="core", label_at=(572, 620), step=6)
    d.line([(456, 650), (728, 650), (728, 690)], "HTTPS（動画を見る）", kind="core", label_at=(650, 644))
    # Worker → ストア（バインディング）
    d.line([(848, 300), (848, 340), (708, 340), (708, 480)], "", kind="store")
    d.line([(848, 340), (848, 480)], "", kind="store")
    d.line([(848, 340), (988, 340), (988, 480)], "", kind="store")
    d.note(640, 604, "↑ Cloudflare のバインディング（内部の呼び出し。通信の鍵は要らない）", "start", 12)
    d.edge("gal", "r", "r2g", "l", "", kind="store")
    # Worker → 外部（鍵は Worker だけが持つ）
    d.line([(876, 175), (1226, 175), (1226, 178), (1330, 178)], "", kind="ext")
    d.line([(1226, 175), (1226, 298), (1330, 298)], "", kind="ext")
    d.line([(1226, 298), (1226, 418), (1330, 418)], "", kind="ext")
    d.line([(1226, 418), (1226, 538), (1330, 538)], "", kind="ext")
    d.note(900, 150, "HTTPS（鍵は Worker だけ。予算つきで中継）", "start", 12, True)
    # ⑦ Slack → Worker（Events API。署名を検証）
    d.line([(1330, 658), (1210, 658), (1210, 205), (876, 205)], "Events API（署名を検証）", kind="ext", label_at=(1100, 652), step=7)
    # ⑧ GitHub → パネル（HoudiniReference を取得）
    d.line([(1330, 778), (1228, 778), (1228, 850), (170, 850), (170, 232)], "HTTPS の GET: 関連の出典（1日1回・キャッシュ 24 時間）", kind="ext", dashed=True, label_at=(700, 844), step=8)

    d.note(24, 935, "番号: ① パネル→Worker ② パネル→動画エンジン（プロセスの起動。通信ではない） ③ Local モード ④⑤ 動画エンジン→クラウド ⑥ 管理画面 ⑦ Slack ⑧ HoudiniReference", "start", 12.5)
    d.note(24, 957, "認証: パネル・エンジン→Worker は Bearer キー（ハッシュで照合）。ギャラリーへの送信は専用のトークン（大きい動画は分割して送る）。外部 API の鍵は、Worker の Secrets だけ。", "start", 12.5)
    return d


def reference_flow() -> Diagram:
    """Reference タブの、説明と画像・動きの作り方（開発側）→ 置き場 → 参加者の画面。HoudiniReference は「関連（出典）」だけ。"""
    d = Diagram(1500, 900, "Reference タブの仕組み", "説明は、開発側が作って点検してから置く。参加者の端末は読むだけ。HoudiniReference は、関連のリンク（出典）だけに使う",
                legend=["ui", "core", "store", "ext", "safe"])
    d.group(24, 90, 700, 760, "開発側（開発者の PC）", "作る → 点検する → 撮る → 公開する。点検に通らないものは公開しない", "ui")
    d.group(760, 90, 360, 520, "Cloudflare（rag-poc）", "置き場。参加者の端末は、ここから読む", "core")
    d.group(760, 640, 360, 210, "HoudiniReference（別リポジトリ）", "Tips・動画・ニュース。題名・URL・日付・抜粋だけ", "ext")
    d.group(1160, 90, 316, 760, "参加者の PC（Reference タブ）", "説明・画像・動きと、関連の出典", "ui")

    d.box("docs", 48, 150, 300, 84, "SideFX 公式ドキュメント", "RAG に登録済み（Worker の /search）", "ext", sub2="説明の材料（資料）")
    d.box("hython", 380, 150, 320, 84, "実機の Houdini 22（hython）", "ノードの実在・本物のパラメータ名・撮影", "ui", sub2="vcc で VEX の関数の実在も確かめる")
    d.box("gen", 48, 300, 300, 84, "説明を書く", "build_reference_entries.py（Claude）", "core", sub2="資料＋実機の名前＋撮影の手順を渡す")
    d.box("audit", 380, 300, 320, 84, "実機と突き合わせる（点検）", "audit_reference.py", "safe", sub2="本物に無い名前・関数は、公開しない")
    d.box("cap", 48, 450, 300, 84, "撮る（33 ノード）", "capture.py ＋ recipes.py", "ui", sub2="適用前・後・値を動かす GIF")
    d.box("pub", 380, 450, 320, 84, "公開する", "publish_reference.py（HTTPS の POST・管理者キー）", "core", sub2="点検に通ったものだけ。画像はハッシュ入りの名前")
    d.note(48, 560, "撮影の検査: 値を初期値に戻して形が変わらない値は、「効く」と書けないので撮らない。", "start", 12.5)
    d.note(48, 582, "適用の前後で何も変わらない絵は、載せない（読んだ人が、同じ手順で何も起きないと困るため）。", "start", 12.5)
    d.note(48, 604, "説明の中の「」で囲んだ英字の名前は、そのノードの本物の名前か、レシピで設定した値だけ。", "start", 12.5)

    d.box("worker", 790, 150, 300, 84, "Worker", "/admin/reference/put・media_put", "core", sub2="/reference/index・entry・media（取得）")
    d.box("d1", 790, 290, 300, 84, "D1: reference_entries", "説明・media の一覧・version", "store", sub2="kind＋key で 1 件（0038）")
    d.box("r2", 790, 430, 300, 84, "R2: rag-poc-reference", "画像・GIF（最大 12MB）", "store", sub2="id に内容のハッシュ → 撮り直すと端末が取り直す")

    d.box("href", 790, 700, 300, 84, "GitHub: HoudiniReference", "data/items.json", "ext", sub2="毎日 収集（公式フィード・API）。約 400 件")

    d.box("p1", 1184, 150, 268, 84, "① 版を見る", "index の version", "ui", sub2="変わった項目だけ取り直す")
    d.box("p2", 1184, 290, 268, 84, "② 取ってきて、保存する", "説明・画像・GIF", "ui", sub2="端末のキャッシュ（古いものは整理）")
    d.box("p3", 1184, 430, 268, 84, "③ 表示する", "何をする・使いどころ・例・画像", "ui", sub2="Guide の手順からも、ここへ飛べる")
    d.box("p4", 1184, 700, 268, 100, "関連（出典）を選ぶ", "題名・タグに、そのノードの名前がある項目", "safe", sub2="別の文脈（COP・LOP）の記事は出さない")

    d.edge("docs", "b", "gen", "t", "資料", kind="ext", label_at=(198, 270), step=1)
    d.line([(540, 234), (540, 300)], "実在する名前", kind="ui", label_at=(590, 272))
    d.edge("gen", "r", "audit", "l", "", kind="core", step=2)
    d.edge("hython", "l", "cap", "t", "", kind="ui", via=[(370, 192), (370, 420), (198, 420)], dashed=True)
    d.edge("audit", "b", "pub", "t", "通過", kind="safe", label_at=(540, 420), step=3)
    d.edge("cap", "r", "pub", "l", "画像・GIF", kind="ui", label_at=(364, 486), step=4)
    d.line([(700, 492), (742, 492), (742, 192), (790, 192)], "", kind="core")
    d.edge("worker", "b", "d1", "t", "", kind="store")
    d.edge("d1", "b", "r2", "t", "", kind="store", dashed=True)

    d.line([(1090, 192), (1184, 192)], "HTTPS", kind="core", label_at=(1137, 184))
    d.edge("p1", "b", "p2", "t", "", kind="ui")
    d.edge("p2", "b", "p3", "t", "", kind="ui")
    d.edge("href", "r", "p4", "l", "1日1回 GET", kind="ext", label_at=(1137, 744), step=5)
    d.edge("p4", "t", "p3", "b", "出典を添える", kind="safe", label_at=(1318, 600))
    d.note(48, 650, "説明は Claude が書くので、材料に無いことは書かせない（資料に無ければ空欄）。", "start", 12.5)
    d.note(48, 672, "公開前の点検は、実機の Houdini で自動で行う。", "start", 12.5)
    d.note(48, 704, "HoudiniReference の項目は、説明の材料にはしない。", "start", 12.5, True)
    d.note(48, 726, "題名・URL・短い抜粋だけを使い、本文は、出典の元のページにある。", "start", 12.5)
    return d


REFERENCE_DIAGRAMS = {
    "communication": (communication, "17-communication"),
    "reference": (reference_flow, "18-reference-flow"),
}
