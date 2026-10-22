// MCPツールの引数スキーマ → Geminiの関数宣言が受け付ける形への変換（共通層。2026-10-08追加）。
// 別プロジェクトの web/src/features/mcp/core/schema.ts にならう。
//
// MCPのツールは引数をJSON Schema全体で記述するが、Geminiの関数宣言が受け付けるのは小さな
// 部分集合（type / properties / required / items / enum / description）だけ。範囲外のものは、
// 1つのツールのせいで呼び出し全体が拒否されないよう、捨てて近い形に丸める。

const MAX_DEPTH = 4;
const TYPE_NAMES: Record<string, string> = {
  string: "STRING",
  number: "NUMBER",
  integer: "INTEGER",
  boolean: "BOOLEAN",
  array: "ARRAY",
  object: "OBJECT",
};

type Schema = Record<string, unknown>;

function isRecord(value: unknown): value is Schema {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// 一部のサーバー（Google・Vercelなど）は、入れ子の引数を局所参照（"$ref": "#/$defs/Waypoint"）で記述する。
// Geminiの関数宣言には $defs が渡らないため、参照は、指す先のスキーマに置き換える
// （しないと、入れ子のオブジェクトが、ただの文字列として見えてしまう）。循環・外部参照は文字列にする。
// 別プロジェクト（AxChatD）の web/src/features/mcp/core/schema.ts の inlineRefs にならう（2026-10-22追加）。
export function inlineRefs(node: unknown, root: Schema, trail: string[] = []): unknown {
  if (Array.isArray(node)) return node.map((item) => inlineRefs(item, root, trail));
  if (!isRecord(node)) return node;
  const ref = node.$ref;
  if (typeof ref === "string") {
    if (!ref.startsWith("#/") || trail.includes(ref) || trail.length >= 8) return { type: "string" };
    const target = ref
      .slice(2)
      .split("/")
      .reduce<unknown>((current, key) => (isRecord(current) ? current[key.replace(/~1/g, "/").replace(/~0/g, "~")] : undefined), root);
    if (!isRecord(target)) return { type: "string" };
    const { $ref: _ref, ...own } = node;
    return inlineRefs({ ...target, ...own }, root, [...trail, ref]);
  }
  return Object.fromEntries(
    Object.entries(node)
      .filter(([key]) => key !== "$defs" && key !== "definitions")
      .map(([key, value]) => [key, inlineRefs(value, root, trail)]),
  );
}

export function toGeminiSchema(schema: unknown, depth = 0): Schema {
  if (depth === 0 && isRecord(schema)) schema = inlineRefs(schema, schema);
  if (!isRecord(schema) || depth > MAX_DEPTH) return { type: "STRING" };
  const alternatives = [schema.anyOf, schema.oneOf].find(Array.isArray) as unknown[] | undefined;
  if (alternatives) {
    const first = alternatives.find((item) => isRecord(item) && item.type !== "null");
    const chosen = isRecord(first) ? { ...first, description: schema.description ?? first.description } : {};
    return toGeminiSchema(chosen, depth);
  }
  const declared = Array.isArray(schema.type) ? schema.type.find((type) => type !== "null") : schema.type;
  const type =
    typeof declared === "string" && TYPE_NAMES[declared] ? TYPE_NAMES[declared] : isRecord(schema.properties) ? "OBJECT" : "STRING";
  const result: Schema = { type };
  if (typeof schema.description === "string" && schema.description) {
    result.description = schema.description.slice(0, 400);
  }
  if (type === "STRING" && Array.isArray(schema.enum)) {
    const values = schema.enum.filter((value): value is string => typeof value === "string");
    if (values.length) result.enum = values;
  }
  if (type === "ARRAY") result.items = toGeminiSchema(schema.items, depth + 1);
  if (type === "OBJECT") {
    const properties: Schema = {};
    if (isRecord(schema.properties)) {
      for (const [name, child] of Object.entries(schema.properties)) {
        properties[name] = toGeminiSchema(child, depth + 1);
      }
    }
    // プロパティの無いOBJECTは拒否されるため、自由形式のオブジェクトはJSON文字列として受ける。
    if (Object.keys(properties).length === 0) {
      return depth === 0
        ? { type: "OBJECT", properties: { reason: { type: "STRING", description: "呼び出しの理由（任意）" } } }
        : { type: "STRING", description: "JSON形式の文字列" };
    }
    result.properties = properties;
    if (Array.isArray(schema.required)) {
      const required = schema.required.filter((name): name is string => typeof name === "string" && name in properties);
      if (required.length) result.required = required;
    }
  }
  return result;
}

export function hasProperties(schema: unknown): boolean {
  return isRecord(schema) && isRecord(schema.properties) && Object.keys(schema.properties).length > 0;
}
