// MCPクライアント（共通層）: initialize / tools/list / tools/call（Streamable HTTP）。
//
// セッションは1リクエストの間だけ持つ（ステートレス）。Workerはリクエストをまたいで
// メモリを持てない前提なので、毎回 initialize から始める。サーバーはPOSTに対して
// 通常のJSONでもSSE（text/event-stream）でも返しうるので、両方をここで吸収し、
// 各サービス（providers.ts）は通信形式を意識しない。

import { McpAuthError, McpError } from "./providers";

export const PROTOCOL_VERSION = "2025-06-18";
const TIMEOUT_MS = 30_000;
export const CLIENT_NAME = "RAG-POC";
const MAX_TOOL_PAGES = 10;
const MAX_RESULT_CHARS = 20_000;

export interface McpToolInfo {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  readOnly: boolean; // サーバー自身のヒント(readOnlyHint===true)。確認の要否の判定は permissions.ts
}

export interface McpCallResult {
  isError: boolean;
  text: string;
  structured?: unknown;
}

type FetchLike = typeof fetch;

export class McpSession {
  private sessionId: string | null = null;
  private nextId = 0;

  constructor(
    private readonly url: string,
    private readonly accessToken: string,
    private readonly fetchImpl: FetchLike = fetch,
  ) {}

  private headers(): Record<string, string> {
    const headers: Record<string, string> = {
      ...(this.accessToken ? { Authorization: `Bearer ${this.accessToken}` } : {}),
      Accept: "application/json, text/event-stream",
      "Content-Type": "application/json",
    };
    if (this.sessionId) {
      headers["Mcp-Session-Id"] = this.sessionId;
      headers["MCP-Protocol-Version"] = PROTOCOL_VERSION;
    }
    return headers;
  }

  private async post(message: Record<string, unknown>): Promise<unknown> {
    let response: Response;
    try {
      response = await this.fetchImpl(this.url, {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify(message),
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
    } catch (err) {
      throw new McpError(`MCPサーバーとの通信に失敗しました: ${err instanceof Error ? err.message : String(err)}`);
    }
    if (response.status === 401) throw new McpAuthError("MCPサーバーが認証を拒否しました。もう一度連携してください");
    if (response.status === 202) return null;
    if (response.status >= 400) throw new McpError(`MCPサーバーがエラーを返しました: HTTP ${response.status}`);
    const sid = response.headers.get("Mcp-Session-Id");
    if (sid) this.sessionId = sid;
    return await messageFor(response, message.id);
  }

  private async request(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
    this.nextId += 1;
    const reply = await this.post({ jsonrpc: "2.0", id: this.nextId, method, params });
    if (reply === null || typeof reply !== "object") throw new McpError("MCPサーバーの応答が不正です");
    const record = reply as { error?: unknown; result?: unknown };
    if (record.error) {
      const error = record.error as { message?: unknown };
      throw new McpError(String(typeof error === "object" && error ? error.message : error));
    }
    return record.result;
  }

  async initialize(): Promise<void> {
    await this.request("initialize", {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: CLIENT_NAME, version: "1.0" },
    });
    await this.post({ jsonrpc: "2.0", method: "notifications/initialized" });
  }

  async listTools(): Promise<McpToolInfo[]> {
    const tools: McpToolInfo[] = [];
    let cursor: string | undefined;
    for (let page = 0; page < MAX_TOOL_PAGES; page++) {
      const result = (await this.request("tools/list", cursor ? { cursor } : {})) as
        | { tools?: Array<Record<string, unknown>>; nextCursor?: string }
        | undefined;
      for (const tool of result?.tools ?? []) {
        const annotations = (tool.annotations && typeof tool.annotations === "object" ? tool.annotations : {}) as Record<string, unknown>;
        tools.push({
          name: String(tool.name),
          description: String(tool.description || tool.title || ""),
          inputSchema: tool.inputSchema && typeof tool.inputSchema === "object" ? (tool.inputSchema as Record<string, unknown>) : { type: "object" },
          readOnly: annotations.readOnlyHint === true,
        });
      }
      cursor = result?.nextCursor;
      if (!cursor) break;
    }
    return tools;
  }

  async callTool(name: string, args: Record<string, unknown>): Promise<McpCallResult> {
    const result = ((await this.request("tools/call", { name, arguments: args })) ?? {}) as {
      isError?: boolean;
      content?: Array<Record<string, unknown>>;
      structuredContent?: unknown;
    };
    const text = (result.content ?? [])
      .filter((part) => part && part.type === "text")
      .map((part) => String(part.text ?? ""))
      .join("\n");
    return {
      isError: result.isError === true,
      text: text.slice(0, MAX_RESULT_CHARS),
      ...(result.structuredContent !== undefined ? { structured: result.structuredContent } : {}),
    };
  }
}

// request_id に対応するJSON-RPCメッセージを、JSON応答でもSSEストリームでも取り出す。
async function messageFor(response: Response, requestId: unknown): Promise<unknown> {
  const contentType = response.headers.get("Content-Type") || "";
  const body = await response.text();
  if (contentType.includes("text/event-stream")) {
    let match: unknown = null;
    for (const line of body.split(/\r?\n/)) {
      if (!line.startsWith("data:")) continue;
      try {
        const message = JSON.parse(line.slice(5).trim()) as { id?: unknown };
        if (message && typeof message === "object" && message.id === requestId) match = message;
      } catch {
        // JSONでないdata行（pingなど）は無視
      }
    }
    return match;
  }
  if (!body) return null;
  try {
    return JSON.parse(body);
  } catch {
    throw new McpError("MCPサーバーの応答を解析できません");
  }
}

export async function openSession(url: string, accessToken: string, fetchImpl: FetchLike = fetch): Promise<McpSession> {
  const session = new McpSession(url, accessToken, fetchImpl);
  await session.initialize();
  return session;
}
