// POST /tts: voice allow-list, per-key and global daily caps, refund on failure, Google request shape.
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const MIG = fileURLToPath(new URL("../migrations/", import.meta.url));
const db = new DatabaseSync(":memory:");
db.exec(readFileSync(MIG + "0031_tts_usage.sql", "utf8"));

const D1 = {
  prepare(sql) {
    return {
      a: [], bind(...x) { this.a = x; return this; },
      async run() { const r = db.prepare(sql).run(...this.a); return { meta: { changes: r.changes } }; },
      async first() { return db.prepare(sql).get(...this.a) ?? null; },
    };
  },
};

const WAV = Buffer.from("RIFF....WAVEfmt fake audio").toString("base64");
let googleCalls = [];
let googleMode = "ok"; // ok | fail500 | reject_rate
globalThis.fetch = async (input, init = {}) => {
  const url = typeof input === "string" ? input : input.url;
  if (!url.startsWith("https://texttospeech.googleapis.com/v1/text:synthesize")) throw new Error("unexpected fetch " + url);
  const body = JSON.parse(init.body);
  googleCalls.push({ body, headers: init.headers });
  if (googleMode === "fail500") return new Response(JSON.stringify({ error: { message: "backend boom" } }), { status: 500 });
  if (googleMode === "reject_rate" && body.audioConfig.speakingRate !== undefined) {
    return new Response(JSON.stringify({ error: { message: "rate unsupported" } }), { status: 400 });
  }
  return new Response(JSON.stringify({ audioContent: WAV }));
};

const T = await import("../src/tts");
const user = { userId: "u1", role: "editor" };
const mkEnv = (extra = {}) => ({ DB: D1, GOOGLE_TTS_API_KEY: "test-key", ...extra });
const post = (env, body, u = user) => T.handleTts(new Request("https://x/tts", { method: "POST", body: JSON.stringify(body) }), env, u);
const used = (id) => db.prepare("SELECT COALESCE(SUM(chars),0) c FROM tts_usage WHERE user_id = ?").get(id).c;
const reset = () => { db.exec("DELETE FROM tts_usage"); googleCalls = []; googleMode = "ok"; };

// 1) pure helpers
assert.equal(T.sanitizeVoice("ja-JP-Neural2-C", "x"), "ja-JP-Neural2-C");
assert.equal(T.sanitizeVoice("ja-JP-Chirp3-HD-Aoede", "x"), "ja-JP-Chirp3-HD-Aoede");
assert.equal(T.sanitizeVoice("ja-JP-Studio-B", "x"), "x", "expensive voice must be refused");
assert.equal(T.sanitizeVoice("en-US-Neural2-A", "x"), "x");
assert.equal(T.sanitizeVoice("ja-JP-Neural2-B; DROP", "x"), "x");
assert.equal(T.sanitizeRate("abc"), 1);
assert.equal(T.sanitizeRate(9), 1.3);
assert.equal(T.sanitizeRate(0.1), 0.8);
assert.equal(T.jstDay(Date.UTC(2026, 9, 20, 16, 0, 0)), "2026-10-21", "JST day rolls over at 15:00 UTC");
assert.equal(T.countChars("あい😀"), 3);

// 2) happy path: audio returned, key sent in header (not URL), usage counted
reset();
let res = await post(mkEnv(), { text: "こんにちは。これはテストです。" });
assert.equal(res.status, 200);
assert.equal(res.headers.get("content-type"), "audio/wav");
assert.equal(res.headers.get("x-tts-voice"), T.TTS_DEFAULT_VOICE);
assert.equal((await res.arrayBuffer()).byteLength, Buffer.from(WAV, "base64").length);
assert.equal(googleCalls.length, 1);
assert.equal(googleCalls[0].headers["x-goog-api-key"], "test-key");
assert.equal(googleCalls[0].body.voice.languageCode, "ja-JP");
assert.equal(googleCalls[0].body.audioConfig.audioEncoding, "LINEAR16");
assert.equal(used("u1"), 15);
assert.equal(used("*"), 15);

// 3) validation
reset();
assert.equal((await post(mkEnv(), { text: "  " })).status, 400);
assert.equal((await post(mkEnv(), {})).status, 400);
assert.equal((await post(mkEnv(), { text: "あ".repeat(T.TTS_MAX_CHARS_PER_REQUEST + 1) })).status, 400);
assert.equal(googleCalls.length, 0, "rejected requests must not reach Google");
assert.equal(used("u1"), 0);
const bad = await T.handleTts(new Request("https://x/tts", { method: "POST", body: "not json" }), mkEnv(), user);
assert.equal(bad.status, 400);

// 4) missing secret
reset();
res = await post({ DB: D1 }, { text: "テスト" });
assert.equal(res.status, 500);

// 5) disallowed voice falls back to the default (never forwarded to Google)
reset();
await post(mkEnv(), { text: "テスト", voice: "ja-JP-Studio-B" });
assert.equal(googleCalls[0].body.voice.name, T.TTS_DEFAULT_VOICE);
await post(mkEnv(), { text: "テスト", voice: "ja-JP-Chirp3-HD-Kore" });
assert.equal(googleCalls[1].body.voice.name, "ja-JP-Chirp3-HD-Kore");
await post(mkEnv({ TTS_VOICE: "ja-JP-Neural2-D" }), { text: "テスト" });
assert.equal(googleCalls[2].body.voice.name, "ja-JP-Neural2-D", "env default voice");

// 6) per-key cap: refused with 429, nothing sent to Google, usage unchanged
reset();
const env10 = mkEnv({ TTS_DAILY_CHARS_PER_KEY: "10" });
assert.equal((await post(env10, { text: "あいうえおかきくけこ" })).status, 200); // exactly 10
assert.equal(used("u1"), 10);
res = await post(env10, { text: "あ" });
assert.equal(res.status, 429);
assert.equal(googleCalls.length, 1);
assert.equal(used("u1"), 10);
// another key is unaffected
assert.equal((await post(env10, { text: "あ" }, { userId: "u2", role: "editor" })).status, 200);

// 7) global cap protects the wallet even across many keys, and the per-key reservation is rolled back
reset();
const envG = mkEnv({ TTS_DAILY_CHARS_GLOBAL: "5" });
assert.equal((await post(envG, { text: "あいうえお" }, { userId: "a" })).status, 200);
res = await post(envG, { text: "あ" }, { userId: "b" });
assert.equal(res.status, 429);
assert.equal(used("b"), 0, "per-key reservation must be refunded when the global cap refuses");
assert.equal(used("*"), 5);

// 8) Google failure refunds both counters
reset();
googleMode = "fail500";
res = await post(mkEnv(), { text: "あいうえお" });
assert.equal(res.status, 502);
assert.match((await res.json()).error, /backend boom/);
assert.equal(used("u1"), 0);
assert.equal(used("*"), 0);

// 9) a voice that rejects speakingRate is retried once without it
reset();
googleMode = "reject_rate";
res = await post(mkEnv(), { text: "あいうえお", speaking_rate: 1.1 });
assert.equal(res.status, 200);
assert.equal(googleCalls.length, 2);
assert.equal(googleCalls[0].body.audioConfig.speakingRate, 1.1);
assert.equal(googleCalls[1].body.audioConfig.speakingRate, undefined);
assert.equal(used("u1"), 5, "retry must not be charged twice");

// 10) reservation is atomic: concurrent requests cannot overshoot the cap
reset();
const envC = mkEnv({ TTS_DAILY_CHARS_PER_KEY: "20" });
const results = await Promise.all(Array.from({ length: 6 }, () => post(envC, { text: "あいうえおかきくけこ" })));
assert.equal(results.filter((r) => r.status === 200).length, 2);
assert.equal(results.filter((r) => r.status === 429).length, 4);
assert.ok(used("u1") <= 20);

console.log("tts tests passed");
