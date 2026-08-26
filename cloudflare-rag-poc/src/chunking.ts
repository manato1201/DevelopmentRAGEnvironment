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
