# 第8回 機能を足す通し演習（「やり直し」を例に、要件から本番まで）

**到達目標:** 1つの機能を、**要件 → 設計の判断 → マイグレーション → 純関数 → ハンドラ → テスト → パネル → 通しの確認 → ドキュメント → 本番**の順に、自分で進められる。各段階で「何を確かめれば、次へ進んでよいか」を言える。
**前提:** 第1〜7回。 **目安:** 5時間（読んで追う2時間 ＋ 自分で足す3時間）

---

## 1. 題材

実際に足した機能です（コミット `62560d8`、`git show 62560d8 --stat` で、変更の全体が見えます）。

> **要望**: 実証実験の「課題」タブで、**間違えて「終了」を押したとき、やり直せない**。また、計測中に**Houdini が落ちたり、処理が重くなったとき**、どうなるのか分からない。

進める前に、**[図12（実験の流れ）](../../images/12-pilot-flow.svg)** と **[図13（課題の状態）](../../images/13-task-states.svg)** を見てください。これが、機能の「地図」です。

[![課題の状態](../../images/13-task-states.svg)](../../images/13-task-states.svg)

## 2. ステップ 1：要件と、設計の判断

要望を、**決めること**に分解します。曖昧なまま作り始めると、あとで作り直しになります。

| 決めること | 選択肢 | 判断と理由 |
|---|---|---|
| 記録を、**消す**か、**残す**か | 物理削除 / `discarded_at`（論理削除） | **残す**。やり直した回数を、分析で使える（学習効果の確認）。集計と「次の課題」の判定からは、外す |
| いつまで、やり直せるか | いつでも / 次の回を始める前まで | **次の回を始めるまで**。回の順序と、対照の割り当てを崩さないため |
| 計測中の記録も破棄できるか | はい / いいえ | **はい**（「計測をやり直す」）。終えた記録と、同じ仕組みで扱う |
| 所要時間に、振り返りに使った時間を含めるか | 含める / 引く | **引く**。作業の時間ではないから |
| Houdini が閉じていた時間は | 含める / 引く（中断） | **引く**。ただし、**落ちずに重かっただけ**の時間は、作業なので引かない |
| 時間は、どの時計で測るか | サーバーの時刻 / パネルの時計 | **パネルが、同じ時計で測った秒数**を送る。PC とサーバーの時計のずれに、左右されない |
| 送信に失敗したら | 答えを捨てる / 残して再送 | **残して再送**。アンケートを、書き直させない |

> 学び: 設計の判断は、**表にして、理由を書く**。あとで「なぜ、こうしたのか」に、答えられる。決めた内容は、設計書（`docs/pilot/pilot-analysis-design.md`）に書く。

## 3. ステップ 2：マイグレーション（表の形）

`cloudflare-rag-poc/migrations/0036_pilot_redo.sql`:

```sql
ALTER TABLE pilot_sessions ADD COLUMN discarded_at INTEGER;
ALTER TABLE pilot_sessions ADD COLUMN paused_sec INTEGER NOT NULL DEFAULT 0;
DROP INDEX idx_pilot_sessions_slot;
CREATE UNIQUE INDEX idx_pilot_sessions_slot ON pilot_sessions(user_id, round, kind) WHERE discarded_at IS NULL;
```

確かめること:
- 列は `ADD COLUMN`（既存の行は、そのまま）。`NOT NULL` なので **`DEFAULT 0` が要る**。
- 「同じ（人・回・種類）の記録は1つ」の索引を、**破棄していない行だけ**に変える（第3回 2.4）。そうしないと、やり直した記録（2行目）が、入れられない。
- **既存の `0035` は、直さない。**

## 4. ステップ 3：純関数（ルールを、テストしやすく）

`src/pilotTasks.ts`:

```ts
export function buildHistory(sessions: PlanSession[]): HistoryItem[] {
  const lastRound = Math.max(0, ...sessions.map((s) => s.round));
  return sessions.filter((s) => s.id).map((s) => ({
    sessionId: s.id as string, round: s.round, kind: s.kind,
    label: …, running: s.ended_at == null, durationSec: s.duration_sec ?? null,
    redoable: s.round >= lastRound,       // ← 「次の回を始める前」= 最後の回のうち
  })).sort(…);
}
```

「やり直せるか」の**ルール**を、1か所（`redoable`）に置いています。ハンドラ側（`handlePilotSessionReset`）は、同じルールを、SQL（`round > ?` の件数が 0 か）で確かめます。**画面の表示（`redoable`）と、サーバーの判定は、別々に実装**されます。**サーバーの判定が、本当の関門**で、画面は、親切のための表示です。

## 5. ステップ 4：ハンドラと、ルート

```ts
export async function handlePilotSessionReset(req, env, user) {
  const body = await readBody(req);
  const id = typeof body.sessionId === "string" ? body.sessionId : "";
  const row = id ? await env.DB.prepare("SELECT user_id, round, discarded_at FROM pilot_sessions WHERE id = ?").bind(id).first() : null;
  if (!row || row.user_id !== user.userId || row.discarded_at != null)
    return jsonResponse(404, { error: "課題の記録が見つかりません" });          // 他人のもの・破棄済みは「無い」
  const later = await env.DB.prepare("SELECT COUNT(*) AS n FROM pilot_sessions WHERE user_id = ? AND discarded_at IS NULL AND round > ?")
    .bind(user.userId, row.round).first();
  if ((later?.n ?? 0) > 0) return jsonResponse(409, { error: "次の回を始めたあとは、前の回はやり直せません。…" });
  await env.DB.prepare("UPDATE pilot_sessions SET discarded_at = ? WHERE id = ?").bind(Math.floor(Date.now() / 1000), id).run();
  return planResponse(env, user.userId);      // 更新後の「次の課題」と記録を返す（画面が、そのまま描ける）
}
```

`src/index.ts` に、import と `case "/pilot/session/reset": return await handlePilotSessionReset(req, env, user);` を足す。**これを忘れると、404**。

終了のハンドラ（`handlePilotSessionEnd`）には、`surveySec`・`pausedSec` を足して、**範囲に丸めて**使う。

```ts
const endedAt = Math.max(row.started_at, now - clampInt(body.surveySec, 0, 0, 86400));
const pausedSec = Math.min(clampInt(body.pausedSec, 0, 0, 604800), endedAt - row.started_at);
// 所要時間 = endedAt − started_at − pausedSec  （異常な値でも、負にならない）
```

## 6. ステップ 5：テスト（サーバー）

`test/pilot_tasks.test.mjs` に足した主なもの（読んで、**何を確かめているか**を、1行ずつ言う）:

- 計測中の記録を破棄 → 新しい記録で、始め直せる（`resumed === false`）。破棄済みは終えられない（404）。二重の破棄は 404。他人の記録は 404。**破棄した行は、D1 に残っている**（件数が 2）。
- 終えた記録を、次の回の前に取り消せる（`round` が 1 に戻る）。**第2回を始めたあとは、第1回は 409**。
- 所要時間: 3600 秒前に開始 → `surveySec: 300`・`pausedSec: 600` → 約 2700 秒。異常な値（99999）でも 0 秒（負にならない）。
- 集計: 破棄した記録は入らず、`redoCount` で回数が分かる。

実行: `cd cloudflare-rag-poc; npm run typecheck; npm test`。

## 7. ステップ 6：パネル（Houdini）

1. **通信**: `rag_client.py` に `pilot_session_reset(session_id)`（`/pilot/session/reset` を POST）。
2. **画面に依存しない部品**（`pilot_task.py`）: `ProgressStore`（途中経過の保存）・`resume_state`（中断の計算）・`format_history_line`・`build_end_payload` の `paused_sec`。→ **単体テスト**（`test_pilot_task.py`）を先に書く。
3. **画面**（`pilot_panel.py`）: 「計測をやり直す」ボタン・「完了した記録」の「やり直す」・`_pending_end`（送信の失敗を残す）・`_on_sample`（採取のたびに、途中経過を保存）。
4. **配置の一覧**（`deploy_panels.py` の `MODULES`）に、新しいモジュールがあれば足す（今回は既存）。

## 8. ステップ 7：通しの確認（hython）

`houdini/tests/smoke_pilot_panel.py` に、次を足して、`hython` で動かす。

- 確認で「いいえ」→ 何も起きない／「はい」→ 破棄 → 最初から始められる
- 送信の失敗 → 答えが残る → 「答えを再送する」で、同じ内容が送られる（`surveySec` が増えている）
- 完了した記録の「やり直す」→ 同じ課題を、また始められる
- 再開（`resumed: true`）→ 途中経過のエラーのノードを引き継ぎ、閉じていた時間（約300秒）が `pausedSec` に入る

## 9. ステップ 8：ドキュメントと、図

- 設計書（`docs/pilot/pilot-analysis-design.md`）の「計測の扱い」。利用者向け（`user-manual.md` §9.5）。運営者向け（`operator-runbook.md` §6.1・`cloudflare-rag-operations-manual.md` §8-4）。
- 図: 課題の状態（[図13](../../images/13-task-states.svg)）。`scripts/build_diagrams_lecture.py` の `task_states()` を直して、`uv run python scripts/build_diagrams.py states`。

## 10. ステップ 9：本番に出す（[図16](../../images/16-change-flow.svg)）

[![変更から本番まで](../../images/16-change-flow.svg)](../../images/16-change-flow.svg)

1. 型検査・テスト・通しの確認が通る。
2. **D1 にマイグレーションを適用**（本番）。**一覧 → 中身を読む → 適用 → 一覧**。
3. **Worker をデプロイ**。
4. **疎通を確かめる**: 鍵なしで新しい API を呼び、**401**（404 なら、Worker が古い）。D1 に、新しい列があること。
5. **パネルを配置**（`deploy_panels.py`）→ Houdini を再起動。
6. ドキュメントを直し、**コミット・プッシュ**。

> 順序の理由: **D1 → Worker → パネル**。逆にすると、新しい Worker が無い列を読んで失敗し、新しいパネルが、まだ無い API を呼んで 404 になる。**実際に、この順序を逆にして、「課題」タブが「未対応」になった**（[第10回](10-troubleshooting.md)）。

## 11. 演習

**演習 8.1（追う）** `git show 62560d8 --stat` で変更されたファイルの一覧を見て、**ステップ 1〜9 のどれか**を、ファイルごとに対応づけてください。

**演習 8.2（読む）** `handlePilotSessionReset` の **404 と 409 の分岐**について、「他人の記録を指定したとき」「破棄済みを、もう一度指定したとき」「第2回を始めたあとに、第1回を指定したとき」の応答を、答えてください。テストで確かめてください。

**演習 8.3（足す・小）** 破棄の回数を、プレイヤー（参加者）の画面にも出したい、という要望が来ました。**設計の判断の表**を、自分で作ってください（出すか・誰に・何を出すか・個人が特定されないか）。**コードは書かなくてよい**。

**演習 8.4（足す・中）** 管理者向けに、`POST /admin/pilot/redos`（参加者番号ごとに、破棄した記録の数を返す）を足してください。ステップ 3〜6 の順で（純関数 → ハンドラ → ルート → テスト）。**マイグレーションは不要**（既存の `discarded_at` を使う）。型検査・テストが通ったら、**元に戻す**（演習なので、コミットしない）。

**演習 8.5（総合）** 「課題後アンケートに、自由記述の文字数の上限を、画面にも出す」変更を、**要件 → 設計の判断（表）→ 実装 → テスト → ドキュメント**の順で、計画だけ書いてください（1ページ）。どの層（Worker・パネル・画面）のどのファイルを変えるか、どのテストを足すかを、挙げること。

## 12. つまずきやすい点

- **サーバーの判定を、画面の表示に任せる。** 画面（`redoable`）は、親切のための表示。**本当の関門は、サーバー**。
- **マイグレーションを、あとから直す。** 適用済みの環境には効かない。新しいファイルで直す。
- **順序を逆にして、本番に出す。** D1 → Worker → パネルの順。
- **テストを、最後にまとめて書く。** 純関数のテストは、**先に書く**と、設計が締まる（失敗することを確かめてから、実装する）。

## 13. 確認問題

1. 記録を「消さず」に、`discarded_at` を入れた理由は？
2. 「画面の `redoable`」と「サーバーの判定」を、両方持つ理由は？
3. `surveySec` と `pausedSec` を、パネルの秒数で送る理由は？
4. 本番に出す順序は？ 逆にすると、何が起きるか？
5. 設計の判断を、表にして残す利点は？

## 解答の方針

- 8.2: 他人の記録 → 404。破棄済みの再指定 → 404。次の回を始めたあとの前の回 → 409。
- 8.3: 参加者本人に出すのは問題ないが、**他人と比べる表示にしない**。運営の集計は、番号（P01）だけで出す。
- 確認問題 3: PC とサーバーの時計がずれていても、結果が狂わないため（同じ時計の差だけを使う）。
