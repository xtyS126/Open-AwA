"""
MCP 客户端实现模块，管理与单个 MCP Server 的连接、工具调用与资源访问。
根据配置自动选择 Stdio 或 SSE 传输层。
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from mcp.protocol import MCPProtocol
from mcp.transport import MCPTransport, MCPTransportError, SSETransport, StdioTransport  # noqa: F401
from mcp.types import MCPResource, MCPServerConfig, MCPTool, MCPToolCallResponse, TransportType


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
        except Exception as e:
            # 连接失败时清理传输层
            if self._transport is not None:
                try:
                    await self._transport.disconnect()
                except Exception as e:
                    logger.warning(f"MCP transport disconnect failed: {e}")
                self._transport = None
            raise MCPClientError(f"连接 MCP Server 失败: {e}")

    async def disconnect(self) -> None:
        """断开与 MCP Server 的连接"""
        if self._transport is not None:
            try:
                await self._transport.disconnect()
            except Exception as e:
                logger.bind(module="mcp.client", event="disconnect_error").warning(
                    f"断开连接时出错: {e}"
                )
            finally:
                self._transport = None
                self._server_info = None
                self._tools = []
                logger.bind(module="mcp.client", event="disconnected").info(
                    f"已断开 MCP Server: {self._config.name}"
                )

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
                    except Exception:
                        proc.kill()
                        proc.wait(timeout=1.0)
                self._transport._process = None
        except Exception as e:
            logger.bind(module="mcp.client", event="cleanup_sync_error").warning(
                f"同步清理客户端资源时出错: {e}"
            )
        finally:
            self._transport = None
            self._server_info = None
            self._tools = []

    async def list_tools(self) -> List[MCPTool]:
        """
        获取 MCP Server 提供的工具列表。
        :return: 工具定义列表
        """
        response = await self._send_request(self._protocol.list_tools())
        result = response.get("result", {})
        tools_data = result.get("tools", [])
        self._tools = [MCPTool(**tool) for tool in tools_data]
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
            return MCPToolCallResponse(
                result=response["error"].get("message", "未知错误"),
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
        :return: 资源定义列表
        """
        response = await self._send_request(self._protocol.list_resources())
        result = response.get("result", {})
        resources_data = result.get("resources", [])
        return [MCPResource(**res) for res in resources_data]

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
