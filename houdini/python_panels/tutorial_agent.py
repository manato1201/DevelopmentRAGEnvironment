"""
tutorial_agent.py — houdini21 チュートリアル自動生成オーケストレーター

docs/content-generation.md §2 の設計に基づく:
  ① RAG検索: houdini21 namespace のみから取得（license-compliance のホワイト
     リスト方針。他 namespace は参照しない）。取得先は rag_mode で切り替える:
       - "local": ローカルブリッジ /search（rag_local_bridge.py）
       - "cloud": GAS WebApp（gas_cloud_rag.js）を mode:'raw' で呼び、
         最終回答生成をスキップして検索結果のみ取得する
     どちらのモードでも取得後に db フィールドが houdini21 のものだけに
     絞り込む（GAS側は許可namespaceが無いと "all" に自動フォールバックする
     ため、呼び出し側でも二重にホワイトリストを強制する）
  ② エージェントループ: MODEL 定数のClaudeモデル + HOUDINI_TOOLS（最大MAX_ITERATIONS回）
     プロンプトキャッシュ: システムプロンプト・ツール定義・RAGコンテキストを
     cache_control で固定
     Claude API呼び出しは必ず GAS（gas_cloud_rag.js、action:'claude_messages'）
     経由で行う。生のANTHROPIC_API_KEYはクライアントに持たせず、GASが
     APIキーごとのClaude専用トークン予算（claudeCapacity/claudeBalance）を
     サーバー側で強制する。gas_url/gas_api_key（Settingsタブ、rag_mode=local
     でも共通）が未設定だと生成を開始できない（docs/cloud-rag.md §8.14）
  ③ コスト上限: 累積 COST_LIMIT_USD を超えたら自動打ち切り（usage から実測計算。
     ローカル側の推定値であり、実際の課金上限はGAS側のclaudeCapacityが強制する）
  ④ 生成完了後 NodeGraphAsset JSON をエクスポート
  ⑤ Markdown はプレビュー用に返すだけ。保存は UI 側（ユーザー確認後）

Anthropic SDK には依存せず urllib のみで API を呼ぶ
（Houdini 同梱 Python に追加パッケージを要求しないため）。
"""

from __future__ import annotations

import datetime
import json
import re
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from houdini_tools import HOUDINI_TOOLS, HoudiniToolExecutor

# ─── 定数 ────────────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-5"     # 設計判断（§4.1）。変更はコストが変わるため要ユーザー確認
MAX_ITERATIONS = 40           # 反復上限（§2.6）
COST_LIMIT_USD = 0.50         # 自動打ち切り上限（§2.7）
MAX_TOKENS_PER_TURN = 4096
RAG_NAMESPACES = ["houdini21"]  # 生成機能が参照してよい namespace のホワイトリスト（§5）
RAG_LIMIT = 6
CLOUD_RAG_DB_KEY = "houdini21"  # Cloud RAG（GAS）に問い合わせる際の dbKey

# MODEL の単価（USD / 1M tokens）。コスト上限判定の実測計算に使う。
# claude-sonnet-5 は標準価格が $3/$15（導入価格 $2/$10 は2026-08-31まで、
# 過大評価になるだけで安全側なのでここでは標準価格を採用）
_PRICE = {
    "input": 3.00,
    "output": 15.00,
    "cache_write": 3.75,
    "cache_read": 0.30,
}

_SYSTEM_PROMPT_TEMPLATE = """あなたは Houdini のエキスパートで、初心者向けチュートリアルを作成するエージェントです。
与えられたツールで Houdini のノードグラフを実際に組み立て、動作確認済みのチュートリアルを作成します。

## 絶対ルール
- ノード操作はサンドボックス `{sandbox_path}` 内でのみ行われます。ノードパスは常にサンドボックス相対（例: `geo1/grid1`）で指定してください。
- ノードタイプ名が少しでも不確かな場合は、create_node の前に必ず list_available_node_types で正確な名前を確認してください（例: `mountain` ではなく `mountain::2.0`）。
- SOP を作るには、まずサンドボックス直下に Object カテゴリの `geo` ノードを作成し、その中に SOP ノードを作成します。
- グラフを組み終えたら必ず最終ノードを cook_node で評価し、エラーがあれば修正して再 cook してください。エラーが残ったまま finish_tutorial を呼んではいけません。
- 表示させたい最終ノードには set_parameter 等で手を加える必要はありません（ディスプレイフラグは不要）。

## 進め方
1. リクエストと参考ドキュメントからチュートリアルの構成を決める（3〜8ノード程度の到達可能なスコープに収める）
2. ノードを作成・接続・パラメータ設定する
3. cook_node でエラー確認 → 自己修正
4. エラーゼロを確認したら finish_tutorial を呼ぶ。steps には実際に行った操作を初心者が再現できる粒度で書き、pitfalls には生成中に遭遇したエラーと対処を書く

## 参考ドキュメント（houdini21 ナレッジベース）
{rag_context}"""


# ─── 結果オブジェクト ─────────────────────────────────────────────────────────────

class TutorialResult:
    """generate() の戻り値。UI がプレビュー・保存に使う。"""

    def __init__(self) -> None:
        self.markdown: str = ""
        self.graph: dict = {}
        self.title: str = ""
        self.slug: str = "tutorial"
        self.sandbox_path: str = ""
        self.cost_usd: float = 0.0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cache_write_tokens: int = 0
        self.cache_read_tokens: int = 0
        # GASが返す、このAPIキーの「実際の」Claudeトークン残高/上限（サーバー側で強制される値）。
        # None = 未取得（GASが古い/claudeQuotaを返さなかった）または無制限キー。
        self.claude_balance: int | None = None
        self.claude_capacity: int | None = None
        # 自動回復の間隔（時間）と次回回復予定時刻（ISO文字列）。null = 自動回復オフ
        # （無制限キー、または管理者が回復間隔を設定していない=手動チャージのみ）。
        self.claude_reset_interval_hours: int | None = None
        self.claude_reset_at: str | None = None
        self.iterations: int = 0
        self.completed: bool = False   # finish_tutorial まで到達したか
        self.abort_reason: str = ""    # 打ち切り理由（上限到達など）
        self.sources: list[dict] = []

    def file_basename(self) -> str:
        date = datetime.datetime.now().strftime("%Y%m%d")
        return f"{self.slug}_{date}"

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens + self.output_tokens
            + self.cache_write_tokens + self.cache_read_tokens
        )


# ─── エージェント本体 ─────────────────────────────────────────────────────────────

class TutorialAgent:
    """
    RAG検索 → エージェントループ → Markdown/JSON 組み立て。

    progress_cb(text) で UI に進行状況を通知する（QThread から Signal 発行される）。
    executor_factory はテスト用フック（省略時は HoudiniToolExecutor を生成）。
    """

    def __init__(
        self,
        bridge_port: int = 8766,
        project_dir: str = "",
        rag_mode: str = "local",
        gas_url: str = "",
        gas_api_key: str = "",
        progress_cb: Callable[[str], None] | None = None,
        executor_factory: Callable[..., HoudiniToolExecutor] | None = None,
    ) -> None:
        self._port = bridge_port
        self._project_dir = project_dir
        self._rag_mode = rag_mode if rag_mode in ("local", "cloud") else "local"
        self._gas_url = gas_url
        self._gas_api_key = gas_api_key
        self._progress = progress_cb or (lambda _: None)
        self._executor_factory = executor_factory or HoudiniToolExecutor
        self.executor: HoudiniToolExecutor | None = None  # 生成後もサンドボックス削除用に保持

    # ── 公開 API ────────────────────────────────────────────────────────────────

    def generate(self, topic: str) -> TutorialResult:
        result = TutorialResult()

        # Claude APIは必ずGAS（gas_cloud_rag.js）経由で呼ぶ。生のANTHROPIC_API_KEYを
        # クライアントに持たせない構成にすることで、APIキーごとのトークン上限を
        # クライアント側から迂回できないようにしている（docs/cloud-rag.md §8.14）。
        if not self._gas_url or not self._gas_api_key:
            raise RuntimeError(
                "GAS WebApp URL / APIキーが未設定です。Settingsタブで設定してください"
                "（houdini21チュートリアル生成はClaude APIをGAS経由で呼ぶため必須です）。"
            )

        # ① RAG検索（houdini21 namespace のみ）
        self._progress(f"RAG検索中（houdini21 ナレッジベース / {self._rag_mode}）...")
        rag_texts, result.sources = self._rag_search(topic)
        if rag_texts:
            self._progress(f"参考ドキュメント {len(result.sources)} 件を取得しました")
        else:
            self._progress("参考ドキュメントが取得できませんでした（コンテキストなしで続行）")

        # ② サンドボックス作成
        log_dir = Path(self._project_dir) / "logs" / "tutorial_agent" if self._project_dir else None
        self.executor = self._executor_factory(log_dir=log_dir)
        result.sandbox_path = self.executor.sandbox_path
        self._progress(f"サンドボックス作成: {result.sandbox_path}")

        # ③ エージェントループ
        system_blocks, tools, messages = self._build_initial_prompt(topic, rag_texts)
        try:
            self._run_loop(system_blocks, tools, messages, result)
        finally:
            result.iterations = self._count_iterations()

        # ④ 成果物組み立て（打ち切りでも途中経過を提示する）
        result.graph = self.executor.export_node_graph()
        finish = self.executor.finish_data or {}
        result.completed = self.executor.finish_data is not None
        result.title = finish.get("title") or f"Houdiniチュートリアル: {topic}"
        result.slug = self._sanitize_slug(finish.get("slug", ""), topic)
        result.markdown = self._assemble_markdown(topic, finish, result)

        status = "完了" if result.completed else f"打ち切り（{result.abort_reason}）"
        self._progress(
            f"生成{status}: {result.iterations} イテレーション / ${result.cost_usd:.3f}"
        )
        return result

    def destroy_sandbox(self) -> None:
        if self.executor is not None:
            self.executor.destroy_sandbox()

    # ── RAG検索 ─────────────────────────────────────────────────────────────────

    def _rag_search(self, topic: str) -> tuple[list[str], list[dict]]:
        """rag_mode に応じてローカルブリッジ or GAS（Cloud RAG）から houdini21 namespace の生チャンクを取得する。"""
        if self._rag_mode == "cloud":
            return self._rag_search_cloud(topic)
        return self._rag_search_local(topic)

    def _rag_search_local(self, topic: str) -> tuple[list[str], list[dict]]:
        """ローカルブリッジの /search から houdini21 namespace の生チャンクを取得する。"""
        try:
            body = json.dumps({
                "query": topic,
                "limit": RAG_LIMIT,
                "namespaces": RAG_NAMESPACES,
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"http://localhost:{self._port}/search",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            return data.get("texts", []), data.get("sources", [])
        except Exception as exc:
            self._progress(f"RAG検索エラー（続行します）: {exc}")
            return [], []

    def _rag_search_cloud(self, topic: str) -> tuple[list[str], list[dict]]:
        """
        GAS WebApp を mode:'raw' で呼び、最終回答生成（Gemini呼び出し）をスキップして
        houdini21 namespace の検索結果だけを取得する。

        GAS 側は APIキーに houdini21 の権限がないと dbKey を "all" にフォールバック
        してしまうため、応答の sources を db=="houdini21" のものだけに絞り込むことで
        ホワイトリスト方針（他 namespace は参照しない）をクライアント側でも強制する。
        """
        if not self._gas_url:
            self._progress("Cloud RAG検索エラー: GAS WebApp URLが未設定です（続行します）")
            return [], []
        try:
            body = json.dumps({
                "query": topic,
                "dbKey": CLOUD_RAG_DB_KEY,
                "history": [],
                "apiKey": self._gas_api_key,
                "mode": "raw",
            }, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self._gas_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())

            status = data.get("status", "error")
            if status not in ("ok",):
                self._progress(f"Cloud RAG検索エラー（{status}）。続行します: {data.get('answer', '')}")
                return [], []

            raw_sources = [
                s for s in data.get("sources", [])
                if s.get("db") == CLOUD_RAG_DB_KEY
            ]
            if not raw_sources:
                self._progress(
                    "Cloud RAGにhoudini21のドキュメントが見つかりませんでした"
                    "（APIキーにhoudini21の権限があるか確認してください）"
                )
                return [], []

            texts = [f"検索結果（{len(raw_sources)} 件）:"]
            sources = []
            for i, s in enumerate(raw_sources[:RAG_LIMIT]):
                texts.append(f"\n[{i + 1}] ファイル: {s.get('title', '')}\n{s.get('text', '')}")
                sources.append({"title": s.get("title", ""), "db": s.get("db", ""), "score": s.get("score", 0)})
            return texts, sources
        except Exception as exc:
            self._progress(f"Cloud RAG検索エラー（続行します）: {exc}")
            return [], []

    # ── プロンプト構築 ──────────────────────────────────────────────────────────

    def _build_initial_prompt(
        self, topic: str, rag_texts: list[str]
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """
        システム・ツール・初期メッセージを構築する。
        固定部分（システムプロンプト＝RAGコンテキスト込み・ツール定義）に
        cache_control を付け、2回目以降のターンのコストを抑える（§4.2）。
        """
        rag_context = "\n\n".join(rag_texts) if rag_texts else "（参考ドキュメントなし）"
        system_text = _SYSTEM_PROMPT_TEMPLATE.format(
            sandbox_path=self.executor.sandbox_path,
            rag_context=rag_context,
        )
        system_blocks = [{
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }]

        tools = [dict(t) for t in HOUDINI_TOOLS]
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}

        messages = [{
            "role": "user",
            "content": f"次のトピックのHoudiniチュートリアルを作成してください: {topic}",
        }]
        return system_blocks, tools, messages

    # ── ループ ──────────────────────────────────────────────────────────────────

    def _run_loop(
        self,
        system_blocks: list[dict],
        tools: list[dict],
        messages: list[dict],
        result: TutorialResult,
    ) -> None:
        for iteration in range(1, MAX_ITERATIONS + 1):
            response = self._call_api(system_blocks, tools, messages)
            quota = response.get("claudeQuota")
            if quota:
                result.claude_balance = quota.get("balance")
                result.claude_capacity = quota.get("capacity")
                result.claude_reset_interval_hours = quota.get("resetIntervalHours")
                result.claude_reset_at = quota.get("resetAt")
            usage = response.get("usage", {})
            result.cost_usd += self._usage_cost(usage)
            result.input_tokens += usage.get("input_tokens", 0)
            result.output_tokens += usage.get("output_tokens", 0)
            result.cache_write_tokens += usage.get("cache_creation_input_tokens", 0)
            result.cache_read_tokens += usage.get("cache_read_input_tokens", 0)

            content = response.get("content", [])
            messages.append({"role": "assistant", "content": content})

            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if not tool_uses:
                # テキストのみの応答 = モデルが作業を終えたと判断
                result.abort_reason = "モデルがツールを呼ばず終了しました"
                return

            tool_results = []
            for block in tool_uses:
                name, args = block["name"], block.get("input", {})
                self._progress(f"[{iteration}/{MAX_ITERATIONS}] {name}({self._short(args)})")
                output, is_error = self.executor.execute(name, args)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": output,
                    "is_error": is_error,
                })
            messages.append({"role": "user", "content": tool_results})

            if self.executor.finish_data is not None:
                return  # 正常完了

            if result.cost_usd > COST_LIMIT_USD:
                result.abort_reason = f"コスト上限 ${COST_LIMIT_USD:.2f} 超過"
                self._progress(f"コスト上限に達したため打ち切ります（${result.cost_usd:.3f}）")
                return

        result.abort_reason = f"反復上限 {MAX_ITERATIONS} 回到達"
        self._progress("反復上限に達したため打ち切ります")

    def _call_api(
        self, system_blocks: list[dict],
        tools: list[dict], messages: list[dict],
    ) -> dict:
        """
        Claude Messages API を、GAS WebApp（gas_cloud_rag.js）経由で呼ぶ。

        このHoudiniクライアントは生のANTHROPIC_API_KEYを一切保持しない。実キーは
        GASのスクリプトプロパティにのみ保存され、GAS側がAPIキーごとのClaude専用
        トークン予算（claudeCapacity/claudeBalance）を強制する。クライアント側の
        Settings設定を書き換えても上限を迂回できないようにするための構成
        （docs/cloud-rag.md §8.14参照）。過負荷系リトライはGAS側で行うため、
        ここでは単純に1回呼ぶだけでよい。
        """
        payload = json.dumps({
            "action": "claude_messages",
            "apiKey": self._gas_api_key,
            "model": MODEL,
            "max_tokens": MAX_TOKENS_PER_TURN,
            "system": system_blocks,
            "tools": tools,
            "messages": messages,
            "purpose": "houdini21_tutorial_agent",
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            self._gas_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GAS呼び出しエラー {exc.code}: {detail}") from exc

        status = data.get("status", "error")
        if status == "quota_exceeded":
            raise RuntimeError(
                data.get("error", {}).get("message")
                or "Claudeトークンの利用上限に達しています。管理者にチャージを依頼してください。"
            )
        if status == "rate_limited":
            raise RuntimeError(
                data.get("error", {}).get("message") or "リクエストが多すぎます。しばらく待ってから再試行してください。"
            )
        if status == "auth_error":
            raise RuntimeError(
                data.get("error", {}).get("message") or "認証エラー: GAS APIキーが無効です。Settingsタブを確認してください。"
            )
        if status != "ok":
            raise RuntimeError(data.get("error", {}).get("message") or f"GAS Claudeプロキシエラー: {data}")
        return data

    @staticmethod
    def _usage_cost(usage: dict) -> float:
        return (
            usage.get("input_tokens", 0) * _PRICE["input"]
            + usage.get("output_tokens", 0) * _PRICE["output"]
            + usage.get("cache_creation_input_tokens", 0) * _PRICE["cache_write"]
            + usage.get("cache_read_input_tokens", 0) * _PRICE["cache_read"]
        ) / 1_000_000

    def _count_iterations(self) -> int:
        return len(self.executor.step_log) if self.executor else 0

    @staticmethod
    def _short(args: dict, limit: int = 80) -> str:
        text = json.dumps(args, ensure_ascii=False)
        return text if len(text) <= limit else text[:limit] + "…"

    # ── Markdown 組み立て ───────────────────────────────────────────────────────

    @staticmethod
    def _sanitize_slug(slug: str, topic: str) -> str:
        slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
        if slug:
            return slug[:60]
        # モデルが slug を返さなかった場合はトピックの ASCII 化を試みる
        ascii_topic = unicodedata.normalize("NFKD", topic).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9-]", "-", ascii_topic.lower()).strip("-")
        return slug[:60] or "tutorial"

    def _assemble_markdown(self, topic: str, finish: dict, result: TutorialResult) -> str:
        """
        localRAG/_templates/tutorial.md のフロントマター形式に合わせて組み立てる。
        watchdog（auto_index.py）がそのままインデックス化できる形式。
        """
        today = datetime.date.today()
        expires = today + datetime.timedelta(days=180)

        node_lines = []
        for node in result.graph.get("nodes", []):
            params = ", ".join(f"{k}={v}" for k, v in node.get("params", {}).items())
            suffix = f"  （{params}）" if params else ""
            node_lines.append(f"- `{node['id']}` : {node['kind']}{suffix}")
        edge_lines = [
            f"- `{e['source']}` → `{e['target']}` (in:{e['targetInput']})"
            for e in result.graph.get("edges", [])
        ]

        # "[エラー] " は cook_node の失敗行にのみ付与される接頭辞。cook成功メッセージ
        # 「cook 成功: ...（エラー・警告なし）」にも "エラー" という部分文字列が
        # 含まれるため、これと区別するには "[エラー]" まで含めて判定する必要がある。
        cook_errors = [
            entry for entry in (self.executor.step_log if self.executor else [])
            if entry["tool"] == "cook_node" and "[エラー]" in str(entry["result"])
        ]

        pitfalls = finish.get("pitfalls", "")
        if not pitfalls and cook_errors:
            pitfalls = "\n".join(
                f"- {e['result'].splitlines()[1].strip() if len(e['result'].splitlines()) > 1 else e['result']}"
                for e in cook_errors[:5]
            )

        source_lines = [
            f"- {s.get('title', '')}（{s.get('db', '')}）" for s in result.sources
        ] or ["- （参考ドキュメントなし）"]

        status_note = ""
        if not result.completed:
            status_note = (
                f"\n> **注意:** この生成は途中で打ち切られました（{result.abort_reason}）。"
                "ノード構成は未完成の可能性があります。\n"
            )

        return f"""---
title: {result.title}
namespace: tutorials
status: active
created: {today.isoformat()}
updated: {today.isoformat()}
expires: {expires.isoformat()}
tags: [houdini, ai-generated, houdini21]
rag_indexed: false
---
{status_note}
## 概要

{finish.get("overview", f"リクエスト「{topic}」から自動生成されたチュートリアルです。")}

## 手順

{finish.get("steps", "（打ち切りのため手順は未完成です。下記のノード構成を参照してください）")}

## コード・ノード構成

サンドボックス: `{result.sandbox_path}`

### ノード
{chr(10).join(node_lines) or "- （ノードなし）"}

### 接続
{chr(10).join(edge_lines) or "- （接続なし）"}

ノードグラフ JSON: `{result.file_basename()}.json`（NodeGraphAsset 形式）

## ハマりポイント

{pitfalls or "特になし"}

## 参考

{chr(10).join(source_lines)}

---
*自動生成: model={MODEL} / iterations={result.iterations} / cost=${result.cost_usd:.3f} / sandbox={result.sandbox_path}*
"""
