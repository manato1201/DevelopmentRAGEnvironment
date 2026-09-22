import type { AuthedUser, Env } from "./types";
import { requireKnowledgeEditor } from "./auth";
import { ingestDocument, logKb } from "./kbIngest";
import { newOpId } from "./chunking";
import { jsonResponse } from "./http";

// Googleマップ（Places API）の場所情報をナレッジ登録する（2026-09-17追加、管理タブ
// 「連携」サブタブ）。Jira/Backlog/カレンダーと違い「継続的に同期すべき一覧」という
// 概念がない（住所や営業時間はテキスト検索ごとの単発登録が自然）ため、
// urlImport.tsのhandleImportUrlと同じ「1回の呼び出しで1件登録」方式を基本としつつ、
// 複数件まとめて登録したい要望（2026-09-19追加）にはCSV一括登録
// （handleImportPlacesCsv、qaImport.tsと同じバッチ処理方式）で応える。
const DEFAULT_BATCH_SIZE = 5;

interface PlaceResult {
  title: string;
  text: string;
}

// 1件の場所を検索し、登録用のタイトル・本文テキストを組み立てる（テキスト検索→詳細取得の
// 2段階。handleImportPlace/handleImportPlacesCsvの両方から使う共通処理、2026-09-19抽出）。
async function lookupPlace(env: Env, query: string): Promise<PlaceResult> {
  const findUrl = new URL("https://maps.googleapis.com/maps/api/place/findplacefromtext/json");
  findUrl.searchParams.set("input", query);
  findUrl.searchParams.set("inputtype", "textquery");
  findUrl.searchParams.set("fields", "place_id");
  findUrl.searchParams.set("key", env.GOOGLE_MAPS_API_KEY!);

  const findRes = await fetch(findUrl.toString());
  if (!findRes.ok) throw new Error(`Places API（検索）エラー (${findRes.status}): ${await findRes.text()}`);
  const findData = (await findRes.json()) as { status: string; candidates: Array<{ place_id: string }> };
  if (findData.status !== "OK" || findData.candidates.length === 0) {
    throw new Error(`場所が見つかりませんでした（Places APIステータス: ${findData.status}）`);
  }
  const placeId = findData.candidates[0].place_id;

  const detailsUrl = new URL("https://maps.googleapis.com/maps/api/place/details/json");
  detailsUrl.searchParams.set("place_id", placeId);
  detailsUrl.searchParams.set(
    "fields",
    "name,formatted_address,formatted_phone_number,website,rating,opening_hours,editorial_summary",
  );
  detailsUrl.searchParams.set("language", "ja");
  detailsUrl.searchParams.set("key", env.GOOGLE_MAPS_API_KEY!);

  const detailsRes = await fetch(detailsUrl.toString());
  if (!detailsRes.ok) throw new Error(`Places API（詳細）エラー (${detailsRes.status}): ${await detailsRes.text()}`);
  const detailsData = (await detailsRes.json()) as {
    status: string;
    result: {
      name?: string;
      formatted_address?: string;
      formatted_phone_number?: string;
      website?: string;
      rating?: number;
      opening_hours?: { weekday_text?: string[] };
      editorial_summary?: { overview?: string };
    };
  };
  if (detailsData.status !== "OK") {
    throw new Error(`場所の詳細取得に失敗しました（Places APIステータス: ${detailsData.status}）`);
  }

  const place = detailsData.result;
  const title = place.name || query;
  const text = [
    place.name,
    place.formatted_address ? `住所: ${place.formatted_address}` : "",
    place.formatted_phone_number ? `電話番号: ${place.formatted_phone_number}` : "",
    place.website ? `Webサイト: ${place.website}` : "",
    typeof place.rating === "number" ? `評価: ${place.rating}` : "",
    place.opening_hours?.weekday_text?.length ? `営業時間:\n${place.opening_hours.weekday_text.join("\n")}` : "",
    place.editorial_summary?.overview ?? "",
  ]
    .filter(Boolean)
    .join("\n\n");

  if (!text.trim()) throw new Error("登録できる情報がありませんでした");
  return { title, text };
}

// POST /admin/kb/import-place — 場所を1件検索してnamespaceへ登録する。
// body: { namespace, query }
export async function handleImportPlace(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  if (!env.GOOGLE_MAPS_API_KEY) {
    return jsonResponse(400, { error: "Googleマップ連携が未設定です（GOOGLE_MAPS_API_KEYをsecretで設定してください）" });
  }

  const body = (await req.json()) as { namespace?: string; query?: string };
  const namespace = (body.namespace || "").trim();
  const query = (body.query || "").trim();
  if (!namespace || !query) return jsonResponse(400, { error: "namespace と query（場所名・住所）は必須です" });

  let place: PlaceResult;
  try {
    place = await lookupPlace(env, query);
  } catch (err) {
    return jsonResponse(400, { error: err instanceof Error ? err.message : String(err) });
  }

  const result = await ingestDocument(env, namespace, place.title, place.text, "manual");

  const opId = newOpId();
  const skipNote = result.skippedVectors.length > 0 ? `（${result.skippedVectors.length}チャンクは登録失敗のためスキップ）` : "";
  await logKb(env, opId, namespace, "manual", place.title, "ok", `Googleマップ登録: ${result.chunks}チャンク登録${skipNote}（検索語: ${query}）`);

  return jsonResponse(200, {
    status: "ok",
    opId,
    title: place.title,
    chunks: result.chunks,
    skipped: result.skippedVectors.length,
  });
}

// POST /admin/kb/import-places-csv — 場所名・住所を1行1件で複数まとめて登録する
// （2026-09-19追加、「店舗リストを一括登録したい」への対応）。住所自体にカンマを含む
// ことが多く、列区切りのCSVにするとかえって扱いにくいため、あえて「1行=1検索クエリ」の
// 単純な行区切りテキストにしている（列の引用符エスケープが不要になる）。
// qaImport.tsのhandleImportQaCsvと同じ、Cloudflareのサブリクエスト数上限対策のバッチ処理方式。
// body: { namespace, queriesText, startIndex?（省略時0）, batchSize?（省略時5）, opId?（継続呼び出し時に指定） }
export async function handleImportPlacesCsv(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  if (!env.GOOGLE_MAPS_API_KEY) {
    return jsonResponse(400, { error: "Googleマップ連携が未設定です（GOOGLE_MAPS_API_KEYをsecretで設定してください）" });
  }

  const body = (await req.json()) as {
    namespace?: string;
    queriesText?: string;
    startIndex?: number;
    batchSize?: number;
    opId?: string;
  };
  const namespace = (body.namespace || "").trim();
  const queries = (body.queriesText || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && line.toLowerCase() !== "query"); // 先頭のヘッダー行（任意）を許容
  if (!namespace || queries.length === 0) {
    return jsonResponse(400, { error: "namespace と queriesText（1行1件の場所名・住所）は必須です" });
  }

  const startIndex = body.startIndex ?? 0;
  const batchSize = body.batchSize ?? DEFAULT_BATCH_SIZE;
  const opId = body.opId || newOpId();
  const batch = queries.slice(startIndex, startIndex + batchSize);

  let documents = 0;
  let chunks = 0;
  const skipped: Array<{ file: string; reason: string }> = [];
  const results: Array<{ file: string; status: "ok" | "skipped" | "error"; detail: string }> = [];

  for (const query of batch) {
    try {
      const place = await lookupPlace(env, query);
      const result = await ingestDocument(env, namespace, place.title, place.text, "manual");
      documents += 1;
      chunks += result.chunks;
      const skipNote = result.skippedVectors.length > 0 ? `（${result.skippedVectors.length}チャンクは登録失敗のためスキップ）` : "";
      const detail = `${result.chunks}チャンク登録${skipNote}`;
      results.push({ file: place.title, status: "ok", detail });
      await logKb(env, opId, namespace, "manual", place.title, "ok", `Googleマップ一括登録: ${detail}（検索語: ${query}）`);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      skipped.push({ file: query, reason: detail });
      results.push({ file: query, status: "error", detail });
      await logKb(env, opId, namespace, "manual", query, "error", detail);
    }
  }

  const nextIndex = startIndex + batchSize < queries.length ? startIndex + batchSize : null;

  return jsonResponse(200, {
    status: "ok",
    opId,
    documents,
    chunks,
    skipped,
    results,
    totalQueries: queries.length,
    processedRange: [startIndex, startIndex + batch.length],
    nextIndex,
  });
}

// POST /admin/kb/test-connection/maps — secretだけで接続確認する（実際の登録は行わない、
// 2026-09-19追加）。既知の場所名（"Google"）で検索し、認証エラー（REQUEST_DENIED等）と
// 単なる無結果（ZERO_RESULTS、まず起きないが理論上あり得る）を区別する。
export async function handleTestMapsConnection(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  requireKnowledgeEditor(user);
  if (!env.GOOGLE_MAPS_API_KEY) {
    return jsonResponse(400, { error: "Googleマップ連携が未設定です（GOOGLE_MAPS_API_KEYをsecretで設定してください）" });
  }
  const url = new URL("https://maps.googleapis.com/maps/api/place/findplacefromtext/json");
  url.searchParams.set("input", "Google");
  url.searchParams.set("inputtype", "textquery");
  url.searchParams.set("fields", "place_id");
  url.searchParams.set("key", env.GOOGLE_MAPS_API_KEY);

  const res = await fetch(url.toString());
  if (!res.ok) return jsonResponse(400, { error: `Places APIエラー (${res.status}): ${await res.text()}` });
  const data = (await res.json()) as { status: string; error_message?: string };
  if (data.status === "REQUEST_DENIED" || data.status === "INVALID_REQUEST") {
    return jsonResponse(400, { error: `Places APIステータス: ${data.status}${data.error_message ? `（${data.error_message}）` : ""}` });
  }
  return jsonResponse(200, { status: "ok", message: "接続成功（Places APIキーは有効です）" });
}
