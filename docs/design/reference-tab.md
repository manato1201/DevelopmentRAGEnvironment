# Reference タブ — ノード・VEX・APEX・シェルフツールの説明（設計と運用）

**更新日:** 2026-11-24 / **状態:** 実装済み・公開済み（ノード 316・VEX 198・APEX 82・シェルフツール 85。うち、適用前後の画像と動きがあるノードは 41）

Houdini パネルの **Reference タブ**は、ノードや VEX の関数の「**何をするか・使いどころ・例**」を、画像と動き（GIF）つきで見せる。説明は**開発側が作って点検してから置き**、参加者の端末は読むだけ（人ごとに内容が違う・AI の費用が際限なくかかる、を避けるため）。

[![Reference タブの仕組み](../images/18-reference-flow.svg)](../images/18-reference-flow.svg)

*図: Reference タブの仕組み。開発側で作って点検し、Cloudflare に置き、参加者の端末が読む。HoudiniReference は、関連のリンク（出典）だけに使う。*

## 1. 画面に出るもの、その元

| 画面に出るもの | 元になるもの |
|---|---|
| 何をするか・使いどころ・例・注意 | SideFX 公式ドキュメント（RAG に登録済み）を材料に、Claude が日本語で書いたもの。**実機の Houdini 22 で点検**してから公開する |
| 適用前・適用後の画像、値を動かす GIF | 実機（hython）で撮ったもの（§3）。ノードの図は、手順から描く |
| 関連（出典）のリンク | **HoudiniReference**（別リポジトリ）の項目から、そのノードの名前に一致するものだけ（§4） |

**HoudiniReference は、説明の材料にしない。** 題名・URL・日付・短い抜粋だけを使い、本文は元のページにある（権利は、それぞれの出典元）。

## 2. 作り方（開発側）

| 段階 | 道具 | やること |
|---|---|---|
| 1. 説明を書く | `scripts/build_reference_entries.py` | 資料（公式ドキュメントの抜粋）と、**実機から書き出した本物のパラメータ名**、撮影の手順（§3）を Claude に渡して書かせる。本物に無い名前が混ざったら、保存しない |
| 2. 点検する | `scripts/audit_reference.py` | 説明の中の「」で囲んだ英字の名前が、そのノードの本物のパラメータ名・メニュー項目（hython）か、ほかのノードの名前に在るかを調べる。VEX は、vcc で関数の実在を確かめる。**通らないものは公開しない** |
| 3. 撮る | `scripts/reference_capture/capture.py` | レシピ（`recipes.py`）から、適用前・適用後・値を動かす GIF を撮る（§3） |
| 4. 公開する | `scripts/publish_reference.py` | 点検に通ったものだけを、Worker（`/admin/reference/*`）に置く。画像は、内容のハッシュ入りの名前で R2 に置く（撮り直すと、端末が取り直す） |

```powershell
uv run python scripts/audit_reference.py                                  # 全部を点検（hython と vcc を使う）
uv run python scripts/build_reference_entries.py --set all --yes          # 無いものだけ作る（--redo --keys sop/xxx で作り直し）
uv run --with pillow --with PySide6 python scripts/reference_capture/capture.py --out build/reference_media --only sop/smooth
uv run python scripts/publish_reference.py --media build/reference_media --dry-run   # まず、何を公開するか確認
uv run python scripts/publish_reference.py --media build/reference_media             # 公開
uv run python scripts/publish_reference.py --unpublish node/sop/xxx                  # 取り下げ
```

作った説明を公開する前に、**人が読んで**、効き方の説明（資料の取り違えなど）を確かめる。パラメータ名の点検では、別のノード（例: COP の同名のノード）の資料が混ざったことは見つからない。

## 3. 撮影（適用前後・動き）

- レシピ 1 件 = 1 ノード。入力のノード（`input` / `inputs`。後ろに別のノードをつなげる `after`）、適用後の値（`parms`）、動かす値（`sweep`）を書く。**33 ノード**（2026-11-22 時点）。
- hython で、OpenGL ROP により撮る。1 回の起動で 1 枚しか撮れない（Houdini 22.0.506 の制約）。動きは連番を ffmpeg で GIF（480px・16fps）にする。
- **撮る前の検査**（`hython_shot.py`）:
  - cook が通り、適用の前後で、点・面の数、形の大きさ、位置、色（Cd）・法線（N）のどれかが変わること（色・法線は、平均だけでなく、ばらつきも見る）。
  - **値を 1 つずつ初期値に戻して、形が変わらない値**（効いていない値）があれば撮らない。説明に「効く」と書けないため。`keep` に挙げた値だけは例外。
  - 値を戻すと cook が失敗する値（例: sweep の Surface Shape）は、効いている値として扱う。
- 撮っていないもの: 入力の無い生成系（box・grid・sphere など。「適用前」が作れない）、ボリューム・VDB（OpenGL ROP で見えない）、パックされた結果を返すノード（isooffset）。color・blast・delete・attribwrangle は、動き（GIF）を作らない（動かす値が無い）。

## 4. 関連（出典）の選び方

`reference_data.match_reference_items` が、HoudiniReference の項目（約 400 件）から、そのノードに関係するものを選ぶ。**名前が含まれるだけでは選ばない**（実データで、別の話題が当たったため）。

- 名前は、**単語として**入っているものだけ（「scatter」は「scattering」に当たらない）。
- 題名かタグに入っているもの。抜粋にだけあるものは、名前が長い・複数語のときだけ。
- 「Color」「Delete」のような**普通の英単語**は、「Color SOP」のように、ノードだと分かる言い方が一緒にあるときだけ。
- **内部の名前**（attribwrangle など）は、9 文字以上の作られた語のときだけ、名前だけで足りる。`primitive`・`geometry` のような普通の英単語は、別名として使わない。表示名が複数語でも、別名（`rest`・`solver`）は、普通の語として扱う。
- ノードの文脈の言い方だけを手がかりにする（SOP の Merge に、Merge LOP の動画を出さない）。**Copernicus（COP）の記事は、SOP・OBJ のノードに出さない**（COP にも、同名のノードがある）。
- VEX は、題名・抜粋・タグに、VEX の語も入っているものだけ。

出典のリンクが生きているかは、公開前に確かめる（2026-11-22 時点: 画面に出る 16 件は、すべて生きている）。

## 5. 置き場と通信

| 置き場 | 内容 |
|---|---|
| D1 `reference_entries`（マイグレーション 0038） | `kind`＋`key` で 1 件。説明（`body`）、画像・動きの一覧（`media`）、`version` |
| R2 `rag-poc-reference` | 画像・GIF（1 件 12MB まで）。id に内容のハッシュ |
| Worker `src/reference.ts` | 書き込みは管理者だけ（`/admin/reference/put`・`media_put`・`delete`）。取得は、認証済みの全員（`/reference/index`・`entry`・`media`）。Worker は、認証後は POST だけを受け付けるので、取得も POST |
| 端末のキャッシュ | `index` の `version` を見て、変わった項目だけ取り直す。古いものは整理する |

通信の全体は [通信構成図](communication-architecture.md)。

## 6. 参加者の画面

- **Reference タブ**: 種類（ノード・VEX）と検索で探す。Guide の手順の「ノードの説明」からも、ここへ飛べる。
- 別のパネルが開いているときは、**そちらのパネルで開く**（Guide を見たまま、もう片方が Reference に切り替わる）。メニュー（≡）の「ほかのパネルがあるとき、そちらで開く」で、オフにできる。
- 説明を作る操作（「説明を作る」）は、開発者モード（環境変数 `RAGREEL_REFERENCE_AUTHOR=1`）だけに出る。

## 6.5 種類の追加（2026-11-24）

説明の種類に、**APEX ノード**と**シェルフツール**を足した（キーは `apex/<ページ名>`・`shelf/<ツール名>`）。作り方・点検・公開は、ノード・VEX と同じ流れ。

- 点検（`audit_reference.py` + `dump_parms.py`）は、実機の Houdini で行う。APEX は、`apex.Registry` に在るか・ポート名が本物か。シェルフは、`hou.shelves.tools()` に在るか・「」の名前が本物か。VEX は、`vcc` で関数が在るか（AI を呼ぶ前にも確かめる）。
- 材料に、実機で確かめた手順（`facts`）を足した。パラメータ名・ポート名・操作を、材料に無いものは書かせない。
- 品質の点検（`check_reference_quality.py`）: 欄の抜け・上限超過・日本語なし・コードブロックの混入は **error**（公開しない）。名前が「何をする」に出ない・断定の言い方・資料なしは **warn**（目で確かめる）。名前の warn は、名前を出さずに説明する自然な書き方でも出るので、数が多くても、誤りとは限らない。
- 関連リンクの生存確認は `check_reference_links.py`。
- 最後の一括生成は 294 件のうち、成功 277・失敗 17。失敗は、作った直後の点検（本物の名前・関数の実在・返事の形）に通らなかったもので、保存せず、公開しない。

## 7. 既知の限界

- 説明は AI が書いたものを、パラメータ名の点検と目視で確かめている。**効き方・使いどころの内容は、機械では保証できない**（資料の取り違えは、目視で見つけた）。
- Houdini の版が上がると、パラメータ名が変わる。版が上がったら、`audit_reference.py` を回して、通らないものを作り直す。
- 撮影のレシピは、Houdini 22.0.506 で確かめた。別の版では、検査（§3）で落ちるレシピが出うる。
- 参加者が見ている Reference の新しい GIF の表示は、Houdini 実機での目視は未確認（2026-11-22）。

## 8. 関連の資料

- [システム全体の構成（図 01）](../images/01-system-overview.svg)・[通信構成図（図 17）](../images/17-communication.svg)
- HoudiniReference のリポジトリの README・`HoudiniReference_DESIGN.md`（収集の対象・利用条件・使わない情報源）
- [ライセンスと権利の点検](../operations/license-and-rights-review-2026-11-21.md)（SideFX の資料の扱い）
