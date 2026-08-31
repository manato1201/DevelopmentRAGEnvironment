import type { Env } from "./types";
import { sendSlackAlert } from "./alerts";

// 知識ベース同期（Drive/Notion）は1バッチ=1リクエストのポーリング方式で、クライアントが
// nextIndexを辿って完了まで何度も呼び出す（driveSync.ts/notionSync.ts参照）。ユーザーが
// ブラウザタブを開いたまま完了を待つ必要をなくすため、最後のバッチ（nextIndex===null）で
// kb_logからopId全体の集計を取り、既存のSlack Webhook（alerts.ts、未設定なら何もしない）へ
// 完了通知を送る（2026-08-31）。
//
// サーバー側は1リクエストごとの状態しか持たないため、累計件数はkb_logから都度集計する
// （idx_kb_log_opでインデックス済みなので、この集計自体はop_id単位で軽量）。
export async function notifySyncComplete(
  env: Env,
  opId: string,
  namespace: string,
  source: "drive" | "notion",
): Promise<void> {
  if (!env.SLACK_WEBHOOK_URL) return; // Slack未設定の環境では何もしない（既存のsendSlackAlertと同じ方針）

  const counts = await env.DB.prepare(
    "SELECT status, COUNT(*) as n FROM kb_log WHERE op_id = ? GROUP BY status",
  )
    .bind(opId)
    .all<{ status: string; n: number }>();

  const byStatus = new Map((counts.results ?? []).map((r) => [r.status, r.n]));
  const ok = byStatus.get("ok") ?? 0;
  const skipped = byStatus.get("skipped") ?? 0;
  const error = byStatus.get("error") ?? 0;
  const sourceLabel = source === "drive" ? "Drive" : "Notion";

  const text =
    `📚 知識ベース同期が完了しました（${sourceLabel} / namespace: ${namespace}）\n` +
    `登録 ${ok}件 ／ スキップ ${skipped}件 ／ エラー ${error}件`;

  try {
    await sendSlackAlert(env, text);
  } catch {
    // 通知の送信失敗で同期そのものの完了レスポンスを失敗扱いにはしない（ベストエフォート）
  }
}
