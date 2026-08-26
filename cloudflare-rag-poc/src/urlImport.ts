import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId } from "./chunking";

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

// POST /admin/kb/import-url — 任意のURLの本文を取得してnamespaceへ登録する
// （既存GAS adminKbImportUrl相当）。body: { namespace, url, title? }
export async function handleImportUrl(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
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

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
