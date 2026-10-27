-- 実証実験の集計（2026-10-27）: チャットの回答が、どの「説明レベル」で作られたかを記録する。
-- 値: "auto:applied"（おまかせで applied になった）/ "fixed:basic"（利用者が basic を選んだ）/ NULL（説明レベルの指定なし）。
-- 管理画面の「実証実験」で、説明レベルごとの評価（役に立った／立たなかった）を比べるために使う。
ALTER TABLE memory ADD COLUMN explain_level TEXT;
