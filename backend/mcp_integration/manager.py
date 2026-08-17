"""
MCP 管理器模块（基于官方 mcp Python SDK）。

用 mcp.stdio_client() / mcp.sse_client() + mcp.ClientSession 替代自实现 transport + client，
保留 sandbox.py（进程级资源隔离）作为 stdio_client 启动命令的外围包装，
保留 config_store.py（多用户配置持久化）。

本模块合并了原 types.py / protocol.py / transport.py / client.py 的对外 API，
确保 api/routes/mcp.py 等调用方的 import 路径与函数签名零修改。
"""

import asyncio
import importlib.util
import json
import re
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, computed_field

# ===========================================================================
# 官方 mcp Python SDK 导入（本地模块已重命名为 mcp_integration，不再与官方 SDK 冲突）
# ===========================================================================
# 使用 importlib 加载官方 SDK 并注册为 _official_mcp，以绕过本地兼容层
# backend/mcp/（若存在）。本地模块已从 mcp 重命名为 mcp_integration，
# 所有内部 import 路径已更新，不再需要复杂的命名空间交换逻辑。

_OFFICIAL_MCP_NAME = "_official_mcp"
_LOCAL_BACKEND_DIR = Path(__file__).resolve().parent.parent

if _OFFICIAL_MCP_NAME not in sys.modules:
    _sdk_dir = None
    for _path_entry in sys.path:
        if not _path_entry:
            continue
        try:
            _resolved = Path(_path_entry).resolve()
        except (OSError, RuntimeError):
            continue
        _sdk_init = _resolved / "mcp" / "__init__.py"
        if _sdk_init.exists() and _resolved / "mcp" != _LOCAL_BACKEND_DIR / "mcp":
            _sdk_dir = _resolved / "mcp"
            break
    if _sdk_dir is None:
        raise ImportError(
            "无法从 site-packages 定位官方 mcp SDK。"
            "请确认已执行 `pip install mcp`。"
        )
    _spec = importlib.util.spec_from_file_location(
        _OFFICIAL_MCP_NAME,
        _sdk_dir / "__init__.py",
        submodule_search_locations=[str(_sdk_dir)],
    )
    if _spec is None or _spec.loader is None:
        raise ImportError(f"无法为 mcp SDK 创建模块 spec: {_sdk_dir}")
    _official_mcp = importlib.util.module_from_spec(_spec)
    sys.modules[_OFFICIAL_MCP_NAME] = _official_mcp
    # 临时将官方 SDK 注册为 sys.modules["mcp"]，确保 SDK 内部 import mcp.types
    # 等绝对导入经由官方 SDK 的 __path__ 解析，而非本地兼容层 backend/mcp/
    _saved_mcp = sys.modules.pop("mcp", None)
    sys.modules["mcp"] = _official_mcp
    try:
        _spec.loader.exec_module(_official_mcp)
    finally:
        # 恢复兼容层（若原先存在），移除临时注册的官方 SDK
        sys.modules.pop("mcp", None)
        if _saved_mcp is not None:
            sys.modules["mcp"] = _saved_mcp

# 从官方 SDK 顶层导入
ClientSession = _official_mcp.ClientSession
McpError = _official_mcp.McpError
StdioServerParameters = _official_mcp.StdioServerParameters

# 从官方 SDK 子模块导入
from _official_mcp.client.sse import sse_client as _mcp_sse_client
from _official_mcp.client.stdio import (
    get_default_environment,
    stdio_client as _mcp_stdio_client,
)
from _official_mcp.types import (
    BlobResourceContents,
    CallToolResult,
    JSONRPCMessage,
    ListResourcesResult,
    ListToolsResult,
    ReadResourceResult,
    Resource,
    TextContent,
    TextResourceContents,
    Tool,
)
from _official_mcp.shared.message import SessionMessage

# 项目内部导入
from core.utils.memoize import memoize_with_lru, memoize_with_ttl
from mcp_integration.config_store import MCPConfigStore
from mcp_integration.sandbox import (
    SandboxError,
    SandboxLimits,
    SandboxTimeoutError,
    _validate_command_path,
    create_sandboxed_subprocess,
    kill_process_tree,
    wait_with_timeout,
)


# ===========================================================================
# 项目特定数据类型（从原 types.py 迁移，保持调用方零修改）
# ===========================================================================


# MCP 工具全限定名前缀，三段式格式 mcp__<server>__<tool>
MCP_TOOL_NAME_PREFIX = "mcp__"
MCP_TOOL_NAME_SEPARATOR = "__"


def build_mcp_tool_name(server: str, tool: str) -> str:
    """
    构建 MCP 工具的三段式全限定名。

    格式：mcp__<server>__<tool>（双下划线分隔）
    示例：build_mcp_tool_name("github", "create_issue") -> "mcp__github__create_issue"

    :param server: MCP Server 名称
    :param tool: 工具名称
    :return: 三段式全限定名
    :raises ValueError: server 或 tool 为空时抛出
    """
    if not server:
        raise ValueError("server 不能为空")
    if not tool:
        raise ValueError("tool 不能为空")
    return f"{MCP_TOOL_NAME_PREFIX}{server}{MCP_TOOL_NAME_SEPARATOR}{tool}"


class TransportType(str, Enum):
    """MCP 传输类型枚举"""
    STDIO = "stdio"
    SSE = "sse"


class MCPTool(BaseModel):
    """MCP 工具定义，描述远程 Server 提供的可调用工具"""
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., description="工具名称")
    description: Optional[str] = Field(None, description="工具描述")
    input_schema: Optional[Dict[str, Any]] = Field(None, alias="inputSchema", description="工具输入参数的 JSON Schema")
    server_name: Optional[str] = Field(None, description="所属 MCP Server 名称，用于生成全限定名")

    @computed_field  # type: ignore[misc]
    @property
    def fully_qualified_name(self) -> str:
        """
        工具全限定名（只读），格式 mcp__<server>__<tool>。

        当 server_name 已提供时返回三段式全限定名；
        否则回退为工具名本身，保证向后兼容。
        """
        if self.server_name:
            return build_mcp_tool_name(self.server_name, self.name)
        return self.name


class MCPResource(BaseModel):
    """MCP 资源定义，描述远程 Server 提供的可读资源"""
    model_config = ConfigDict(populate_by_name=True)

    uri: str = Field(..., description="资源唯一标识符")
    name: str = Field(..., description="资源名称")
    description: Optional[str] = Field(None, description="资源描述")
    mime_type: Optional[str] = Field(None, alias="mimeType", description="资源 MIME 类型")


class MCPResourceContent(BaseModel):
    """MCP 资源内容，包含读取资源后返回的实际数据"""
    model_config = ConfigDict(populate_by_name=True)

    uri: str = Field(..., description="资源唯一标识符")
    mime_type: Optional[str] = Field(None, alias="mimeType", description="资源 MIME 类型")
    text: Optional[str] = Field(None, description="文本内容（文本资源）")
    blob: Optional[str] = Field(None, description="Base64 编码的二进制内容（二进制资源）")


class MCPServerConfig(BaseModel):
    """MCP Server 连接配置"""
    name: str = Field(..., description="服务器显示名称")
    command: Optional[str] = Field(None, description="stdio 模式下的启动命令")
    args: Optional[List[str]] = Field(default_factory=list, description="启动命令参数")
    env: Optional[Dict[str, str]] = Field(default_factory=dict, description="环境变量")
    transport_type: TransportType = Field(default=TransportType.STDIO, description="传输类型")
    url: Optional[str] = Field(None, description="SSE 模式下的远程服务器地址")
    # 安全：SSE 模式自定义请求头（如认证头），auth_token 以 Bearer 方式附加
    headers: Dict[str, str] = Field(default_factory=dict, description="SSE 模式自定义请求头")
    auth_token: Optional[str] = Field(None, description="SSE 模式认证令牌（Bearer Token）")
    # 安全：归属用户 ID，用于多用户隔离，防止 IDOR 跨用户访问他人 MCP Server
    # 旧配置文件可能缺少此字段，向后兼容默认为 None（路由层会拒绝 None 与具体 ID 的混用）
    owner_user_id: Optional[str] = Field(None, description="归属用户 ID，用于多用户隔离")


class MCPToolCallRequest(BaseModel):
    """工具调用请求"""
    tool_name: str = Field(..., description="工具名称")
    arguments: Optional[Dict[str, Any]] = Field(default_factory=dict, description="调用参数")


class MCPToolCallResponse(BaseModel):
    """工具调用响应"""
    result: Any = Field(None, description="调用结果")
    is_error: bool = Field(False, description="是否为错误响应")


class MCPMessage(BaseModel):
    """JSON-RPC 2.0 消息格式"""
    jsonrpc: str = Field(default="2.0", description="JSON-RPC 版本")
    id: Optional[int] = Field(None, description="请求标识符")
    method: Optional[str] = Field(None, description="方法名称")
    params: Optional[Dict[str, Any]] = Field(None, description="方法参数")
    result: Optional[Any] = Field(None, description="响应结果")
    error: Optional[Dict[str, Any]] = Field(None, description="错误信息")


# ===========================================================================
# 异常类型
# ===========================================================================


class MCPClientError(Exception):
    """MCP 客户端异常"""
    pass


class MCPTransportError(Exception):
    """MCP 传输层异常（保留用于向后兼容，实际传输由官方 SDK 处理）"""
    pass


# ===========================================================================
# SSE origin 白名单（项目特定安全层，官方 SDK 不提供）
# ===========================================================================


class SSETransport:
    """
    SSE 传输层 origin 白名单管理。

    官方 mcp SDK 的 sse_client 不提供 origin 校验，此处保留项目特定的安全层。
    白名单为空时允许所有 origin（仅适用于开发环境）。
    """

    # 允许的 origin 白名单（空集合表示不校验）
    _allowed_origins: set = set()

    @classmethod
    def set_allowed_origins(cls, origins: list) -> None:
        """设置全局 origin 白名单。"""
        cls._allowed_origins = {o.rstrip("/").lower() for o in origins if o}

    @classmethod
    def is_origin_allowed(cls, origin: str) -> bool:
        """检查 origin 是否在白名单中。白名单为空时允许所有 origin。"""
        if not cls._allowed_origins:
            return True
        return origin.rstrip("/").lower() in cls._allowed_origins

    @classmethod
    def _check_origin(cls, url: str) -> None:
        """
        校验 URL 对应的 origin 是否在白名单中。

        :param url: 待校验的 SSE 端点 URL
        :raises MCPTransportError: origin 不在白名单时抛出
        """
        from urllib.parse import urlparse
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}".lower()
        if not cls.is_origin_allowed(origin):
            raise MCPTransportError(
                f"SSE 连接 origin 被拒绝: {origin} 不在白名单中"
            )


# ===========================================================================
# 会话过期检测（项目特定重连逻辑）
# ===========================================================================


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

    # 检查 McpError 内部的 ErrorData.code
    mcp_error = getattr(error, "error", None)
    if mcp_error is not None:
        mcp_code = getattr(mcp_error, "code", None)
        if mcp_code == _MCP_SESSION_EXPIRED_CODE:
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


# ===========================================================================
# 缓存辅助（项目特定性能优化）
# ===========================================================================


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
    工具列表缓存的透传函数（LRU 缓存，maxsize=32）。
    实际缓存读取通过 cache_get 完成，写入通过调用本函数完成。
    """
    return tools


@memoize_with_lru(maxsize=32)
def _cache_resources(cache_key: str, resources: List[MCPResource]) -> List[MCPResource]:
    """
    资源列表缓存的透传函数（LRU 缓存，maxsize=32）。
    实际缓存读取通过 cache_get 完成，写入通过调用本函数完成。
    """
    return resources


# ===========================================================================
# 沙箱 stdio 传输（用 sandbox 包装子进程启动，替代裸 stdio_client）
# ===========================================================================


@asynccontextmanager
async def _sandboxed_stdio_client(
    server: Any,
    limits: Optional[SandboxLimits] = None,
):
    """
    在沙箱中启动 MCP Server 子进程并建立 stdio 传输连接。

    与官方 stdio_client 的差异（安全增强）：
    - 子进程通过 create_sandboxed_subprocess 启动（命令路径校验 + 资源限制 + 进程组隔离）
    - stderr 边读边丢弃，防止管道缓冲阻塞子进程
    - 退出时通过 wait_with_timeout 优雅终止，超时后 kill_process_tree 强制清理进程树

    yield (read_stream, write_stream)，接口与官方 SDK 的 stdio_client 一致，
    便于 ClientSession 直接消费。

    :param server: StdioServerParameters 启动参数（SDK 动态加载，类型标注为 Any）
    :param limits: 沙箱资源限制，None 时使用默认限制
    """
    import anyio

    read_stream_writer: Any
    read_stream: Any
    write_stream: Any
    write_stream_reader: Any
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    try:
        process = await create_sandboxed_subprocess(
            command=server.command,
            args=list(server.args or []),
            env=server.env if server.env is not None else get_default_environment(),
            limits=limits,
        )
    except SandboxError as exc:
        # 启动失败：清理已创建的流，避免资源泄漏
        await read_stream.aclose()
        await write_stream.aclose()
        await read_stream_writer.aclose()
        await write_stream_reader.aclose()
        raise MCPClientError(f"沙箱启动 MCP Server 失败: {exc}") from exc

    # 沙箱保证 stdin/stdout/stderr 均为 PIPE 管道，此处断言消除 Optional 类型
    assert process.stdout is not None
    assert process.stdin is not None
    assert process.stderr is not None

    async def stdout_reader() -> None:
        """从沙箱子进程 stdout 读取 JSON-RPC 消息并转发到读流。"""
        stdout = process.stdout
        assert stdout is not None  # 沙箱保证 stdout 为 PIPE
        try:
            async with read_stream_writer:
                while True:
                    line = await stdout.readline()
                    if not line:
                        break
                    try:
                        message = JSONRPCMessage.model_validate_json(line)
                    except Exception as exc:
                        # 非法消息转发给上层（与官方 SDK 行为一致）
                        await read_stream_writer.send(exc)
                        continue
                    await read_stream_writer.send(SessionMessage(message))
        except (anyio.ClosedResourceError, ValueError):
            pass  # 读流已关闭，读取循环正常结束

    async def stdin_writer() -> None:
        """将写流中的 JSON-RPC 消息写入沙箱子进程 stdin。"""
        stdin = process.stdin
        assert stdin is not None  # 沙箱保证 stdin 为 PIPE
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    data = session_message.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                    stdin.write((data + "\n").encode("utf-8"))
                    await stdin.drain()
        except (anyio.ClosedResourceError, ValueError):
            pass  # 写流已关闭，写入循环正常结束

    async def stderr_drainer() -> None:
        """读取并丢弃子进程 stderr，防止管道缓冲阻塞子进程。"""
        stderr = process.stderr
        assert stderr is not None  # 沙箱保证 stderr 为 PIPE
        try:
            while True:
                chunk = await stderr.read(4096)
                if not chunk:
                    break
        except (anyio.ClosedResourceError, ValueError):
            pass  # stderr 流已关闭，读取循环正常结束

    reader_task = asyncio.create_task(stdout_reader())
    writer_task = asyncio.create_task(stdin_writer())
    stderr_task = asyncio.create_task(stderr_drainer())
    try:
        yield read_stream, write_stream
    finally:
        # MCP spec: stdio 关闭顺序——先关闭 stdin → 等待进程退出 → 超时强制终止
        if process.stdin is not None:
            try:
                process.stdin.close()
            except Exception:
                pass  # stdin 可能已关闭，忽略
        try:
            await wait_with_timeout(process.wait(), timeout=5.0, process=process)
        except SandboxTimeoutError:
            await kill_process_tree(process)
        except SandboxError:
            pass  # 进程已终止或异常，交给 kill_process_tree 兜底
        # 取消 reader/writer/stderr 任务并等待结束，避免悬挂任务泄漏
        for task in (reader_task, writer_task, stderr_task):
            task.cancel()
        await asyncio.gather(reader_task, writer_task, stderr_task, return_exceptions=True)
        await read_stream.aclose()
        await write_stream.aclose()
        await read_stream_writer.aclose()
        await write_stream_reader.aclose()


# ===========================================================================
# MCPClient（包装官方 mcp.ClientSession）
# ===========================================================================


class MCPClient:
    """
    MCP 客户端，基于官方 mcp Python SDK 的 ClientSession 实现。

    根据配置自动选择 stdio_client 或 sse_client 建立传输层，
    并在其上创建 ClientSession 处理 JSON-RPC 协议。
    """

    def __init__(self, config: MCPServerConfig):
        """
        初始化 MCP 客户端。

        :param config: MCP Server 连接配置
        """
        self._config = config
        self._session: Optional[ClientSession] = None
        # stdio_client / sse_client 的异步上下文管理器（需在 disconnect 时退出）
        self._transport_ctx: Optional[Any] = None
        self._session_ctx: Optional[Any] = None
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
        return self._session is not None

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
        根据传输类型建立连接并初始化 ClientSession。

        stdio 模式：通过 sandbox 校验命令路径，使用官方 SDK 的 stdio_client 启动子进程；
        sse 模式：先校验 origin 白名单，再使用官方 SDK 的 sse_client 建立 HTTP 长连接。
        """
        if self.is_connected:
            logger.bind(module="mcp.client", event="already_connected").warning(
                f"已连接到 MCP Server: {self._config.name}"
            )
            return

        try:
            if self._config.transport_type == TransportType.STDIO:
                await self._connect_stdio()
            elif self._config.transport_type == TransportType.SSE:
                await self._connect_sse()
            else:
                raise MCPClientError(f"不支持的传输类型: {self._config.transport_type}")

            # 初始化握手
            await self._session.initialize()
            logger.bind(module="mcp.client", event="connected").info(
                f"MCP Server 连接成功: {self._config.name}"
            )
        except (MCPClientError, MCPTransportError) as e:
            # 已知业务异常直接抛出
            await self._cleanup_on_connect_failure()
            raise
        except McpError as e:
            await self._cleanup_on_connect_failure()
            raise MCPClientError(f"连接 MCP Server 失败（协议错误）: {e}") from e
        except (asyncio.TimeoutError, ConnectionError, OSError) as e:
            await self._cleanup_on_connect_failure()
            raise MCPClientError(f"连接 MCP Server 失败: {e}") from e
        except Exception as e:
            await self._cleanup_on_connect_failure()
            raise MCPClientError(f"连接 MCP Server 失败: {e}") from e

    async def _connect_stdio(self) -> None:
        """通过沙箱包装的 stdio 传输建立连接。"""
        if not self._config.command:
            raise MCPClientError("Stdio 模式需要指定启动命令")

        # 安全：使用 sandbox 校验命令路径（防止路径穿越、null 字节注入等）
        _validate_command_path(self._config.command)

        # 构建环境变量：以官方 SDK 的白名单为基础，叠加用户显式指定的环境变量
        # get_default_environment() 返回 PATH/HOME/USER 等安全变量的白名单
        filtered_env: Dict[str, str] = dict(get_default_environment())
        if self._config.env:
            filtered_env.update(self._config.env)

        # 构建 StdioServerParameters
        params = StdioServerParameters(
            command=self._config.command,
            args=list(self._config.args or []),
            env=filtered_env,
        )

        # 安全：沙箱资源限制——限制 CPU/内存/输出大小/子进程数，超时强制终止
        sandbox_limits = SandboxLimits(
            max_cpu_time_seconds=60.0,
            max_memory_mb=1024,  # 1GB
            max_output_size_bytes=10 * 1024 * 1024,  # 10MB
        )

        logger.bind(
            module="mcp.client",
            event="stdio_connect",
            command=self._config.command,
        ).info(f"通过沙箱 stdio 传输启动 MCP Server: {self._config.command}")

        # 手动进入异步上下文管理器（connect/disconnect 模式而非 async with）
        self._transport_ctx = _sandboxed_stdio_client(params, limits=sandbox_limits)
        read_stream, write_stream = await self._transport_ctx.__aenter__()
        self._session_ctx = ClientSession(read_stream, write_stream)
        self._session = await self._session_ctx.__aenter__()

    async def _connect_sse(self) -> None:
        """通过官方 sse_client 建立 SSE 传输连接。"""
        if not self._config.url:
            raise MCPClientError("SSE 模式需要指定服务器地址")

        # 安全：origin 白名单校验（项目特定安全层，官方 SDK 不提供）
        SSETransport._check_origin(self._config.url)

        # 安全：构建认证请求头——合并用户自定义 headers，并附加 auth_token（Bearer 认证）
        sse_headers: Dict[str, str] = dict(self._config.headers or {})
        if self._config.auth_token:
            # 用户显式提供的 Authorization 头优先，未提供时使用 auth_token 生成
            sse_headers.setdefault("Authorization", f"Bearer {self._config.auth_token}")

        logger.bind(
            module="mcp.client",
            event="sse_connect",
            url=self._config.url,
        ).info(f"通过官方 SDK sse_client 连接 MCP Server: {self._config.url}")

        # 手动进入异步上下文管理器
        self._transport_ctx = _mcp_sse_client(self._config.url, headers=sse_headers)
        read_stream, write_stream = await self._transport_ctx.__aenter__()
        self._session_ctx = ClientSession(read_stream, write_stream)
        self._session = await self._session_ctx.__aenter__()

    async def _cleanup_on_connect_failure(self) -> None:
        """连接失败时清理已建立的传输层与会话上下文。"""
        # 按相反顺序退出上下文管理器
        if self._session_ctx is not None:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"清理 session_ctx 时出错: {e}")
            self._session_ctx = None
        if self._transport_ctx is not None:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f"清理 transport_ctx 时出错: {e}")
            self._transport_ctx = None
        self._session = None

    async def disconnect(self) -> None:
        """断开与 MCP Server 的连接，退出官方 SDK 的上下文管理器。"""
        # 按相反顺序退出：先 session，再 transport
        if self._session_ctx is not None:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception as e:
                logger.bind(module="mcp.client", event="session_exit_error").warning(
                    f"退出 session 上下文时出错: {e}"
                )
            self._session_ctx = None
        if self._transport_ctx is not None:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception as e:
                logger.bind(module="mcp.client", event="transport_exit_error").warning(
                    f"退出 transport 上下文时出错: {e}"
                )
            self._transport_ctx = None

        self._session = None
        self._server_info = None
        self._tools = []
        # 断开连接时清除工具和资源缓存
        self.clear_caches()
        logger.bind(module="mcp.client", event="disconnected").info(
            f"已断开 MCP Server: {self._config.name}"
        )

    def cleanup_sync(self) -> None:
        """
        同步方式尽力清理客户端持有的资源。
        在无法等待异步 disconnect 的场景下使用（如 remove_server/rollback_to_snapshot）。

        注意：官方 SDK 的 stdio_client 内部管理子进程生命周期，
        同步清理只能重置内存状态；子进程的优雅终止由 SDK 在 __aexit__ 中处理。
        若需确保子进程立即终止，应在异步上下文中调用 disconnect()。
        """
        self._session = None
        self._session_ctx = None
        self._transport_ctx = None
        self._server_info = None
        self._tools = []
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
        # 优先读取缓存
        cached = _cache_tools.cache_get(self._cache_key)
        if cached is not None:
            return cached
        if self._session is None:
            raise MCPClientError("未连接到 MCP Server")

        try:
            result: ListToolsResult = await self._session.list_tools()
        except McpError as e:
            raise MCPClientError(f"获取工具列表失败（协议错误）: {e}") from e
        except Exception as e:
            raise MCPClientError(f"获取工具列表失败: {e}") from e

        # 转换官方 SDK 的 Tool 类型为项目 MCPTool 类型
        self._tools = [
            MCPTool(
                name=tool.name,
                description=tool.description,
                input_schema=tool.inputSchema,
                server_name=self._config.name,
            )
            for tool in result.tools
        ]
        # 写入 LRU 缓存
        _cache_tools.cache_set(self._cache_key, self._tools)
        return self._tools

    async def call_tool(
        self, tool_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> MCPToolCallResponse:
        """
        调用 MCP Server 上的指定工具。

        :param tool_name: 工具名称
        :param arguments: 调用参数
        :return: 工具调用响应
        """
        if self._session is None:
            raise MCPClientError("未连接到 MCP Server")

        try:
            result: CallToolResult = await self._session.call_tool(
                tool_name,
                arguments or {},
            )
        except McpError as e:
            # 检测会话过期错误码，抛出带 code 属性的异常以便上层检测
            error_code = getattr(e.error, "code", None) if e.error else None
            error_message = getattr(e.error, "message", "未知错误") if e.error else str(e)
            if error_code == _MCP_SESSION_EXPIRED_CODE:
                expired = MCPClientError(f"MCP 会话过期 (code -32001): {error_message}")
                expired.code = error_code  # type: ignore[attr-defined]
                raise expired from e
            raise MCPClientError(f"调用工具失败（协议错误）: {error_message}") from e
        except Exception as e:
            raise MCPClientError(f"调用工具失败: {e}") from e

        # 提取文本内容（MCP 工具调用结果包含 content 数组）
        text_parts: List[str] = []
        for item in result.content:
            if isinstance(item, TextContent):
                text_parts.append(item.text)

        if text_parts:
            return MCPToolCallResponse(
                result="\n".join(text_parts),
                is_error=bool(result.isError),
            )
        # 无文本内容时返回原始 content 的序列化形式
        return MCPToolCallResponse(
            result=[item.model_dump() for item in result.content],
            is_error=bool(result.isError),
        )

    async def list_resources(self) -> List[MCPResource]:
        """
        获取 MCP Server 提供的资源列表。
        结果通过 LRU 缓存，避免重复请求。

        :return: 资源定义列表
        """
        # 优先读取缓存
        cached = _cache_resources.cache_get(self._cache_key)
        if cached is not None:
            return cached
        if self._session is None:
            raise MCPClientError("未连接到 MCP Server")

        try:
            result: ListResourcesResult = await self._session.list_resources()
        except McpError as e:
            raise MCPClientError(f"获取资源列表失败（协议错误）: {e}") from e
        except Exception as e:
            raise MCPClientError(f"获取资源列表失败: {e}") from e

        # 转换官方 SDK 的 Resource 类型为项目 MCPResource 类型
        resources = [
            MCPResource(
                uri=str(res.uri),
                name=res.name,
                description=res.description,
                mime_type=res.mimeType,
            )
            for res in result.resources
        ]
        # 写入 LRU 缓存
        _cache_resources.cache_set(self._cache_key, resources)
        return resources

    async def read_resource(self, uri: str) -> MCPResourceContent:
        """
        读取指定 URI 的资源内容。

        :param uri: 资源 URI（如 file:///path/to/file）
        :return: 资源内容对象
        """
        if self._session is None:
            raise MCPClientError("未连接到 MCP Server")

        try:
            result: ReadResourceResult = await self._session.read_resource(uri)
        except McpError as e:
            raise MCPClientError(f"读取资源失败（协议错误）: {e}") from e
        except Exception as e:
            raise MCPClientError(f"读取资源失败: {e}") from e

        if not result.contents:
            return MCPResourceContent(uri=uri, mime_type=None, text="", blob=None)
        # 取第一个内容块（多数 MCP Server 单次返回单个资源）
        first = result.contents[0]
        # 根据类型提取 text 或 blob
        # 注意：SDK 的 TextResourceContents.uri / BlobResourceContents.uri 是 AnyUrl 类型，
        # 需转换为 str 以匹配 MCPResourceContent.uri: str 字段
        if isinstance(first, TextResourceContents):
            return MCPResourceContent(
                uri=str(first.uri),
                mime_type=first.mimeType,
                text=first.text,
                blob=None,
            )
        if isinstance(first, BlobResourceContents):
            return MCPResourceContent(
                uri=str(first.uri),
                mime_type=first.mimeType,
                text=None,
                blob=first.blob,
            )
        # 未知类型，尝试通用属性访问
        return MCPResourceContent(
            uri=str(getattr(first, "uri", uri)),
            mime_type=getattr(first, "mimeType", None),
            text=getattr(first, "text", None),
            blob=getattr(first, "blob", None),
        )

    async def _send_request(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        内部方法：发送 JSON-RPC 请求并等待响应。

        注意：此方法为向后兼容保留，实际由官方 ClientSession 处理协议层。
        测试用例可通过 mock 此方法控制返回值。

        :param message: JSON-RPC 请求消息
        :return: 响应消息字典
        """
        if self._session is None:
            raise MCPClientError("未连接到 MCP Server")

        method = message.get("method", "")
        params = message.get("params") or {}

        try:
            if method == "tools/list":
                result = await self._session.list_tools()
                return {"result": {"tools": [t.model_dump() for t in result.tools]}}
            elif method == "tools/call":
                tool_result = await self._session.call_tool(
                    params.get("name", ""),
                    params.get("arguments") or {},
                )
                return {
                    "result": {
                        "content": [c.model_dump() for c in tool_result.content],
                        "isError": tool_result.isError,
                    }
                }
            elif method == "resources/list":
                result = await self._session.list_resources()
                return {"result": {"resources": [r.model_dump() for r in result.resources]}}
            elif method == "resources/read":
                read_result = await self._session.read_resource(params.get("uri", ""))
                return {
                    "result": {
                        "contents": [c.model_dump() for c in read_result.contents]
                    }
                }
            elif method == "initialize":
                return {"result": {}}
            else:
                raise MCPClientError(f"不支持的 JSON-RPC 方法: {method}")
        except McpError as e:
            error_obj = e.error
            return {
                "error": {
                    "code": getattr(error_obj, "code", -1),
                    "message": getattr(error_obj, "message", str(e)),
                }
            }


# ===========================================================================
# MCPManager（单例，保持原 API 签名不变）
# ===========================================================================


class MCPManager:
    """
    MCP 管理器，管理多个 MCP Server 的连接、工具发现与调用。
    使用单例模式确保全局唯一实例，通过 threading.RLock 保证创建与初始化都线程安全。
    """

    _instance: Optional["MCPManager"] = None
    _instance_lock = threading.RLock()

    def __new__(cls) -> "MCPManager":
        """单例模式：使用双重检查减少无意义加锁，并确保只创建一次实例。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化管理器内部状态（仅首次创建时执行）。"""
        if getattr(self, "_initialized", False):
            return

        with type(self)._instance_lock:
            if self._initialized:
                return

            self._lock = threading.Lock()
            self._clients: Dict[str, MCPClient] = {}
            self._configs: Dict[str, MCPServerConfig] = {}
            self._config_store = MCPConfigStore()
            self._initialized = True

        logger.bind(module="mcp_integration.manager", event="initialized").info("MCP 管理器已初始化")
        # 启动时尝试从持久化配置恢复
        self._restore_from_persistent_config()

    def add_server(
        self,
        config: MCPServerConfig,
        server_id: Optional[str] = None,
        owner_user_id: Optional[str] = None,
    ) -> str:
        """
        添加 MCP Server 配置并持久化。
        使用 memoize 连接模式创建客户端（key = server_id + config JSON 哈希）。

        :param config: 服务器配置
        :param server_id: 可选的自定义 ID，未指定则自动生成
        :param owner_user_id: 归属用户 ID，用于多用户隔离；非 None 时写入 config.owner_user_id
        :return: 分配的 server_id
        """
        if server_id is None:
            server_id = str(uuid.uuid4())
        # 安全：将 owner_user_id 绑定到 config，持久化时一同写入文件
        if owner_user_id is not None:
            config = config.model_copy(update={"owner_user_id": owner_user_id})
        # 通过 memoize 函数创建客户端，相同 config 在 TTL 内复用同一实例
        cache_key = _make_connection_key(server_id, config)
        config_json = json.dumps(config.model_dump(), sort_keys=True)
        client = _create_mcp_client(cache_key, config_json)
        with self._lock:
            self._configs[server_id] = config
            self._clients[server_id] = client
        # 持久化到配置文件
        self._config_store.set_server(server_id, config.model_dump())
        logger.bind(module="mcp_integration.manager", event="server_added").info(
            f"添加 MCP Server: {config.name} (ID: {server_id}, owner_user_id={owner_user_id})"
        )
        return server_id

    def get_server_owner(self, server_id: str) -> Optional[str]:
        """
        安全：获取指定 MCP Server 的归属用户 ID。
        用于路由层做 IDOR 校验，确保用户只能操作自己的 Server。
        :return: 归属用户 ID；不存在返回 None；旧配置无 owner_user_id 字段也返回 None
        """
        with self._lock:
            config = self._configs.get(server_id)
        if config is None:
            return None
        return config.owner_user_id

    def list_servers_for_user(self, user_id: str) -> List[str]:
        """
        安全：列出指定用户拥有的所有 server_id。
        旧配置（owner_user_id=None）不计入任何用户，仅管理员可清理（暂不开放）。
        """
        with self._lock:
            return [
                sid for sid, cfg in self._configs.items()
                if cfg.owner_user_id == user_id
            ]

    def remove_server(self, server_id: str) -> None:
        """
        移除 MCP Server 配置、断开连接并从持久化存储中删除。
        如果客户端已连接，会先尽力通过 cleanup_sync 清理子进程资源。
        :param server_id: 服务器 ID
        """
        with self._lock:
            if server_id not in self._clients:
                raise MCPClientError(f"未找到 MCP Server: {server_id}")
            client = self._clients.pop(server_id, None)
            self._configs.pop(server_id, None)
        # 尽力清理客户端持有的子进程资源
        if client is not None:
            client.cleanup_sync()
        # 从持久化存储中删除
        self._config_store.remove_server(server_id)
        logger.bind(module="mcp_integration.manager", event="server_removed").info(
            f"已移除 MCP Server: {server_id}"
        )

    async def connect_server(self, server_id: str) -> None:
        """
        连接指定的 MCP Server。
        :param server_id: 服务器 ID
        """
        client = self._get_client(server_id)
        await client.connect()

    async def disconnect_server(self, server_id: str) -> None:
        """
        断开指定的 MCP Server 连接。
        :param server_id: 服务器 ID
        """
        client = self._get_client(server_id)
        await client.disconnect()

    async def get_all_tools(self) -> List[Dict[str, Any]]:
        """
        聚合所有已连接 Server 的工具列表。
        :return: 包含 server_id 信息的工具列表
        """
        all_tools: List[Dict[str, Any]] = []
        # 创建字典快照，避免迭代期间并发修改导致 RuntimeError
        with self._lock:
            clients_snapshot = dict(self._clients)
        for server_id, client in clients_snapshot.items():
            if client.is_connected:
                try:
                    tools = await client.list_tools()
                    for tool in tools:
                        all_tools.append({
                            "server_id": server_id,
                            "server_name": client.config.name,
                            "tool": tool.model_dump(),
                        })
                except MCPClientError as e:
                    logger.bind(
                        module="mcp.manager",
                        event="list_tools_error",
                        server_id=server_id,
                    ).warning(f"获取 Server {server_id} 工具列表失败: {e}")
                    # 失败不静默跳过：以显式 error 条目标记该 Server，结果不消失、调用方可感知
                    all_tools.append({
                        "server_id": server_id,
                        "server_name": client.config.name,
                        "error": f"获取工具列表失败: {e}",
                    })
        return all_tools

    async def call_tool(
        self, server_id: str, tool_name: str, arguments: Optional[Dict[str, Any]] = None
    ) -> MCPToolCallResponse:
        """
        调用指定 Server 上的工具。

        当检测到会话过期错误（HTTP 404 或 JSON-RPC -32001）时：
        1. 清除连接缓存（memoize 缓存）
        2. 清除工具列表缓存（LRU 缓存）
        3. 清除资源列表缓存（LRU 缓存）
        4. 自动重连一次后重试调用
        5. 重连失败则抛出原始异常
        6. 只重试一次，避免无限重试

        :param server_id: 服务器 ID
        :param tool_name: 工具名称
        :param arguments: 调用参数
        :return: 工具调用响应
        """
        client = self._get_client(server_id)
        if not client.is_connected:
            raise MCPClientError(f"MCP Server 未连接: {server_id}")

        try:
            return await client.call_tool(tool_name, arguments)
        except MCPClientError as e:
            # 非会话过期错误直接抛出
            if not is_mcp_session_expired_error(e):
                raise

            # 会话过期，清除所有缓存
            logger.bind(
                module="mcp.manager", event="session_expired", server_id=server_id
            ).warning(f"MCP 会话过期，清除缓存: {server_id}")
            # 1. 清除连接缓存（memoize 缓存）
            _create_mcp_client.cache_clear()
            # 2. 清除工具列表缓存和 3. 资源列表缓存（LRU 缓存）
            client.clear_caches()

            # 自动重连一次，失败则抛出原始异常
            try:
                await client.disconnect()
                await client.connect()
            except (MCPClientError, MCPTransportError, asyncio.TimeoutError, ConnectionError) as reconnect_error:
                logger.bind(
                    module="mcp.manager", event="reconnect_failed", server_id=server_id
                ).warning(f"MCP 重连失败: {reconnect_error}")
                raise e from reconnect_error

            # 重连成功后重试原始调用（只重试一次）
            return await client.call_tool(tool_name, arguments)

    async def get_server_tools(self, server_id: str) -> List[MCPTool]:
        """
        获取指定 Server 的工具列表。
        :param server_id: 服务器 ID
        :return: 工具列表
        """
        client = self._get_client(server_id)
        if not client.is_connected:
            raise MCPClientError(f"MCP Server 未连接: {server_id}")
        return await client.list_tools()

    async def get_server_resources(self, server_id: str) -> List[MCPResource]:
        """
        获取指定 Server 的资源列表。
        :param server_id: 服务器 ID
        :return: 资源列表
        """
        client = self._get_client(server_id)
        if not client.is_connected:
            raise MCPClientError(f"MCP Server 未连接: {server_id}")
        return await client.list_resources()

    async def read_server_resource(self, server_id: str, uri: str) -> MCPResourceContent:
        """
        读取指定 Server 的资源内容。
        :param server_id: 服务器 ID
        :param uri: 资源 URI
        :return: 资源内容对象
        """
        client = self._get_client(server_id)
        if not client.is_connected:
            raise MCPClientError(f"MCP Server 未连接: {server_id}")
        return await client.read_resource(uri)

    async def get_all_resources(self) -> List[Dict[str, Any]]:
        """
        获取所有已连接 Server 的资源列表（聚合）。
        :return: 资源列表，每项包含 server_id 和资源定义
        """
        all_resources: List[Dict[str, Any]] = []
        # 创建快照避免并发修改
        with self._lock:
            clients_snapshot = dict(self._clients)
        for server_id, client in clients_snapshot.items():
            if not client.is_connected:
                continue
            try:
                resources = await client.list_resources()
                for res in resources:
                    all_resources.append({
                        "server_id": server_id,
                        "uri": res.uri,
                        "name": res.name,
                        "description": res.description,
                        "mime_type": res.mime_type,
                    })
            except (MCPClientError, MCPTransportError, asyncio.TimeoutError, ConnectionError) as e:
                logger.bind(
                    module="mcp.manager",
                    event="list_resources_error",
                    server_id=server_id,
                ).warning(f"获取 Server {server_id} 资源列表失败: {e}")
                # 失败不静默跳过：以显式 error 条目标记该 Server，结果不消失、调用方可感知
                all_resources.append({
                    "server_id": server_id,
                    "error": f"获取资源列表失败: {e}",
                })
        return all_resources

    def get_server_status(self, server_id: str) -> Dict[str, Any]:
        """
        获取指定 Server 的连接状态信息。
        :param server_id: 服务器 ID
        :return: 状态信息字典
        """
        client = self._get_client(server_id)
        config = self._configs.get(server_id)
        return {
            "server_id": server_id,
            "name": config.name if config else "unknown",
            "transport_type": config.transport_type.value if config else "unknown",
            "connected": client.is_connected,
            "tools_count": len(client.tools),
        }

    def get_all_servers(self) -> List[Dict[str, Any]]:
        """
        获取所有已配置的 Server 状态列表。
        :return: 服务器状态列表
        """
        servers = []
        # 创建快照避免并发修改
        with self._lock:
            config_ids = list(self._configs.keys())
        for server_id in config_ids:
            servers.append(self.get_server_status(server_id))
        return servers

    def is_server_connected(self, server_id: str) -> bool:
        """
        检查指定 Server 是否已连接。
        :param server_id: 服务器 ID
        :return: 是否已连接
        """
        with self._lock:
            client = self._clients.get(server_id)
        if client is None:
            return False
        return client.is_connected

    def _get_client(self, server_id: str) -> MCPClient:
        """
        获取指定 ID 的客户端实例。
        :param server_id: 服务器 ID
        :return: MCPClient 实例
        :raises MCPClientError: 未找到对应 ID 的客户端
        """
        with self._lock:
            client = self._clients.get(server_id)
        if client is None:
            raise MCPClientError(f"未找到 MCP Server: {server_id}")
        return client

    def _restore_from_persistent_config(self) -> None:
        """启动时从持久化配置文件恢复 Server 配置（不自动连接）。

        整体恢复失败（配置存储读取异常）显式传播：mcp_preheat 启动步骤
        已按 fail-fast 设计（见 main.py），禁止吞掉异常后以"零配置"假成功。

        Raises:
            Exception: 持久化配置读取失败（显式传播）。
        """
        saved_configs = self._config_store.load_all()
        if not saved_configs:
            return
        restored = 0
        for server_id, config_dict in saved_configs.items():
            with self._lock:
                if server_id in self._configs:
                    continue
                try:
                    config = MCPServerConfig(**config_dict)
                    self._configs[server_id] = config
                    self._clients[server_id] = MCPClient(config)
                except (ValueError, TypeError, MCPClientError) as exc:
                    logger.bind(
                        module="mcp.manager", event="restore_error", server_id=server_id
                    ).warning(f"恢复 MCP Server 配置失败: {exc}")
                    continue
            restored += 1
        if restored > 0:
            logger.bind(module="mcp_integration.manager", event="restored").info(
                f"从持久化配置恢复了 {restored} 个 MCP Server"
            )

    def check_hot_reload(self) -> bool:
        """
        检测配置文件是否被外部修改，如果有变更则重新加载并同步内存状态。
        :return: 是否发生了热更新
        """
        new_configs = self._config_store.reload_if_changed()
        if new_configs is None:
            return False

        with self._lock:
            current_ids = set(self._configs.keys())
            new_ids = set(new_configs.keys())

            # 移除已删除的配置——先清理子进程资源再移除
            for removed_id in current_ids - new_ids:
                old_client = self._clients.pop(removed_id, None)
                self._configs.pop(removed_id, None)
                if old_client is not None:
                    old_client.cleanup_sync()
                logger.bind(module="mcp_integration.manager", event="hot_reload_remove").info(
                    f"热更新：移除 Server {removed_id}"
                )

            # 添加新增或更新的配置
            for server_id, config_dict in new_configs.items():
                try:
                    config = MCPServerConfig(**config_dict)
                    if server_id not in self._configs:
                        self._configs[server_id] = config
                        self._clients[server_id] = MCPClient(config)
                        logger.bind(module="mcp_integration.manager", event="hot_reload_add").info(
                            f"热更新：添加 Server {config.name} ({server_id})"
                        )
                    else:
                        # 配置有变更时，更新内存配置并重建客户端
                        old_config = self._configs[server_id]
                        if config != old_config:
                            self._configs[server_id] = config
                            self._clients[server_id] = MCPClient(config)
                            logger.bind(module="mcp_integration.manager", event="hot_reload_update").info(
                                f"热更新：重建 Server {config.name} ({server_id}) 客户端"
                            )
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    logger.bind(
                        module="mcp.manager", event="hot_reload_error", server_id=server_id
                    ).warning(f"热更新配置解析失败: {exc}")

        return True

    def list_snapshots(self) -> list:
        """列出可用的配置版本快照。"""
        return self._config_store.list_snapshots()

    def create_snapshot(self, label: str = "") -> Optional[str]:
        """手动创建一个配置快照。"""
        return self._config_store.create_manual_snapshot(label)

    def rollback_to_snapshot(self, snapshot_name: str) -> Dict[str, Dict[str, Any]]:
        """
        回滚到指定版本快照，并同步内存状态。
        回滚前会先清理所有现有客户端的子进程资源。
        :return: 回滚后的配置
        """
        new_configs = self._config_store.rollback_to_snapshot(snapshot_name)
        # 同步内存状态——先清理旧客户端资源再清空
        with self._lock:
            old_clients = dict(self._clients)
            self._clients.clear()
            self._configs.clear()
        for client in old_clients.values():
            client.cleanup_sync()
        self._restore_from_persistent_config()
        logger.bind(module="mcp_integration.manager", event="rollback").info(
            f"已回滚到快照: {snapshot_name}"
        )
        return new_configs
