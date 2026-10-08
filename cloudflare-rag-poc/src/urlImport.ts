import type { AuthedUser, Env } from "./types";
import { requireKnowledgeEditor } from "./auth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId } from "./chunking";
import { jsonResponse, clampInt } from "./http";

// HTMLから本文テキストを抽出する（Workers組み込みのHTMLRewriterを使用。DOMパーサ相当の
// ライブラリを追加せずに済む）。本文抽出に加え、ページ内のリンク（絶対URLに正規化済み）と
// titleタグの内容も収集できる（再帰クロール用。単発URL登録はtext以外を読み捨てる）。
async function extractTextLinksAndTitle(
  html: string,
  baseUrl: string,
): Promise<{ text: string; links: string[]; title: string }> {
  const chunks: string[] = [];
  const links = new Set<string>();
  let title = "";
  const rewriter = new HTMLRewriter()
    .on("script", { element: (el) => { el.remove(); } })
    .on("style", { element: (el) => { el.remove(); } })
    .on("title", { text: (t) => { title += t.text; } })
    .on("a[href]", {
      element: (el) => {
        const href = el.getAttribute("href");
        if (!href) return;
        try {
          const abs = new URL(href, baseUrl);
          abs.hash = "";
          links.add(abs.toString());
        } catch {
          // 相対解決できない不正なhref（javascript:等）は無視
        }
      },
    })
    .on("*", { text: (t) => { chunks.push(t.text); } });
  await rewriter.transform(new Response(html)).text();
  const text = chunks.join(" ").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  return { text, links: Array.from(links), title: title.trim() };
}

// POST /admin/kb/import-url — 任意のURLの本文を取得してnamespaceへ登録する
// （既存GAS adminKbImportUrl相当）。body: { namespace, url, title? }
export async function handleImportUrl(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const body = (await req.json()) as { namespace?: string; url?: string; title?: string };
  const namespace = (body.namespace || "").trim();
  const url = (body.url || "").trim();
  if (!namespace || !url) return jsonResponse(400, { error: "namespace と url は必須です" });

  let res: Response;
  try {
    res = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0 (compatible; RAGImportBot/1.0)" } });
  } catch (err) {
    return jsonResponse(400, { error: `URLの取得に失敗しました: ${err instanceof Error ? err.message : String(err)}` });
  }
  if (!res.ok) return jsonResponse(400, { error: `URLの取得に失敗しました (HTTP ${res.status})` });

  const html = await res.text();
  const { text } = await extractTextLinksAndTitle(html, res.url || url);
  if (!text) return jsonResponse(400, { error: "本文を抽出できませんでした（対応していないページ形式の可能性があります）" });

  const title = (body.title || url).trim();
  const result = await ingestDocument(env, namespace, title, text, "manual");

  const opId = newOpId();
  const skipNote = result.skippedVectors.length > 0 ? `（${result.skippedVectors.length}チャンクは登録失敗のためスキップ）` : "";
  await logKb(env, opId, namespace, "manual", title, "ok", `URL登録: ${result.chunks}チャンク登録${skipNote}（${url}）`);

  return jsonResponse(200, {
    status: "ok",
    opId,
    title,
    chunks: result.chunks,
    skipped: result.skippedVectors.length,
  });
}

const CRAWL_DEFAULT_MAX_PAGES = 20;
// 最大ページ数の上限（2026-10-06に50から事実上の無制限へ）。以前は50で頭打ちだったが、大きなドキュメント
// サイトを丸ごと取り込めなかった。バッチ処理（1リクエスト1〜5ページ）なので1リクエストの負荷は
// ページ数に依存しない。実際の歯止めは下のCRAWL_MAX_STATE_CHARS（進行状態がD1の1行に収まる範囲）。
const CRAWL_HARD_MAX_PAGES = 100000;
// 進行状態（キュー＋訪問済みURLのJSON）をcrawl_jobsの1行に保存するため、D1の行サイズ上限（約2MB）に
// 余裕を持たせた文字数で打ち切る。超えたらそこまでを正常終了として返す（取り込み済みの分は有効）。
// 目安: URLが1件100文字前後なら、訪問済み約1万ページ分。
const CRAWL_MAX_STATE_CHARS = 1_500_000;
// キューの長さの上限。ファンアウトの大きいページで未処理URLが際限なく溜まるのを防ぐ
// （溢れたURLは捨てるだけで、別のページのリンクから後で再発見される）。
const CRAWL_MAX_QUEUE = 3000;
const CRAWL_DEFAULT_DEPTH = 1;
const CRAWL_HARD_MAX_DEPTH = 3;
// Drive/Notion同期と同じ理由（Cloudflare Workers Freeプランはこのアカウントでは
// limits.cpu_msを引き上げられず、1リクエストで大量のfetch＋Gemini埋め込みを処理すると
// Error 1102で強制終了する）でバッチ処理にする。1バッチのデフォルトを1ページにしている
// のも driveSync.ts/notionSync.ts と同じ理由（実機の連続タイムアウト経験に基づく）。
const CRAWL_DEFAULT_BATCH_SIZE = 1;
const CRAWL_MAX_BATCH_SIZE = 5;

type CrawlResultStatus = "ok" | "error" | "skipped_existing";

interface CrawlPageResult {
  url: string;
  title: string;
  chunks: number;
  skipped: number;
  status: CrawlResultStatus;
  error?: string;
}

interface CrawlJobState {
  namespace: string;
  originForLinkFilter: string;
  pathPrefix: string;
  excludePatterns: string[];
  skipExisting: boolean;
  maxPages: number;
  maxDepth: number;
  queue: Array<{ url: string; depth: number }>;
  visited: string[];
  processedCount: number;
}

interface CrawlJobRow {
  namespace_id: string;
  origin_for_link_filter: string;
  path_prefix: string | null;
  exclude_patterns: string | null;
  skip_existing: number;
  max_pages: number;
  max_depth: number;
  queue_json: string;
  visited_json: string;
  processed_count: number;
}

async function loadCrawlJob(env: Env, opId: string): Promise<CrawlJobState | null> {
  const row = await env.DB.prepare("SELECT * FROM crawl_jobs WHERE op_id = ?").bind(opId).first<CrawlJobRow>();
  if (!row) return null;
  return {
    namespace: row.namespace_id,
    originForLinkFilter: row.origin_for_link_filter,
    pathPrefix: row.path_prefix || "",
    excludePatterns: row.exclude_patterns ? (JSON.parse(row.exclude_patterns) as string[]) : [],
    skipExisting: row.skip_existing === 1,
    maxPages: row.max_pages,
    maxDepth: row.max_depth,
    queue: JSON.parse(row.queue_json) as Array<{ url: string; depth: number }>,
    visited: JSON.parse(row.visited_json) as string[],
    processedCount: row.processed_count,
  };
}

async function insertCrawlJob(env: Env, opId: string, job: CrawlJobState): Promise<void> {
  const now = Math.floor(Date.now() / 1000);
  await env.DB.prepare(
    `INSERT INTO crawl_jobs
       (op_id, namespace_id, origin_for_link_filter, path_prefix, exclude_patterns, skip_existing,
        max_pages, max_depth, queue_json, visited_json, processed_count, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(
      opId,
      job.namespace,
      job.originForLinkFilter,
      job.pathPrefix || null,
      JSON.stringify(job.excludePatterns),
      job.skipExisting ? 1 : 0,
      job.maxPages,
      job.maxDepth,
      JSON.stringify(job.queue),
      JSON.stringify(job.visited),
      job.processedCount,
      now,
      now,
    )
    .run();
}

async function updateCrawlJobProgress(env: Env, opId: string, job: CrawlJobState): Promise<void> {
  await env.DB.prepare(
    "UPDATE crawl_jobs SET queue_json = ?, visited_json = ?, processed_count = ?, updated_at = ? WHERE op_id = ?",
  )
    .bind(JSON.stringify(job.queue), JSON.stringify(job.visited), job.processedCount, Math.floor(Date.now() / 1000), opId)
    .run();
}

async function deleteCrawlJob(env: Env, opId: string): Promise<void> {
  await env.DB.prepare("DELETE FROM crawl_jobs WHERE op_id = ?").bind(opId).run();
}

// カンマまたは改行区切りの除外パターン文字列を配列にする。パターンはURL全体に対する
// 単純な部分一致（大文字小文字を無視）で判定する——正規表現にすると管理者が入力した
// 任意パターンでReDoSを起こすリスクがあるため、意図的に単純な文字列一致に留めている。
function parseExcludePatterns(raw: string | undefined): string[] {
  return (raw || "")
    .split(/[\n,]+/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

// 既にnamespace内に同名file（タイトル）で登録済みかどうかを確認する（重複URLスキップ用）。
// タイトルはページを実際に取得しないと分からないため「事前にfetchをスキップ」はできない
// が、HTMLRewriterでのfetch＋パース自体は軽く、コストが大きいのはGemini埋め込み呼び出し
// （ingestDocument内）なので、そこだけ避けられれば実用上の効果は十分ある。
async function documentAlreadyExists(env: Env, namespace: string, file: string): Promise<boolean> {
  const row = await env.DB.prepare("SELECT 1 FROM chunks_fts WHERE namespace = ? AND file = ? LIMIT 1")
    .bind(namespace, file)
    .first();
  return row !== null;
}

// POST /admin/kb/crawl-url — 起点URLからリンクをたどって複数ページをまとめてnamespaceへ
// 登録する（例: ドキュメントサイトの目次ページを起点に配下ページを一括登録）。
// SSRF対策としてhttp/https以外のスキームは拒否し、起点と同一オリジンのリンクのみ辿る。
// Cloudflare Workers FreeプランのCPU時間制限のため、Drive/Notion同期と同じバッチ方式
// （1リクエストにつきbatchSize件だけ処理し、続きはopIdを指定して呼び直す）にしている。
// body: 初回 { namespace, url, depth?, maxPages?, pathPrefix?, excludePatterns?,
//              skipExisting?, batchSize? }
//       継続呼び出し { opId, batchSize? }（namespace等は初回作成時の値がジョブに保存済み）
export async function handleCrawlUrl(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const body = (await req.json()) as {
    namespace?: string;
    url?: string;
    depth?: number;
    maxPages?: number;
    pathPrefix?: string;
    excludePatterns?: string;
    skipExisting?: boolean;
    batchSize?: number;
    opId?: string;
  };

  const batchSize = clampInt(body.batchSize, CRAWL_DEFAULT_BATCH_SIZE, 1, CRAWL_MAX_BATCH_SIZE);
  const requestedOpId = (body.opId || "").trim();

  let opId: string;
  let job: CrawlJobState;
  let isNewJob: boolean;

  if (requestedOpId) {
    const loaded = await loadCrawlJob(env, requestedOpId);
    if (!loaded) {
      return jsonResponse(404, { error: `opId(${requestedOpId})のクロールジョブが見つかりません（完了済みまたは期限切れの可能性があります）` });
    }
    opId = requestedOpId;
    job = loaded;
    isNewJob = false;
  } else {
    const namespace = (body.namespace || "").trim();
    const seedUrl = (body.url || "").trim();
    if (!namespace || !seedUrl) return jsonResponse(400, { error: "namespace と url は必須です" });

    let seedOrigin: string;
    try {
      const parsed = new URL(seedUrl);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        return jsonResponse(400, { error: "http/https以外のURLは指定できません" });
      }
      seedOrigin = parsed.origin;
    } catch {
      return jsonResponse(400, { error: "urlの形式が不正です" });
    }

    opId = newOpId();
    job = {
      namespace,
      originForLinkFilter: seedOrigin,
      pathPrefix: (body.pathPrefix || "").trim(),
      excludePatterns: parseExcludePatterns(body.excludePatterns),
      skipExisting: body.skipExisting === true,
      maxPages: clampInt(body.maxPages, CRAWL_DEFAULT_MAX_PAGES, 1, CRAWL_HARD_MAX_PAGES),
      maxDepth: clampInt(body.depth, CRAWL_DEFAULT_DEPTH, 0, CRAWL_HARD_MAX_DEPTH),
      queue: [{ url: seedUrl, depth: 0 }],
      visited: [],
      processedCount: 0,
    };
    isNewJob = true;
  }

  const visited = new Set<string>(job.visited);
  const results: CrawlPageResult[] = [];
  let processedThisBatch = 0;

  while (job.queue.length > 0 && job.processedCount < job.maxPages && processedThisBatch < batchSize) {
    const current = job.queue.shift()!;
    if (visited.has(current.url)) continue;
    visited.add(current.url);
    processedThisBatch++;
    job.processedCount++;

    let html: string;
    let finalUrl = current.url;
    try {
      const res = await fetch(current.url, { headers: { "User-Agent": "Mozilla/5.0 (compatible; RAGImportBot/1.0)" } });
      if (!res.ok) {
        results.push({ url: current.url, title: current.url, chunks: 0, skipped: 0, status: "error", error: `HTTP ${res.status}` });
        continue;
      }
      finalUrl = res.url || current.url;
      html = await res.text();
    } catch (err) {
      results.push({ url: current.url, title: current.url, chunks: 0, skipped: 0, status: "error", error: err instanceof Error ? err.message : String(err) });
      continue;
    }

    // 起点URLがリダイレクトする場合（http→https、bare domain→www等）に備え、リンクの
    // オリジン判定は起点の最終到達先で更新する（そうしないとリダイレクト後のページの
    // リンクが全て「起点と別オリジン」と誤判定され、一切辿れなくなる）。
    if (current.depth === 0) {
      try {
        job.originForLinkFilter = new URL(finalUrl).origin;
      } catch {
        // 解析できない場合は初回に求めたoriginForLinkFilterのまま
      }
    }

    // リンクは元URLではなく、リダイレクト後の実際のページURL（finalUrl）を基準に
    // 相対解決する（そうしないと起点がリダイレクトするサイトで相対リンクが壊れる）。
    const { text, links, title: pageTitle } = await extractTextLinksAndTitle(html, finalUrl);
    const title = pageTitle || current.url;

    if (!text) {
      results.push({ url: current.url, title, chunks: 0, skipped: 0, status: "error", error: "本文を抽出できませんでした" });
    } else if (job.skipExisting && (await documentAlreadyExists(env, job.namespace, title))) {
      results.push({ url: current.url, title, chunks: 0, skipped: 0, status: "skipped_existing" });
    } else {
      const result = await ingestDocument(env, job.namespace, title, text, "manual");
      const skipNote = result.skippedVectors.length > 0 ? `（${result.skippedVectors.length}チャンクは登録失敗のためスキップ）` : "";
      await logKb(env, opId, job.namespace, "manual", title, "ok", `クロール登録: ${result.chunks}チャンク登録${skipNote}（${current.url}）`);
      results.push({ url: current.url, title, chunks: result.chunks, skipped: result.skippedVectors.length, status: "ok" });
    }

    if (current.depth < job.maxDepth) {
      for (const link of links) {
        if (visited.has(link)) continue;
        // ファンアウトの大きいページ（リンクが数百〜数千件）でキューが際限なく
        // 肥大化しないよう、実際に処理され得る件数（maxPages）の数倍で頭打ちにする。
        if (job.queue.length >= Math.min(job.maxPages * 4, CRAWL_MAX_QUEUE)) break;
        let linkUrl: URL;
        try {
          linkUrl = new URL(link);
        } catch {
          continue;
        }
        if (linkUrl.protocol !== "http:" && linkUrl.protocol !== "https:") continue;
        if (linkUrl.origin !== job.originForLinkFilter) continue;
        if (job.pathPrefix && !linkUrl.pathname.startsWith(job.pathPrefix)) continue;
        const linkLower = link.toLowerCase();
        if (job.excludePatterns.some((p) => linkLower.includes(p))) continue;
        job.queue.push({ url: link, depth: current.depth + 1 });
      }
    }
  }

  job.visited = Array.from(visited);
  let done = job.queue.length === 0 || job.processedCount >= job.maxPages;
  let stoppedEarly = "";
  if (!done) {
    const stateSize = JSON.stringify(job.queue).length + JSON.stringify(job.visited).length;
    if (stateSize > CRAWL_MAX_STATE_CHARS) {
      done = true;
      stoppedEarly = `${job.processedCount}ページ処理した時点で、クロールの進行状態が保存できる大きさを超えたため終了しました（取り込み済みの分は登録されています）。続きは、パス絞り込みを変えて別のクロールとして実行してください。`;
    }
  }

  if (done) {
    if (!isNewJob) await deleteCrawlJob(env, opId);
  } else if (isNewJob) {
    await insertCrawlJob(env, opId, job);
  } else {
    await updateCrawlJobProgress(env, opId, job);
  }

  return jsonResponse(200, {
    status: "ok",
    opId,
    results,
    processedCount: job.processedCount,
    maxPages: job.maxPages,
    done,
    stoppedEarly: stoppedEarly || undefined,
  });
}
