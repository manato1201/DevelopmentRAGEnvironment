# レビュー: worker（Cloudflare Worker と、課題タブ・集計）

2026-11-17。担当: `cloudflare-rag-poc/src/`（pilotTasks.ts・chatUi.ts・index.ts）、`cloudflare-rag-poc/test/`、`houdini/python_panels/pilot_panel.py`・`pilot_task.py`、`houdini/tests/`、`docs/pilot/`。

## 1. 確認した範囲

- `pilotTasks.ts` の差分すべて（`ConditionMode`・`assignmentForSlot`・`buildPlan`・`summarizeTasks`・`handlePilotTasks`・`handlePilotConfig`・`handlePilotSessionStart`）。
- `chatUi.ts` の差分すべて（条件の切り替え UI、回答の一覧、事前アンケート、CSV）。`downloadCsv`・`appendRow` も読んだ。
- `index.ts` のルーティング（`/admin/pilot/summary|tasks|config`、`/pilot/*`）。`requireAdmin` は、3 つの管理用ハンドラの先頭にある（`pilotStats.ts` も同じ）。`ForbiddenError` は 403 になる。
- マイグレーション 0035〜0037 と、コードが読む列・表: `pilot_profile`（pid・slot・experience_years・self_level・background・practice・tool_history・created_at）、`pilot_sessions`（started_at・ended_at・paused_sec・discarded_at ほか）、`pilot_config`（key/value。`condition_mode` は新しい行を足すだけ）。**新しい列・表は、マイグレーション無しで読んでいない**（新しいマイグレーションは不要）。
- 応答に `user_id`・キーのハッシュ・氏名は含まれない（`/admin/pilot/tasks` の SQL は `user_id` を選ばず、`pid` を `P01` にして返す）。テストでも確かめている。
- 集計: 0 件・1 件・片方の群が空・同値で、0 割り・NaN・Infinity は出ない（`median` と `cliffsDelta` は空なら null。`comparable` が false の指標は、差と効果量を null にする）。
- `condition_mode` の保存と割り当て: 不正な値は 400。始めた固定課題（終えたものを含む）は、記録された題材と条件のまま（`buildPlan` が、記録を優先）。`/pilot/plan` と `/pilot/session/start` は、同じ `buildPlan(..., config.conditionMode)` を使い、整合している。
- Houdini の課題カード: `format_task_title`・`apply_started` は、新しい項目が無い古い Worker の応答でも落ちない（条件が無ければ、見出しに付けず、何も上書きしない）。パネルは、新しい応答の項目（`conditionMode` など）を読んでいない。デプロイの前後どちらの順でも動く。
- HTML: 管理画面の動的な値は、すべて `appendRow`（`textContent`）か `textContent` で入れている。`innerHTML` は、固定の文字列（`""` と「記録はまだありません」）だけ。`${}`・バッククォート・`</script>` の混入は無い（`ui_syntax.test.mjs`・新しいテストが構文を確かめる）。
- 文書（運営手順書 §6.3・§6.4、設計書 §12）と、実装の食い違い。

## 2. 見つけた不備と、直したこと

1. **CSV の式注入の対策が、全列にかかっていなかった**（重大）。`chatUi.ts` の `pilotCsvText` は、課題の CSV の自由記述の 1 列と、事前アンケートの 4 列だけにかかっていた。題材・条件などの文字列の列は、素通り。また、先頭が空白・改行・全角空白のあとに `=` が来るものは、通っていた。
   - 直した: `pilotCsvText` を、先頭の空白・タブ・改行・全角空白を飛ばした先が `= + - @` のとき、先頭に `'` を付ける形にした（先頭がタブ・CR のものも付ける）。数値は、そのまま（負の数を壊さない）。新しく `pilotCsvRow(cells)` を足し、2 つの CSV（課題・事前アンケート）の**すべての列**に通す。
   - 同じ `downloadCsv` で、CR だけを含むセルが、引用符で囲まれていなかった。正規表現に `\r` を足した（`/[",\\r\\n]/`。テンプレートリテラルの中なので、バックスラッシュは 2 個）。
   - テスト: `test/pilot_admin.test.mjs` に、画面のスクリプトから関数を取り出して、10 通りの悪い入力（`=`・`+`・`-`・`@`・タブ・CR・先頭の空白・改行・全角空白・空白タブ）と、無害な入力 7 通り、数値、null、行全体、2 つの CSV が `pilotCsvRow` を通っていること、を足した。
2. **`/admin/pilot/config` が、片方だけ保存して 400 を返すことがあった**。`openRound` を保存したあとで `conditionMode` を検査していたので、`{ openRound: 2, conditionMode: "both" }` は、受付の回だけ変わって、400 が返った。
   - 直した: `handlePilotConfig` で、すべての値を検査してから、保存する（`pilotTasks.ts`）。
   - テスト: 不正な `conditionMode` と `openRound` の組み合わせで、400 になり、何も変わらないことを足した。
3. **管理画面が、保存に失敗しても「保存しました」と出していた**（回の切り替え・条件の切り替え）。`loadPilotRounds` は、エラーを握りつぶして、トーストだけ出していた。
   - 直した: `loadPilotRounds` が、成功なら true、失敗なら false を返し、2 つの保存ボタンは、成功のときだけ「保存しました」を出す（条件の保存のときは、課題の記録の再読み込みも、成功のときだけ）。

## 3. リファクタリング

- CSV の列の処理を、`pilotCsvRow` にまとめた（各列に `pilotCsvText` を書き並べる形をやめた）。動きは、上の修正のとおり。それ以外は、読みやすく、やり過ぎの前に止めた（広範囲の書き換えは、していない）。

## 4. 直していないもの（理由）

- **「やり直し」で破棄した人は、その時点の割り当てで始め直す**: 仕様（設計書 §12-1・運営手順書 §6.3 に明記）。破棄した記録は、集計に入らないので、混ざらない。
- **条件を切り替えると、群が混ざる**: 仕様。管理画面に、条件ごとの人数と、「比較できない」の表示がある。
- **`/admin/pilot/tasks` の `profiles` に、自由記述（個人情報の可能性）が含まれる**: 管理者だけが見る設計（`requireAdmin`）。管理画面と手順書に、注意を書いてある。
- **`smoke_pilot_panel.py` は、通常の Python では、116 行目（`_sampler.samples >= 1`）で止まる**: hython（実機の `hou`）が要る、前からの制約（この変更の前の行）。この変更に関わる、条件の表示の確認（`［ドキュメントのみ］`）は、その手前（106 行目）で通る。
- `docs/pilot/pilot-analysis-design.md` の改行が、CRLF と LF の混在になっている（別の担当の追記が LF）。コミット時に、autocrlf で揃う。
- `test/pilot_admin.test.mjs` は、新規の未追跡ファイルで、改行は LF（他の担当のファイル。そのまま）。

## 5. テストの結果

- Worker: `npm run typecheck` 通過。`npm test` 34 件すべて通過（`pilot_admin.test.mjs` に、上の追加を含む）。
- Houdini: `unittest discover -s houdini/tests` 759 件すべて通過。
- 文書: `scripts/build_docs_html.py` で `operator-runbook.html` を作り直した。
