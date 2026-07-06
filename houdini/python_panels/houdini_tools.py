"""
houdini_tools.py — houdini21 チュートリアル生成用 hou モジュールラッパー

tutorial_agent.py のエージェントループから呼ばれるツール群。
Anthropic tool-use 形式のスキーマ（HOUDINI_TOOLS）と、それを実行する
HoudiniToolExecutor を提供する。

安全設計（docs/content-generation.md §2.6）:
  ・全ノード操作は /obj/ai_tutorial_<timestamp> サンドボックスサブネット内に限定
  ・サンドボックス外パスの指定は実行前に拒否し、監査ログに記録
  ・全ツール呼び出しを JSONL 監査ログ（logs/tutorial_agent/）に追記
  ・hou 操作は hdefereval で Houdini メインスレッドにディスパッチ
    （QThread から呼んでもクラッシュしない）

このモジュール自体は import 時に hou を要求しない（テスト用に差し替え可能）。
"""

from __future__ import annotations

import datetime
import json
import re
import threading
from pathlib import Path
from typing import Any, Callable


# ─── Anthropic tool-use スキーマ ─────────────────────────────────────────────────
# ツール定義はエージェントループの固定部分としてプロンプトキャッシュされるため、
# description は多少長くても2回目以降のコストにはほぼ影響しない。

HOUDINI_TOOLS: list[dict] = [
    {
        "name": "create_node",
        "description": (
            "サンドボックスサブネット内に新しいノードを作成する。"
            "node_type はカテゴリ内での正確なタイプ名（例: 'grid', 'mountain::2.0'）。"
            "タイプ名が不確かな場合は必ず先に list_available_node_types で確認すること。"
            "parent を省略するとサンドボックス直下に作成される。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_type": {
                    "type": "string",
                    "description": "作成するノードのタイプ名（例: 'grid', 'copytopoints::2.0'）",
                },
                "name": {
                    "type": "string",
                    "description": "ノード名（省略時は自動命名）。英数字とアンダースコアのみ",
                },
                "parent": {
                    "type": "string",
                    "description": "親ノードのサンドボックス相対パス（省略時はサンドボックス直下）",
                },
            },
            "required": ["node_type"],
        },
    },
    {
        "name": "set_parameter",
        "description": (
            "ノードのパラメータに値を設定する。parm は Houdini 内部パラメータ名"
            "（例: 'tx', 'scale', 'rows'）。タプルパラメータ（例: 't', 'size'）に対しては "
            "value に空白区切り文字列（例: '0 1 0'）を渡すと各成分に展開される。"
            "パラメータ名が不明な場合は get_node_info で確認できる。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "対象ノードのサンドボックス相対パス（例: 'grid1'）",
                },
                "parm": {
                    "type": "string",
                    "description": "パラメータの内部名",
                },
                "value": {
                    "type": ["string", "number", "boolean"],
                    "description": "設定する値。タプルには空白区切り文字列",
                },
            },
            "required": ["node", "parm", "value"],
        },
    },
    {
        "name": "connect_nodes",
        "description": "2つのノードを接続する（from_node の出力 → to_node の入力）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_node": {
                    "type": "string",
                    "description": "接続元ノードのサンドボックス相対パス",
                },
                "to_node": {
                    "type": "string",
                    "description": "接続先ノードのサンドボックス相対パス",
                },
                "input_index": {
                    "type": "integer",
                    "description": "接続先の入力インデックス（デフォルト 0）",
                },
                "output_index": {
                    "type": "integer",
                    "description": "接続元の出力インデックス（デフォルト 0）",
                },
            },
            "required": ["from_node", "to_node"],
        },
    },
    {
        "name": "cook_node",
        "description": (
            "ノードを強制的に cook（評価）してエラーと警告を取得する。"
            "グラフを組み終えたら必ず最終ノードを cook し、エラーがあれば修正して再度 cook すること。"
            "エラーが空になるまで finish_tutorial を呼んではならない。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "cook するノードのサンドボックス相対パス",
                },
            },
            "required": ["node"],
        },
    },
    {
        "name": "list_available_node_types",
        "description": (
            "指定カテゴリで利用可能なノードタイプを検索する。"
            "Houdini のノードタイプ名はバージョン依存（例: 'mountain' は存在せず 'mountain::2.0'）"
            "のため、create_node の前に正確な名前をこのツールで確認すること。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "ノードカテゴリ: 'Sop' | 'Object' | 'Dop' | 'Vop' | 'Cop2' | 'Top'",
                },
                "filter": {
                    "type": "string",
                    "description": "タイプ名・説明に含まれる文字列で絞り込み（例: 'noise'）",
                },
            },
            "required": ["category"],
        },
    },
    {
        "name": "get_node_info",
        "description": (
            "既存ノードの状態（タイプ・デフォルト値から変更されたパラメータ・入出力接続・"
            "エラー/警告・利用可能なパラメータ名一覧）を取得する。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "対象ノードのサンドボックス相対パス",
                },
            },
            "required": ["node"],
        },
    },
    {
        "name": "delete_node",
        "description": "不要になったノードをサンドボックス内から削除する。",
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "削除するノードのサンドボックス相対パス",
                },
            },
            "required": ["node"],
        },
    },
    {
        "name": "finish_tutorial",
        "description": (
            "チュートリアル生成を完了する。最終ノードの cook がエラーなしで通ってから呼ぶこと。"
            "steps / pitfalls は Markdown 形式で記述する（見出しレベルは ### 以下を使用）。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "チュートリアルのタイトル（日本語）",
                },
                "slug": {
                    "type": "string",
                    "description": "ファイル名用スラッグ（英小文字・数字・ハイフンのみ。例: 'rock-scatter-basic'）",
                },
                "overview": {
                    "type": "string",
                    "description": "概要（何を作るか・学べること。2〜4文）",
                },
                "steps": {
                    "type": "string",
                    "description": "手順の Markdown。実際に実行したノード作成・パラメータ設定を番号付きで解説",
                },
                "pitfalls": {
                    "type": "string",
                    "description": "ハマりポイントの Markdown。生成中に遭遇した cook エラーと対処を含める",
                },
            },
            "required": ["title", "slug", "overview", "steps"],
        },
    },
]


# ─── メインスレッドディスパッチ ─────────────────────────────────────────────────

def _run_in_main_thread(fn: Callable[[], Any]) -> Any:
    """
    hou 操作を Houdini のメインスレッドで実行する。
    hou のノード操作は UI スレッド以外から呼ぶと不安定なため、
    QThread（TutorialWorker）から呼ばれる場合は hdefereval 経由でディスパッチする。
    hdefereval が無い環境（テスト・スタンドアロン）ではそのまま実行する。
    """
    try:
        import hdefereval
        return hdefereval.executeInMainThreadWithResult(fn)
    except ImportError:
        return fn()


def _json_safe(value) -> Any:
    """パラメータ値を JSON 化可能な型に変換する（hou.Ramp 等は文字列化）。"""
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


# ─── ツール実行エンジン ─────────────────────────────────────────────────────────

class SandboxViolation(Exception):
    """サンドボックス外のノードパスが指定されたときに送出される。"""


class HoudiniToolExecutor:
    """
    HOUDINI_TOOLS の実行エンジン。

    サンドボックス保証:
      ・コンストラクタで /obj 直下に ai_tutorial_<timestamp> サブネットを作成
      ・全ツールのノードパスは _resolve() でサンドボックス内に解決され、
        外を指すパス（絶対パス・'..' を含むパス）は SandboxViolation として拒否
      ・拒否を含む全呼び出しが JSONL 監査ログに残る（安全性の事後検証用）

    hou_module 引数はテスト用のフック。省略時は import hou する。
    """

    SANDBOX_PREFIX = "ai_tutorial_"

    def __init__(self, log_dir: Path | None = None, hou_module=None) -> None:
        if hou_module is None:
            import hou as hou_module  # Houdini 内でのみ成功する
        self._hou = hou_module

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._sandbox_name = f"{self.SANDBOX_PREFIX}{timestamp}"
        self._sandbox = _run_in_main_thread(self._create_sandbox)
        self.sandbox_path: str = self._sandbox.path()

        self.finish_data: dict | None = None  # finish_tutorial の入力を保持
        self.step_log: list[dict] = []        # Markdown 組み立て用の全呼び出し履歴
        self._lock = threading.Lock()

        # 監査ログ（JSONL）。書き込み不能でも生成自体は止めない
        self._log_path: Path | None = None
        if log_dir is not None:
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                self._log_path = log_dir / f"{self._sandbox_name}.jsonl"
                self._append_audit({"event": "sandbox_created", "path": self.sandbox_path})
            except OSError:
                self._log_path = None

    # ── サンドボックス管理 ──────────────────────────────────────────────────────

    def _create_sandbox(self):
        obj = self._hou.node("/obj")
        sandbox = obj.createNode("subnet", self._sandbox_name)
        sandbox.setComment("AI生成チュートリアル用サンドボックス（tutorial_agent）")
        sandbox.moveToGoodPosition()
        return sandbox

    def destroy_sandbox(self) -> None:
        """ユーザーが明示的に「削除」を選んだ場合のみ呼ばれる。"""
        def _destroy():
            node = self._hou.node(self.sandbox_path)
            if node is not None:
                node.destroy()
        _run_in_main_thread(_destroy)
        self._append_audit({"event": "sandbox_destroyed", "path": self.sandbox_path})

    def _resolve(self, rel_path: str):
        """
        サンドボックス相対パスをノードに解決する。
        サンドボックス外を指すパスは SandboxViolation。
        絶対パスはサンドボックス配下を指している場合のみ許可する。
        """
        rel_path = (rel_path or "").strip()
        if not rel_path:
            raise SandboxViolation("ノードパスが空です")
        if ".." in rel_path.split("/"):
            raise SandboxViolation(f"'..' を含むパスは許可されません: {rel_path}")

        if rel_path.startswith("/"):
            # 絶対パス: サンドボックス自身か配下のみ許可
            if rel_path != self.sandbox_path and not rel_path.startswith(self.sandbox_path + "/"):
                raise SandboxViolation(
                    f"サンドボックス外のパスは操作できません: {rel_path}"
                )
            full_path = rel_path
        else:
            full_path = f"{self.sandbox_path}/{rel_path}"

        node = self._hou.node(full_path)
        if node is None:
            raise ValueError(f"ノードが見つかりません: {full_path}")
        # シンボリックな別名等でサンドボックス外に解決された場合も拒否する
        real = node.path()
        if real != self.sandbox_path and not real.startswith(self.sandbox_path + "/"):
            raise SandboxViolation(f"サンドボックス外のノードです: {real}")
        return node

    def _rel(self, node) -> str:
        """ノードのサンドボックス相対パスを返す（ログ・応答の表記用）。"""
        path = node.path()
        if path.startswith(self.sandbox_path + "/"):
            return path[len(self.sandbox_path) + 1:]
        return path

    # ── 監査ログ ────────────────────────────────────────────────────────────────

    def _append_audit(self, record: dict) -> None:
        record = {"ts": datetime.datetime.now().isoformat(), **record}
        if self._log_path is None:
            return
        try:
            with self._lock, open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # ログ書き込み失敗で生成を止めない

    # ── ツールディスパッチ ──────────────────────────────────────────────────────

    def execute(self, tool_name: str, tool_input: dict) -> tuple[str, bool]:
        """
        ツールを実行して (結果テキスト, is_error) を返す。
        例外はすべて捕捉して結果テキストに変換する（エージェントの自己修正材料になる）。
        SandboxViolation は監査ログに violation として記録する。
        """
        handler = getattr(self, f"_tool_{tool_name}", None)
        if handler is None:
            result, is_error = f"未知のツールです: {tool_name}", True
        else:
            try:
                result, is_error = _run_in_main_thread(lambda: handler(tool_input)), False
            except SandboxViolation as exc:
                result, is_error = f"[サンドボックス違反] {exc}", True
                self._append_audit({
                    "event": "sandbox_violation",
                    "tool": tool_name, "input": tool_input, "error": str(exc),
                })
            except Exception as exc:
                result, is_error = f"エラー: {exc}", True

        entry = {
            "tool": tool_name, "input": tool_input,
            "result": result, "is_error": is_error,
        }
        self.step_log.append(entry)
        self._append_audit({"event": "tool_call", **entry})
        return result, is_error

    # ── 各ツール実装 ────────────────────────────────────────────────────────────

    def _tool_create_node(self, args: dict) -> str:
        parent = self._resolve(args["parent"]) if args.get("parent") else self._sandbox
        name = args.get("name") or None
        if name and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            return f"ノード名が不正です（英数字とアンダースコアのみ）: {name}"
        try:
            node = parent.createNode(args["node_type"], name)
        except Exception as exc:
            return (
                f"ノード作成失敗（タイプ名 '{args['node_type']}' が不正な可能性）: {exc}\n"
                "list_available_node_types で正確なタイプ名を確認してください。"
            )
        node.moveToGoodPosition()
        return f"作成しました: {self._rel(node)}（タイプ: {node.type().name()}）"

    def _tool_set_parameter(self, args: dict) -> str:
        node = self._resolve(args["node"])
        parm_name = args["parm"]
        value = args["value"]

        parm = node.parm(parm_name)
        if parm is not None:
            parm.set(self._coerce_scalar(parm, value))
            return f"{self._rel(node)}.{parm_name} = {value}"

        tuple_parm = node.parmTuple(parm_name)
        if tuple_parm is not None:
            components = str(value).split()
            if len(components) != len(tuple_parm):
                return (
                    f"タプル {parm_name} は {len(tuple_parm)} 成分です。"
                    f"空白区切りで {len(tuple_parm)} 個の値を渡してください（受領: {value}）"
                )
            tuple_parm.set(tuple(float(c) for c in components))
            return f"{self._rel(node)}.{parm_name} = ({', '.join(components)})"

        available = ", ".join(p.name() for p in node.parms()[:40])
        return (
            f"パラメータ '{parm_name}' が見つかりません。"
            f"利用可能なパラメータ（先頭40件）: {available}"
        )

    @staticmethod
    def _coerce_scalar(parm, value):
        """パラメータのテンプレート型に合わせて値を変換する。"""
        try:
            import hou
            data_type = parm.parmTemplate().dataType()
            if data_type == hou.parmData.Int:
                return int(float(value))
            if data_type == hou.parmData.Float:
                return float(value)
            return str(value)
        except Exception:
            return value  # 型情報が取れない場合はそのまま渡す（hou 側で変換）

    def _tool_connect_nodes(self, args: dict) -> str:
        src = self._resolve(args["from_node"])
        dst = self._resolve(args["to_node"])
        input_index = int(args.get("input_index", 0))
        output_index = int(args.get("output_index", 0))
        dst.setInput(input_index, src, output_index)
        return (
            f"接続しました: {self._rel(src)}[out:{output_index}] → "
            f"{self._rel(dst)}[in:{input_index}]"
        )

    def _tool_cook_node(self, args: dict) -> str:
        node = self._resolve(args["node"])
        try:
            node.cook(force=True)
        except Exception:
            pass  # cook 例外の詳細は errors() から取得する
        errors = list(node.errors())
        warnings = list(node.warnings())
        if not errors and not warnings:
            return f"cook 成功: {self._rel(node)}（エラー・警告なし）"
        lines = [f"cook 結果: {self._rel(node)}"]
        for e in errors:
            lines.append(f"  [エラー] {e}")
        for w in warnings:
            lines.append(f"  [警告] {w}")
        return "\n".join(lines)

    def _tool_list_available_node_types(self, args: dict) -> str:
        category_map = {
            "sop": "sopNodeTypeCategory",
            "object": "objNodeTypeCategory",
            "obj": "objNodeTypeCategory",
            "dop": "dopNodeTypeCategory",
            "vop": "vopNodeTypeCategory",
            "cop2": "cop2NodeTypeCategory",
            "top": "topNodeTypeCategory",
        }
        cat_key = args["category"].lower()
        getter_name = category_map.get(cat_key)
        if getter_name is None:
            return f"未知のカテゴリです: {args['category']}（Sop/Object/Dop/Vop/Cop2/Top）"
        category = getattr(self._hou, getter_name)()

        keyword = (args.get("filter") or "").lower()
        matches = []
        for type_name, node_type in category.nodeTypes().items():
            desc = node_type.description()
            if keyword and keyword not in type_name.lower() and keyword not in desc.lower():
                continue
            matches.append(f"{type_name}  —  {desc}")
        if not matches:
            return f"'{args.get('filter', '')}' に一致するノードタイプがありません"
        matches.sort()
        shown = matches[:40]
        suffix = f"\n（他 {len(matches) - 40} 件省略。filter で絞り込んでください）" if len(matches) > 40 else ""
        return "\n".join(shown) + suffix

    def _tool_get_node_info(self, args: dict) -> str:
        node = self._resolve(args["node"])
        lines = [f"ノード: {self._rel(node)}（タイプ: {node.type().name()}）"]

        changed = [
            f"  {p.name()} = {p.eval()}"
            for p in node.parms() if not p.isAtDefault()
        ]
        lines.append("デフォルトから変更されたパラメータ:")
        lines.extend(changed[:30] or ["  （なし）"])

        inputs = [
            f"  in[{i}] ← {self._rel(inp)}" if inp else f"  in[{i}] ← （未接続）"
            for i, inp in enumerate(node.inputs())
        ]
        lines.append("入力接続:")
        lines.extend(inputs or ["  （入力なし）"])

        errors = list(node.errors())
        warnings = list(node.warnings())
        if errors or warnings:
            lines.append("エラー/警告:")
            lines.extend(f"  [エラー] {e}" for e in errors)
            lines.extend(f"  [警告] {w}" for w in warnings)

        parm_names = ", ".join(p.name() for p in node.parms()[:60])
        lines.append(f"利用可能なパラメータ名（先頭60件）: {parm_names}")
        return "\n".join(lines)

    def _tool_delete_node(self, args: dict) -> str:
        node = self._resolve(args["node"])
        if node.path() == self.sandbox_path:
            raise SandboxViolation("サンドボックス自体は削除できません")
        rel = self._rel(node)
        node.destroy()
        return f"削除しました: {rel}"

    def _tool_finish_tutorial(self, args: dict) -> str:
        self.finish_data = dict(args)
        return "チュートリアル生成を完了しました。"

    # ── NodeGraphAsset エクスポート ─────────────────────────────────────────────

    def export_node_graph(self) -> dict:
        """
        サンドボックス内のノード構成を NodeGraphAsset 互換 JSON に変換する。
        Node-Management（Blender版）の nodes/edges/params/position スキーマに合わせる。
        ネストしたサブネットも parent フィールド付きで再帰的に含める。
        """
        def _export():
            nodes: list[dict] = []
            edges: list[dict] = []

            def visit(parent, parent_id: str | None):
                for child in parent.children():
                    node_id = self._rel(child)
                    pos = child.position()
                    entry = {
                        "id": node_id,
                        "kind": child.type().name(),
                        "label": child.name(),
                        # Houdini のネットワーク座標は y が上向きなので反転して保存
                        "position": [round(pos[0], 3), round(-pos[1], 3)],
                        "params": {
                            p.name(): _json_safe(p.eval())
                            for p in child.parms() if not p.isAtDefault()
                        },
                    }
                    if parent_id:
                        entry["parent"] = parent_id
                    nodes.append(entry)

                    for connection in child.inputConnections():
                        src = connection.inputNode()
                        if src is None:
                            continue
                        edges.append({
                            "source": self._rel(src),
                            "sourceOutput": connection.outputIndex(),
                            "target": node_id,
                            "targetInput": connection.inputIndex(),
                        })
                    if child.children():
                        visit(child, node_id)

            visit(self._sandbox, None)
            return {
                "version": 1,
                "app": "houdini",
                "sandbox": self.sandbox_path,
                "created": datetime.datetime.now().isoformat(),
                "nodes": nodes,
                "edges": edges,
            }

        graph = _run_in_main_thread(_export)
        self._append_audit({
            "event": "graph_exported",
            "node_count": len(graph["nodes"]),
            "edge_count": len(graph["edges"]),
        })
        return graph
