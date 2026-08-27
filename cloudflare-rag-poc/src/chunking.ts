// 長文を検索しやすい大きさに分割する（既存GAS chunkText_相当）。
// スライディングウィンドウ方式：sizeごとに切り出し、overlap分だけ前のチャンクと重複させて
// チャンク境界で文脈が切れることによる検索精度低下を緩和する。
export function chunkText(text: string, size = 1000, overlap = 150): string[] {
  const trimmed = text.trim();
  if (trimmed.length === 0) return [];
  if (trimmed.length <= size) return [trimmed];

  const chunks: string[] = [];
  let start = 0;
  while (start < trimmed.length) {
    const end = Math.min(start + size, trimmed.length);
    chunks.push(trimmed.slice(start, end));
    if (end >= trimmed.length) break;
    start = end - overlap;
  }
  return chunks;
}

// 知識ベース同期の1回の実行を識別するID（既存GAS kbNewOpId_相当）。
export function newOpId(): string {
  return `op_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// 1ファイルの処理（Gemini File APIのアップロード＋ACTIVE待ちポーリング等）が想定外に
// 長引くと、Cloudflareのエッジ側がリクエスト自体を打ち切りHTMLエラーページ（非JSON、
// HTTP 503）を返してしまい、クライアント側でバッチ全体が失敗扱いになる不具合が実機で
// 発生した（2026-08-27）。Promise.raceで期限を区切ることで、遅い1件を「タイムアウト」
// としてスキップし、バッチの残りとレスポンス自体は正常に返せるようにする。
// 注意：内部のfetch自体を中断するわけではない（真のキャンセルにはAbortControllerを
// 個々の実装まで通す必要がある）ため、あくまで「レスポンスを待たない」ための対策。
export async function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label}がタイムアウトしました（${Math.round(ms / 1000)}秒経過）`)), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer!);
  }
}

// withTimeout()の弱点（2026-08-27に実機で判明）: Promise.raceは「待つのをやめる」だけで、
// 負けた方のPromiseの中身（実際のfetch）は裏で動き続ける。1ファイルをタイムアウトさせて
// 次に進んでも、その裏で継続中のDriveダウンロード等がWorker全体の実行時間を消費し続け、
// 結果としてバッチ全体がCloudflareエッジに打ち切られ503になる、という形で問題が
// 再発した。fetch自体を本当にAbortController.abort()で中断できる処理にのみ、
// こちらの「真にキャンセルする」版を使う（driveSyncのダウンロード等）。
// fn自身がsignalを律儀にチェックしなくても（内部のfetch呼び出しにsignalを渡していれば
// そのfetch単体は中断されるが、それ以降の非fetch処理まで止まるとは限らない）、
// Promise.raceで確実に期限が来たら次に進めるようにする。abort()はあくまで
// 「止められるものは止める」ためのベストエフォート、raceが「待つのをやめる」保証。
export async function withAbortTimeout<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  ms: number,
  label: string,
): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error(`${label}がタイムアウトしました（${Math.round(ms / 1000)}秒経過。可能な範囲で処理を中断しました）`));
    }, ms);
  });
  try {
    return await Promise.race([fn(controller.signal), timeout]);
  } finally {
    clearTimeout(timer!);
  }
}
