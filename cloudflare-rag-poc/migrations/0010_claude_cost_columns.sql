-- Claude API使用量・コスト可視化のため、audit_logにinput/output内訳とモデル名を追加する
-- （2026-09-10）。既存のtokens_usedは合計値のみでinput/output比率が分からず、Claudeの
-- 非対称な単価（出力トークンの方が高い）で正確なコスト計算ができなかった。
-- namespace_id = 'claude:proxy' の行（claude.tsのhandleClaudeMessages経由）だけが
-- これらの列を埋める。RAG系のnamespace_idを持つ行は従来通りNULLのまま。
ALTER TABLE audit_log ADD COLUMN input_tokens INTEGER;
ALTER TABLE audit_log ADD COLUMN output_tokens INTEGER;
ALTER TABLE audit_log ADD COLUMN model TEXT;
