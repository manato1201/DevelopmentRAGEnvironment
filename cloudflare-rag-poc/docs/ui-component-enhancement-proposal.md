# chatUi.ts UIコンポーネント強化提案書

**目的: X上の@ozwxy氏の実演(GPT-6 Astraによる金属反射・ガラス質感等30種のUIコンポーネント生成デモ)から抽出した18種のうち、既存`chatUi.ts`(2,001行、5タブ構成のRAGチャットUI)に実際に適合する箇所を具体的に特定する**
作成日: 2026-09-09 / 対象: `src/chatUi.ts`(単一ファイル完結のHTML/CSS/JSテンプレートリテラル)

---

## 前提・スコープ

`chatUi.ts`は既に「Dala」スタイルガイド由来のダークトークン体系(`--accent: #8052ff`紫、`--highlight: #ffb829`アンバー、`--teal`、`--bad`赤)と、チャット/グラフ/履歴/お気に入り/管理の5タブ構成を持つ、成熟した実装である。ファイル冒頭のコメントに「フォームや管理画面のテーブルは枠線ゼロを厳密適用すると実用上見分けが付かなくなるため意図的に逸脱した」等、既に多くの実用上の判断が積み重なっている。

**本書は直接のコード変更ではなく提案書とする。** 理由: このファイルはテンプレートリテラル1本にHTML/CSS/クライアントJSが同居する構造で、過去に「バックスラッシュのエスケープ数を間違えるとスクリプト全体が起動不能になる」という実障害(2026-09-03のコメント参照)が記録されている。自動化されたエージェントによる一括書き換えはリスクが高く、レビュー可能な提案として先に整理し、実際の適用はユーザー自身または慎重なレビューを経て行うことを推奨する。

18種のうち、既存コードに具体的な接続点が見つかったもの5件のみを提案する。無理に全て当てはめない。

---

## 提案1: スタックトースト(Stack Toast) — `alert()`呼び出しの置き換え

**現状の課題**: `rate()`関数(chatUi.ts:1002-1010)がエラー時に生の`alert("評価の送信に失敗しました: " + e.message)`を呼んでいる。ブラウザネイティブの`alert()`はUIをブロックし、既存のダークテーマとも視覚的に統一感がない。一方`exportBtn`の「コピーしました」(chatUi.ts:876)は2秒後に元のラベルへ戻すという、簡易的な自前トースト実装が既に部分的に存在する。

**提案**: 両者を統一する軽量トーストコンポーネントを新設する。

```javascript
// 追加案: showToast() を1箇所に集約し、alert()呼び出しを全て置き換える
function showToast(message, kind /* "error" | "success" */) {
  const stack = document.getElementById("toastStack") || createToastStack();
  const toast = document.createElement("div");
  toast.className = "toast " + (kind || "");
  toast.textContent = message;
  stack.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("show"));
  setTimeout(() => {
    toast.classList.remove("show");
    toast.addEventListener("transitionend", () => toast.remove(), {
      once: true,
    });
  }, 3200);
}
```

```css
#toastStack {
  position: fixed;
  bottom: 1.2rem;
  right: 1.2rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  z-index: 999;
}
.toast {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.6rem 1rem;
  font-size: 0.82rem;
  color: var(--text);
  opacity: 0;
  transform: translateY(8px);
  transition:
    opacity 0.2s ease,
    transform 0.2s ease;
}
.toast.show {
  opacity: 1;
  transform: translateY(0);
}
.toast.error {
  border-color: var(--bad);
  color: var(--bad);
}
.toast.success {
  border-color: var(--teal);
  color: var(--teal);
}
```

**適用箇所**: `rate()`(1008行目)、`togglePin()`(1012行目以降、要確認)、KB同期エラー時の`kbSyncProgress`表示など、既存の`.hint`/`.error`テキスト表示を使っている箇所の一部を段階的に置き換える候補とする。

---

## 提案2: ラジアルプログレス(Radial Progress) — トークン予算表示の強化

**現状**: `loadMyBudget()`(chatUi.ts:606-627)が`myBudget`要素にプレーンテキスト(例: "RAG 残り23%")を表示し、残量10%以下で`budget-low`クラスにより赤文字化する。既に`pct`(パーセンテージ)が計算済みであり、可視化のためのデータは揃っている。

**提案**: ヘッダーの`#myBudget`をテキストのみからSVG円環ゲージ+テキストの組み合わせに強化する。

```javascript
function budgetRadialSvg(pct, isLow) {
  const r = 8,
    c = 2 * Math.PI * r;
  const offset = c * (1 - pct / 100);
  const color = isLow ? "var(--bad)" : "var(--accent)";
  return (
    '<svg width="20" height="20" viewBox="0 0 20 20" class="radial-progress">' +
    '<circle cx="10" cy="10" r="' +
    r +
    '" fill="none" stroke="var(--border)" stroke-width="2"/>' +
    '<circle cx="10" cy="10" r="' +
    r +
    '" fill="none" stroke="' +
    color +
    '" stroke-width="2" ' +
    'stroke-dasharray="' +
    c +
    '" stroke-dashoffset="' +
    offset +
    '" stroke-linecap="round" ' +
    'transform="rotate(-90 10 10)"/></svg>'
  );
}
```

`loadMyBudget()`内で`span.textContent`の代わりに、このSVGとラベルを横並びで`span.innerHTML`(自己生成の数値のみのため既存のtextContent方針への影響は限定的、ただし既存コードはXSS対策でtextContent/appendChildを徹底しているため、innerHTML化する場合は静的な数値以外を埋め込まないよう注意する)。

---

## 提案3: フォーカスリング(Focus Ring) — 引用ジャンプの既存演出の形式化

**現状**: `jumpToSource()`(chatUi.ts:807-814)が既に`li.classList.add("citation-highlight")`→1.5秒後に除去、という一時ハイライト演出を持つ。CSSは`.citation-highlight { background: var(--accent); color: #fff; border-radius: 4px; transition: background 1.5s ease; }`(130行目)で背景色フラッシュのみ。

**提案**: 背景フラッシュに加えて、リング状のoutlineアニメーションを追加し「フォーカスリング」として明確化する。

```css
.citation-highlight {
  background: var(--accent);
  color: #fff;
  border-radius: 4px;
  transition:
    background 1.5s ease,
    box-shadow 1.5s ease;
  box-shadow: 0 0 0 3px var(--accent);
}
```

実装コストが極めて低い(既存クラスへのプロパティ追加のみ)ため、5提案中最も着手しやすい。

---

## 提案4: クロームダイヤル(Chrome Dial) — グラフ制御スライダーの置き換え(検討・優先度低)

**現状**: `#graphRepel`/`#graphCenter`(chatUi.ts:277-282)は素の`<input type="range">`で、3Dナレッジグラフ(Three.js)の反発力・結集力を制御する。

**提案**: 見た目を金属質感の回転ダイヤルに変更する場合、`conic-gradient`ベースの疑似ダイヤルを新設できるが、native rangeスライダーはドラッグ操作の実装コストがゼロで、キーボード操作(矢印キー)にも標準対応している。ダイヤル化は視覚的な統一感(3Dグラフ画面の「装置感」)には寄与するが、アクセシビリティ面でのトレードオフがある。

**優先度**: 低。見送っても実用上の問題はない。導入する場合はnative `<input type="range">`をvisually-hiddenで残しつつ上にクロームダイヤルのビジュアルを重ねる(キーボード操作性を犠牲にしない)実装を推奨する。

---

## 提案5: エッジライト(Edge Light) — ヘルスチェック結果の視覚化

**現状**: 管理タブの「ヘルスチェック・アラート通知」セクション(chatUi.ts:324-330)は`healthCheckBtn`実行後、結果を`healthCheckResult`にテキストで表示するのみ。

**提案**: ヘルスチェック結果に応じて、そのセクションのカード(`.section`)の左端に健全(緑)/劣化(黄)/異常(赤)の縦バーを表示する軽量な実装。

```css
.section.health-ok {
  border-left: 3px solid var(--teal);
  padding-left: 1rem;
}
.section.health-warn {
  border-left: 3px solid var(--highlight);
  padding-left: 1rem;
}
.section.health-bad {
  border-left: 3px solid var(--bad);
  padding-left: 1rem;
}
```

`healthCheckBtn`のクリックハンドラ内で、レスポンス結果に応じて該当`.section`要素にこれらのクラスをtoggleするだけで実装できる。

---

## 適用しないもの(既存UIとの適合が薄い、または過剰)

メタルトグル・ピールチケット・リキッドタブ・モーフメニュー・オービタルメニュー・スタックブラウザ・セグメントレール・コンテキストツールバー・ドットチャート・スペクトラムミキサー・スプリットフラップ・サーマルゲージ・スクラッチパスは、既存の5タブ管理画面という実用重視のダッシュボードUIには接続点が薄いか、導入コストに見合う効果が見込みにくいため見送る。特にセグメントレールは既存の`nav.tabs`が既に十分機能しており、置き換える理由がない。

---

## 実装時の注意(既存コードの制約を踏襲すること)

- このファイルはテンプレートリテラル1本のため、追加するJS内の改行エスケープは既存コメント(778-784行目)の警告通り、バックスラッシュを2個重ねる必要がある箇所がある
- 既存コードはXSS対策として`textContent`/`appendChild`を徹底し`innerHTML`をほぼ使っていない。新規コンポーネントもこの方針を踏襲し、サーバー由来の未検証文字列を`innerHTML`に渡さないこと
- 配色は必ず既存CSS変数(`--accent`/`--highlight`/`--teal`/`--bad`/`--border`/`--panel`)を再利用し、新規の色を追加しないこと(ライトモード`@media (prefers-color-scheme: light)`との整合を保つため)
