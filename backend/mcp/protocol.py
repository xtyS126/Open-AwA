"""
MCP 协议处理模块，负责构建符合 JSON-RPC 2.0 规范的请求消息。
每个方法对应 MCP 协议中的一种操作，返回可直接发送的消息字典。
"""

import itertools
import threading
from typing import Any, Dict, Optional


class MCPProtocol:
    """MCP 协议消息构建器，生成标准 JSON-RPC 2.0 请求"""

    def __init__(self):
        """初始化消息 ID 计数器"""
        self._id_counter = itertools.count(1)
        self._id_lock = threading.Lock()

    def _next_id(self) -> int:
        """生成下一个请求 ID（线程安全）"""
        with self._id_lock:
            return next(self._id_counter)

    def _build_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        构建 JSON-RPC 2.0 请求消息。
        :param method: 方法名称
        :param params: 方法参数
        :return: 完整的 JSON-RPC 消息字典
        """
        message: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            message["params"] = params
        return message

    def initialize(self, client_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        构建初始化请求，用于与 MCP Server 建立连接握手。
        :param client_info: 客户端信息
        :return: 初始化请求消息
        """
        params: Dict[str, Any] = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
        }
        if client_info:
            params["clientInfo"] = client_info
        else:
            params["clientInfo"] = {
                "name": "open-awa",
                "version": "1.0.0",
            }
        return self._build_request("initialize", params)

    def list_tools(self) -> Dict[str, Any]:
        """
        构建获取工具列表请求。
        :return: list_tools 请求消息
        """
        return self._build_request("tools/list")

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        构建工具调用请求。
        :param tool_name: 工具名称
        :param arguments: 调用参数
        :return: call_tool 请求消息
        """
        params: Dict[str, Any] = {"name": tool_name}
        if arguments:
            params["arguments"] = arguments
        return self._build_request("tools/call", params)

    def list_resources(self) -> Dict[str, Any]:
        """
        构建获取资源列表请求。
        :return: list_resources 请求消息
        """
        return self._build_request("resources/list")

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """
        构建读取指定资源请求。
        :param uri: 资源 URI
        :return: read_resource 请求消息
        """
        return self._build_request("resources/read", {"uri": uri})
