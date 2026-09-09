import type { ChunkMetadata, Env } from "./types";
import { embedTextBatch, sha256Hex } from "./embeddings";
import { chunkText } from "./chunking";

// VectorizeのベクトルIDは64バイト上限。日本語の長いページタイトルをそのままIDに使うと
// UTF-8で1文字3バイトになり簡単に超過する（実際にHoudini21同期で発生した）。
// 人間が読めるファイル名はmetadata.fileに持たせ、IDそのものはハッシュベースの固定長にする。
async function makeChunkId(
  namespaceId: string,
  file: string,
  chunkIndex: number,
): Promise<string> {
  const hash = (await sha256Hex(`${namespaceId}::${file}`)).slice(0, 40);
  return `${hash}:${chunkIndex}`;
}

// 制御文字・孤立サロゲート（不正なUTF-16単位）・U+FFFD（不正なバイト列のデコード時に
// 挿入される置換文字）を除去する。Google Drive/Notionから取得したテキストにこれらが
// 混入していると、VectorizeへのupsertがVECTOR_UPSERT_ERROR（JSON形式エラー）で失敗する
// ことがある（実際に「Houdini 22 Sneak Peek | SideFX」の同期で発生・確認）。
// U+FFFDはリテラル文字ではなくコードポイント指定（�）で書く：ファイル保存・
// エディタ間の往復でリテラル文字が化ける事故を避けるため。
const REPLACEMENT_CHAR = String.fromCharCode(0xfffd);
function sanitizeText(text: string): string {
  let result = "";
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0;
    if (cp <= 0x1f && ch !== "\t" && ch !== "\n" && ch !== "\r") continue;
    if (cp === 0x7f) continue;
    if (ch === REPLACEMENT_CHAR) continue;
    result += ch;
  }
  return result;
}

// Notion/Drive同期・手動登録の共通ゴール：1ドキュメント分のテキストをチャンク分割し、
// Gemini埋め込み→Vectorize（共有スコープ）＋D1 FTS5への書き込みまで行う
// （既存GAS kbBulkEmbedAndIndex_/kbWriteAndIndex_相当）。
export interface IngestResult {
  chunks: number;
  skippedVectors: Array<{ chunkIndex: number; reason: string }>;
}

// batchEmbedContentsに1回で渡すチャンク数。埋め込みを1チャンクずつ（あるいは
// 少数ずつ並列に）待っていると、チャンク数の多いドキュメント（大きいPDF/Notion
// ページ等）でHTTP往復回数がチャンク数に比例して増え続け、withAbortTimeoutで
// 想定している「1ファイルあたりの処理時間」の枠を簡単に超えてしまう
// （実機のDrive同期で85/335件目付近から連続タイムアウトとして発覚、2026-08-29）。
// 1リクエストにまとめて埋め込みAPIの往復回数自体を減らす。上限件数はGoogle側で
// 公開されていないため、安全側の値を決め打ちしている。
const EMBED_BATCH_SIZE = 50;
// バッチ自体も複数を同時発行する。1バッチ50件の呼び出しは1件だけの呼び出しより
// レスポンスに時間がかかる（サーバ側の処理量が増えるため）ので、バッチを完全に
// 逐次実行すると「往復回数は減ったが並列に発行しなくなった分」で相殺されうる。
// 往復回数削減と並列発行を両立させるため、バッチ単位でもEMBED_BATCH_CONCURRENCY
// 個ずつ同時に投げる。
const EMBED_BATCH_CONCURRENCY = 3;

export async function ingestDocument(
  env: Env,
  namespaceId: string,
  file: string,
  rawText: string,
  source: "notion" | "drive" | "manual" = "manual",
  signal?: AbortSignal,
): Promise<IngestResult> {
  const fullText = sanitizeText(rawText);
  const chunks = chunkText(fullText);
  if (chunks.length === 0) return { chunks: 0, skippedVectors: [] };

  const ingestedAt = Math.floor(Date.now() / 1000);
  const size = fullText.length;

  // 埋め込みはEMBED_BATCH_SIZE件ずつbatchEmbedContentsでまとめて呼び出し、さらに
  // EMBED_BATCH_CONCURRENCY個のバッチを同時発行する（D1書き込みは各バッチの埋め込みが
  // 返ってきた直後にそのバッチ内で並列実行する。D1書き込み自体はチャンク間で独立なので
  // 並列実行しても問題ない）。
  const chunkIds = await Promise.all(
    chunks.map((_, i) => makeChunkId(namespaceId, file, i)),
  );
  const vectors: Array<{
    id: string;
    values: number[];
    metadata: ChunkMetadata;
  }> = new Array(chunks.length);

  const processBatch = async (start: number, end: number) => {
    const batchValues = await embedTextBatch(env, chunks.slice(start, end), signal);
    await Promise.all(
      batchValues.map(async (values, offset) => {
        const i = start + offset;
        const chunkId = chunkIds[i];
        const metadata: ChunkMetadata = {
          file,
          namespace: namespaceId,
          scope: "shared",
          chunk_index: i,
          text: chunks[i],
          source,
          size,
          ingested_at: ingestedAt,
        };
        vectors[i] = { id: chunkId, values, metadata };

        await env.DB.prepare("DELETE FROM chunks_fts WHERE chunk_id = ?")
          .bind(chunkId)
          .run();
        await env.DB.prepare(
          "INSERT INTO chunks_fts (chunk_id, file, namespace, scope, owner_user_id, difficulty, body) VALUES (?, ?, ?, ?, NULL, NULL, ?)",
        )
          .bind(chunkId, file, namespaceId, "shared", chunks[i])
          .run();

        // グラフビュー用の軽量インデックス（migrations/0008_kb_documents.sql参照）。
        // ドキュメントごとに1行（chunk_index=0のチャンクIDのみ）を維持することで、
        // graph.tsがchunks_fts本体（UNINDEXED列への先頭ワイルドカードLIKE、実質フル
        // スキャン）を毎回スキャンせずに済むようにする。
        if (i === 0) {
          await env.DB.prepare(
            "INSERT OR REPLACE INTO kb_documents (chunk_id, file, namespace, scope, owner_user_id) VALUES (?, ?, ?, ?, NULL)",
          )
            .bind(chunkId, file, namespaceId, "shared")
            .run();
        }
      }),
    );
  };

  const batchRanges: Array<{ start: number; end: number }> = [];
  for (let start = 0; start < chunks.length; start += EMBED_BATCH_SIZE) {
    batchRanges.push({ start, end: Math.min(start + EMBED_BATCH_SIZE, chunks.length) });
  }
  for (let g = 0; g < batchRanges.length; g += EMBED_BATCH_CONCURRENCY) {
    const group = batchRanges.slice(g, g + EMBED_BATCH_CONCURRENCY);
    await Promise.all(group.map((r) => processBatch(r.start, r.end)));
  }

  // 1回のupsertにまとめて全チャンクを送ると、ドキュメントが大きい場合にリクエストが
  // 壊れることがある（実際に「Houdini 22 Sneak Peek | SideFX」の同期でVECTOR_UPSERT_ERROR
  // 「json形式の解析に失敗」が発生。原因はチャンク単位でも特定できず、恐らくVectorize側の
  // パーサが特定のバイト列を嫌う稀なケース。小分けにして送ることで影響範囲を抑え、
  // それでも個別に失敗するチャンクは「ドキュメント全体を失敗させず、そのチャンクだけ
  // スキップ」する方針にした＝1件のためにドキュメント全体（他の全チャンク）を
  // 無駄にしないための実利的な対処）。
  const UPSERT_CHUNK = 20;
  const skippedVectors: Array<{ chunkIndex: number; reason: string }> = [];
  const toVectorizeFormat = (v: (typeof vectors)[number]) => ({
    id: v.id,
    values: v.values,
    metadata: v.metadata as unknown as Record<
      string,
      VectorizeVectorMetadataValue
    >,
  });
  for (let i = 0; i < vectors.length; i += UPSERT_CHUNK) {
    const batch = vectors.slice(i, i + UPSERT_CHUNK);
    try {
      await env.VEC_SHARED.upsert(batch.map(toVectorizeFormat));
    } catch (batchErr) {
      // バッチ全体が失敗した場合、原因の1件を特定するために1件ずつ再試行する
      for (const v of batch) {
        try {
          await env.VEC_SHARED.upsert([toVectorizeFormat(v)]);
        } catch (singleErr) {
          const detail =
            singleErr instanceof Error ? singleErr.message : String(singleErr);
          skippedVectors.push({
            chunkIndex: v.metadata.chunk_index,
            reason: detail,
          });
        }
      }
    }
  }

  return { chunks: chunks.length, skippedVectors };
}

export async function logKb(
  env: Env,
  opId: string,
  namespaceId: string,
  source: "notion" | "drive" | "manual",
  file: string | null,
  status: "ok" | "error" | "skipped",
  detail: string,
): Promise<void> {
  await env.DB.prepare(
    "INSERT INTO kb_log (op_id, namespace_id, source, file, status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
  )
    .bind(
      opId,
      namespaceId,
      source,
      file,
      status,
      detail,
      Math.floor(Date.now() / 1000),
    )
    .run();
}
