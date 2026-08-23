// 既存の rag_local_bridge.py（scripts/rag_local_bridge.py）との契約を維持するための型定義。
// docs/cloud-local-unification-plan.md §8.3 を参照。

export interface Env {
  DB: D1Database;
  VEC_SHARED: VectorizeIndex;
  VEC_PERSONAL: VectorizeIndex;
  GEMINI_API_KEY: string;
  EMBEDDING_MODEL: string;
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
}

// POST /search レスポンス（既存契約と同一形式：texts/sources/status）
export interface SearchResponse {
  texts: string[];
  sources: SourceEntry[];
  status: "ok";
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
}
