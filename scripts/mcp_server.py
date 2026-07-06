"""
mcp_server.py — MCP サーバーモジュール

Model Context Protocol (MCP) に準拠したサーバーを提供する。
JSON-RPC over stdio を使用してクライアント（Claude Desktop 等）からの
リクエストを処理する。mcp-rag-server から独立させた版。
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List


class MCPServer:
    """
    Model Context Protocol (MCP) に準拠したサーバークラス

    Attributes:
        tools: 登録されたツールのディクショナリ
        logger: ロガー
    """

    def __init__(self):
        self.tools = {}
        self.tool_handlers = {}

        self.logger = logging.getLogger("mcp_server")
        self.logger.setLevel(logging.INFO)

        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "mcp_server.log")
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def register_tool(self, name: str, description: str, input_schema: Dict[str, Any], handler: Callable):
        self.tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }
        self.tool_handlers[name] = handler
        self.logger.info(f"ツール '{name}' を登録しました")

    def start(self, server_name: str = "rag-mcp-server", version: str = "0.1.0", description: str = "Python MCP Server"):
        self.logger.info(f"MCPサーバー '{server_name}' を起動しました")

        self.server_name = server_name
        self.server_version = version
        self.server_description = description

        while True:
            try:
                request_line = sys.stdin.readline()
                if not request_line:
                    break

                request = json.loads(request_line)
                self.logger.info(f"リクエストを受信しました: {request}")
                self._handle_request(request)

            except json.JSONDecodeError:
                self.logger.error("JSONのパースに失敗しました")
                self._send_error(-32700, "Parse error", None)

            except Exception as e:
                self.logger.error(f"エラーが発生しました: {str(e)}")
                self._send_error(-32603, f"Internal error: {str(e)}", None)

    def _handle_request(self, request: Dict[str, Any]):
        if "jsonrpc" not in request or request["jsonrpc"] != "2.0":
            self._send_error(-32600, "Invalid Request", request.get("id"))
            return

        if "method" not in request:
            self._send_error(-32600, "Method not specified", request.get("id"))
            return

        method = request["method"]
        params = request.get("params", {})
        request_id = request.get("id")

        if method == "initialize":
            self._handle_initialize(params, request_id)
        elif method == "tools/list":
            self._handle_tools_list(request_id)
        elif method == "tools/call":
            self._handle_tools_call(params, request_id)
        elif method == "ping":
            # MCP 2025-xx 以降に追加された ping/pong ハンドシェイク
            if request_id is not None:
                self._send_result({}, request_id)
        elif method.startswith("notifications/"):
            # notifications/* は一方向通知のため応答不要（id があっても送らない）
            self.logger.info(f"通知を受信しました: {method}")
        elif method == "resources/list":
            self._handle_resources_list(request_id)
        elif method == "resources/templates/list":
            self._handle_resources_templates_list(request_id)
        else:
            if method in self.tool_handlers:
                try:
                    result = self.tool_handlers[method](params)
                    self._send_result(result, request_id)
                except Exception as e:
                    self._send_error(-32603, f"Tool execution error: {str(e)}", request_id)
            else:
                self.logger.warning(f"未知のメソッド: {method}")
                if request_id is not None:
                    self._send_error(-32601, f"Method not found: {method}", request_id)

    def _handle_initialize(self, params: Dict[str, Any], request_id: Any):
        client_name = params.get("clientInfo", {}).get("name", "unknown")
        client_version = params.get("clientInfo", {}).get("version", "unknown")
        # クライアントが要求したプロトコルバージョンをそのまま採用する
        # （バージョン不一致で Claude Desktop が接続拒否するのを防ぐ）
        requested_protocol = params.get("protocolVersion", "2024-11-05")
        self.logger.info(f"クライアント '{client_name} {client_version}' が接続しました (protocol: {requested_protocol})")

        response = {
            "protocolVersion": requested_protocol,
            "serverInfo": {
                "name": getattr(self, "server_name", "rag-mcp-server"),
                "version": getattr(self, "server_version", "0.1.0"),
            },
            "capabilities": {
                "tools": {},
                "resources": {},
            },
        }
        self._send_result(response, request_id)

    def _send_result(self, result: Any, request_id: Any):
        self._send_response({"jsonrpc": "2.0", "result": result, "id": request_id})

    def _send_error(self, code: int, message: str, request_id: Any):
        # id が None（null）のエラー応答は Claude Desktop の Zod バリデーターが拒否する。
        # リクエスト前のパースエラー等で id を特定できない場合はログのみに留める。
        if request_id is None:
            self.logger.error(f"Error (no request_id): {code} {message}")
            return
        self._send_response({"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": request_id})

    def _send_response(self, response: Dict[str, Any]):
        response_json = json.dumps(response)
        print(response_json, flush=True)
        self.logger.info(f"レスポンスを送信しました: {response_json}")

    def _get_tools(self) -> List[Dict[str, Any]]:
        return list(self.tools.values())

    def _handle_tools_call(self, params: Dict[str, Any], request_id: Any):
        if "name" not in params:
            self._send_error(-32602, "Invalid params: name is required", request_id)
            return
        if "arguments" not in params:
            self._send_error(-32602, "Invalid params: arguments is required", request_id)
            return

        tool_name = params["name"]
        arguments = params["arguments"]

        if tool_name in self.tool_handlers:
            try:
                result = self.tool_handlers[tool_name](arguments)
                if isinstance(result, dict) and "content" in result:
                    self._send_result(result, request_id)
                else:
                    content = [{"type": "text", "text": str(result)}]
                    self._send_result({"content": content}, request_id)
            except Exception as e:
                self.logger.error(f"ツール '{tool_name}' の実行中にエラーが発生しました: {str(e)}")
                self._send_result(
                    {
                        "content": [{"type": "text", "text": f"ツールの実行中にエラーが発生しました: {str(e)}"}],
                        "isError": True,
                    },
                    request_id,
                )
        else:
            self._send_result(
                {"content": [{"type": "text", "text": f"ツールが見つかりません: {tool_name}"}], "isError": True}, request_id
            )

    def _handle_tools_list(self, request_id: Any):
        self._send_result({"tools": self._get_tools()}, request_id)

    def _handle_notifications_initialized(self, params: Dict[str, Any], request_id: Any):
        self.logger.info("クライアントの初期化が完了しました")
        if request_id is not None:
            self._send_result({}, request_id)

    def _handle_resources_list(self, request_id: Any):
        self._send_result({"resources": self._get_resources()}, request_id)

    def _handle_resources_templates_list(self, request_id: Any):
        self._send_result({"templates": self._get_resource_templates()}, request_id)

    def _get_resources(self) -> List[Dict[str, Any]]:
        return []

    def _get_resource_templates(self) -> List[Dict[str, Any]]:
        return []
