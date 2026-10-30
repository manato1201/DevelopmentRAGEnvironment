# 第7回 Web 画面（`chatUi.ts`）の仕組み

**到達目標:** 画面が**「1つの大きな文字列」**として作られている理由と、その**書き方の決まり**（記号のエスケープ）を説明できる。小さな部品（ボタン・保存される設定）を足し、**テストで守れる**。
**前提:** 第1・5回、HTML・CSS・JavaScript の基本（タグ・クラス・`addEventListener`）。 **目安:** 2時間

---

## 1. 全体像

ブラウザで `https://rag-poc.….workers.dev/` を開くと出る画面（チャット・グラフ・履歴・管理）は、**`cloudflare-rag-poc/src/chatUi.ts` の `chatUiHtml()` が返す、1つの HTML の文字列**です（約 7,200 行）。

```
GET /  ──▶ index.ts ──▶ chatUiHtml()（HTML 全体を、文字列で返す）──▶ ブラウザが、描画・実行
                                  └ <style> … </style>（CSS）
                                  └ <body> …（HTML）
                                  └ <script> …（素の JavaScript。この文字列の中に、直接書く）
```

React や Vue のような**ビルド工程は、ありません**。1ファイルを直して、デプロイすれば、反映されます。小さなチームで、**仕組みを少なく保つ**ための選択です。

## 2. 基礎

### 2.1 テンプレート文字列と、3つの禁止

`chatUiHtml()` は、`` ` `` （バッククォート）で囲んだ**テンプレート文字列**を返します。この中では、次の3つが**特別な意味**を持つので、画面の JavaScript の中に、**そのまま書けません**。

| 書きたいもの | 問題 | 書き方 |
|---|---|---|
| `` ` ``（バッククォート） | 文字列が、そこで終わってしまう | 使わない。`"…"` か `'…'` で書く（JavaScript の文字列の連結 `+` を使う） |
| `${`  | テンプレートの「値の差し込み」と解釈される | 使わない。`"a" + b` と書く |
| `\`（バックスラッシュ） | `\n` が、**本物の改行**に変わってしまう | **2つ重ねて** `\\n` と書く（画面に届くときに `\n` になる） |

> 画面が**真っ白**になったり、ボタンが**効かなかったり**したら、まず、ブラウザの Console（F12）で、`SyntaxError` を探す。原因の多くは、この3つです。

### 2.2 TypeScript が、守ってくれない場所

画面の `<script>` の中身は、TypeScript から見れば**ただの文字列**です。**書き間違いがあっても、`tsc` は何も言いません**。ブラウザで開いて、初めて壊れていると分かります。そこで、**テストで守ります**。

```js
// test/ui_syntax.test.mjs
const { chatUiHtml } = await import("../src/chatUi");
const html = chatUiHtml();
const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]).filter((c) => c.trim());
for (const code of scripts) new vm.Script(code);   // 構文を読むだけ（実行しない）。間違いがあれば SyntaxError
```

さらに、**`assert.match(code, /正規表現/)`** で、「この機能が入っている」「あの危険な書き方が無い」を、文字列として確かめます（`test/ascii_art.test.mjs`）。

### 2.3 純関数を、文字列として埋め込む（`asciiArt.ts`・`listSort.ts`）

画面の `<script>` の中の関数は、そのままでは**テストしにくい**。そこで、**純関数だけを、別のファイルに文字列で持ち**、画面に**差し込み**ます。

```ts
// src/asciiArt.ts
export const ASCII_ART_JS = `
  const ART_RAMPS = { classic: " .:-=+*#%@", critter: " .ot%8SX@" };
  function brightnessToChar(b, ramp) { … }
  function critterFrame(w, h, t, progress, ramp) { … }   // 時刻 t と進み具合だけで絵が決まる純関数
`;
```

```ts
// src/chatUi.ts（<script> の中）
${ASCII_ART_JS}
```

テストは、**同じ文字列を評価して、同じ関数を取り出し**、入力と出力を確かめます（`test/ascii_art.test.mjs`）。**画面と、テストが、同じコードを見る**ので、ずれません。ただし、この文字列の中にも、**2.1 の3つの禁止**が、そのまま当てはまります（テストで `!ASCII_ART_JS.includes("\\")` などを確かめている）。

### 2.4 安全な画面の作り方

- **ユーザーが入力した文字や、サーバーから来た文字を、`innerHTML` に入れない。** 入れた文字の中に `<script>` があると、実行されてしまう（XSS）。**`textContent` か、`createElement` で作る**。

```js
// 背景の生き物（paintCritter）: 文字は textContent と文字ノードだけで組み立てる
pre.textContent = "";
pre.appendChild(document.createTextNode(plainPart));
const glow = document.createElement("span"); glow.textContent = darkPart; pre.appendChild(glow);
```

- **`localStorage` は、失敗しうる**（プライベートウィンドウ・無効化）。**必ず `try/catch` で包み**、**無くても動く**ようにする。

```js
let saved = "off";
try { saved = localStorage.getItem("ragPocWallpaper") === "critter" ? "critter" : "off"; } catch { /* 不可環境はなし */ }
```

### 2.5 見た目の決まり

- **色は、変数（`--accent` など）**で持つ。ライトとダークは、変数の値を切り替える（`:root[data-theme="light"]`、`@media (prefers-color-scheme: light)`）。**色を直接書かない**。
- **動きは、少なく**（原則 P8）。空状態と待ち時間だけ。**`prefers-reduced-motion`** のときは、止める。
- **画面の外・見えないタブでは、描かない**（`IntersectionObserver`・`document.hidden`）。**取り除かれたら、タイマーも止める**（`pre.isConnected`）。
- **操作の邪魔をしない**（装飾に `pointer-events: none`）。

## 3. 実例：背景の生き物（Z20）を足した手順

ヘッダーの「背景: なし／クラゲ」は、次の4つで足しました（`git log` で、コミット `e9a3f42` を見る）。

1. **HTML**: `themeToggle` の隣に、`<button id="wallpaperToggle">背景: なし</button>`。
2. **CSS**: `.ascii-wallpaper { position: fixed; right: 1rem; bottom: 1rem; z-index: -1; opacity: .14; pointer-events: none; }`。ライトは濃く（.2）。720px 未満は `display: none`。
3. **JavaScript**: `initWallpaper()`。既存の `asciiCritter()` を**そのまま使い**（動きを減らす設定・画面の外での停止は、すでに入っている）、`document.body` に足す／外す。選択は `localStorage`（`try/catch`）。**既定は「なし」**。
4. **テスト**: `test/ascii_art.test.mjs` に、「既定はなし」「同じ生き物を使う」「`z-index: -1` と `pointer-events: none`」「狭い画面で隠す」「外すとタイマーが止まる」を、`assert.match` で足す。

> 設計の判断: 原則 P8（動きは空状態と待ち時間だけ）に反するので、**選んだ人だけ**に出す。**新しい動きを足すときは、既定をオフにする**。

## 4. 演習

**演習 7.1（読む）** `chatUi.ts` を開き、`initTheme`（テーマの切り替え）を探して、(a) 選択がどこに保存されるか、(b) 保存できない環境で、どうなるか、を答えてください。

**演習 7.2（壊す）** `chatUi.ts` の `<script>` の中の、どこか1か所に `${` を書き（例: コメントの中に `${x}`）、`npx tsx --test test/ui_syntax.test.mjs` を動かして、何が起きるか見てください。**終わったら、元に戻す**（`git diff` で、何も変わっていないことを確認）。

**演習 7.3（書く）** ヘッダーに、`<button id="compactToggle">表示: ふつう</button>` を足し、押すと、`document.body` に `compact` クラスを付け外しして（`localStorage` に保存。`try/catch`）、`.compact .msg { font-size: .85rem; }` で、文字を小さくしてください。**テスト**（`assert.match`）も、1つ足してください。終わったら、元に戻す。

**演習 7.4（考える）** サーバーから来た `title`（スレッドの題名）を、`element.innerHTML = title` で表示すると、何が起きうるか。どう直すか。

## 5. つまずきやすい点

- **`\n` が、本物の改行になって、文字列が壊れる。** `\\n` と書く。
- **`${` を、うっかり書く。** 画面全体が、`undefined` 混じりになる、または、構文エラー。
- **ボタンを足したのに、効かない。** `id` の綴りの違い・`getElementById` が `null`・`addEventListener` を呼ぶ前に、要素が無い。Console を見る。
- **ライトだけ、文字が読めない。** 色を直接書いている。変数にする。

## 6. 確認問題

1. 画面が、1つの文字列である理由は？ 利点と欠点を、1つずつ。
2. テンプレート文字列の中で、書いてはいけないものを3つ。
3. `tsc` が、画面の `<script>` の間違いに気づけない理由は？ 何で守るか？
4. `innerHTML` を避ける理由は？
5. 新しい動きを足すとき、既定をオフにする理由は？

## 解答の方針

- 7.1: `localStorage`（キー `ragPocTheme`）。保存できないときは `try/catch` で握りつぶし、「自動」になる。
- 7.2: `ui_syntax.test.mjs` が `SyntaxError` で落ちる（または、`${x}` が評価されて、文字列が変わる）。
- 7.4: 題名に `<img onerror=…>` が含まれると、実行される（XSS）。`textContent = title` にする。
- 確認問題 1: 利点: ビルドが要らず、1ファイルで完結する。欠点: 型の検査が効かず、書き方の禁止事項がある。
