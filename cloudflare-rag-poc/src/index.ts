import type { Env } from "./types";
import { authenticate } from "./auth";
import { handleSearch } from "./search";
import { handleIngest } from "./ingest";

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);

    if (url.pathname === "/health") {
      return json(200, { status: "ok" });
    }

    if (req.method !== "POST") {
      return json(405, { error: "POST のみ対応しています" });
    }

    const user = await authenticate(req, env);
    if (!user) {
      return json(401, { error: "認証に失敗しました（Authorization: Bearer <APIキー> が必要です）" });
    }

    try {
      switch (url.pathname) {
        case "/search":
          return await handleSearch(req, env, user);
        case "/ingest":
          return await handleIngest(req, env, user);
        default:
          return json(404, { error: `未定義のエンドポイントです: ${url.pathname}` });
      }
    } catch (err) {
      return json(500, { error: err instanceof Error ? err.message : String(err) });
    }
  },
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
