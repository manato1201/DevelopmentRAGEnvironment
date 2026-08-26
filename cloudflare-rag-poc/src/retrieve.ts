import type { AuthedUser, Env, SourceEntry } from "./types";
import { embedText, hydeExpand } from "./embeddings";
import { hybridSearch, type RankedChunk } from "./hybrid";
import { consumeBudget } from "./budget";

export interface RetrieveResult {
  ranked: RankedChunk[];
  hydeTokensUsed: number;
}

// namespace（DB）ごとの採用件数上限を取得する。設定が無いnamespaceはMapに含まれない
// （呼び出し側でdefaultCapにフォールバックする＝後方互換）。
async function getNamespaceCaps(
  env: Env,
  namespaces: string[],
): Promise<Map<string, number>> {
  const caps = new Map<string, number>();
  if (namespaces.length === 0) return caps;
  const placeholders = namespaces.map(() => "?").join(",");
  const res = await env.DB.prepare(
    `SELECT namespace_id, result_limit FROM namespaces WHERE namespace_id IN (${placeholders})`,
  )
    .bind(...namespaces)
    .all<{ namespace_id: string; result_limit: number | null }>();
  for (const r of res.results ?? []) {
    if (r.result_limit != null) caps.set(r.namespace_id, r.result_limit);
  }
  return caps;
}

// 複数DBを横断検索した際、無関係なDBのチャンクがスコアの偶然の一致で紛れ込み
// 結果を圧迫することがある（実際のクエリ例で確認）。namespaceごとに明示的な上限が
// 設定されている場合はそれを、無ければdefaultCap（=呼び出し時のlimit）を適用する
// 「クォータ」方式：スコア順を維持したまま、上限に達したnamespace以降の候補だけを間引く。
function capPerNamespace(
  ranked: RankedChunk[],
  caps: Map<string, number>,
  defaultCap: number,
): RankedChunk[] {
  const counts = new Map<string, number>();
  const result: RankedChunk[] = [];
  for (const r of ranked) {
    const ns = r.metadata.namespace;
    const cap = caps.get(ns) ?? defaultCap;
    const count = counts.get(ns) ?? 0;
    if (count >= cap) continue;
    counts.set(ns, count + 1);
    result.push(r);
  }
  return result;
}

// HyDE→ハイブリッド検索→レベルフィルタ→namespace別上限、という/search・/query共通の検索パイプライン
// （既存GAS ragQueryInternal_の検索部分に相当）。
export async function retrieve(
  env: Env,
  user: AuthedUser,
  query: string,
  namespaces: string[],
  level: string,
  limit: number,
): Promise<RetrieveResult> {
  const hyde = await hydeExpand(env, query);
  const queryVector = await embedText(env, hyde.text);
  const ranked = await hybridSearch(
    env,
    queryVector,
    query,
    namespaces,
    user.userId,
    limit * 3,
  );
  const filtered = level
    ? ranked.filter(
        (r) => !r.metadata.difficulty || r.metadata.difficulty === level,
      )
    : ranked;
  const caps = await getNamespaceCaps(env, namespaces);
  const capped = capPerNamespace(filtered, caps, limit);
  return {
    ranked: capped.slice(0, limit),
    hydeTokensUsed: hyde.promptTokens + hyde.candidateTokens,
  };
}

export function buildContextTexts(ranked: RankedChunk[]): {
  texts: string[];
  sources: SourceEntry[];
} {
  // RRFスコアは絶対値に意味が無い（k=60起因の小さい値）ため、この回答内での最高スコアを
  // 100として相対的なパーセンテージに正規化する（UIでの「関連度」表示用）。
  const maxScore = Math.max(...ranked.map((r) => r.score ?? 0), 1e-9);
  const texts: string[] = [`検索結果（${ranked.length} 件）:`];
  const sources: SourceEntry[] = [];
  ranked.forEach((r, i) => {
    texts.push(`\n[${i + 1}] ファイル: ${r.metadata.file}\n${r.metadata.text}`);
    sources.push({
      file: r.metadata.file,
      namespace: r.metadata.namespace,
      difficulty: r.metadata.difficulty,
      score: Math.round((100 * (r.score ?? 0)) / maxScore),
    });
  });
  return { texts, sources };
}

export function resolveEffectiveNamespaces(
  user: AuthedUser,
  requested: string[] | undefined,
): string[] {
  const req =
    requested && requested.length > 0 ? requested : user.allowedNamespaces;
  return req.filter((ns) => user.allowedNamespaces.includes(ns));
}

// POST /me/namespaces — 自分がアクセス可能なnamespace一覧を返す（管理者権限不要）。
// チャットUIの「個別DBに絞って検索」ドロップダウンを、管理者以外のユーザーでも
// 正しく表示できるようにするための2026-08-26追加エンドポイント
// （/admin/namespaces/listは管理者専用のため、一般ユーザーは自分の許可リストを
// 別の手段で知る必要があった）。
export async function handleMyNamespaces(_req: Request, _env: Env, user: AuthedUser): Promise<Response> {
  return new Response(JSON.stringify({ namespaces: user.allowedNamespaces, status: "ok" }), {
    status: 200,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

export { consumeBudget };
