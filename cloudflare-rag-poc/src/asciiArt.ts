// 空状態の「文字で描いた生き物」の部品（2026-10-27。設計書 追補第3弾 D1・D4・D5）。
//
// 画面（chatUi.ts）は、1つのテンプレート文字列で出す素のJavaScriptなので、import できない。
// そこで、純粋な関数だけを、ここに文字列として持ち、画面に埋め込む（listSort.ts と同じ方式）。
// テスト（test/ascii_art.test.mjs）は、同じ文字列を評価して、同じ関数を検証する。
//
//   D1 輝度 → 文字の階調 … 明るさ（0〜1）に応じて、薄い文字から濃い文字を選ぶ。
//   D4 文字の差し替え   … 階調表（RAMPS）は、パラメータ。同じ仕組みで、別の雰囲気にできる。
//   D5 マスごとの遅延   … マスごとに決まった遅れをつけて、粒状に現れる。
//   どれも「時刻 t と進み具合 progress だけで絵が決まる」純関数。乱数は使わない（同じ入力なら、同じ絵）。
//   動きは、空状態と待ち時間だけ（原則 P8）。prefers-reduced-motion では、静止した完成形だけを出す。
//
// 守ること: この文字列の中に、バックスラッシュ・バッククォート・「${」を書かない（テンプレート文字列として解釈されるため）。
export const ASCII_ART_JS = `
  // ---------- 文字で描いた生き物（純粋な関数） ----------
  // 薄い文字 → 濃い文字。明るいマスほど、右（濃い）側の文字になる。
  const ART_RAMPS = {
    classic: " .:-=+*#%@",
    critter: " .ot%8SX@",
  };
  function brightnessToChar(b, ramp) {
    const chars = ramp || ART_RAMPS.classic;
    const clamped = Math.min(1, Math.max(0, Number(b) || 0));
    return chars.charAt(Math.round(clamped * (chars.length - 1)));
  }
  // 生き物の明るさ（0〜1）。ドーム（傘）と、ゆれる触手。t は秒。
  function critterBrightness(x, y, w, h, t) {
    const u = ((x + 0.5) / w) * 2 - 1; // -1〜1
    const v = (y + 0.5) / h; // 0〜1（上が0）
    const pulse = 1 + 0.05 * Math.sin(t * 1.6);
    let b = 0;
    const dome = (u / (0.86 * pulse)) * (u / (0.86 * pulse)) + ((v - 0.34) / 0.3) * ((v - 0.34) / 0.3);
    if (dome < 1) {
      b = 0.38 + 0.62 * (1 - dome); // 中心ほど明るい
      if (dome > 0.72) b = Math.min(1, b + 0.25); // ふちを、少し強く
      const eye = Math.abs(Math.abs(u) - 0.3) < 0.09 && Math.abs(v - 0.3) < 0.07; // 2つの目（暗い点）
      if (eye) b = 0.12;
    }
    if (v >= 0.52) {
      for (let k = 0; k < 5; k++) {
        const cx = -0.64 + 0.32 * k + 0.1 * Math.sin(t * 1.3 + v * 6 + k * 1.7);
        const d = (u - cx) / 0.07;
        const tentacle = Math.exp(-d * d) * (1 - (v - 0.52) * 0.95);
        if (tentacle > b) b = tentacle;
      }
    }
    return Math.min(1, Math.max(0, b));
  }
  // マスごとの遅れ（0以上1未満）。座標だけから決まる（乱数ではない）。
  function cellDelay(x, y) {
    const n = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453;
    return n - Math.floor(n);
  }
  // 1コマ分の文字（行は改行で区切る）。progress（0〜1）が小さいうちは、遅れの小さいマスだけが現れる（D5）。
  function critterFrame(w, h, t, progress, ramp) {
    const p = Math.min(1, Math.max(0, progress));
    const rows = [];
    for (let y = 0; y < h; y++) {
      let row = "";
      for (let x = 0; x < w; x++) {
        row += cellDelay(x, y) <= p ? brightnessToChar(critterBrightness(x, y, w, h, t), ramp) : " ";
      }
      rows.push(row.replace(/ +$/, ""));
    }
    return rows.join(String.fromCharCode(10));
  }
`;
