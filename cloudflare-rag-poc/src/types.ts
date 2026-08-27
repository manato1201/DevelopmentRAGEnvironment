// 既存の rag_local_bridge.py（scripts/rag_local_bridge.py）との契約を維持するための型定義。
// docs/cloud-local-unification-plan.md §8.3 を参照。

export interface Env {
  DB: D1Database;
  VEC_SHARED: VectorizeIndex;
  VEC_PERSONAL: VectorizeIndex;
  GEMINI_API_KEY: string;
  EMBEDDING_MODEL: string;
  GENERATION_MODEL: string;
  NOTION_API_KEY: string;
  GOOGLE_SERVICE_ACCOUNT_JSON: string;
  // Claude APIプロキシ用（2026-08-26追加。Houdiniチュートリアル生成エージェント（tutorial_agent.py）が
  // 従来GAS経由で呼んでいたclaude_messagesアクションの移行先。RAG自体はGeminiのまま変更しない）
  ANTHROPIC_API_KEY?: string;
  // ヘルスチェックのアラート通知先（2026-08-26追加）。いずれも未設定なら該当チャンネルへは送らない
  SLACK_WEBHOOK_URL?: string;
  // Gmail送信は個人アカウントのOAuthリフレッシュトークン方式（Domain-Wide Delegationは
  // Google Workspace限定のため、個人のgmail.comアカウントでは使えなかった。src/gmailOAuth.ts参照）
  GMAIL_OAUTH_CLIENT_ID?: string;
  GMAIL_OAUTH_CLIENT_SECRET?: string;
  GMAIL_OAUTH_REFRESH_TOKEN?: string;
  GMAIL_ALERT_TO?: string; // アラートの送信先メールアドレス
}

// POST /search リクエスト（既存契約と同一形式）
export interface SearchRequest {
  query: string;
  limit?: number;
  namespaces?: string[];
  level?: "basic" | "applied" | "advanced" | "";
}

export interface SourceEntry {
  file: string;
  namespace: string;
  difficulty?: string;
  score: number;
  cited?: boolean;
  // 回答文中で [n] が実際に何回参照されたか（同じ出典を繰り返し根拠にした場合ほど大きくなる）。
  // 複数出典を引用した際の「貢献度の比率」表示に使う（2026-08-27追加）。
  citationCount?: number;
}

// POST /search レスポンス（既存契約と同一形式：texts/sources/status）
export interface SearchResponse {
  texts: string[];
  sources: SourceEntry[];
  status: "ok";
}

// POST /query リクエスト（既存 rag_local_bridge.py の /query と同一契約。
// namespacesは2026-08-26追加：個別DBに絞った検索（検索精度向上のため）に対応するための
// 任意フィールド。省略時は従来通り全アクセス可能namespaceを横断検索する）
export interface QueryRequest {
  query: string;
  history?: Array<{ role: string; content: string }>;
  limit?: number;
  level?: "basic" | "applied" | "advanced" | "";
  namespaces?: string[];
}

// POST /query レスポンス（既存契約と同一形式。memoryIdはPOC独自追加、チャットUIの評価ボタン用）
export interface QueryResponse {
  answer: string;
  sources: SourceEntry[];
  status: "ok";
  namespaces: string[];
  extractionRate: number;
  extractionDetail: string;
  memoryId?: number;
}

export interface ErrorResponse {
  error: string;
}

export interface AuthedUser {
  userId: string;
  role: "admin" | "member" | "guest";
  allowedNamespaces: string[]; // 'shared:*' 相当は個別に解決する
}

// Vectorizeに保存するチャンクのメタデータ（namespace/difficultyは既存契約のsourcesへそのまま反映する）
export interface ChunkMetadata {
  file: string;
  namespace: string;
  scope: "shared" | "personal";
  owner_user_id?: string;
  difficulty?: string;
  chunk_index: number;
  text: string;
  // グラフ表示のノード詳細パネル用（2026-08-25追加。それ以前に投入済みのベクトルには無い）
  source?: "notion" | "drive" | "manual";
  size?: number; // ドキュメント全体の文字数
  ingested_at?: number; // 登録時のUnixタイムスタンプ（秒）
}

// 知識ベース同期（Notion/Drive）の結果サマリ（既存GAS syncNotionToSheets/syncDriveToSheetsの戻り値相当）
export interface KbSyncResult {
  status: "ok";
  opId: string;
  documents: number;
  chunks: number;
  skipped: Array<{ file: string; reason: string }>;
}
