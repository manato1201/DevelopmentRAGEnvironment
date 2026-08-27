import type { AuthedUser, Env } from "./types";
import { requireAdmin } from "./auth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId } from "./chunking";
import { createNotionPage } from "./notion";

// POST /admin/kb/add-faq — 質問と回答を1件だけサクッと登録する（既存GAS adminKbAddFaq相当、
// 2026-08-27追加）。QA CSV一括登録（/admin/kb/import-qa-csv）はあったが、1件だけ試したい/
// 手早く追加したい場合にCSVを組み立てる手間があったための追加。
// alsoWriteToNotionを指定すると、D1/Vectorizeへの登録に加えてnamespaceの同期先Notion DBにも
// ページを作成する（既存GASは全登録が常にNotion/Driveへの書き込みを経由する設計だったが、
// POC側はD1が直接の正とする設計のため、Notionへの複製は任意のオプトインにした）。
// body: { namespace, question, answer, alsoWriteToNotion? }
export async function handleAddFaq(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireAdmin(user);
  const body = (await req.json()) as {
    namespace?: string;
    question?: string;
    answer?: string;
    alsoWriteToNotion?: boolean;
  };
  const namespace = (body.namespace || "").trim();
  const question = (body.question || "").trim();
  const answer = (body.answer || "").trim();
  if (!namespace || !question || !answer) {
    return jsonResponse(400, { error: "namespace, question, answer は必須です" });
  }

  const title = `Q: ${question.slice(0, 90)}`;
  const bodyText = `Q: ${question}\nA: ${answer}`;
  const opId = newOpId();

  let notionPageId: string | null = null;
  if (body.alsoWriteToNotion) {
    const source = await env.DB.prepare("SELECT notion_database_id FROM kb_sources WHERE namespace_id = ?")
      .bind(namespace)
      .first<{ notion_database_id: string | null }>();
    if (!source?.notion_database_id) {
      return jsonResponse(400, { error: `namespace(${namespace})にNotionデータベースIDが設定されていません。先に /admin/kb/set-source で設定するか、alsoWriteToNotionを外してください` });
    }
    try {
      const page = await createNotionPage(env, source.notion_database_id, title, bodyText, answer.slice(0, 200));
      notionPageId = page.id;
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      await logKb(env, opId, namespace, "manual", title, "error", `Notion書き込み失敗: ${detail}`);
      return jsonResponse(502, { error: `Notionへの書き込みに失敗しました: ${detail}` });
    }
  }

  const result = await ingestDocument(env, namespace, title, bodyText, "manual");
  if (!result.chunks) {
    return jsonResponse(400, { error: "本文からチャンクを生成できませんでした" });
  }
  const skipNote = result.skippedVectors.length > 0 ? `（${result.skippedVectors.length}チャンクは登録失敗のためスキップ）` : "";
  const notionNote = notionPageId ? `、Notionページ作成済み（${notionPageId}）` : "";
  await logKb(env, opId, namespace, "manual", title, "ok", `FAQ単発登録: ${result.chunks}チャンク登録${skipNote}${notionNote}`);

  return jsonResponse(200, { status: "ok", opId, title, chunks: result.chunks, skipped: result.skippedVectors.length, notionPageId });
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
