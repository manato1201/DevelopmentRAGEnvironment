// ツールの許可・確認ポリシー（共通層。2026-10-08追加）。AxChatDの mcp/core/permissions.py にならう。
// 「モデルにどのツールを見せるか」と「呼び出しに確認が要るか」を、全サービス共通で
// ここ1か所だけが決める。
//
// read_only の優先順位:
//   provider.blockedTools   -> 一切見せない
//   provider.writeTools     -> false（常に確認）。サーバーが読み取り専用と言っても
//   provider.readOnlyTools  -> true
//   サーバーの readOnlyHint -> ちょうど true のときだけ true
//   それ以外                 -> false。「不明＝書き込みかもしれない」として扱う

import type { McpToolInfo } from "./protocol";
import { McpToolNotAllowed, type McpProvider } from "./providers";

export interface ClassifiedTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  readOnly: boolean;
}

export function classify(
  provider: McpProvider,
  tool: McpToolInfo,
): ClassifiedTool | null {
  if (provider.blockedTools.includes(tool.name)) return null;
  let readOnly: boolean;
  if (provider.writeTools.includes(tool.name)) readOnly = false;
  else if (provider.readOnlyTools.includes(tool.name)) readOnly = true;
  else readOnly = tool.readOnly === true;
  const hint = provider.toolHints[tool.name];
  return {
    name: tool.name,
    description: hint ? `${tool.description} ${hint}`.trim() : tool.description,
    inputSchema: tool.inputSchema,
    readOnly,
  };
}

export function applyPolicy(
  provider: McpProvider,
  tools: McpToolInfo[],
): ClassifiedTool[] {
  return tools
    .map((tool) => classify(provider, tool))
    .filter((tool): tool is ClassifiedTool => tool !== null);
}

// このデプロイで使ってよいツール。enabled が null なら、ポリシーが許す全ツール。
export function offered(
  tools: ClassifiedTool[],
  enabled: string[] | null,
): ClassifiedTool[] {
  return enabled === null
    ? tools
    : tools.filter((tool) => enabled.includes(tool.name));
}

export function requireAllowed(
  tools: ClassifiedTool[],
  enabled: string[] | null,
  name: string,
): ClassifiedTool {
  const found = offered(tools, enabled).find((tool) => tool.name === name);
  if (!found) throw new McpToolNotAllowed(`使えないツールです: ${name}`);
  return found;
}

export function needsConfirmation(tool: ClassifiedTool): boolean {
  return !tool.readOnly;
}
