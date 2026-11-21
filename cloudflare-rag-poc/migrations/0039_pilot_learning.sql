-- 実証実験の「学びの確認」（2026-11-22）。設計: docs/pilot/pilot-analysis-design.md §13
--   目的: 本システムは、生成物を作れるようになるためのものではなく、作られたものを追って、Houdini（DCC ツール）の中身
--         （ノードの組み合わせ・使い方）を理解し、自分の制作に使えるようになるためのもの。それが達成されているかを、統計にする。
--   事前（pilot_profile。実験の最初に 1 回）:
--     goal_pre          … 得たいもの。1 = 完成物を手早く作れるようになること … 5 = Houdini の仕組み（ノードのつながり・原理）を理解すること
--     self_how_pre      … 「ノードのつながりを見て、それぞれが何をしているか説明できる」（1〜5）
--     self_explore_pre  … 「初めて見るノードでも、調べて使い方を判断できる」（1〜5）
--     self_what_pre     … 「Houdini が何をするツールか、人に説明できる」（1〜5）
--     houdini_def_pre   … 「Houdini とは、どんなツールか」を、自分の言葉で（自由記述）
--   事後（pilot_sessions。固定課題の終了時。同じ質問を、事前と同じ形で聞く → 差を見る）:
--     goal_post / self_how / self_explore / self_what / houdini_def … 事前と同じ質問
--     goal_used         … 本システムの使い方。1 = 答え・完成物を出してもらうため … 5 = 作られた中身を追って、仕組みを理解するため
--                         （「公式ドキュメントのみ」の回は、本システムを使わないので聞かない）
--     learned           … 「この時間で、Houdini について、新しく理解できたことがあった」（1〜5）
--     explain_own       … できあがったネットワークから、ノードを 1 つ選び、何をしているか・なぜそのつながりかを、自分の言葉で（自由記述。理解の証拠）
--     fun               … やってみて、何が楽しかったか（自由記述。固定課題・自由課題の両方）
--   すべて任意（答えなくても送れる。空欄は NULL）。
ALTER TABLE pilot_profile ADD COLUMN goal_pre INTEGER;
ALTER TABLE pilot_profile ADD COLUMN self_how_pre INTEGER;
ALTER TABLE pilot_profile ADD COLUMN self_explore_pre INTEGER;
ALTER TABLE pilot_profile ADD COLUMN self_what_pre INTEGER;
ALTER TABLE pilot_profile ADD COLUMN houdini_def_pre TEXT;
ALTER TABLE pilot_sessions ADD COLUMN goal_post INTEGER;
ALTER TABLE pilot_sessions ADD COLUMN goal_used INTEGER;
ALTER TABLE pilot_sessions ADD COLUMN self_how INTEGER;
ALTER TABLE pilot_sessions ADD COLUMN self_explore INTEGER;
ALTER TABLE pilot_sessions ADD COLUMN self_what INTEGER;
ALTER TABLE pilot_sessions ADD COLUMN learned INTEGER;
ALTER TABLE pilot_sessions ADD COLUMN explain_own TEXT;
ALTER TABLE pilot_sessions ADD COLUMN houdini_def TEXT;
ALTER TABLE pilot_sessions ADD COLUMN fun TEXT;
