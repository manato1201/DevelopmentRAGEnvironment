-- 再帰クロールをバッチ処理化するための一時的な進行状態テーブル（2026-09-13追加）。
-- このアカウントはCloudflare Workers Freeプラン（CPU時間制限が固定・引き上げ不可、
-- driveSync.ts/notionSync.ts参照）のため、1回のクロールを1リクエストで最後まで処理する
-- 実装だと、ページ数が数件を超えたあたりでError 1102（Worker exceeded resource limits）
-- により強制終了するリスクがある。Drive/Notion同期と同じ「1リクエストで少数ページだけ
-- 処理し、続きは次のリクエストで再開する」バッチ方式に作り直すにあたり、BFSキューと
-- 訪問済みURL集合をリクエスト間で持ち越す必要があるため、その状態をここに保存する。
-- クロールが完了（またはエラーで打ち切り）した時点で行は削除する。恒久的な履歴は
-- 従来通りkb_logが担う。
CREATE TABLE crawl_jobs (
  op_id TEXT PRIMARY KEY,
  namespace_id TEXT NOT NULL,
  origin_for_link_filter TEXT NOT NULL,
  path_prefix TEXT,
  exclude_patterns TEXT,
  skip_existing INTEGER NOT NULL DEFAULT 0,
  max_pages INTEGER NOT NULL,
  max_depth INTEGER NOT NULL,
  queue_json TEXT NOT NULL,
  visited_json TEXT NOT NULL,
  processed_count INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
