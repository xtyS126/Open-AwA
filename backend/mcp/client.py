"""
MCP 客户端实现模块，管理与单个 MCP Server 的连接、工具调用与资源访问。
根据配置自动选择 Stdio 或 SSE 传输层。
"""

import asyncio
import json
import re
import subprocess
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

from core.utils.memoize import memoize_with_lru, memoize_with_ttl
from mcp.protocol import MCPProtocol
from mcp.transport import MCPTransport, MCPTransportError, SSETransport, StdioTransport  # noqa: F401
from mcp.types import MCPResource, MCPResourceContent, MCPServerConfig, MCPTool, MCPToolCallResponse, TransportType


# JSON-RPC 错误码 -32001 表示会话过期
_MCP_SESSION_EXPIRED_CODE = -32001
# HTTP 404 状态码表示会话端点不存在
_HTTP_NOT_FOUND = 404


def is_mcp_session_expired_error(error: Exception) -> bool:
    """
    判断异常是否表示 MCP 会话过期。

    检测两种过期信号：
    1. HTTP 404 错误（会话端点不存在）
    2. JSON-RPC 错误码 -32001（会话过期）

    通过检查异常的属性（code/status_code/response）和字符串表示进行匹配。

    :param error: 待检测的异常
    :return: 如果是会话过期错误返回 True，否则 False
    """
    # 检查 JSON-RPC 错误码 -32001（通过 code 属性）
    code = getattr(error, "code", None)
    if code == _MCP_SESSION_EXPIRED_CODE:
        return True

    # 检查 HTTP 状态码 404（通过 status_code 属性）
    status_code = getattr(error, "status_code", None)
    if status_code == _HTTP_NOT_FOUND:
        return True

    # 检查 httpx.HTTPStatusError 的 response.status_code 属性
    response = getattr(error, "response", None)
    if response is not None:
        response_status = getattr(response, "status_code", None)
        if response_status == _HTTP_NOT_FOUND:
            return True

    # 检查错误消息字符串
    error_str = str(error)
    # 匹配 JSON-RPC 错误码 -32001
    if str(_MCP_SESSION_EXPIRED_CODE) in error_str:
        return True
    # 匹配 HTTP 404（使用词边界避免误匹配 4040 等数字）
    if re.search(r"\b404\b", error_str):
        return True

    return False


def _make_connection_key(server_id: str, config: MCPServerConfig) -> str:
    """
    生成连接缓存键。

    键格式：f"{server_id}:{hash(json.dumps(config, sort_keys=True))}"

    :param server_id: 服务器 ID
    :param config: 服务器配置
    :return: 连接缓存键字符串
    """
    config_json = json.dumps(config.model_dump(), sort_keys=True)
    return f"{server_id}:{hash(config_json)}"


@memoize_with_ttl(ttl=300)
def _create_mcp_client(cache_key: str, config_json: str) -> "MCPClient":
    """
    创建 MCPClient 实例（按 server_id + config 哈希记忆化）。

    TTL 默认 300 秒（5 分钟），相同 cache_key + config_json 在 TTL 内返回同一实例。

    :param cache_key: 连接缓存键（由 _make_connection_key 生成）
    :param config_json: 配置的 JSON 字符串
    :return: MCPClient 实例
    """
    config_dict = json.loads(config_json)
    config = MCPServerConfig(**config_dict)
    return MCPClient(config)


@memoize_with_lru(maxsize=32)
def _cache_tools(cache_key: str, tools: List[MCPTool]) -> List[MCPTool]:
    """
    工具列表缓存的透传函数。

    通过 memoize_with_lru 实现 LRU 缓存，maxsize 默认 32。
    实际缓存读取通过 cache_get 完成，写入通过调用本函数完成。

    :param cache_key: 缓存键（客户端唯一标识）
    :param tools: 工具列表
    :return: 传入的工具列表（透传）
    """
    return tools


@memoize_with_lru(maxsize=32)
def _cache_resources(cache_key: str, resources: List[MCPResource]) -> List[MCPResource]:
    """
    资源列表缓存的透传函数。

    通过 memoize_with_lru 实现 LRU 缓存，maxsize 默认 32。
    实际缓存读取通过 cache_get 完成，写入通过调用本函数完成。

    :param cache_key: 缓存键（客户端唯一标识）
    :param resources: 资源列表
    :return: 传入的资源列表（透传）
    """
    return resources


class MCPClientError(Exception):
    """MCP 客户端异常"""
    pass


class MCPClient:
    """
    MCP 客户端，负责管理与单个 MCP Server 的完整通信生命周期。
    支持连接建立、工具发现、工具调用和资源访问。
    """

    def __init__(self, config: MCPServerConfig):
        """
        初始化 MCP 客户端。
        :param config: MCP Server 连接配置
        """
        self._config = config
        self._transport: Optional[MCPTransport] = None
        self._protocol = MCPProtocol()
        self._server_info: Optional[Dict[str, Any]] = None
        self._tools: List[MCPTool] = []
        # 客户端唯一缓存键，用于工具/资源 LRU 缓存
        self._cache_key: str = str(uuid.uuid4())

    @property
    def config(self) -> MCPServerConfig:
        """获取服务器配置"""
        return self._config

    @property
    def is_connected(self) -> bool:
        """当前是否已连接"""
        return self._transport is not None and self._transport.is_connected

    @property
    def tools(self) -> List[MCPTool]:
        """已发现的工具列表"""
        return self._tools

    @property
    def cache_key(self) -> str:
        """获取客户端缓存键"""
        return self._cache_key

    async def connect(self) -> None:
        """
        根据传输类型创建对应 Transport 并连接到 MCP Server。
        连接成功后自动发送初始化握手请求。
        """
        if self.is_connected:
            logger.bind(module="mcp.client", event="already_connected").warning(
                f"已连接到 MCP Server: {self._config.name}"
            )
            return

        # 根据配置创建传输层
        if self._config.transport_type == TransportType.STDIO:
            if not self._config.command:
                raise MCPClientError("Stdio 模式需要指定启动命令")
            self._transport = StdioTransport(
                command=self._config.command,
                args=self._config.args,
                env=self._config.env,
            )
        elif self._config.transport_type == TransportType.SSE:
            if not self._config.url:
                raise MCPClientError("SSE 模式需要指定服务器地址")
            self._transport = SSETransport(url=self._config.url)
        else:
            raise MCPClientError(f"不支持的传输类型: {self._config.transport_type}")

        try:
            await self._transport.connect()
            # 发送初始化握手
            init_response = await self._send_request(self._protocol.initialize())
            self._server_info = init_response.get("result", {})
            logger.bind(module="mcp.client", event="connected").info(
                f"MCP Server 连接成功: {self._config.name}"
            )
        except (MCPTransportError, MCPClientError, asyncio.TimeoutError, ConnectionError, OSError) as e:
            # 连接失败时清理传输层
            if self._transport is not None:
                try:
                    await self._transport.disconnect()
                except (MCPTransportError, asyncio.TimeoutError, ConnectionError, OSError) as disconnect_err:
                    logger.warning(f"MCP transport disconnect failed: {disconnect_err}")
                self._transport = None
            raise MCPClientError(f"连接 MCP Server 失败: {e}")

    async def disconnect(self) -> None:
        """断开与 MCP Server 的连接"""
        if self._transport is not None:
            try:
                await self._transport.disconnect()
            except (MCPTransportError, asyncio.TimeoutError, ConnectionError, OSError) as e:
                logger.bind(module="mcp.client", event="disconnect_error").warning(
                    f"断开连接时出错: {e}"
                )
            finally:
                self._transport = None
                self._server_info = None
                self._tools = []
                # 断开连接时清除工具和资源缓存
                self.clear_caches()
                logger.bind(module="mcp.client", event="disconnected").info(
                    f"已断开 MCP Server: {self._config.name}"
                )
        else:
            # 即使未连接也清除缓存，确保状态一致
            self.clear_caches()

    def cleanup_sync(self) -> None:
        """
        同步方式尽力清理客户端持有的子进程资源。
        在无法等待异步 disconnect 的场景下使用（如 remove_server/rollback_to_snapshot）。
        """
        if self._transport is None:
            return
        from mcp.transport import StdioTransport
        try:
            if isinstance(self._transport, StdioTransport) and self._transport._process is not None:
                proc = self._transport._process
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=1.0)
                self._transport._process = None
        except (OSError, subprocess.SubprocessError) as e:
            logger.bind(module="mcp.client", event="cleanup_sync_error").warning(
                f"同步清理客户端资源时出错: {e}"
            )
        finally:
            self._transport = None
            self._server_info = None
            self._tools = []
            # 同步清理时也清除缓存
            self.clear_caches()

    def clear_caches(self) -> None:
        """清除本客户端的工具和资源 LRU 缓存。"""
        _cache_tools.cache_delete(self._cache_key)
        _cache_resources.cache_delete(self._cache_key)

    async def list_tools(self) -> List[MCPTool]:
        """
        获取 MCP Server 提供的工具列表。
        结果通过 LRU 缓存，避免重复请求。

        :return: 工具定义列表
        """
        # 优先读取缓存（按客户端唯一 cache_key 查找）
        cached = _cache_tools.cache_get(self._cache_key)
        if cached is not None:
            return cached
        # 缓存未命中，发送请求获取
        response = await self._send_request(self._protocol.list_tools())
        result = response.get("result", {})
        tools_data = result.get("tools", [])
        self._tools = [MCPTool(**tool) for tool in tools_data]
        # 写入 LRU 缓存（直接按 cache_key 存储，避免参数化键不匹配）
        _cache_tools.cache_set(self._cache_key, self._tools)
        return self._tools

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> MCPToolCallResponse:
        """
        调用 MCP Server 上的指定工具。
        :param tool_name: 工具名称
        :param arguments: 调用参数
        :return: 工具调用响应
        """
        response = await self._send_request(
            self._protocol.call_tool(tool_name, arguments)
        )
        # 检查是否有错误响应
        if "error" in response and response["error"] is not None:
            error_obj = response["error"]
            error_code = error_obj.get("code")
            error_message = error_obj.get("message", "未知错误")
            # JSON-RPC 错误码 -32001 表示会话过期，抛出异常以便上层检测并重连
            if error_code == _MCP_SESSION_EXPIRED_CODE:
                raise MCPClientError(f"MCP 会话过期 (code -32001): {error_message}")
            return MCPToolCallResponse(
                result=error_message,
                is_error=True,
            )
        result = response.get("result", {})
        # MCP 工具调用结果可能包含 content 数组
        content = result.get("content", [])
        if content and isinstance(content, list):
            # 提取文本内容
            text_parts = [
                item.get("text", "") for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            return MCPToolCallResponse(
                result="\n".join(text_parts) if text_parts else content,
                is_error=result.get("isError", False),
            )
        return MCPToolCallResponse(result=result, is_error=False)

    async def list_resources(self) -> List[MCPResource]:
        """
        获取 MCP Server 提供的资源列表。
        结果通过 LRU 缓存，避免重复请求。

        :return: 资源定义列表
        """
        # 优先读取缓存（按客户端唯一 cache_key 查找）
        cached = _cache_resources.cache_get(self._cache_key)
        if cached is not None:
            return cached
        # 缓存未命中，发送请求获取
        response = await self._send_request(self._protocol.list_resources())
        result = response.get("result", {})
        resources_data = result.get("resources", [])
        resources = [MCPResource(**res) for res in resources_data]
        # 写入 LRU 缓存（直接按 cache_key 存储，避免参数化键不匹配）
        _cache_resources.cache_set(self._cache_key, resources)
        return resources

    async def read_resource(self, uri: str) -> MCPResourceContent:
        """
        读取指定 URI 的资源内容。
        :param uri: 资源 URI（如 file:///path/to/file）
        :return: 资源内容对象
        """
        response = await self._send_request(self._protocol.read_resource(uri))
        result = response.get("result", {})
        contents_data = result.get("contents", [])
        if not contents_data:
            return MCPResourceContent(uri=uri, mime_type=None, text="", blob=None)
        # 取第一个内容块（多数 MCP Server 单次返回单个资源）
        first = contents_data[0]
        return MCPResourceContent(
            uri=first.get("uri", uri),
            mime_type=first.get("mimeType"),
            text=first.get("text"),
            blob=first.get("blob"),
        )

    async def _send_request(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        内部方法：发送 JSON-RPC 请求并等待响应。
        根据传输层类型选择合适的发送方式。
        :param message: JSON-RPC 请求消息
        :return: 响应消息字典
        """
        if not self.is_connected or self._transport is None:
            raise MCPClientError("未连接到 MCP Server")

        try:
            # 统一通过 send_and_receive 接口处理，SSE/Stdio 各自实现
            return await self._transport.send_and_receive(message)
        except MCPTransportError as e:
            raise MCPClientError(f"请求失败: {e}")
