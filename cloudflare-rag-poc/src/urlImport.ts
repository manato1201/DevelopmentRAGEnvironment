import type { AuthedUser, Env } from "./types";
import { requireKnowledgeEditor } from "./auth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId } from "./chunking";
import { jsonResponse } from "./http";

// HTMLからscript/style要素を除去した上でテキストのみを抽出する（Workers組み込みの
// HTMLRewriterを使用。DOMパーサ相当のライブラリを追加せずに済む）。
async function extractTextFromHtml(html: string): Promise<string> {
  const chunks: string[] = [];
  const rewriter = new HTMLRewriter()
    .on("script", { element: (el) => { el.remove(); } })
    .on("style", { element: (el) => { el.remove(); } })
    .on("*", { text: (t) => { chunks.push(t.text); } });
  await rewriter.transform(new Response(html)).text();
  return chunks.join(" ").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
}

// 本文抽出に加え、ページ内のリンク（絶対URLに正規化済み）とtitleタグの内容も収集する
// （再帰クロール用。extractTextFromHtmlとほぼ同じ処理だが、単発URL登録の挙動を変えない
// よう別関数として分離）。
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
  const text = await extractTextFromHtml(html);
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
const CRAWL_HARD_MAX_PAGES = 50;
const CRAWL_DEFAULT_DEPTH = 1;
const CRAWL_HARD_MAX_DEPTH = 3;

interface CrawlPageResult {
  url: string;
  title: string;
  chunks: number;
  skipped: number;
  error?: string;
}

// POST /admin/kb/crawl-url — 起点URLからリンクをたどって複数ページをまとめてnamespaceへ
// 登録する（例: ドキュメントサイトの目次ページを起点に配下ページを一括登録）。
// SSRF対策としてhttp/https以外のスキームは拒否し、起点と同一オリジンのリンクのみ辿る。
// body: { namespace, url, depth?, maxPages?, pathPrefix? }
export async function handleCrawlUrl(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  const body = (await req.json()) as {
    namespace?: string;
    url?: string;
    depth?: number;
    maxPages?: number;
    pathPrefix?: string;
  };
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

  const maxPages = Math.min(Math.max(1, Math.trunc(body.maxPages ?? CRAWL_DEFAULT_MAX_PAGES)), CRAWL_HARD_MAX_PAGES);
  const maxDepth = Math.min(Math.max(0, Math.trunc(body.depth ?? CRAWL_DEFAULT_DEPTH)), CRAWL_HARD_MAX_DEPTH);
  const pathPrefix = (body.pathPrefix || "").trim();

  const opId = newOpId();
  const visited = new Set<string>();
  const queue: Array<{ url: string; depth: number }> = [{ url: seedUrl, depth: 0 }];
  const results: CrawlPageResult[] = [];

  while (queue.length > 0 && results.length < maxPages) {
    const current = queue.shift()!;
    if (visited.has(current.url)) continue;
    visited.add(current.url);

    let html: string;
    try {
      const res = await fetch(current.url, { headers: { "User-Agent": "Mozilla/5.0 (compatible; RAGImportBot/1.0)" } });
      if (!res.ok) {
        results.push({ url: current.url, title: current.url, chunks: 0, skipped: 0, error: `HTTP ${res.status}` });
        continue;
      }
      html = await res.text();
    } catch (err) {
      results.push({ url: current.url, title: current.url, chunks: 0, skipped: 0, error: err instanceof Error ? err.message : String(err) });
      continue;
    }

    const { text, links, title: pageTitle } = await extractTextLinksAndTitle(html, current.url);
    const title = pageTitle || current.url;
    if (!text) {
      results.push({ url: current.url, title, chunks: 0, skipped: 0, error: "本文を抽出できませんでした" });
    } else {
      const result = await ingestDocument(env, namespace, title, text, "manual");
      const skipNote = result.skippedVectors.length > 0 ? `（${result.skippedVectors.length}チャンクは登録失敗のためスキップ）` : "";
      await logKb(env, opId, namespace, "manual", title, "ok", `クロール登録: ${result.chunks}チャンク登録${skipNote}（${current.url}）`);
      results.push({ url: current.url, title, chunks: result.chunks, skipped: result.skippedVectors.length });
    }

    if (current.depth < maxDepth) {
      for (const link of links) {
        if (visited.has(link)) continue;
        let linkUrl: URL;
        try {
          linkUrl = new URL(link);
        } catch {
          continue;
        }
        if (linkUrl.protocol !== "http:" && linkUrl.protocol !== "https:") continue;
        if (linkUrl.origin !== seedOrigin) continue;
        if (pathPrefix && !linkUrl.pathname.startsWith(pathPrefix)) continue;
        queue.push({ url: link, depth: current.depth + 1 });
      }
    }
  }

  const totalChunks = results.reduce((sum, r) => sum + r.chunks, 0);
  const errorCount = results.filter((r) => r.error).length;

  return jsonResponse(200, {
    status: "ok",
    opId,
    totalPages: results.length,
    totalChunks,
    errorCount,
    results,
  });
}
