// 書き込みツールの、実行前の確認（共通層。2026-10-22追加）。別プロジェクト（AxChatD）の
// mcp/core/approval.py にならう。確認は「1回だけ・5分で失効・本人だけ」。引数はサーバー側に
// 保存し、実行するのはその保存した値だけ（画面から送られた値は使わない）。

import type { Env } from "../types";
import { McpError } from "./providers";

export const APPROVAL_TTL_SECONDS = 300;

export class McpApprovalError extends McpError {
  constructor(message: string) {
    super(message);
    this.name = "McpApprovalError";
  }
}

export interface Approval {
  id: string;
  userId: string;
  ownerId: string;
  providerId: string;
  tool: string;
  arguments: Record<string, unknown>;
  expiresAt: number;
}

interface ApprovalRow {
  id: string;
  user_id: string;
  owner_id: string;
  provider_id: string;
  tool: string;
  arguments_json: string;
  expires_at: number;
}

function rowToApproval(row: ApprovalRow): Approval {
  let args: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(row.arguments_json) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed))
      args = parsed as Record<string, unknown>;
  } catch {
    args = {};
  }
  return {
    id: row.id,
    userId: row.user_id,
    ownerId: row.owner_id,
    providerId: row.provider_id,
    tool: row.tool,
    arguments: args,
    expiresAt: row.expires_at,
  };
}

export async function createApproval(
  env: Env,
  input: {
    userId: string;
    ownerId: string;
    providerId: string;
    tool: string;
    arguments: Record<string, unknown>;
  },
): Promise<Approval> {
  const now = Math.floor(Date.now() / 1000);
  const id = crypto.randomUUID();
  const approval: Approval = {
    id,
    ...input,
    expiresAt: now + APPROVAL_TTL_SECONDS,
  };
  await env.DB.prepare(
    `INSERT INTO mcp_approvals (id, user_id, owner_id, provider_id, tool, arguments_json, expires_at, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(
      id,
      input.userId,
      input.ownerId,
      input.providerId,
      input.tool,
      JSON.stringify(input.arguments),
      approval.expiresAt,
      now,
    )
    .run();
  return approval;
}

// 確認を1回だけ使う。本人のものだけを取り出して、同時に消す（同じ確認を2回実行できない）。
// 期限切れは、消した上で拒否する。
export async function consumeApproval(
  env: Env,
  id: string,
  userId: string,
): Promise<Approval> {
  const row = await env.DB.prepare(
    "DELETE FROM mcp_approvals WHERE id = ? AND user_id = ? RETURNING *",
  )
    .bind(id, userId)
    .first<ApprovalRow>();
  if (!row)
    throw new McpApprovalError(
      "確認が見つからないか、すでに使われています。もう一度、依頼してください",
    );
  if (row.expires_at <= Math.floor(Date.now() / 1000)) {
    throw new McpApprovalError(
      "確認の期限（5分）が切れました。もう一度、依頼してください",
    );
  }
  return rowToApproval(row);
}

export async function cancelApproval(
  env: Env,
  id: string,
  userId: string,
): Promise<void> {
  await env.DB.prepare("DELETE FROM mcp_approvals WHERE id = ? AND user_id = ?")
    .bind(id, userId)
    .run();
}

// 期限が切れた確認を消す（毎日のメンテナンスで呼ぶ）。
export async function purgeExpiredApprovals(env: Env): Promise<void> {
  await env.DB.prepare("DELETE FROM mcp_approvals WHERE expires_at < ?")
    .bind(Math.floor(Date.now() / 1000))
    .run();
}
