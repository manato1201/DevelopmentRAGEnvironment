import type { Env } from "./types";
import { generateContentWithParts } from "./embeddings";
import { uploadGeminiFile, waitForGeminiFileActive, deleteGeminiFile } from "./geminiFile";

// PDFはGeminiのネイティブなドキュメント理解機能に渡し、本文をそのまま書き出してもらう
// （既存GAS _convertBinaryBlobToText_のPDF部分に相当。専用のPDFパーサライブラリを
// Workers上に用意する必要がなく、レイアウト崩れにも強い）。
// Gemini APIのインラインデータには実質的なサイズ上限（約20MB）があるため、それを超える
// PDFはFile API（音声/動画と同じアップロード方式）に切り替える。実際に26MBのPDF
// （CEDECの発表資料）でこの上限に達したことを確認済み（2026-08-26）。
const INLINE_SIZE_LIMIT = 18 * 1024 * 1024;
const PDF_PROMPT = "このPDFに含まれる本文をすべてテキストとして書き出してください。要約や意見は加えず、原文の内容をできるだけそのまま出力してください。";

export async function extractTextFromPdf(env: Env, bytes: ArrayBuffer, fileName = "document.pdf"): Promise<string> {
  if (bytes.byteLength <= INLINE_SIZE_LIMIT) {
    const base64 = arrayBufferToBase64(bytes);
    const result = await generateContentWithParts(env, [
      { inlineData: { mimeType: "application/pdf", data: base64 } },
      { text: PDF_PROMPT },
    ]);
    return result.text;
  }

  const file = await uploadGeminiFile(env, bytes, "application/pdf", fileName);
  try {
    const active = file.state === "ACTIVE" ? file : await waitForGeminiFileActive(env, file.name);
    const result = await generateContentWithParts(env, [
      { fileData: { mimeType: active.mimeType, fileUri: active.uri } },
      { text: PDF_PROMPT },
    ]);
    return result.text;
  } finally {
    await deleteGeminiFile(env, file.name);
  }
}

function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

// ---- DOCX/PPTX（OOXML）: 実体はZIPアーカイブなので、必要なXMLエントリだけを取り出して
// テキストを抽出する。Workers上にZIPライブラリを追加せずに済むよう最小限の実装にしている。

interface ZipEntry {
  fileName: string;
  compressionMethod: number;
  compressedSize: number;
  localHeaderOffset: number;
}

function findEndOfCentralDirectory(view: DataView): { cdOffset: number; cdCount: number } {
  const EOCD_SIG = 0x06054b50;
  const searchStart = Math.max(0, view.byteLength - 66000);
  for (let i = view.byteLength - 22; i >= searchStart; i--) {
    if (view.getUint32(i, true) === EOCD_SIG) {
      const cdCount = view.getUint16(i + 10, true);
      const cdOffset = view.getUint32(i + 16, true);
      return { cdOffset, cdCount };
    }
  }
  throw new Error("ZIP形式として解析できませんでした（End of Central Directoryが見つかりません）");
}

function readCentralDirectory(view: DataView, cdOffset: number, cdCount: number): ZipEntry[] {
  const CD_SIG = 0x02014b50;
  const entries: ZipEntry[] = [];
  let offset = cdOffset;
  for (let i = 0; i < cdCount; i++) {
    if (view.getUint32(offset, true) !== CD_SIG) break;
    const compressionMethod = view.getUint16(offset + 10, true);
    const compressedSize = view.getUint32(offset + 20, true);
    const fileNameLen = view.getUint16(offset + 28, true);
    const extraLen = view.getUint16(offset + 30, true);
    const commentLen = view.getUint16(offset + 32, true);
    const localHeaderOffset = view.getUint32(offset + 42, true);
    const nameBytes = new Uint8Array(view.buffer, view.byteOffset + offset + 46, fileNameLen);
    const fileName = new TextDecoder().decode(nameBytes);
    entries.push({ fileName, compressionMethod, compressedSize, localHeaderOffset });
    offset += 46 + fileNameLen + extraLen + commentLen;
  }
  return entries;
}

async function inflateRaw(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function readZipEntryData(view: DataView, entry: ZipEntry): Promise<Uint8Array> {
  const LOCAL_SIG = 0x04034b50;
  const off = entry.localHeaderOffset;
  if (view.getUint32(off, true) !== LOCAL_SIG) {
    throw new Error(`ZIPのローカルヘッダーが不正です（${entry.fileName}）`);
  }
  const fileNameLen = view.getUint16(off + 26, true);
  const extraLen = view.getUint16(off + 28, true);
  const dataStart = off + 30 + fileNameLen + extraLen;
  const raw = new Uint8Array(view.buffer, view.byteOffset + dataStart, entry.compressedSize);
  if (entry.compressionMethod === 0) return raw;
  if (entry.compressionMethod === 8) return inflateRaw(raw);
  throw new Error(`未対応の圧縮方式です（method=${entry.compressionMethod}）`);
}

// XMLタグを除去してテキストのみを残す（HTMLRewriterはHTML5パーサ前提でOOXMLの
// カスタム名前空間タグ（w:p, a:t等）だと属性解釈で崩れることがあるため、ここでは
// 正規表現ベースの単純なタグ除去にする。段落境界（</w:p>）で改行を入れて読みやすくする）。
function stripXmlTags(xml: string): string {
  return xml
    .replace(/<\/w:p>/g, "\n")
    .replace(/<\/a:p>/g, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// DOCX/PPTXはZIP解凍・XML文字列全体をメモリ上に保持する実装のため、Workers isolateの
// メモリ上限（128MB）に対して大きすぎるファイルは事前に弾く。実際に埋め込み動画/画像を
// 多く含む大きいPPTX（CEDECの発表資料）で"Memory limit exceeded before EOF"が発生し、
// 原因を特定した上で追加した対策（2026-08-26）。
const OOXML_SIZE_LIMIT = 20 * 1024 * 1024;

export async function extractTextFromDocx(bytes: ArrayBuffer): Promise<string> {
  if (bytes.byteLength > OOXML_SIZE_LIMIT) {
    throw new Error(`ファイルが大きすぎます（${Math.round(bytes.byteLength / 1024 / 1024)}MB）。現在は約20MBまでに対応しています`);
  }
  const view = new DataView(bytes);
  const { cdOffset, cdCount } = findEndOfCentralDirectory(view);
  const entries = readCentralDirectory(view, cdOffset, cdCount);
  const docEntry = entries.find((e) => e.fileName === "word/document.xml");
  if (!docEntry) throw new Error("word/document.xmlが見つかりません（.docx形式ではない可能性があります）");
  const xmlBytes = await readZipEntryData(view, docEntry);
  const xml = new TextDecoder("utf-8").decode(xmlBytes);
  return stripXmlTags(xml);
}

export async function extractTextFromPptx(bytes: ArrayBuffer): Promise<string> {
  if (bytes.byteLength > OOXML_SIZE_LIMIT) {
    throw new Error(`ファイルが大きすぎます（${Math.round(bytes.byteLength / 1024 / 1024)}MB）。現在は約20MBまでに対応しています`);
  }
  const view = new DataView(bytes);
  const { cdOffset, cdCount } = findEndOfCentralDirectory(view);
  const entries = readCentralDirectory(view, cdOffset, cdCount);
  const slideEntries = entries
    .filter((e) => /^ppt\/slides\/slide\d+\.xml$/.test(e.fileName))
    .sort((a, b) => {
      const na = parseInt(a.fileName.match(/(\d+)/)![1], 10);
      const nb = parseInt(b.fileName.match(/(\d+)/)![1], 10);
      return na - nb;
    });
  if (slideEntries.length === 0) throw new Error("スライドが見つかりません（.pptx形式ではない可能性があります）");

  const texts: string[] = [];
  for (let i = 0; i < slideEntries.length; i++) {
    const xmlBytes = await readZipEntryData(view, slideEntries[i]);
    const xml = new TextDecoder("utf-8").decode(xmlBytes);
    texts.push(`--- スライド${i + 1} ---\n${stripXmlTags(xml)}`);
  }
  return texts.join("\n\n");
}
