import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { requireAdmin } from "./auth";

// 「答えられなかった質問」の集計（2026-10-16追加）。足りないナレッジが見え、何を取り込むべきかが分かる。
// 対象は、直近の回答のうち次のどれかに当たるもの。
//   ・出典が0件（検索に何も引っかからなかった）
//   ・出典はあるが、回答がどれも引用していない
//   ・利用者が「役に立たなかった」を付けた
// 質問文は同じ内容（前後の空白・大文字小文字・連続する空白を揃えたもの）ごとにまとめ、回数の多い順に返す。
// 管理者だけが見られ、誰の質問かは返さない（質問文と回数だけ）。履歴の保存期間（90日）より前は対象外。
const MAX_ROWS = 1000;
const MAX_GROUPS = 50;

export interface GapGroup {
  query: string;
  count: number;
  noSources: number;
  uncited: number;
  disliked: number;
  lastAt: number;
}

export function normalizeQuery(q: string): string {
  return q.trim().replace(/\s+/g, " ").toLowerCase();
}

interface MemoryGapRow {
  query: string;
  sources_json: string;
  rating: number | null;
  created_at: number;
}

export function groupGaps(rows: MemoryGapRow[]): GapGroup[] {
  const groups = new Map<string, GapGroup>();
  for (const r of rows) {
    let sources: Array<{ cited?: boolean }> = [];
    try {
      const parsed = JSON.parse(r.sources_json || "[]") as unknown;
      if (Array.isArray(parsed)) sources = parsed as Array<{ cited?: boolean }>;
    } catch {
      sources = [];
    }
    const noSources = sources.length === 0;
    const uncited = !noSources && sources.every((s) => !s.cited);
    const disliked = r.rating === -1;
    if (!noSources && !uncited && !disliked) continue;
    const key = normalizeQuery(r.query);
    if (!key) continue;
    const g = groups.get(key) ?? {
      query: r.query.trim(),
      count: 0,
      noSources: 0,
      uncited: 0,
      disliked: 0,
      lastAt: 0,
    };
    g.count += 1;
    if (noSources) g.noSources += 1;
    if (uncited) g.uncited += 1;
    if (disliked) g.disliked += 1;
    if (r.created_at > g.lastAt) {
      g.lastAt = r.created_at;
      g.query = r.query.trim(); // 表示は最新の言い回し
    }
    groups.set(key, g);
  }
  return [...groups.values()]
    .sort((a, b) => b.count - a.count || b.lastAt - a.lastAt)
    .slice(0, MAX_GROUPS);
}

// POST /admin/insights/gaps — body: { days?（既定30、最大90） }
export async function handleKnowledgeGaps(
  req: Request,
  env: Env,
  user: AuthedUser,
): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json().catch(() => ({}))) as { days?: number };
  const days = Math.max(
    1,
    Math.min(
      Number.isFinite(body.days) ? Math.floor(body.days as number) : 30,
      90,
    ),
  );
  const since = Math.floor(Date.now() / 1000) - days * 86400;
  const res = await env.DB.prepare(
    "SELECT query, sources_json, rating, created_at FROM memory WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
  )
    .bind(since, MAX_ROWS)
    .all<MemoryGapRow>();
  const rows = res.results ?? [];
  return jsonResponse(200, {
    status: "ok",
    days,
    scanned: rows.length,
    gaps: groupGaps(rows),
  });
}
