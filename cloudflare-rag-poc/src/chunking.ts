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
