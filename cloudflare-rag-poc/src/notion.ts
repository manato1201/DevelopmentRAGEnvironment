import type { Env } from "./types";

const NOTION_VERSION = "2022-06-28";

function notionHeaders(env: Env): Record<string, string> {
  return {
    Authorization: `Bearer ${env.NOTION_API_KEY}`,
    "Notion-Version": NOTION_VERSION,
    "content-type": "application/json",
  };
}

export interface NotionPageSummary {
  id: string;
  title: string;
  lastEditedTime: string;
}

// Notionデータベース内の全ページを取得する（既存GAS syncNotionToSheets相当のクエリ部分）。
export async function listNotionPages(
  env: Env,
  databaseId: string,
): Promise<NotionPageSummary[]> {
  const pages: NotionPageSummary[] = [];
  let cursor: string | undefined;

  do {
    const res = await fetch(
      `https://api.notion.com/v1/databases/${databaseId}/query`,
      {
        method: "POST",
        headers: notionHeaders(env),
        body: JSON.stringify(
          cursor
            ? { start_cursor: cursor, page_size: 100 }
            : { page_size: 100 },
        ),
      },
    );
    if (!res.ok) {
      throw new Error(
        `Notion database query APIエラー (${res.status}): ${await res.text()}`,
      );
    }
    const data = (await res.json()) as {
      results: Array<{
        id: string;
        properties: Record<string, unknown>;
        last_edited_time: string;
      }>;
      has_more: boolean;
      next_cursor: string | null;
    };
    for (const page of data.results) {
      pages.push({
        id: page.id,
        title: extractTitle(page.properties),
        lastEditedTime: page.last_edited_time,
      });
    }
    cursor = data.has_more ? (data.next_cursor ?? undefined) : undefined;
  } while (cursor);

  return pages;
}

function extractTitle(properties: Record<string, unknown>): string {
  for (const value of Object.values(properties)) {
    const prop = value as {
      type?: string;
      title?: Array<{ plain_text?: string }>;
    };
    if (prop.type === "title" && Array.isArray(prop.title)) {
      return prop.title.map((t) => t.plain_text ?? "").join("") || "(無題)";
    }
  }
  return "(無題)";
}

// ページ本文（ブロック）を再帰的に取得し、プレーンテキストへ結合する
// （既存GAS extractPageData_相当。ネストしたブロックはdepth段まで辿る）。
// depth=3だと目次付きページ等でネストが深い場合に本文が欠落する実例があったため8に引き上げ
// （2026-08-27）。depthを増やすとネストしたブロックの数だけサブリクエストが増えるため、
// Cloudflareのサブリクエスト数上限に近づく可能性がある点とのトレードオフ。
export async function getPageText(
  env: Env,
  pageId: string,
  depth = 8,
): Promise<string> {
  const lines: string[] = [];
  await collectBlockText(env, pageId, depth, lines);
  return lines.join("\n");
}

async function collectBlockText(
  env: Env,
  blockId: string,
  depth: number,
  lines: string[],
): Promise<void> {
  let cursor: string | undefined;
  do {
    const url = new URL(`https://api.notion.com/v1/blocks/${blockId}/children`);
    url.searchParams.set("page_size", "100");
    if (cursor) url.searchParams.set("start_cursor", cursor);

    const res = await fetch(url.toString(), { headers: notionHeaders(env) });
    if (!res.ok) {
      throw new Error(
        `Notion blocks APIエラー (${res.status}): ${await res.text()}`,
      );
    }
    const data = (await res.json()) as {
      results: Array<{
        id: string;
        type: string;
        has_children: boolean;
        [key: string]: unknown;
      }>;
      has_more: boolean;
      next_cursor: string | null;
    };

    for (const block of data.results) {
      const content = block[block.type] as
        { rich_text?: Array<{ plain_text?: string }> } | undefined;
      if (content?.rich_text && content.rich_text.length > 0) {
        lines.push(content.rich_text.map((t) => t.plain_text ?? "").join(""));
      }
      if (block.has_children && depth > 0) {
        await collectBlockText(env, block.id, depth - 1, lines);
      }
    }
    cursor = data.has_more ? (data.next_cursor ?? undefined) : undefined;
  } while (cursor);
}
