"""
build_diagrams.py — ドキュメント用の構成図（docs/images/*.svg）を作る（2026-10-23追加）

実行:  uv run python scripts/build_diagrams.py            # 全部作る
       uv run python scripts/build_diagrams.py overview   # 名前を指定して1枚だけ
図は diagram_kit.py の部品で、座標を手で決めて描く。内容を変えたら、このファイルを直して再実行する。
文書に入れるときは、Markdown に  ![説明](images/01-system-overview.svg)  と書く。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diagram_kit import Diagram  # noqa: E402
from build_diagrams_lecture import LECTURE_DIAGRAMS  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"


def overview() -> Diagram:
    d = Diagram(1440, 940, "システム全体の構成", "Houdini の手元の道具と、Cloudflare 上の検索・回答・動画の置き場、外部の AI・サービス",
                legend=["ui", "core", "store", "ext"])
    d.group(24, 80, 400, 560, "利用者のPC", "Houdini と動画エンジン", "ui")
    d.group(464, 80, 580, 560, "Cloudflare（rag-poc）", "検索・回答・Claude の中継・MCP・管理画面・実証実験。鍵は Secrets に保管", "core")
    d.group(1084, 80, 332, 640, "外部のAI・サービス", "鍵は Worker だけが持つ", "ext")
    d.group(24, 700, 1020, 200, "Cloudflare（ragreel-gallery）", "動画の置き場とダッシュボード", "core")

    d.node("panel", 70, 190, "Houdini パネル", "チャット・グラフ", glyph="Hou", kind="ui", sub2="チュートリアル・設定")
    d.node("engine", 270, 190, "RAGReel", "動画を作る .exe", glyph="RR", kind="ui")
    d.node("files", 270, 430, "保存フォルダ", "手順書・動画", glyph="FS", kind="store")

    d.node("worker", 700, 190, "Worker", "/query /search /claude", glyph="W", kind="core", sub2="/tts /mcp")
    d.node("d1", 560, 430, "D1", "全文検索・履歴・予算", glyph="D1", kind="store")
    d.node("vec", 800, 430, "Vectorize", "意味検索", glyph="Vec", kind="store")

    d.node("gemini", 1200, 190, "Gemini", "埋め込み・回答", glyph="Gem", kind="ext")
    d.node("claude", 1200, 330, "Claude", "チュートリアル生成・台本", glyph="Cl", kind="ext")
    d.node("tts", 1200, 470, "Google TTS", "ナレーションの音声", glyph="TTS", kind="ext")
    d.node("mcp", 1200, 610, "公式MCP", "Notion・GitHub・Slack…", glyph="MCP", kind="ext")

    d.node("gal", 270, 770, "Worker", "/api/videos（受け口）", glyph="W", kind="core")
    d.node("r2", 560, 770, "R2", "動画・サムネイル・目次", glyph="R2", kind="store")
    d.node("dash", 820, 770, "ダッシュボード", "ブラウザで動画を見る", glyph="WEB", kind="ui")

    d.line([(98, 190), (98, 156), (728, 156), (728, 190)], "質問・検索・生成（HTTPS＋APIキー）", kind="ui", label_at=(412, 150), step=1)
    d.line([(298, 190), (298, 156)], "", kind="ui", arrow=False)
    d.note(318, 180, "音声 /tts", "start", 12.5, True)
    d.edge("panel", "r", "engine", "l", "動画を作る", kind="ui", label_at=(190, 212))
    d.edge("engine", "bb", "files", "t", "書き出す", kind="ui", label_at=(345, 400))
    d.line([(728, 308), (728, 360), (588, 360), (588, 430)], "", kind="core")
    d.line([(728, 360), (828, 360), (828, 430)], "", kind="core")
    d.line([(756, 218), (1064, 218)], "", kind="ext", arrow=False)
    d.line([(1064, 218), (1064, 638)], "", kind="ext", arrow=False)
    d.line([(1064, 218), (1200, 218)], "", kind="ext")
    d.line([(1064, 358), (1200, 358)], "予算つきで中継", kind="ext", label_at=(1132, 346))
    d.line([(1064, 498), (1200, 498)], "", kind="ext")
    d.line([(1064, 638), (1200, 638)], "読み取り＋確認つき", kind="ext", label_at=(1128, 626))
    d.edge("files", "bb", "gal", "t", "アップロード（トークン）", kind="ui", label_at=(420, 670))
    d.edge("gal", "r", "r2", "l", "保存", kind="core")
    d.edge("r2", "r", "dash", "l", "配信", kind="core")
    return d


def tutorial_flow() -> Diagram:
    d = Diagram(1500, 640, "チュートリアルと動画ができるまで", "Houdini パネルでトピックを入れてから、ダッシュボードに載るまで（番号の順）",
                legend=["ui", "core", "ext", "store"])
    W, H = 250, 96
    xs = [40, 340, 640, 940]
    y1, y2 = 120, 380
    d.box("s1", xs[0], y1, W, H, "トピックを入力", "Houdini パネルの Tutorial タブ", "ui", sub2="条件・参考画像・対象モデル")
    d.box("s2", xs[1], y1, W, H, "ナレッジを検索", "Worker /search", "core", sub2="バージョン別・章ヒントつき")
    d.box("s3", xs[2], y1, W, H, "授業を設計", "目標・実験・つまずきを決める", "ui", sub2="（Claude に1回だけ聞く）")
    d.box("s4", xs[3], y1, W, H, "ノードを組み立てる", "エージェントが最大80回", "ext", sub2="Claude（Worker 経由・予算つき）")
    d.box("s5", xs[3], y2, W, H, "採点して保存", "手順書 .md ＋ グラフ .json", "store", sub2="内容を確認して「保存」")
    d.box("s6", xs[2], y2, W, H, "台本をつくる", "初心者向けの説明文", "ext", sub2="Claude（Worker 経由）")
    d.box("s7", xs[1], y2, W, H, "動画を作る", "RAGReel（音声・描画・WebM）", "ui", sub2="音声は Worker /tts → Google")
    d.box("s8", xs[0], y2, W, H, "ダッシュボードへ", "ギャラリーに自動アップロード", "core", sub2="URL とトークンを設定したとき")
    d.box("sb", 1240, y1, 230, H, "サンドボックス", "/obj/ai_tutorial_*", "ui", sub2="この中のノードだけを操作")
    for i, n in enumerate(["s1", "s2", "s3", "s4"]):
        d.badge(i + 1, d.nodes[n][0] + 14, d.nodes[n][1] - 2, "core")
    for i, n in enumerate(["s5", "s6", "s7", "s8"]):
        d.badge(i + 5, d.nodes[n][0] + 14, d.nodes[n][1] - 2, "core")
    d.edge("s1", "r", "s2", "l", "", kind="core")
    d.edge("s2", "r", "s3", "l", "", kind="core")
    d.edge("s3", "r", "s4", "l", "", kind="core")
    d.edge("s4", "b", "s5", "t", "完成", kind="core", label_at=(1090, 300))
    d.edge("s5", "l", "s6", "r", "", kind="core")
    d.edge("s6", "l", "s7", "r", "", kind="core")
    d.edge("s7", "l", "s8", "r", "", kind="core")
    d.edge("s4", "r", "sb", "l", "", kind="ui", both=True)
    d.note(1215, 108, "作る・直す", "middle", 12.5, True)
    d.note(40, 540, "Claude と音声合成の鍵は Worker だけが持ち、キーごとの予算（トークン・文字数）で止まります。Houdini の PC に鍵は置きません。", "start", 13)
    d.note(40, 566, "Houdini の操作は、サンドボックス（/obj/ai_tutorial_*）の中だけ。ファイルへの書き込みや、任意のコード実行のツールは持ちません。", "start", 13)
    return d


def rag_flow() -> Diagram:
    d = Diagram(1500, 620, "質問から回答までの流れ（RAG）", "検索は「意味」と「キーワード」の両方。回答には、必ず出典の番号をつける",
                legend=["ui", "core", "store", "ext"])
    W, H = 250, 96
    xs = [40, 340, 640, 940]
    y1, y2 = 120, 360
    d.box("q", xs[0], y1, W, H, "質問", "チャット・Houdini・Slack", "ui", sub2="（画像を添えてもよい）")
    d.box("ctx", xs[1], y1, W, H, "作業場所を読む", "SOP / DOP / APEX など", "core", sub2="同名ノードの章の取り違えを防ぐ")
    d.box("hyde", xs[2], y1, W, H, "検索語を補う", "仮の回答を作って検索に使う", "ext", sub2="Gemini（温度0・毎回同じ）")
    d.box("vec", 940, 106, 250, 56, "意味で探す", "Vectorize", "store")
    d.box("fts", 940, 174, 250, 56, "キーワードで探す", "D1 全文検索", "store")
    d.box("merge", xs[3], y2, W, H, "統合して並べる", "低い一致は除く", "core", sub2="作業場所の章を先に並べる")
    d.box("amb", xs[2], y2, W, H, "章が曖昧なら", "既定は SOP と答える", "core", sub2="冒頭に「前提: SOP の場合」")
    d.box("gen", xs[1], y2, W, H, "回答を作る", "検索結果だけを根拠に", "ext", sub2="Gemini・出典に [1] [2] の番号")
    d.box("out", xs[0], y2, W, H, "画面に出す", "出典パネル・根拠の経路", "ui", sub2="履歴・お気に入りに保存")
    d.edge("q", "r", "ctx", "l", "", kind="core")
    d.edge("ctx", "r", "hyde", "l", "", kind="core")
    d.line([(890, 168), (915, 168)], "", kind="core", arrow=False)
    d.line([(915, 134), (915, 202)], "", kind="core", arrow=False)
    d.line([(915, 134), (940, 134)], "", kind="core")
    d.line([(915, 202), (940, 202)], "", kind="core")
    d.line([(1190, 134), (1230, 134), (1230, 408), (1190, 408)], "", kind="core")
    d.line([(1190, 202), (1230, 202)], "", kind="core", arrow=False)
    d.edge("merge", "l", "amb", "r", "", kind="core")
    d.edge("amb", "l", "gen", "r", "", kind="core")
    d.edge("gen", "l", "out", "r", "", kind="core")
    for i, n in enumerate(["q", "ctx", "hyde"]):
        d.badge(i + 1, d.nodes[n][0] + 14, d.nodes[n][1] - 2, "core")
    d.badge(4, 954, 104, "core")
    for i, n in enumerate(["merge", "amb", "gen", "out"]):
        d.badge(i + 5, d.nodes[n][0] + 14, d.nodes[n][1] - 2, "core")
    d.note(40, 520, "ナレッジは namespace（houdini22・shared:…・personal:…）で分かれ、キーごとに、使える範囲が決まっています。", "start", 13)
    d.note(40, 546, "質問のたびに「予算の確保 → 使った分の精算」を行い、失敗したときは、確保した分を戻します。", "start", 13)
    return d


def mcp_flow() -> Diagram:
    d = Diagram(1500, 830, "外部サービス（MCP）の使い方と、書き込みの確認", "読み取りはそのまま、書き込みは毎回「実行」を押したときだけ",
                legend=["ui", "core", "store", "ext", "safe"])
    d.group(24, 80, 760, 690, "チャットでの流れ", "「外部サービスも使う」をオンにした質問", "core")
    d.group(824, 80, 652, 340, "つなげられる10サービス", "公式のリモートMCPだけ（任意のURLは受け付けない）", "ext")
    d.group(824, 440, 652, 330, "接続の種類", "誰の権限で動くかで、できることが変わる", "safe")
    W, H = 230, 90
    d.box("q", 54, 150, W, H, "質問", "チャット画面", "ui")
    d.box("loop", 314, 150, W, H, "ツール呼び出し", "Gemini が最大4往復・6回", "ext", sub2="結果は外部の文章＝命令にしない")
    d.box("read", 584, 150, 170, H, "読み取り", "そのまま実行", "safe", sub2="結果を回答に使う")
    d.box("write", 314, 330, W, H, "書き込み", "作成・更新・削除・送信", "warn", sub2="ここでは実行しない")
    d.box("pend", 314, 500, W, H, "確認待ちを保存", "D1（引数はサーバーに保存）", "store", sub2="1回だけ・5分で失効")
    d.box("card", 54, 500, W, H, "確認カード", "内容を見て「実行」を押す", "ui", sub2="やめることもできる")
    d.box("run", 54, 660, W, 90, "実行", "/mcp/confirm", "safe", sub2="保存した内容だけを実行")
    d.box("svc", 584, 500, 170, H, "外部サービス", "接続した人の権限", "ext")
    d.edge("q", "r", "loop", "l", "", kind="core")
    d.edge("loop", "r", "read", "l", "", kind="safe")
    d.edge("loop", "b", "write", "t", "書き込みのツール", kind="warn", label_at=(498, 300))
    d.edge("write", "b", "pend", "t", "", kind="warn")
    d.edge("pend", "l", "card", "r", "", kind="ui")
    d.edge("card", "b", "run", "t", "「実行」", kind="ui", label_at=(190, 640))
    d.edge("read", "b", "svc", "t", "呼ぶ", kind="ext", label_at=(672, 380))
    d.edge("run", "r", "svc", "b", "保存した内容を実行", kind="safe", via=[(669, 705)], label_at=(470, 697))
    d.note(60, 276, "モデルには、許可したツールだけを見せます。", "start", 12.5)
    names = [("Notion", "Nt"), ("GitHub", "GH"), ("Slack", "Sl"), ("Gmail", "Gm"), ("Drive", "Dr"),
             ("カレンダー", "Cal"), ("Figma", "Fg"), ("Canva", "Cv"), ("Vercel", "Vc"), ("CF Docs", "CF")]
    for i, (label, glyph) in enumerate(names):
        col, row = i % 5, i // 5
        d.node(f"p{i}", 880 + col * 112, 140 + row * 120, label, "", glyph=glyph, kind="ext", size=52)
    d.note(850, 408, "Cloudflare Docs は認証なし。ほかは OAuth（Google・GitHub・Slack は事前の登録が必要）。", "start", 12.5)
    d.box("shared", 860, 500, 280, 110, "共有の接続", "管理者が接続・全員のチャットで使う", "gray", sub2="読み取りだけ（書き込まない）")
    d.box("own", 1170, 500, 280, 110, "自分用の接続", "本人だけが使う", "safe", sub2="書き込みは許可したツールだけ")
    d.note(860, 650, "個人の権限のサービス（Gmail・Slack・GitHub など）は、「自分用」で接続します。", "start", 12.5, True)
    d.note(860, 676, "書き込みは、ツールの選択で、そのツールに明示的にチェックを入れたときだけ（初期は読み取りだけ）。", "start", 12.5)
    d.note(860, 702, "実行の記録は監査ログに残りますが、引数の中身は記録しません。", "start", 12.5)
    return d


def video_flow() -> Diagram:
    d = Diagram(1500, 810, "動画ができるまで（RAGReel）", "チュートリアルの手順書から、音声つきの WebM を作り、ダッシュボードに載せる",
                legend=["ui", "core", "store", "ext"])
    d.group(24, 80, 330, 440, "入力", "Houdini パネルが用意する", "ui")
    d.group(384, 80, 1092, 440, "RAGReel エンジン（手元の .exe）", "処理の進み具合がログに出て、パネルの進行バーになる", "core")
    d.group(24, 560, 1452, 190, "置き場とダッシュボード", "", "store")
    H = 80
    d.box("md", 54, 140, 270, H, "手順書 .md ＋ グラフ .json", "チュートリアル本体", "store")
    d.box("shot", 54, 250, 270, H, "ステップごとの画面", "ビューポート・ネットワーク", "store")
    d.box("scr", 54, 360, 270, H, "台本 .json", "初心者向けの説明（Claude）", "ext")
    d.box("sl", 414, 140, 240, H, "スライドに分ける", "見出し・手順・コード", "core")
    d.box("na", 694, 140, 240, H, "ナレーションを作る", "スライドごとの音声", "core")
    d.box("rd", 974, 140, 240, H, "描画する", "1コマずつ描く", "core")
    d.box("tts", 694, 340, 240, 110, "音声の経路", "Worker /tts → Google", "ext", sub2="だめなら VOICEVOX → Windows の声")
    d.box("en", 974, 340, 240, H, "エンコード", "VP9 ＋ Opus の WebM", "core")
    d.box("pub", 1234, 340, 220, H, "書き出す", "output/ に manifest と動画", "core")
    d.box("loc", 1234, 610, 220, 100, "手元の output/", "manifest.json", "store", sub2="videos/<id>/video.webm")
    d.box("up", 934, 610, 250, 100, "アップロード", "POST /api/videos", "core", sub2="トークンで認証（上限 約95MB）")
    d.box("r2", 634, 610, 250, 100, "R2 に保存", "動画・サムネイル・目次", "store")
    d.box("dash", 334, 610, 250, 100, "ダッシュボード", "ブラウザで見る", "ui", sub2="ギャラリー・動画の詳細")
    for i, n in enumerate(["sl", "na", "rd"]):
        d.badge(i + 1, d.nodes[n][0] + 14, d.nodes[n][1] - 2, "core")
    d.badge(4, 988, 338, "core")
    d.badge(5, 1248, 338, "core")
    d.edge("md", "r", "sl", "l", "", kind="core", via=[(374, 180)])
    d.line([(324, 290), (374, 290), (374, 180)], "", kind="core", arrow=False)
    d.line([(324, 400), (374, 400), (374, 180)], "", kind="core", arrow=False)
    d.edge("sl", "r", "na", "l", "", kind="core")
    d.edge("na", "r", "rd", "l", "", kind="core")
    d.edge("na", "b", "tts", "t", "音声", kind="ext", dashed=True, label_at=(742, 285))
    d.edge("rd", "b", "en", "t", "", kind="core")
    d.edge("en", "r", "pub", "l", "", kind="core")
    d.edge("pub", "b", "loc", "t", "", kind="store")
    d.edge("loc", "l", "up", "r", "", kind="core")
    d.edge("up", "l", "r2", "r", "", kind="core")
    d.edge("r2", "l", "dash", "r", "配信", kind="core")
    d.note(40, 540, "アップロードは、動画ができたあとに自動で行うか、「動画」タブの「選択をダッシュボードへ」「未アップロードをすべて」で行います。", "start", 12.5)
    return d


def distribution() -> Diagram:
    d = Diagram(1500, 780, "配布と、キー・予算の管理", "運営が作って配り、テスターは zip とインストーラーで入れる。鍵と予算は運営の Worker で管理する",
                legend=["ui", "core", "store", "safe"])
    d.group(24, 80, 446, 640, "運営のPC", "", "ui")
    d.group(510, 80, 450, 640, "Cloudflare（rag-poc）", "", "core")
    d.group(1000, 80, 476, 640, "テスターのPC", "", "ui")
    d.node("pkg", 70, 210, "配布 zip", "パッケージ＋install.cmd", glyph="ZIP", kind="store", sub2="build_houdini_package.py")
    d.node("inst", 270, 210, "インストーラー", "RAGReel-Setup.exe", glyph="EXE", kind="store", sub2="Inno Setup・利用者ごと")
    d.node("admin", 170, 470, "管理画面", "キー・ナレッジ・予算", glyph="ADM", kind="ui")
    d.node("worker", 700, 210, "Worker", "検索・回答・中継", glyph="W", kind="core")
    d.node("keys", 580, 470, "キーと予算", "ロール・範囲・上限", glyph="KEY", kind="safe")
    d.node("d1", 800, 470, "D1", "履歴・利用量", glyph="D1", kind="store")
    d.node("ins", 1040, 210, "install.cmd", "パッケージ登録・設定", glyph="CMD", kind="ui")
    d.node("rr", 1240, 210, "RAGReel", "動画を作る", glyph="RR", kind="ui")
    d.node("hou", 1140, 470, "Houdini パネル", "チュートリアル・動画", glyph="Hou", kind="ui", sub2="URL とキーを設定")
    d.line([(98, 210), (98, 150), (1068, 150), (1068, 210)], "配る（zip）", kind="store", label_at=(600, 142))
    d.line([(298, 210), (298, 170), (1268, 170), (1268, 210)], "配る（インストーラー）", kind="store", label_at=(800, 162))
    d.edge("admin", "r", "keys", "l", "キーを発行・予算を決める", kind="safe", label_at=(400, 490))
    d.edge("keys", "t", "worker", "bb", "", kind="safe", via=[(608, 350), (728, 350)])
    d.edge("ins", "bb", "hou", "t", "設定を書く", kind="ui", via=[(1068, 400), (1168, 400)], label_at=(1118, 392))
    d.edge("hou", "l", "worker", "r", "質問・生成・音声（キー）", kind="ui", via=[(900, 498), (900, 238)], label_at=(1020, 490))
    d.note(40, 690, "テスターは、Cloudflare の管理画面に入れません。1人ごとのキーと予算で、使える量が決まります。", "start", 13)
    return d


def security_layers() -> Diagram:
    d = Diagram(1300, 840, "守りの層（リクエストが通る順）", "上から順に確認し、どこかで止まったら、そこで終わる",
                legend=["safe", "warn", "store"])
    layers = [
        ("1", "画面を守る", "他のサイトの枠に埋め込めない（X-Frame-Options・frame-ancestors）。Referer を送らない", "http.ts・index.ts"),
        ("2", "APIキー", "32バイトの乱数。ハッシュで照合・期限つき。無効と期限切れは同じ応答（存在を教えない）", "auth.ts"),
        ("3", "ロール", "admin / editor / member / guest。管理の操作は admin、ナレッジ登録は editor まで", "auth.ts"),
        ("4", "ナレッジの範囲", "namespace の許可リスト。共有と個人（personal:）は別。他人の個人用には書けない", "auth.ts・retrieve.ts"),
        ("5", "予算と回数", "キーごとのトークン・文字数・回数の上限。超えたら 429 で止まる", "budget.ts・rateLimit.ts"),
        ("6", "外部との接続", "接続先は登録簿のURLだけ。OAuth の state は1回・10分。Backlog はドメイン限定。書き込みは確認", "mcp/・*OAuth.ts"),
        ("7", "記録", "監査ログに、誰が・何を・成否を残す。引数の中身は残さない。180日で削除", "mcp_audit・audit_log"),
    ]
    y = 100
    for i, (n, title, text, where) in enumerate(layers):
        kind = "warn" if n == "6" else ("store" if n == "7" else "safe")
        d.box(f"l{i}", 90, y, 960, 80, title, text, kind)
        d.badge(n, 62, y + 40, kind)
        d.note(1066, y + 44, where, "start", 11.5)
        if i:
            d.edge(f"l{i - 1}", "b", f"l{i}", "t", "", kind="gray")
        y += 96
    return d


def cost_flow() -> Diagram:
    d = Diagram(1500, 680, "費用と上限の流れ", "1回の処理ごとに「確保 → 実行 → 精算」。予算が足りなければ、実行の前に止める",
                legend=["core", "ext", "store", "warn"])
    W, H = 240, 90
    xs = [40, 330, 620, 910, 1200]
    y = 120
    d.box("a", xs[0], y, W, H, "キーを確認", "ロール・期限", "core")
    d.box("b", xs[1], y, W, H, "回数の制限", "短い間の連打を止める", "core")
    d.box("c", xs[2], y, W, H, "予算を確保", "見積りの分を先に引く", "core", sub2="足りなければ 429")
    d.box("e", xs[3], y, W, H, "外部の API を呼ぶ", "Gemini・Claude・Google TTS", "ext")
    d.box("f", xs[4], y, 260, H, "使った分で精算", "余りを戻す・失敗なら全額戻す", "core")
    for i, n in enumerate("abcef"):
        d.badge(i + 1, d.nodes[n][0] + 14, y - 2, "core")
    for a, b in zip("abce", "bcef"):
        d.edge(a, "r", b, "l", "", kind="core")
    d.box("stop", xs[2], 300, W, 70, "429 で止める", "予算超過・回数超過", "warn")
    d.edge("c", "b", "stop", "t", "足りない", kind="warn", label_at=(700, 262))
    d.group(40, 420, 1420, 220, "予算の種類（キーごとに設定）", "管理画面のキー管理で、人ごとに決める", "store")
    d.node("rag", 100, 480, "RAG", "Gemini のトークン", glyph="RAG", kind="store", sub2="質問・検索の補助・チャットの回答")
    d.node("cl", 560, 480, "Claude", "トークン（入力＋出力）", glyph="Cl", kind="store", sub2="チュートリアル・台本（キャッシュは数えない）")
    d.node("tt", 1020, 480, "音声", "文字数（日本時間で1日）", glyph="TTS", kind="store", sub2="キーごと 50,000 字・全体 300,000 字")
    d.note(40, 664, "目安: 1人あたり Claude 予算 約 42万トークン（チュートリアル＋台本で 5〜10回分）。詳しくは cost-and-quota.md。", "start", 12.5)
    return d


def positioning() -> Diagram:
    d = Diagram(1300, 820, "同じ Houdini と AI でも、立ち位置が違う", "縦軸: Houdini を外の AI から操作する範囲 ／ 横軸: 知識（ドキュメント検索）の厚み。筆者の整理で、数値ではありません",
                legend=["ui", "ext", "gray"])
    x0, y0, x1, y1 = 130, 110, 1230, 720
    d.parts.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="14" fill="var(--panel)" fill-opacity="0.6" stroke="var(--line)" stroke-width="1.5"/>')
    d.parts.append(f'<line x1="{(x0 + x1) // 2}" y1="{y0}" x2="{(x0 + x1) // 2}" y2="{y1}" stroke="var(--grid)" stroke-width="2" stroke-dasharray="6 6"/>')
    d.parts.append(f'<line x1="{x0}" y1="{(y0 + y1) // 2}" x2="{x1}" y2="{(y0 + y1) // 2}" stroke="var(--grid)" stroke-width="2" stroke-dasharray="6 6"/>')
    d.note((x0 + x1) // 2, y1 + 36, "知識（ドキュメント検索）が厚い →", "middle", 14, True)
    d.note(x0, y1 + 36, "薄い（なし・全文検索のみ）", "start", 12.5)
    d.note(x1, y1 + 36, "厚い（索引・RAG・版ごとの区別）", "end", 12.5)
    d.parts.append(f'<text class="muted" transform="translate(70 {(y0 + y1) // 2}) rotate(-90)" text-anchor="middle" font-size="14" font-weight="700">Houdini を操作できる範囲 →</text>')
    d.note(x0 + 8, y0 + 22, "広い（数百のツール）", "start", 12)
    d.note(x0 + 8, y1 - 10, "狭い（数個）", "start", 12)
    pts = [
        ("fx", 470, 170, "fxhoudinimcp", "215ツール・版ごとの全文検索", "ext"),
        ("dcc", 190, 200, "dcc-mcp-core", "47種の DCC を束ねる", "gray"),
        ("ocu", 330, 340, "oculairmedia", "43ツール・hrpyc", "ext"),
        ("cap", 190, 430, "capoomgit", "基本の操作・コード実行", "ext"),
        ("syn", 740, 280, "Synapse", "Houdini 内のアシスタント", "ext"),
        ("h21", 740, 560, "Houdini21MCP", "10ツール＋BM25 検索", "ext"),
        ("me", 1020, 520, "本システム", "RAG＋教材・動画の制作", "ui"),
    ]
    for nid, x, y, label, sub, kind in pts:
        d.node(nid, x, y, label, sub, glyph=("★" if nid == "me" else ""), kind=kind, size=48)
    d.note(1020, 700, "操作は、サンドボックス内の8ツール（＋完了の申告2）", "middle", 11.5)
    return d


def comparison_arch() -> Diagram:
    d = Diagram(1500, 760, "つなぎ方の違い", "左: 外の AI が Houdini を操作する型（fxhoudinimcp の公開された説明による） ／ 右: Houdini の中のパネルが、クラウドの知識と AI を使う型（本システム）",
                legend=["ui", "core", "ext", "store"])
    d.group(24, 100, 720, 600, "MCP サーバー型（外の AI → Houdini）", "", "ext")
    d.group(776, 100, 700, 600, "パネル＋クラウド型（Houdini → クラウドの知識と AI）", "", "ui")
    d.node("cl", 70, 190, "AI クライアント", "Claude・Cursor など", glyph="AI", kind="ext")
    d.node("srv", 280, 190, "MCP サーバー", "別プロセス（stdio）", glyph="MCP", kind="core")
    d.node("plug", 490, 190, "Houdini プラグイン", "hwebserver・ローカルHTTP", glyph="Hou", kind="ui")
    d.node("hou", 490, 440, "hou（メインスレッド）", "hdefereval で実行", glyph="hou", kind="ui")
    d.node("doc", 280, 440, "同梱マニュアル", "全文検索（3ツール）", glyph="DOC", kind="store")
    d.edge("cl", "r", "srv", "l", "ツール呼び出し", kind="core", label_at=(205, 210))
    d.edge("srv", "r", "plug", "l", "ローカルHTTP", kind="core", label_at=(415, 210))
    d.edge("plug", "bb", "hou", "t", "", kind="ui")
    d.edge("hou", "l", "doc", "r", "", kind="store", dashed=True)
    d.note(44, 640, "認証・ツールごとの許可・書き込みの確認は、公開されている説明では見当たらない（ローカルだけで動かす前提）。", "start", 12)
    d.node("pan", 820, 190, "Houdini パネル", "PySide（Houdini の中）", glyph="Hou", kind="ui")
    d.node("wk", 1050, 190, "Worker", "検索・Claude 中継・予算", glyph="W", kind="core", sub2="HTTPS＋キー")
    d.node("ai", 1280, 190, "Claude・Gemini", "鍵は Worker だけ", glyph="AI", kind="ext")
    d.node("tools", 820, 440, "ツール実行", "操作8＋完了の申告2", glyph="hou", kind="ui", sub2="hdefereval")
    d.node("kb", 1050, 440, "知識（D1・Vectorize）", "版ごと・章ごと", glyph="RAG", kind="store")
    d.node("ext", 1280, 440, "外部サービス（MCP）", "読み取り＋確認つき書き込み", glyph="MCP", kind="ext")
    d.edge("pan", "r", "wk", "l", "質問・生成", kind="core", label_at=(950, 210))
    d.edge("wk", "r", "ai", "l", "", kind="ext")
    d.edge("pan", "bb", "tools", "t", "", kind="ui")
    d.edge("wk", "bb", "kb", "t", "検索", kind="store")
    d.edge("ai", "bb", "ext", "t", "", kind="ext", dashed=True)
    d.note(796, 640, "操作は AI（Claude）の判断で進むが、触れるのはサンドボックスだけ。コード実行・ファイル書き込みのツールは持たない。", "start", 12)
    return d


DIAGRAMS = {
    "overview": (overview, "01-system-overview"),
    "tutorial": (tutorial_flow, "02-tutorial-flow"),
    "rag": (rag_flow, "03-rag-flow"),
    "mcp": (mcp_flow, "04-mcp-flow"),
    "video": (video_flow, "05-video-flow"),
    "distribution": (distribution, "06-distribution"),
    "security": (security_layers, "07-security-layers"),
    "cost": (cost_flow, "08-cost-flow"),
    "positioning": (positioning, "09-positioning"),
    "architecture": (comparison_arch, "10-comparison-architecture"),
    **LECTURE_DIAGRAMS,  # 11〜16（講義・保守用。build_diagrams_lecture.py）
}


def main(argv: list[str]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = argv or list(DIAGRAMS)
    for name in wanted:
        build, filename = DIAGRAMS[name]
        path = OUT / f"{filename}.svg"
        path.write_text(build().svg(), encoding="utf-8")
        print("wrote", path.relative_to(OUT.parents[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
