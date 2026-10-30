# 第16回 スクリプトを読み・書く（配置・点検・図・資料の生成）

**到達目標:** `scripts/` と `houdini/deploy_panels.py` を**1行ずつ読み**、何をして、何を壊しうるかを言える。**安全なスクリプトの型**に沿って、新しい小さなスクリプトを書ける。
**前提:** 第9回（本番を変える操作の見分け方）、第11回、`docs/learning/05-scripts.md`（シェルの基本）。 **目安:** 4時間

> `05-scripts.md` が「**道具の使い方**（PowerShell・wrangler）」なのに対し、この回は「**スクリプトの中身の読み方と書き方**」です。

---

## 1. 全体像：`scripts/` の地図

```
scripts/
├─ A. 資料・図を作る        diagram_kit.py  build_diagrams.py  build_diagrams_lecture.py
│                           build_docs_html.py  build_system_guide.py  guide_svg.py
├─ B. 配布・点検・退避       build_houdini_package.py  estimate_generation_cost.py  check_gemini_api.py
│   （＋ houdini/）          ci_check_namespaces.py  backup_data.py     ／ houdini/deploy_panels.py
└─ C. ローカル RAG（補助層）  rag_local_bridge.py(約1100行)  rag_service.py  vector_database.py
                            document_pipeline.py  auth_manager.py  pep.py  score_engine.py  auto_index.py …
```

- **A・B** は、この回の主題。**保守で最もよく触る。**
- **C** は、手元（ローカル）で動く**補助の層**（Cloudflare 上のクラウド版が主）。数が多いので、**必要になったときに、冒頭の docstring から読む**。どのファイルも、先頭の docstring に「何をするか・使い方」が書いてあります（このリポジトリの約束）。
- 実行は原則 `uv run python scripts/<名前>.py`（`pyproject` の環境で動かす）。

| スクリプト | 何をする | 本番に影響 | 書き換えるもの |
|---|---|---|---|
| `build_diagrams.py` | `docs/images/*.svg` を作る | なし | `docs/images/` |
| `build_docs_html.py` | `docs/**/*.md` → `.html` | なし | `.html` |
| `houdini/deploy_panels.py` | パネルを Houdini の設定フォルダへ配置 | **自分の PC** | `Documents/houdini<版>/python_panels/` |
| `ci_check_namespaces.py` | 未知の namespace フォルダを検知 | なし（読むだけ） | なし |
| `backup_data.py` | 再生成できないデータを zip に退避／復元 | `restore` は上書き | `backups/`、復元時は元の場所 |
| `estimate_generation_cost.py` | 記録から費用を見積もる | なし（読むだけ） | なし |

## 2. 基礎：安全なスクリプトの型

どのスクリプトも、次の**型**に沿っています。読むときは「型のどこか」を探すと速い。

| 部品 | 目的 | 例 |
|---|---|---|
| **docstring に使い方** | 実行前に、何をするか分かる | `deploy_panels.py` の冒頭に3つの実行例 |
| `from __future__ import annotations` | 型注釈を後ろ向きに許す（古い Python との互換） | ほぼ全ファイル |
| `main() -> int` ＋ `raise SystemExit(main())` | **終了コード**を返す（0 = 成功、それ以外 = 失敗）。CI や他のスクリプトが判定できる | `ci_check_namespaces.py` |
| `argparse` | 引数・サブコマンド・`--help` | `backup_data.py`（`backup`/`list`/`restore`） |
| `Path(__file__).resolve().parent` | **どこから実行しても**同じ場所を指す | `REPO = Path(__file__).resolve().parent / "python_panels"` |
| `--check` / `--dry-run` | **書かずに**、何が起きるかだけ見る | `deploy_panels.py --check` |
| **上書き前の退避** | 戻せるようにする | `deploy_panels.py` の `python_panels_backup_<日時>` |
| **確認プロンプト**／`--force` | 危険な操作の前に、人に聞く | `backup_data.py restore` |
| **標準エラーに出す** | 失敗の説明を、通常の出力と分ける | `print(..., file=sys.stderr)` |
| **冪等** | 何度実行しても同じ結果 | `_same()` で、同じなら何もしない |
| **秘密を持たない** | 鍵・トークンを、コード・引数・ログに書かない | 鍵は `wrangler secret`／環境変数 |

> 「型を満たしているか」は、**新しいスクリプトのレビューの観点**にもなります。

## 3. 読解1：`ci_check_namespaces.py`（検査スクリプトの見本）

**目的:** `localRAG/` の下に、**登録されていない namespace フォルダ**や、フォルダに属さない `.md` があれば、**失敗（終了コード 1）**にする（CI 用）。

読む順序：

1. **docstring を読む**（約30行）。**設計の経緯**が書かれている：最初は `pep.py` の表を“正”にしようとしたが、既存の正当なフォルダが引っかかる（**誤検知＝false positive**）と分かり、**`auto_index.py` の `NAMESPACES`** を“正”に変えた。→ **「何を基準に検査するか」が最重要**で、基準が間違うと、全部が誤検知になる。
2. `main()` の流れ：
   ```python
   known = set(NAMESPACES)                        # 集合にして、所属判定を O(1) に
   for entry in sorted(vault.iterdir()):          # sorted … 出力の順序を毎回同じに
       if entry.name.startswith(("_", ".")): continue     # 内部用は対象外
       if entry.is_dir():
           if entry.name not in known: unknown_dirs.append(entry.name)
       elif entry.is_file() and entry.suffix == ".md":
           unknown_files.append(entry.name)
   ```
3. **終了コード:** 問題があれば 1。**メッセージに“次にすること”を書く**（「`auto_index.py` の `NAMESPACES` に登録してください」）。
4. **フォルダが無ければスキップ（0）。** 検査対象が無いのは失敗ではない。

**この型の使い道:** 「**基準の一覧（正）**」と「**実際の状態**」を突き合わせ、**差が出たら失敗**にする検査は、さまざまな場面で書ける（例: マイグレーションの番号の欠番、図のファイルの有無、資料のリンク切れ）。

## 4. 読解2：`houdini/deploy_panels.py`（配置スクリプト）

**背景（2026-09-26）:** Houdini は `Documents/houdini<版>/python_panels/` の**コピー**を読むため、リポジトリを直しても、**手でコピーしない限り実機に反映されない**。約12日間、修正が届いていなかった。→ **配置を1コマンドにした。**

**流れ（97行）:**

```
引数 → 配置先を決める → 差分を調べる(_same) → [--check ならここで終了]
     → 変わったファイルだけ、元のファイルを退避してからコピー
     → [--pypanel なら] default.pypanel を作り直す（退避してから）
     → 「Houdini を再起動してください」
```

**1. 比較の工夫（`_same`）:** 改行コードの違い（Windows の `\r\n` と `\n`）で**誤って“違う”と判定しない**よう、両方を `\n` にそろえてから比べる。`b.exists() and …` で、配置先に無ければ「違う」。

**2. 変更だけをコピー:** `changed = [m for m in MODULES if not _same(...)]`。**変わっていないファイルは触らない**ので、バックアップも増えない。

**3. バックアップ:** `backup = house / f"python_panels_backup_{日時}"`。`copy2`（更新日時も保持）で退避してから上書き。→ **戻し方**（第9回）：その退避フォルダからコピーし戻す。

**4. `MODULES` の一覧:** 配置するモジュール名を**明示的に列挙**している。**新しい `.py` を `python_panels/` に足したら、この一覧にも足す**（足し忘れると、そのファイルだけ実機に届かない＝同じ事故）。`test_package.py` は、**`MODULES` と配布 zip の中身**のずれを検知する（登録漏れの再発防止）。一方、**`python_panels/` にあるのに `MODULES` に無い**ファイルは、このテストでは検知されない——現時点（実測）で一覧に無いのは `rag_chatbot.py` の1つだけで、これは `--pypanel` で `default.pypanel` に**埋め込む**ための意図した別扱い（演習 16.2）。

**5. `--pypanel` の“文字化けよけ”（要注意の読みどころ）:**

```python
embedded = script.encode("utf-8").decode("latin-1")
```

- `.pypanel` は XML で、スクリプトを `<![CDATA[ … ]]>` に入れる。Houdini は、この中身を**「UTF-8 のバイト列を1バイト＝1文字として読み替えた文字列」**として保存している（Houdini 自身が保存した形）。
- 日本語や `§` をそのまま書くと、Houdini 22 で `SyntaxError: (unicode error) 'utf-8' codec can't decode byte 0xa7` になった（2026-09-27、hython で再現）。
- **例:** `"§"` の UTF-8 は2バイト `C2 A7`。これを Latin-1 として読むと **2文字**（`Â` と `§`）になる。それを UTF-8 の XML として保存すると、Houdini が読むときに元の1文字へ戻る。
- **`"]]>"` を含むと CDATA が途中で閉じる**ので、事前に検査して中止（`return 1`）。

> 読み方のコツ：**奇妙なコードには、必ず“事故の記録”がコメントにある。** 消す前に、コメントを読む。

**6. 終了コード:** Houdini のフォルダが無ければ `return 1`（標準エラーに説明）。

## 5. 読解3：`backup_data.py`（何を退避し、何をしないか）

- **対象を絞る設計:** 「**再生成できるもの**（ChromaDB のインデックス＝ソースから作り直せる）は**対象外**。**消えたら二度と作れない**もの（認証 DB・ナレッジの履歴・監査ログ・取り込み済み Markdown）**だけ**」。→ **退避の対象は、“失うと困るか”で決める。**
- `restore` は**上書き**。確認プロンプト（`y/N`）があり、`--force` で省ける。**CI や自動化で `--force` を付けるときは、対象のファイルが正しいことを自分で保証する。**
- `zf.extractall(_REPO_ROOT)`：zip の中身を**リポジトリの根へ展開**する。Python の `zipfile` は、絶対パスや `..` を含む名前を無害化するが、**出所の分からない zip は復元しない**（`../` を使ったファイルの上書き攻撃＝Zip Slip の考え方）。
- **注意：このスクリプトは Local RAG（手元）用。** Cloudflare 側（D1 など）の退避は、**管理画面のバックアップのエクスポート**（`/admin/backup/export`）や `wrangler d1 export` を使う（第9回）。

## 6. 読解4：`diagram_kit.py`（図を“座標で”作る）

**方針（冒頭の docstring）:** 外部ライブラリなしの**単体 SVG**。**座標は手で決める（自動配置はしない）**——図の意図をそのまま固定するため。ライト／ダークは SVG の中の CSS 変数（`@media (prefers-color-scheme: dark)`）で切り替える。

**最小の図（実測）:**

```python
d = Diagram(420, 200, "例", "最小の図", legend=["ui", "core"])
d.node("a", 40, 80, "画面", "ブラウザ", "UI", kind="ui")        # タイルの左上 (40,80)、一辺56
d.node("b", 260, 80, "Worker", "処理", "W", kind="core")
d.edge("a", "r", "b", "l", "HTTPS", step=1)                      # a の右(r) → b の左(l)
open("x.svg", "w", encoding="utf-8").write(d.svg())
```

**座標の計算（コードと一致を確認済み）:**

| 量 | 式 | 値 |
|---|---|---|
| `a` の右辺の中点 | `(x + w, y + h/2) = (40+56, 80+28)` | (96, 108) |
| `b` の左辺の中点 | `(260, 80+28)` | (260, 108) |
| 矢印の経路 | `M 96.0 108.0 L 260.0 108.0` | 直線 |
| ラベルの位置 | 一番長い線分の中点、上に6px | x=178、y=102 |
| 番号の丸の位置 | ラベルの左。`中点x − (文字数×7 + 18)` | x = 178 − (5×7+18) = **125**、y = 108−6−5 = **97** |

- **`anchor(nid, side)`**: `l/r/t/b`（辺の中点）と `bb`（タイルの下の“文字”のさらに下）。**どこから矢印を出すか**を、名前で指定する。
- **`via=[(x,y),…]`**: 途中の折れ点。**直角に曲げて**、枠や文字を避ける。
- **描画の順序:** `parts`（枠・タイル）→ `edges`（矢印）の順に重ねる。**矢印は、枠の上に描かれる**。
- **`escape()`**: 文字を SVG に入れる前に、`<`・`&` を無害化（`html.escape`）。**文字を直接組み込む場所では、必ず通す。**
- **色は意味で固定:** `KINDS`（画面＝橙、中核＝緑、保存＝紫、外部＝青、安全＝濃緑、注意＝赤…）。凡例は `legend=[…]`。

**図を足す手順（第10回の課題 D と同じ）:**

1. `scripts/build_diagrams_lecture.py` に、`Diagram` を返す関数を書く。
2. 同じファイル末尾の `LECTURE_DIAGRAMS` に、`"名前": (関数, "17-ファイル名")` を足す。
3. `uv run python scripts/build_diagrams.py 名前` で 1 枚だけ作る（`build_diagrams.py` が `**LECTURE_DIAGRAMS` で合流している）。
4. **ブラウザで開いて見る**（ライトとダーク、両方）。
5. 資料に、他の図と同じ形で画像として埋め込む（例: この講義シリーズの `README.md` の「図11」の書き方を真似る）。

**既知の小さな重複（改善の候補）:** `edge()` と `_step_badge()` に、「一番長い線分を探す」ループが**ほぼ同じ形で2か所**ある。関数に切り出せば、位置の決め方を変えるとき、1か所で済む。（直すなら、既存の図の出力が**変わらない**ことを、全図の SVG の差分で確かめる。）

## 7. 読解5：`build_docs_html.py`（Markdown → HTML）

`uv run --with markdown python scripts/build_docs_html.py [資料のパス…]`。引数なしで全部、引数ありでその資料だけ作り直す。

**変換の流れ（`convert_one`）:**

| 段 | 何をする | なぜ |
|---|---|---|
| ① `dedent_list_fences` | リストの中の**字下げされたコードブロック**を、行頭に直す | python-markdown は行頭以外のフェンスを認識しない（GitHub は認識する） |
| ② `markdown.Markdown(...)` | 表・コードブロック・目次・番号付きリストを変換 | 拡張 `tables, fenced_code, toc, sane_lists, nl2br` |
| ③ タイトル抽出 | 最初の `<h1>` を本文から外してヘッダへ | 重複を避ける |
| ④ 手書きの「目次」節を除去 | 自動生成の目次と重ならないように | |
| ⑤ mermaid 変換 | `language-mermaid` を `<div class="mermaid">` に、必要なときだけ読み込み | ページを軽く保つ |
| ⑥ 表を横スクロール | `<div class="table-scroll">` で包む | 狭い画面で崩れない |
| ⑦ `fix_href` | 相対リンクの `.md` を `.html` に | **変換対象、または HTML が既にあるときだけ**（無いのに変えると切れる） |
| ⑧ シリーズのナビ | 同じフォルダの資料を「前へ／次へ」でつなぐ | 講義・座学資料 |

**`slugify`（見出し ID）:** 日本語を残し、`[^\w\s-]`（単語文字・空白・ハイフン以外）を消し、空白を `-` に。Python 3 の `\w` は日本語も含む。実測：

| 見出し | ID |
|---|---|
| `2.1 テンプレート文字列と、3つの禁止` | `21-テンプレート文字列と3つの禁止` |
| `` `chunkText` を読む`` | `chunktext-を読む` |
| `9. 演習 (A/B)` | `9-演習-ab` |

資料内の `#…` リンクは、この ID と**一致させる**必要がある（GitHub に近い規則に揃えてある）。

**`dedent_list_fences` の考え方（状態機械）:** 行を1つずつ見て、「字下げされたフェンス（` ``` `）」を見つけたら、**閉じのフェンスまで**を読み、字下げを取って出力する。前後に空行を足す。入力 `"1. 手順\n   ```bash\n   echo hi\n   ```\n2. 次\n"` は、`"1. 手順\n\n```bash\necho hi\n```\n\n2. 次\n"` になる（実測）。**コードブロックの前後でリストが分かれる**が、`sane_lists` で番号は引き継がれる。

> **変換の結果の `.html` は、直接編集しない。** 元の Markdown を直して、再生成する（フッターにも書いてある）。

## 8. 新しいスクリプトを書く（チェックリスト）

1. **目的を1行で。**「〇〇を読むだけで調べる」「〇〇を生成する」。
2. **読むだけか、書くか。** 書くなら、①`--dry-run`／`--check` ②上書き前の退避 ③確認 を付ける。
3. **本番（`--remote`・デプロイ）に触れない。** 触れるなら、スクリプトにせず、**人が名前を挙げて許可する手順**にする（第9回）。
4. **終了コード**を決める（0 = OK、1 = 問題あり）。
5. **場所に依存しない**（`Path(__file__)`）。
6. **秘密を持たない。**
7. **docstring に使い方と、設計の理由を書く。**
8. **テストを書く**（純粋な関数に分けて、`main` を薄くする）。

**見本：読むだけの点検スクリプト（動作確認済み）** — 資料の相対リンクの宛先が存在するか調べる。

```python
#!/usr/bin/env python3
"""check_doc_links.py — Markdown の相対リンクの宛先が存在するか調べる（読むだけ。何も書き換えない）

使い方:  uv run python scripts/check_doc_links.py docs/learning/lectures
終了コード: 0 = 切れたリンクなし / 1 = あり
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

LINK = re.compile(r"\]\(([^)\s]+)\)")          # [表示](宛先)
FENCE = re.compile(r"^\s*(```|~~~)")


def broken_links(md: Path) -> list[tuple[int, str]]:
    bad: list[tuple[int, str]] = []
    in_code = False
    for no, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            in_code = not in_code           # コードブロックの中は、リンクではない
            continue
        if in_code:
            continue
        for target in LINK.findall(line):
            if re.match(r"^(https?:|mailto:|#)", target):
                continue                    # 外部リンクと同じページ内は対象外
            path = target.split("#", 1)[0]
            if path and not (md.parent / path).resolve().exists():
                bad.append((no, target))
    return bad


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv] or [Path("docs")]
    found = 0
    for root in roots:
        for md in sorted(root.rglob("*.md")):
            for no, target in broken_links(md):
                print(f"{md.as_posix()}:{no}: 宛先がありません → {target}")
                found += 1
    print(f"切れたリンク: {found} 件")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

このスクリプトを講義フォルダに実行すると「切れたリンク: 0 件」（終了コード 0）になります。**型の部品がどこにあるか**を、上の表で確認してください：docstring／`main`／終了コード／読むだけ／場所に依存しない。

> このコードは**リポジトリには入れていません**（教材の見本）。演習 16.4 で、自分で `scripts/` に置き、テストを付けます。

## 9. 演習

**演習 16.1（読む）** `deploy_panels.py 22.0 --check` を実行し、出力の `DIFF`／`same` の意味を説明してください。**何も書き込まれない**ことを、コードのどの行で保証しているか答えてください。

**演習 16.2（読む）** `MODULES` と `houdini/python_panels/*.py` を見比べ、**一覧にないファイル**を挙げてください（`rag_chatbot.py` は別扱い）。なぜ、それは配置されないのか／配置されるべきか、理由も添えて。

**演習 16.3（トレース）** `"§".encode("utf-8").decode("latin-1")` の結果と、文字数を答えてください。

**演習 16.4（書く）** 見本の `check_doc_links.py` を `scripts/` に置き、(1) わざとリンクを1つ壊した一時的な Markdown（`docs` の外の一時フォルダ）で、終了コード 1 になること、(2) コードブロックの中のリンクは無視されること、を確かめるテストを書いてください（`houdini/tests` と同じ `unittest` で、`scripts/` から import する）。

**演習 16.5（図）** 見本の最小の図を、`d.node` を1つ増やして3ノードにし、`via` を使って**折れ線の矢印**を1本足してください。ライトとダークの両方で見て、矢印が文字に重なっていないことを確認する。

**演習 16.6（設計）** 「`migrations/` の番号に欠番がないか調べる」点検スクリプトの設計（入力・出力・終了コード・テストの観点）を、箇条書きで書いてください。

**演習 16.7（考える）** `backup_data.py restore --force` を、定期ジョブから呼ぶ設計は妥当か。理由を述べてください。

## 10. つまずきやすい点

- **相対パスで書く。** 実行した場所によって動かなくなる。`Path(__file__)` を基準に。
- **`print` だけで失敗を伝える。** 終了コードが 0 のままだと、CI が失敗に気づけない。
- **上書きの前に退避しない。** 戻せなくなる。
- **一覧（`MODULES`）の更新を忘れる。** 新しいファイルだけ届かない。
- **Windows の改行（`\r\n`）。** 比較・ハッシュ・差分の前に、そろえる。
- **生成物（`.html`・`.svg`）を直接直す。** 次の再生成で消える。元を直す。

## 11. 確認問題

1. `main() -> int` ＋ `raise SystemExit(main())` の利点は？
2. `--check` をスクリプトに付ける理由は？
3. `_same` が改行コードをそろえて比べる理由は？
4. `ci_check_namespaces.py` が最初に失敗しかけた理由と、その解決は？
5. `diagram_kit` が自動配置をしない理由は？

## 解答の方針

- 演習 16.1: `DIFF` = リポジトリと配置済みが違う（または配置先に無い）、`same` = 同じ。`if args.check: return 0`（`dst.mkdir` やコピーの**前**で返る）。
- 演習 16.2: 実測では、`python_panels/*.py` のうち `MODULES` に無いのは **`rag_chatbot` だけ**（`MODULES` にあってファイルが無いものは無し）。`rag_chatbot.py` は `--pypanel` で `default.pypanel` に**埋め込む**ので、`MODULES`（そのまま `.py` を配置するもの）とは別扱いで正しい。**新しい `.py` を足したときは、この比較をもう一度行い、一覧に足す**。この確認を自動化する検査（`python_panels/` と `MODULES` の差を出す）を足すのも、良い保守の演習になる。
- 演習 16.3: `'Â§'`、**2文字**。
- 演習 16.7: 不適切。`--force` は確認を省くので、**対象のファイルが正しいことを人が確かめる**前提。定期ジョブでの上書き復元は、データを失う事故になりうる。
- 確認問題 4: 検査の基準に `pep.py` の表を使うと、既存の正当なフォルダが引っかかる（誤検知）。基準を `auto_index.NAMESPACES`（実際にインデックス対象のフォルダ一覧）に変えた。
- 確認問題 5: 図の意図（何を、どこに置き、どの順に読むか）を、そのまま固定するため。自動配置は、データが変わると図が変わってしまう。
