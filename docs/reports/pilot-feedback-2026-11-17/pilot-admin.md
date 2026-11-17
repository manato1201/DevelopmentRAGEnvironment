# pilot-admin（前と後の差）

## 項目ごとの差

### アンケートが送信されたが、Cloudflare 側だと、自由記述の内容が見れない／計測時間などの取ったパラメータも確認できるように
- **前**:
  - D1（`pilot_sessions`）には、自由記述（`comment`）・アンケート 6 項目・到達・cook エラー・自己申告のミス・所要・中断（`paused_sec`）・質問数・開始/終了の時刻（`started_at`/`ended_at`）が、すべて入っていた（`handlePilotSessionEnd`）。
  - `POST /admin/pilot/tasks`（`handlePilotTasks`）は、自由記述と各項目を返していたが、**開始・終了の時刻と中断（`paused_sec`）は、SELECT していなかった**。
  - 管理画面（`chatUi.ts` の `loadPilotTasks`）は、中央値の表と比較の表だけで、**1 件ずつの回答の表が無く、自由記述は画面のどこにも出ていなかった**（CSV にだけ入っていた）。CSV にも、開始・終了の時刻と中断は無かった。
  - 事前アンケート（`pilot_profile` の経歴・練習・ツール経験の自由記述）は、API にも画面にも出ていなかった。
  - 確認した根拠: `pilotTasks.ts` の SELECT 列、`chatUi.ts` の `pilotTaskGroups`/`pilotCompared` だけを埋めるコード、既存テスト（`pilot_tasks.test.mjs`）に行の時刻の検査が無いこと。
- **後**:
  - `/admin/pilot/tasks` に、`startedAt`・`endedAt`・`pausedSec`・`pausedMin` を足し、`profiles`（事前アンケート。番号 P01 で出し、氏名・ユーザー ID は出さない）を足した。いずれも `requireAdmin` の経路だけ。
  - 管理画面に「回答の一覧（アンケートと計測した値）」の表を足した（参加者、回、種類、題材、条件、開始、終了、所要、中断、質問数、cook エラー、自己申告ミス、到達、アンケート 6 項目、やり直し、自由記述）。事前アンケートの表も足した。
  - CSV: 課題ごとのCSVに、開始・終了・中断の列を足した。「回答の一覧のCSV」「事前アンケートのCSV」のボタンを足した。自由記述は、先頭が `= + - @` のとき `'` を付けて、表計算ソフトで式として実行されないようにした。
  - XSS: 表は `appendRow`（`textContent`）で入れる。テストで、回答の一覧を作る部分に、動的な `innerHTML` 連結が無いことを確かめた（自由記述に `<img onerror>` を入れても、文字としてそのまま返る）。
  - 変更したファイル: `cloudflare-rag-poc/src/pilotTasks.ts`、`cloudflare-rag-poc/src/chatUi.ts`。
  - 確認した根拠: `test/pilot_admin.test.mjs`（行の時刻・中断・各項目、自由記述の返却、事前アンケート、氏名・ID が出ないこと、会員が読めないこと、画面の要素とスクリプトの構文）。
- **状態**: 完了（本番には未反映。デプロイ・画面での目視は、ユーザーが行う）

### 課題タブの内容を修正（ドキュメントなのか、ツール使用なのかを選択できるようにする。今回はツール使用で行う）
- **前**: 条件は、参加者番号から機械的に決まっていた（`assignmentForSlot`。slot 1〜3 = 本システム、4〜6 = ドキュメントのみ）。運営が切り替える手段は無かった。テストでも、`assignmentForSlot(4)` が `docs_only` になることを確認（変更前に、新しいテストが、「全員ツール使用」の期待で失敗することを確認）。
- **後**:
  - `pilot_config` のキー `condition_mode`（`auto`／`system`／`docs_only`）を足した。**既定は `auto`**（無い・不正な値も `auto`）。**新しいマイグレーションは不要**（キー・値の表なので）。
  - `assignmentForSlot(slot, mode)`・`buildPlan(slot, sessions, openRound, mode)`: モードが `system`／`docs_only` のときは、題材は番号のまま、条件だけをそろえる。**すでに固定課題を始めた人（終えたものを含む）は、記録の題材と条件のまま**（`buildPlan` が、記録の `task_id`・`condition` を使う）。自由課題は、いつも本システム。
  - `/pilot/plan` と `/pilot/session/start` は、この設定を反映する。`POST /admin/pilot/config { conditionMode }`（管理者だけ。不正な値は 400 で、何も変えない）。返事に `conditionMode` と、始めた固定課題の条件ごとの人数 `conditionCounts` を足した。
  - 管理画面: 「受け付ける回の切り替え」の下に、「課題の条件の割り当て」（自動／全員ツール使用／全員ドキュメントのみ）と保存ボタン（確認つき）、いまの割り当てと条件ごとの人数の表示を足した。
  - Houdini: 課題カードの見出しに、サーバーの条件を「［ツール使用］／［ドキュメントのみ］」と出す（`format_task_title`）。条件の説明文は「【条件: ツール使用】…使って行ってください」「【条件: ドキュメントのみ】…使わないでください」に変え、色も分けた（緑／黄）。課題を始めたときに返った条件で、手元の plan も更新する（`apply_started`。運営が途中で切り替えたあとも、古い表示が残らない）。
  - 変更したファイル: `pilotTasks.ts`、`chatUi.ts`、`houdini/python_panels/pilot_task.py`、`pilot_panel.py`。
  - 確認した根拠: `pilot_admin.test.mjs`（切り替え・不正値・会員の拒否・始めた課題が変わらないこと・再開で条件が変わらないこと・保存された条件が実際に使った条件であること・自動に戻すこと）、`test_pilot_task.py` の 3 件。
- **状態**: 完了（既定は自動のまま。本番での切り替えは、ユーザーが管理画面で行う）

### 比較の集計: 条件が混ざらない場合は「比較できない」
- **前**: `summarizeTasks` の `compared` は、片方の群が 0 件のとき、差と効果量は null になるが、画面は「-」が並ぶだけで、理由が分からなかった（全員ツール使用にすると、ほぼ全部の欄が「-」）。
- **後**: `comparison { comparable, nSystem, nDocs, reason }` と、指標ごとの `comparable` を足した。片方が 0 件なら、差・効果量は出さず、画面に「比較できない: 固定課題がすべて「ツール使用」です（ドキュメントのみの記録が 0 件）…」と出し、表の差・効果量の欄も「比較できない」にした。自由課題は、比較に入れない。
- 確認した根拠: `pilot_admin.test.mjs`（ツールだけ・ドキュメントだけ・0 件・両方あり・自由課題だけが混ざる・指標ごとに片方の値が空）。
- **状態**: 完了

### 設計書・運営手順書への反映
- `docs/pilot/operator-runbook.md`（§6.3 条件の割り当ての切り替え、§6.4 回答を見る。§6.1 の admin の説明に注記）と、`operator-runbook.html`（再生成）。`docs/pilot/pilot-analysis-design.md` に §12 を足した（割り当ての切り替え・比較できない場合の扱い・回答の一覧・これまで見えなかった理由）。
- **状態**: 完了

## 変更したファイル
- `cloudflare-rag-poc/src/pilotTasks.ts`: 条件モード、`buildPlan` の固定、比較の `comparable`、回答の行に時刻・中断、`profiles`、config の `conditionMode`・`conditionCounts`
- `cloudflare-rag-poc/src/chatUi.ts`: 回答の一覧・事前アンケートの表と CSV、条件の切り替え、「比較できない」の表示
- `cloudflare-rag-poc/test/pilot_admin.test.mjs`: 新規（上記の再現・確認のテスト）
- `houdini/python_panels/pilot_task.py`: 条件の文言、`format_task_title`、`apply_started`
- `houdini/python_panels/pilot_panel.py`: 見出し・色・始めたときの plan 更新
- `houdini/tests/test_pilot_task.py`: 3 件追加
- `houdini/tests/smoke_pilot_panel.py`: 条件の表示の検査を 1 行追加（hython が要るため、ここでは未実行）
- `docs/pilot/operator-runbook.md`・`.html`、`docs/pilot/pilot-analysis-design.md`
- マイグレーションは、足していない（`ls cloudflare-rag-poc/migrations` の最新は 0037。`condition_mode` は、既存の `pilot_config` に入れるため不要）

## テスト
- `cd cloudflare-rag-poc && npm run typecheck`: エラーなし
- `npm test`: 34 件が通る（既存 33 + 新規 `pilot_admin.test.mjs` 1 ファイル）
- `PYTHONIOENCODING=utf-8 uv run --with PySide6 python -m unittest discover -s houdini/tests`: 470 件が通る（既存 467 + 3）
- `smoke_pilot_panel.py` は、`hou` が要る（採取の検査）ため、この環境では最後まで動かない。条件の表示を検査する新しい行までは、通った（その後の `_sampler.samples >= 1` は、hou 無しでは元から通らない）。

## 未対応・要確認（ユーザーの判断・実機確認が要るもの）
- 本番の反映: Worker のデプロイ後、管理画面で「全員ツール使用」に切り替える（既定は自動のまま）。画面の目視（回答の一覧の見え方、横幅 1500px のスクロール）は、実機で確認してください。
- すでに「ドキュメントのみ」で固定課題を始めた人は、そのまま続く（仕様）。全員ツール使用にしたい場合は、その人が「計測をやり直す」で破棄するか、そのまま対照として残すかを、運営が決める。
- 「やり直す」で破棄した人は、その時点のモードで割り当て直す（私の判断。元の条件に固定する案もあるが、運営が切り替えた意図を優先した）。
- 運営（管理者）のテストの記録は、元からの仕様で、一覧・集計に出ない。アンケートを管理者のアカウントで送った場合は、画面には出ない（D1 には入っている）。
- 始めたまま終えていない記録（途中で閉じた）は、回答の一覧には出ない（アンケートは、終了時に送るため、まだ無い）。
- 全員同じ条件にすると、群の間の比較ができない（設計書 §12-2）。報告での扱い（記述に徹する）は、ユーザーの判断。
