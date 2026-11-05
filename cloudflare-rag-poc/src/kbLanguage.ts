// ナレッジ一覧の「言語」の推定（設計書 追補 T13: 絞り込み属性）。
// 画面の出典パネルの sourceLang()（chatUi.ts）と同じ考え方: ひらがな・カタカナ・漢字があれば日本語、
// 文字があってそれが無ければ「英語など」、文字が無ければ「不明」。推定であって、言語の判定ではない。

export type DocumentLanguage = "日本語" | "英語など" | "不明";

export function guessLanguage(text: string): DocumentLanguage {
  if (!text || !text.trim()) return "不明";
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if ((c >= 0x3040 && c <= 0x30ff) || (c >= 0x4e00 && c <= 0x9fff)) return "日本語";
  }
  return "英語など";
}
