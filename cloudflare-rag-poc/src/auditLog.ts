import type { Env } from "./types";

// audit_logへの書き込みを2段階にする（2026-09-04追加）。
// 従来は「検索・生成が全部終わった後」に1回だけINSERTしていたため、rateLimit.tsの
// assertNotRateLimited（audit_logの直近件数を数えるだけの実装）が同時多発リクエストを
// 検知できなかった（どのリクエストもまだ自分のaudit_log行を書いていない状態で
// お互いのCOUNT(*)チェックを通過してしまうTOCTOU）。
// namespace/query_hashなど分かっている情報はリクエスト開始時点で全て揃っているため、
// 高価な処理（HyDE・埋め込み・検索・生成）を始める前にプレースホルダ行を先に書き込み、
// それ自体を「このリクエストは今アクティブである」という予約として機能させる。
// 処理完了後にresult_count/latency_ms/tokens_usedだけ埋め戻す。
export async function startAuditLog(
  env: Env,
  userId: string,
  namespaceId: string | null,
  queryHash: string,
  difficulty: string | null,
): Promise<number> {
  const res = await env.DB.prepare(
    "INSERT INTO audit_log (user_id, namespace_id, query_hash, difficulty, result_count, latency_ms, tokens_used, created_at) VALUES (?, ?, ?, ?, 0, NULL, 0, ?)",
  )
    .bind(
      userId,
      namespaceId,
      queryHash,
      difficulty,
      Math.floor(Date.now() / 1000),
    )
    .run();
  return res.meta.last_row_id as number;
}

export async function finalizeAuditLog(
  env: Env,
  id: number,
  fields: {
    resultCount: number;
    latencyMs: number | null;
    tokensUsed: number;
    // Claude API使用量・コスト可視化（2026-09-10追加）用。claude.tsのhandleClaudeMessages
    // だけが渡す。他の呼び出し元（query.ts/search.ts）は省略してよく、その場合は
    // migrations/0010の新カラムにNULLが入ったままになる。
    inputTokens?: number;
    outputTokens?: number;
    model?: string;
  },
): Promise<void> {
  await env.DB.prepare(
    "UPDATE audit_log SET result_count = ?, latency_ms = ?, tokens_used = ?, input_tokens = ?, output_tokens = ?, model = ? WHERE id = ?",
  )
    .bind(
      fields.resultCount,
      fields.latencyMs,
      fields.tokensUsed,
      fields.inputTokens ?? null,
      fields.outputTokens ?? null,
      fields.model ?? null,
      id,
    )
    .run();
}
