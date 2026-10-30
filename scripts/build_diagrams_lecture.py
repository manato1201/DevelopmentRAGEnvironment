"""
build_diagrams_lecture.py — 講義資料・各ドキュメント用の図（docs/images/11〜16）（2026-10-30追加）

build_diagrams.py から読み込まれる（単独で実行しない）。部品は diagram_kit.py。
作り方の決まり（番号つきの矢印・目的の名前の枠・主役は実線／補助は破線）は、diagram_kit.py の冒頭を見る。
"""

from __future__ import annotations

from diagram_kit import Diagram


def request_life() -> Diagram:
    d = Diagram(1500, 910, "質問が届いて、答えが返るまで（リクエストの一生）",
                "番号の順。名前を住所に直す → 暗号化した通信で送る → Worker が鍵を確かめる → 検索して回答 → 記録して返す",
                legend=["ui", "core", "store", "ext", "safe", "warn"])
    d.group(24, 90, 250, 690, "利用者", "Houdini パネル・ブラウザ・Slack", "ui")
    d.group(310, 90, 330, 170, "名前を住所に直す", "DNS（インターネットの電話帳）", "ext")
    d.group(310, 300, 900, 480, "Cloudflare", "世界中の拠点のうち、いちばん近い所が受ける", "core")
    d.group(1250, 300, 226, 480, "外部のAI", "鍵は Worker だけが持つ", "ext")

    d.node("app", 70, 380, "チャット・パネル", "質問を書く", glyph="Hou", kind="ui")
    d.node("dns", 560, 130, "DNS", "名前 → 住所（IP）", glyph="DNS", kind="ext")

    d.node("edge", 350, 380, "拠点（エッジ）", "HTTPS を受ける", glyph="TLS", kind="core")
    d.node("worker", 540, 380, "Worker", "index.ts が道案内", glyph="W", kind="core")
    d.node("auth", 730, 380, "認証・権限", "キー → ハッシュ", glyph="Key", kind="safe", sub2="→ users で照合")
    d.node("budget", 920, 380, "予算の確保", "上限を超えたら止める", glyph="Bgt", kind="warn")
    d.node("search", 1110, 380, "検索", "意味＋キーワード", glyph="Ret", kind="core")
    d.node("d1", 730, 600, "D1", "users・予算・履歴", glyph="D1", kind="store", sub2="キーワード検索（FTS）")
    d.node("answer", 920, 600, "精算して保存", "使った分を引く", glyph="Log", kind="core")
    d.node("vec", 1110, 600, "Vectorize", "意味検索", glyph="Vec", kind="store")
    d.node("gemini", 1335, 380, "Gemini", "検索語の補強・回答", glyph="Gem", kind="ext")

    # 1・2: 名前を住所に直す（往復）
    d.edge("app", "t", "dns", "l", "", kind="ext", dashed=True, via=[(98, 158)], both=True)
    d.badge(1, 345, 186, "ext")
    d.badge(2, 373, 186, "ext")
    d.note(392, 190, "問い合わせる／住所が返る", "start", 12.5, True)
    d.edge("app", "r", "edge", "l", "HTTPS＋キー", kind="ui", label_at=(238, 398), step=3)
    d.edge("edge", "r", "worker", "l", "起動", kind="core", label_at=(473, 398), step=4)
    d.edge("worker", "r", "auth", "l", "鍵を照合", kind="safe", label_at=(663, 398), step=5)
    d.edge("auth", "r", "budget", "l", "予算を確保", kind="warn", label_at=(853, 398), step=6)
    d.edge("budget", "r", "search", "l", "質問を渡す", kind="core", label_at=(1043, 398), step=7)
    d.edge("auth", "bb", "d1", "t", "", kind="store", dashed=True)
    d.edge("search", "bb", "vec", "t", "意味で探す", kind="store", dashed=True, label_at=(1138, 548))
    d.edge("search", "r", "gemini", "l", "回答を作る", kind="ext", label_at=(1250, 398), step=8)
    d.line([(1363, 484), (1363, 736), (962, 736), (962, 708)], "回答が返る", kind="ext", label_at=(1190, 728), step=9)
    d.edge("answer", "l", "d1", "r", "精算・保存", kind="store", label_at=(853, 648), step=10)
    d.line([(934, 708), (934, 840), (98, 840), (98, 490)], "JSON で返す（回答・出典・説明レベル）", kind="ui", label_at=(540, 832), step=11)

    d.note(330, 768, "失敗したときは、段階ごとに返す: 401（鍵が違う）・403（権限なし）・429（上限）・503（サーバー）", "start", 12)
    d.note(24, 892, "詳しくは、講義 1（インターネットの基礎）・2（Cloudflare の基礎）・5（Worker のコードを読む）。", "start", 12)
    return d


def pilot_flow() -> Diagram:
    d = Diagram(1500, 860, "実証実験の流れ（1人あたり 3回）", "登録 → 3回（各回に固定課題と自由課題）→ 回ごとにアンケート → 管理画面で集計。対照は、参加者の中に作る",
                legend=["ui", "core", "warn", "store"])
    d.box("a", 40, 96, 330, 96, "1. 事前アンケート", "学習背景・経験・使用歴（氏名は聞かない）", "ui", sub2="Houdini の「課題」タブで 1回だけ")
    d.box("b", 430, 96, 330, 96, "2. 番号を割り当てる", "参加者番号 P01…（登録順）", "core", sub2="割り当て番号 = ((番号−1) を 3 で割った余り)+1")
    d.box("c", 820, 96, 380, 96, "3. 順序と対照が決まる", "固定課題の順序を、割り当て番号ごとにずらす", "core", sub2="公式ドキュメントのみの回 = 割り当て番号と同じ回")
    d.edge("a", "r", "b", "l", "", kind="core")
    d.edge("b", "r", "c", "l", "", kind="core")

    d.note(40, 232, "割り当て番号 → 固定課題の順（回1・回2・回3）:  1 = Pyro → RBD → 雲（対照は回1） ／ 2 = RBD → 雲 → Pyro（対照は回2） ／ 3 = 雲 → Pyro → RBD（対照は回3）", "start", 13, True)
    rounds = [
        (40, "第1回", "Pyro（煙・炎）", "公式ドキュメント・Web検索のみ（対照）", "warn"),
        (520, "第2回", "RBD（剛体・破壊）", "本システムを使ってよい", "core"),
        (1000, "第3回", "雲（パーティクル）", "本システムを使ってよい", "core"),
    ]
    for x, title, task, cond, kind in rounds:
        d.group(x, 260, 460, 300, title, "割り当て番号 1 の例", "gray")
        d.box(f"f{x}", x + 24, 320, 412, 100, f"固定課題: {task}", cond, kind, sub2="到達の基準: 課題の題材として、作品物ができていること")
        d.box(f"g{x}", x + 24, 440, 412, 90, "自由課題: 自分の作りたいもの", "本システムを使ってよい", "core", sub2="どの回も同じ（題材は自由）")
    d.line([(500, 410), (520, 410)], "", kind="core")
    d.line([(980, 410), (1000, 410)], "", kind="core")
    d.box("survey", 40, 590, 1420, 96, "どの課題も、終えるたびに", "課題後アンケート（難しさ・わかりやすさ・集中・正確性の不安・出典の有用性・また使いたいか）／ 到達 ／ 操作ミスの自己申告", "ui",
          sub2="答えなくても送れる（空欄）。サーバーが記録する: 所要時間・質問回数（時間内の質問を数える）・cookエラーのノード数（Houdini が測る）")
    d.box("agg", 40, 716, 1420, 80, "4. 集計（管理画面の「実証実験」）", "回 × 種類 × 条件ごとの中央値 ／ 同じ参加者の中で、対照の回と本システムの回を比べる（差の中央値・効果量）／ CSV", "store",
          sub2="氏名は出さず、P01 のような番号。運営（管理者）のテストは入れない。人数が少ないうちは、参考値")
    return d


def task_states() -> Diagram:
    d = Diagram(1500, 790, "課題1回の状態の移り変わり", "ボタンを押すたびに、どう変わるか。サーバーに残るのは「計測中」と「完了」。破棄した記録は、消さずに残して集計から外す",
                legend=["ui", "core", "warn", "store"])
    W, H, Y = 190, 100, 330
    d.box("idle", 40, Y, W, H, "未開始", "「開始」を押せる", "gray")
    d.box("run", 420, Y, W, H, "計測中", "時間とエラーを記録", "core", sub2="20秒ごとに採取")
    d.box("survey", 800, Y, W, H, "振り返り", "アンケートに答える", "ui", sub2="時間は、終了を押した所まで")
    d.box("done", 1180, Y, W, H, "完了", "所要時間・質問回数を確定", "store", sub2="両方終えたら、次の回へ")
    d.box("pause", 420, 120, W, H, "中断", "Houdini が閉じた・落ちた", "warn", sub2="記録はサーバーに残る")

    d.edge("idle", "r", "run", "l", "開始", kind="core", label_at=(335, 372), step=1)
    d.edge("run", "r", "survey", "l", "終了を押す", kind="core", label_at=(715, 372), step=2)
    d.edge("survey", "r", "done", "l", "送信", kind="store", label_at=(1095, 372), step=3)
    d.line([(895, 430), (895, 480), (565, 480), (565, 430)], "戻る（終了を取り消す）", kind="ui", dashed=True, label_at=(730, 472))
    d.line([(480, 330), (480, 220)], "閉じる・落ちる", kind="warn", dashed=True, label_at=(412, 282))
    d.line([(550, 220), (550, 330)], "続きから開始", kind="warn", dashed=True, label_at=(622, 282))
    d.line([(460, 430), (460, 560), (135, 560), (135, 430)], "計測をやり直す（破棄）", kind="warn", label_at=(298, 552))
    d.line([(1275, 430), (1275, 650), (90, 650), (90, 430)], "完了した記録の「やり直す」（次の回を始める前だけ）", kind="warn", label_at=(680, 642))

    d.note(800, 515, "送信に失敗したら、答えを残して「答えを再送する」", "start", 12.5, True)
    d.note(40, 700, "やり直しで破棄した記録は、消さずに残す（やり直した回数が分析で分かる）。集計と、次の課題の判定には入れない。", "start", 13)
    d.note(40, 724, "再開すると、エラーのノードを引き継ぎ、閉じていた時間（40秒以上の空き）は「中断」として所要時間から引く。", "start", 13)
    d.note(40, 748, "次の回の課題を始めたあとは、前の回はやり直せない（回の順序と、対照の割り当てを崩さないため）。", "start", 13)
    return d


def data_model() -> Diagram:
    d = Diagram(1500, 900, "データの置き場（D1 の主な表）", "表は migrations/ の SQL で作る。どの表も、利用者は user_id（キーのハッシュ）で users とつながる",
                legend=["safe", "core", "store", "ui", "plan"])
    d.group(24, 90, 460, 280, "人と権限", "誰が、どの置き場を、どれだけ使えるか", "safe")
    d.box("users", 44, 152, 210, 84, "users", "キーのハッシュ＝利用者", "safe", sub2="user_id・role・expires_at")
    d.box("budgets", 264, 152, 210, 84, "token_budgets", "トークンの予算", "safe", sub2="budget_type・limit・used")
    d.box("grants", 44, 262, 210, 84, "key_namespace_grants", "キーが使える置き場", "safe", sub2="user_id・namespace_id")
    d.box("ns", 264, 262, 210, 84, "namespaces", "知識の置き場の名前", "safe", sub2="scope・token_budget")
    d.edge("grants", "r", "ns", "l", "", kind="safe")

    d.group(510, 90, 480, 280, "質問と回答", "チャットの履歴と、使われ方の記録", "core")
    d.box("memory", 530, 152, 220, 84, "memory", "質問と回答の履歴", "core", sub2="rating・pinned・explain_level")
    d.box("threads", 770, 152, 200, 84, "threads", "会話のまとまり", "core", sub2="thread_id・title")
    d.box("audit", 530, 262, 220, 84, "audit_log", "利用の記録", "core", sub2="tokens_used・model")
    d.box("terms", 770, 262, 200, 84, "user_terms", "習熟度（使った専門用語）", "core", sub2="term・count")
    d.edge("memory", "r", "threads", "l", "", kind="core")

    d.group(1016, 90, 460, 280, "ナレッジ（知識の断片）", "検索の元になるもの", "store")
    d.box("docs", 1036, 152, 200, 84, "kb_documents", "断片（チャンク）の出どころ", "store", sub2="chunk_id・file・namespace")
    d.box("rows", 1256, 152, 200, 84, "chunk_rows", "全文検索との対応", "store", sub2="chunk_id・fts_rowid")
    d.box("fts", 1036, 262, 200, 84, "FTS（全文検索）", "キーワードで探す", "store", sub2="D1 の仮想表")
    d.box("vec", 1256, 262, 200, 84, "Vectorize", "意味で探す", "ext", sub2="D1 の外にある索引")
    d.edge("docs", "r", "rows", "l", "", kind="store")
    d.edge("rows", "b", "vec", "t", "", kind="store", dashed=True)

    d.group(24, 410, 460, 150, "評価", "チュートリアルの良し悪し", "ui")
    d.box("fb", 44, 462, 420, 84, "tutorial_feedback", "チュートリアルの評価（1人1件×チュートリアル）", "ui", sub2="rating・tags・note・metrics（反復・cookエラー・費用）")

    d.group(510, 410, 966, 300, "実証実験", "参加者・課題の記録・アンケート（管理者のテストは集計に入れない）", "plan")
    d.box("pp", 530, 462, 260, 96, "pilot_profile", "参加者（事前アンケート）", "plan", sub2="pid（P01…）・slot・経験年数")
    d.box("ps", 860, 462, 596, 96, "pilot_sessions", "課題1回の記録（固定／自由 × 3回）", "plan", sub2="round・kind・condition・started／ended・duration・paused_sec")
    d.edge("pp", "r", "ps", "l", "user_id", kind="plan", label_at=(825, 496))
    d.note(530, 604, "pilot_sessions のアンケート列: difficulty・clarity・focus・accuracy_worry・source_useful・reuse・reached・self_mistakes・cook_error_nodes", "start", 12.5)
    d.note(530, 630, "discarded_at が入った行は「やり直しで破棄した記録」。同じ（人・回・種類）の有効な行は 1つだけ（部分一意索引）。", "start", 12.5)
    d.note(530, 656, "質問回数は、課題の時間内の memory の数をサーバーが数える（画面の申告に頼らない）。", "start", 12.5)

    d.note(24, 740, "つながり: memory・audit_log・token_budgets・user_terms・tutorial_feedback・pilot_profile は、どれも user_id で users に結ぶ。", "start", 13)
    d.note(24, 764, "表を増やす・変えるときは、migrations/ に連番の SQL を足す（既存のファイルは直さない）。講義 3・8 を参照。", "start", 13)
    return d


def houdini_panel() -> Diagram:
    d = Diagram(1500, 990, "Houdini パネルの内部構成", "画面（Qt）と、画面に依存しない部品を分けてある。部品は、Houdini なしで単体テストできる",
                legend=["ui", "safe", "core", "ext", "plan"])
    d.group(24, 90, 440, 820, "画面（PySide6 / Qt）", "rag_chatbot.py がタブを束ねる", "ui")
    d.node("main", 130, 160, "rag_chatbot.py", "メインのパネル・タブ・接続", glyph="Pan", kind="ui")
    d.node("ppanel", 130, 300, "pilot_panel.py", "「課題」タブ・アンケート", glyph="Pil", kind="ui")
    d.node("tview", 130, 440, "tutorial_view.py", "Tutorial タブ・評価・履歴", glyph="Tut", kind="ui")
    d.node("report", 130, 580, "report_dialog.py", "評価の集計の画面", glyph="Rep", kind="ui")
    d.node("gview", 130, 720, "graph_view.py", "グラフ・panel_widgets.py", glyph="Gra", kind="ui")

    d.group(510, 90, 450, 450, "画面に依存しない部品", "単体テストできる（unittest 186件）", "safe")
    d.node("pinfo", 580, 160, "panel_info.py", "文面・エラーの言い換え", glyph="Inf", kind="safe", sub2="出典の集計")
    d.node("ptask", 580, 300, "pilot_task.py", "計測・文言・送信内容", glyph="Tsk", kind="safe", sub2="エラーの採取・途中経過")
    d.node("tfb", 580, 440, "tutorial_feedback.py", "評価の保存・再送・集計", glyph="Fbk", kind="safe")
    d.node("pdbg", 800, 440, "panel_debug.py", "記録・秘密の伏せ字", glyph="Dbg", kind="safe")

    d.group(510, 570, 450, 340, "生成の本体（チュートリアル）", "Claude とのやりとりと、Houdini の操作", "core")
    d.node("agent", 580, 620, "tutorial_agent.py", "道具を呼ぶ繰り返し", glyph="Agt", kind="core", sub2="（最大80回）")
    d.node("tools", 800, 620, "houdini_tools.py", "hou を操作する道具", glyph="hou", kind="ui", sub2="サンドボックスの中だけ")
    d.node("client", 580, 770, "rag_client.py", "サーバーへの通信（HTTPS）", glyph="Net", kind="core", sub2="鍵は設定に保存")

    d.group(1006, 90, 470, 330, "クラウド", "鍵と予算は、ここで管理する", "ext")
    d.node("worker", 1100, 170, "Worker", "/query・/claude・/pilot/*", glyph="W", kind="ext", sub2="Cloudflare（rag-poc）")
    d.node("ai", 1330, 170, "Claude・Gemini", "鍵は Worker だけ", glyph="AI", kind="ext")
    d.edge("worker", "r", "ai", "l", "", kind="ext")

    d.group(1006, 570, 470, 340, "配置とテスト", "リポジトリ → Houdini の読む場所", "plan")
    d.node("deploy", 1060, 620, "deploy_panels.py", "コピーして配置", glyph="Dep", kind="plan", sub2="22.0 --pypanel")
    d.node("dest", 1290, 620, "python_panels/", "Documents/houdini22.0", glyph="Hou", kind="ui", sub2="（再起動で読み込み）")
    d.node("tests", 1130, 760, "tests/", "unittest・hython の通し", glyph="Tst", kind="safe", sub2="QT_QPA_PLATFORM=offscreen")
    d.edge("deploy", "r", "dest", "l", "コピー", kind="plan", label_at=(1243, 638))

    d.edge("main", "r", "pinfo", "l", "文面", kind="safe", label_at=(385, 178))
    d.edge("ppanel", "r", "ptask", "l", "測る・文言", kind="safe", label_at=(385, 318))
    d.edge("tview", "r", "tfb", "l", "評価", kind="safe", label_at=(385, 458))
    d.line([(330, 468), (330, 648), (580, 648)], "生成", kind="core", label_at=(360, 640))
    d.edge("agent", "r", "tools", "l", "道具を使う", kind="ui", label_at=(740, 638))
    d.edge("agent", "bb", "client", "t", "", kind="core")
    d.line([(636, 798), (983, 798), (983, 320), (1128, 320), (1128, 296)], "HTTPS で、鍵つきで送る", kind="core", label_at=(820, 790))
    d.note(40, 950, "決まり: 画面（Qt）に書くのは「表示と、ボタンの結びつけ」だけ。計算・文言・送信内容は、画面に依存しない部品に置く（テストできる形）。", "start", 12.5)
    return d


def change_flow() -> Diagram:
    d = Diagram(1500, 760, "変更してから本番に出すまで（保守・拡張の標準の流れ）", "番号の順。赤い工程（5・6）は、本番を変える。自動で進めず、名指しで許可してから行う",
                legend=["ui", "core", "warn", "store"])
    W, H = 230, 100
    xs = [40, 340, 640, 940, 1240]
    y1, y2 = 140, 400
    d.box("s1", xs[0], y1, W, H, "変更する", "コード・テスト・ドキュメント", "ui", sub2="DB なら migrations/ に SQL")
    d.box("s2", xs[1], y1, W, H, "型を検査する", "cd cloudflare-rag-poc", "core", sub2="npx tsc --noEmit")
    d.box("s3", xs[2], y1, W, H, "テストする", "Worker: npm test", "core", sub2="Houdini: unittest discover")
    d.box("s4", xs[3], y1, W, H, "画面で通し確認", "hython で、パネルを作って動かす", "core", sub2="（Houdini 側を変えたとき）")
    d.box("s5", xs[4], y1, W, H, "D1 に適用（本番）", "wrangler d1 migrations", "warn", sub2="apply --remote（戻せない）")
    d.box("s6", xs[4], y2, W, H, "Worker をデプロイ", "npx wrangler deploy", "warn", sub2="戻すなら wrangler rollback")
    d.box("s7", xs[3], y2, W, H, "動作を確かめる", "未認証で 401・画面・実機", "core", sub2="新しい API は 404 でないこと")
    d.box("s8", xs[2], y2, W, H, "パネルを配置", "deploy_panels.py 22.0", "store", sub2="--pypanel → Houdini を再起動")
    d.box("s9", xs[1], y2, W, H, "ドキュメントを直す", "関係する資料・図・講義", "ui", sub2="日付と、変えた理由を書く")
    d.box("s10", xs[0], y2, W, H, "コミット・プッシュ", "実際に出した内容と同じ版を", "ui", sub2="local-chat/ などは入れない")
    for i, n in enumerate(["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10"]):
        d.badge(i + 1, d.nodes[n][0] + 14, d.nodes[n][1] - 2, "warn" if n in ("s5", "s6") else "core")
    for a_, b_ in (("s1", "s2"), ("s2", "s3"), ("s3", "s4")):
        d.edge(a_, "r", b_, "l", "", kind="core")
    d.edge("s4", "r", "s5", "l", "", kind="warn")
    d.edge("s5", "b", "s6", "t", "", kind="warn")
    for a_, b_ in (("s6", "s7"), ("s7", "s8"), ("s8", "s9"), ("s9", "s10")):
        d.edge(a_, "l", b_, "r", "", kind="warn" if a_ == "s6" else "core")
    d.line([(755, 140), (755, 100), (155, 100), (155, 140)], "失敗したら、1 に戻って直す", kind="warn", dashed=True, label_at=(455, 92))
    d.note(40, 560, "順序の理由: D1（表の形）を先に変え、そのあと Worker を出す。逆だと、新しい Worker が、まだ無い列を読んでエラーになる。", "start", 13)
    d.note(40, 586, "パネルは、Worker を出したあとに配る。先に配ると、新しい機能が「サーバーが、この機能にまだ対応していません」（404）と出る。", "start", 13)
    d.note(40, 612, "戻し方: Worker は wrangler rollback。D1 は自動では戻らないので、打ち消す SQL を、新しいマイグレーションとして足す。", "start", 13)
    d.note(40, 638, "本番に触る操作（5・6）は、人が名指しで許可してから行う。テスト用の値と、本番のキーは混ぜない。", "start", 13)
    return d


LECTURE_DIAGRAMS = {
    "request": (request_life, "11-request-life"),
    "pilot": (pilot_flow, "12-pilot-flow"),
    "states": (task_states, "13-task-states"),
    "data": (data_model, "14-data-model"),
    "panel": (houdini_panel, "15-houdini-panel"),
    "change": (change_flow, "16-change-flow"),
}
