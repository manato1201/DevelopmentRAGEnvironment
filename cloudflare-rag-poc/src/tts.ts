import type { AuthedUser, Env } from "./types";
import { jsonResponse } from "./http";
import { sha256Hex } from "./embeddings";

// POST /tts — Google Cloud Text-to-Speech への中継（2026-10-20）。
// 動画エンジン（RAGReel）が、スライドのナレーションを音声にするために呼ぶ。VOICEVOXを各自の
// PCに入れなくて済むようにするための経路で、/claude/messages と同じく「鍵をクライアントに渡さない」。
//
// 費用の守り（Googleは文字数課金。docs/houdini-distribution-plan.md）:
//   1. 鍵（user_id）ごとの1日の文字数上限   … TTS_DAILY_CHARS_PER_KEY（既定 50,000）
//   2. 全体の1日の文字数上限               … TTS_DAILY_CHARS_GLOBAL（既定 300,000）
//   3. 同じ文章・声・速さの再合成はキャッシュから返し、文字数を数えない
//   4. 声は ja-JP の Neural2 / Chirp3-HD だけ（Studio など高額な声は使えない）
// 上限は、Google側の割り当て（クォータ）とは別の、最初の防波堤。

export const TTS_MAX_CHARS_PER_REQUEST = 1200; // Googleの入力上限は5,000バイト。日本語は1文字3バイトなので余裕を持たせる
export const TTS_DEFAULT_PER_KEY = 50_000;
export const TTS_DEFAULT_GLOBAL = 300_000;
export const TTS_DEFAULT_VOICE = "ja-JP-Neural2-B";
const SAMPLE_RATE = 24000;
const GOOGLE_URL = "https://texttospeech.googleapis.com/v1/text:synthesize";
const CACHE_SECONDS = 60 * 60 * 24 * 30;

// 許可する声。Studio（$160/100万文字）などは通さない。
const VOICE_RE = /^ja-JP-(Neural2-[A-D]|Chirp3-HD-[A-Za-z]+)$/;

export function sanitizeVoice(raw: unknown, fallback: string): string {
  return typeof raw === "string" && VOICE_RE.test(raw) ? raw : fallback;
}

export function sanitizeRate(raw: unknown): number {
  const n = Number(raw);
  if (!Number.isFinite(n)) return 1;
  return Math.round(Math.min(Math.max(n, 0.8), 1.3) * 100) / 100;
}

function limitFromEnv(raw: string | undefined, fallback: number): number {
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : fallback;
}

// 日本時間の日付（YYYY-MM-DD）。
export function jstDay(now = Date.now()): string {
  return new Date(now + 9 * 3600 * 1000).toISOString().slice(0, 10);
}

export function countChars(text: string): number {
  return [...text].length;
}

export class TtsLimitError extends Error {}

async function reserve(env: Env, userId: string, day: string, chars: number, limit: number): Promise<boolean> {
  const res = await env.DB.prepare(
    `INSERT INTO tts_usage (user_id, day, chars) VALUES (?, ?, ?)
     ON CONFLICT(user_id, day) DO UPDATE SET chars = chars + excluded.chars
     WHERE chars + excluded.chars <= ?`,
  )
    .bind(userId, day, chars, limit)
    .run();
  return (res.meta.changes ?? 0) > 0;
}

async function refund(env: Env, userId: string, day: string, chars: number): Promise<void> {
  await env.DB.prepare("UPDATE tts_usage SET chars = MAX(0, chars - ?) WHERE user_id = ? AND day = ?")
    .bind(chars, userId, day)
    .run();
}

export async function ttsUsageToday(env: Env, userId: string): Promise<number> {
  const row = await env.DB.prepare("SELECT chars FROM tts_usage WHERE user_id = ? AND day = ?")
    .bind(userId, jstDay())
    .first<{ chars: number }>();
  return row?.chars ?? 0;
}

function decodeBase64(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function audioResponse(bytes: Uint8Array, headers: Record<string, string>): Response {
  return new Response(bytes, { status: 200, headers: { "content-type": "audio/wav", ...headers } });
}

async function callGoogle(
  env: Env, text: string, voice: string, rate: number,
): Promise<{ ok: true; audio: Uint8Array } | { ok: false; status: number; message: string }> {
  const send = async (speakingRate: number | undefined) => {
    const audioConfig: Record<string, unknown> = { audioEncoding: "LINEAR16", sampleRateHertz: SAMPLE_RATE };
    if (speakingRate !== undefined) audioConfig.speakingRate = speakingRate;
    return fetch(GOOGLE_URL, {
      method: "POST",
      headers: { "content-type": "application/json", "x-goog-api-key": env.GOOGLE_TTS_API_KEY ?? "" },
      body: JSON.stringify({ input: { text }, voice: { languageCode: "ja-JP", name: voice }, audioConfig }),
    });
  };
  let res = await send(rate === 1 ? undefined : rate);
  // 声によっては速さの指定を受け付けない。速さなしで1回だけやり直す。
  if (res.status === 400 && rate !== 1) res = await send(undefined);
  if (!res.ok) {
    let message = `Google TTS ${res.status}`;
    try {
      const err = (await res.json()) as { error?: { message?: string } };
      if (err.error?.message) message += `: ${err.error.message.slice(0, 200)}`;
    } catch { /* 本文が読めなくても、状態コードは返す */ }
    return { ok: false, status: res.status, message };
  }
  const data = (await res.json()) as { audioContent?: string };
  if (!data.audioContent) return { ok: false, status: 502, message: "Google TTS: audioContent がありません" };
  return { ok: true, audio: decodeBase64(data.audioContent) };
}

export async function handleTts(req: Request, env: Env, user: AuthedUser): Promise<Response> {
  if (!env.GOOGLE_TTS_API_KEY) {
    return jsonResponse(500, { error: "GOOGLE_TTS_API_KEYが設定されていません（wrangler secret put GOOGLE_TTS_API_KEY）" });
  }
  let body: { text?: unknown; voice?: unknown; speaking_rate?: unknown };
  try {
    body = (await req.json()) as typeof body;
  } catch {
    return jsonResponse(400, { error: "JSONで送ってください" });
  }
  const text = typeof body.text === "string" ? body.text.trim() : "";
  if (!text) return jsonResponse(400, { error: "text は必須です" });
  const chars = countChars(text);
  if (chars > TTS_MAX_CHARS_PER_REQUEST) {
    return jsonResponse(400, { error: `text は${TTS_MAX_CHARS_PER_REQUEST}文字までです（${chars}文字）。スライドごとに分けて送ってください` });
  }
  const voice = sanitizeVoice(body.voice, sanitizeVoice(env.TTS_VOICE, TTS_DEFAULT_VOICE));
  const rate = sanitizeRate(body.speaking_rate);

  // キャッシュ（Cache API。無い環境、例えばテストでは使わない）。同じ文章は課金されない。
  const hash = await sha256Hex(`${voice}|${rate}|${text}`);
  const cache = typeof caches !== "undefined" ? (caches as unknown as { default?: Cache }).default : undefined;
  const cacheKey = new Request(`https://tts-cache.invalid/${hash}`);
  if (cache) {
    const hit = await cache.match(cacheKey);
    if (hit) {
      return audioResponse(new Uint8Array(await hit.arrayBuffer()), { "x-tts-cache": "hit", "x-tts-voice": voice });
    }
  }

  const perKey = limitFromEnv(env.TTS_DAILY_CHARS_PER_KEY, TTS_DEFAULT_PER_KEY);
  const global = limitFromEnv(env.TTS_DAILY_CHARS_GLOBAL, TTS_DEFAULT_GLOBAL);
  const day = jstDay();
  if (!(await reserve(env, user.userId, day, chars, perKey))) {
    return jsonResponse(429, { error: `音声合成の1日の上限（${perKey}文字）に達しています。明日また試してください`, limit: perKey, used: await ttsUsageToday(env, user.userId) });
  }
  if (!(await reserve(env, "*", day, chars, global))) {
    await refund(env, user.userId, day, chars);
    return jsonResponse(429, { error: "音声合成の全体の1日の上限に達しています。明日また試してください" });
  }

  let result: Awaited<ReturnType<typeof callGoogle>>;
  try {
    result = await callGoogle(env, text, voice, rate);
  } catch (err) {
    result = { ok: false, status: 502, message: err instanceof Error ? err.message : String(err) };
  }
  if (!result.ok) {
    await refund(env, user.userId, day, chars);
    await refund(env, "*", day, chars);
    const status = result.status === 429 ? 429 : 502;
    return jsonResponse(status, { error: result.message });
  }

  if (cache) {
    await cache.put(
      cacheKey,
      new Response(result.audio, { headers: { "content-type": "audio/wav", "cache-control": `public, max-age=${CACHE_SECONDS}` } }),
    );
  }
  const used = await ttsUsageToday(env, user.userId);
  return audioResponse(result.audio, {
    "x-tts-cache": "miss",
    "x-tts-voice": voice,
    "x-tts-chars-used-today": String(used),
    "x-tts-chars-limit": String(perKey),
  });
}
