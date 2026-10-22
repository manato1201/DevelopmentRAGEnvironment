-- チャットから、外部サービスの「書き込み」ツール（作成・更新・削除・送信など）を使うときの、実行前の確認（2026-10-22）。
-- 別プロジェクト（AxChatD）の mcp/core/approval.py にならう。
--
-- 流れ: モデルが書き込みツールを呼ぼうとする → 実行せず、ここに「確認待ち」を1件作って画面に出す
--       → 利用者が「実行」を押す（/mcp/confirm）→ この行を消して（1回だけ）実行する。
-- 引数はサーバー側（この表）に保存し、確認のときは、画面から送られた値ではなく、これを実行する
-- （＝確認した内容と実行する内容が、必ず同じ）。期限は5分。本人以外は使えない。
CREATE TABLE mcp_approvals (
    id TEXT PRIMARY KEY,                    -- 推測できないID（UUID）
    user_id TEXT NOT NULL,                  -- 質問した本人。確認できるのは、この人だけ
    owner_id TEXT NOT NULL DEFAULT '',      -- どの接続で実行するか（本人専用の接続のみ。共有の接続では書き込まない）
    provider_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    arguments_json TEXT NOT NULL,           -- 実行する引数（確認画面にも、これを出す）
    expires_at INTEGER NOT NULL,            -- unix秒
    created_at INTEGER NOT NULL
);
CREATE INDEX idx_mcp_approvals_expires ON mcp_approvals (expires_at);
