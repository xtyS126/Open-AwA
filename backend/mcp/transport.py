"""
MCP 传输层实现模块，提供 Stdio 和 SSE 两种传输方式。
Stdio 通过子进程 stdin/stdout 通信，SSE 通过 HTTP 长连接与远程 Server 通信。
"""

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from loguru import logger


# 默认超时时间（秒）
DEFAULT_TIMEOUT = 30


class MCPTransportError(Exception):
    """MCP 传输层异常"""
    pass


class MCPTransport(ABC):
    """MCP 传输层抽象基类，定义通信接口"""

    @abstractmethod
    async def connect(self) -> None:
        """建立连接"""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        ...

    @abstractmethod
    async def send(self, message: Dict[str, Any]) -> None:
        """发送消息"""
        ...

    @abstractmethod
    async def receive(self, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """接收消息"""
        ...

    async def send_and_receive(self, message: Dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """
        发送请求并接收响应的统一方法。
        默认实现依次调用 send + receive，子类可覆写以优化。
        """
        await self.send(message)
        return await self.receive(timeout)

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """当前是否已连接"""
        ...


class StdioTransport(MCPTransport):
    """
    Stdio 传输层实现。
    通过 subprocess 启动 MCP Server 进程，使用 stdin/stdout 进行 JSON-RPC 通信。
    """

    def __init__(self, command: str, args: Optional[list] = None, env: Optional[Dict[str, str]] = None):
        """
        初始化 Stdio 传输层。
        :param command: 启动命令
        :param args: 命令参数列表
        :param env: 环境变量
        """
        self._command = command
        self._args = args or []
        self._env = env
        self._process: Optional[asyncio.subprocess.Process] = None
        self._connected = False
        self._stderr_task: Optional[asyncio.Task] = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._process is not None and self._process.returncode is None

    async def connect(self) -> None:
        """启动子进程并建立 stdio 通信"""
        if self._connected:
            return
        try:
            import os
            # 过滤敏感环境变量，防止 API key、数据库密码等泄露给 MCP 子进程
            SENSITIVE_ENV_PATTERNS = (
                "KEY", "SECRET", "PASSWORD", "TOKEN", "PASSWD", "CREDENTIAL",
                "DATABASE_URL", "DB_URL", "REDIS_URL", "SENTRY_DSN",
            )
            full_env = {}
            for env_key, env_value in os.environ.items():
                is_sensitive = any(
                    pattern in env_key.upper() for pattern in SENSITIVE_ENV_PATTERNS
                )
                if not is_sensitive:
                    full_env[env_key] = env_value
            # 用户显式指定的环境变量优先级最高
            if self._env:
                full_env.update(self._env)

            cmd = [self._command] + self._args
            logger.bind(module="mcp.transport", event="stdio_connect").info(
                f"启动 MCP Server 进程: {' '.join(cmd)}"
            )
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=full_env,
            )
            self._connected = True
            # 启动后台任务持续读取 stderr，防止缓冲区满导致子进程阻塞
            self._stderr_task = asyncio.create_task(self._drain_stderr())
            logger.bind(module="mcp.transport", event="stdio_connected").info(
                f"MCP Server 进程已启动，PID: {self._process.pid}"
            )
        except FileNotFoundError:
            raise MCPTransportError(f"启动命令未找到: {self._command}")
        except Exception as e:
            raise MCPTransportError(f"启动 MCP Server 进程失败: {e}")

    async def _drain_stderr(self) -> None:
        """持续读取子进程 stderr 并记录日志，防止缓冲区满导致进程阻塞"""
        try:
            while self._process and self._process.stderr:
                line = await self._process.stderr.readline()
                if not line:
                    break
                stderr_text = line.decode("utf-8", errors="replace").strip()
                if stderr_text:
                    logger.bind(module="mcp.transport", event="stderr").debug(
                        f"MCP Server stderr: {stderr_text}"
                    )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.bind(module="mcp.transport", event="stderr_error").warning(
                f"读取 stderr 时出错: {e}"
            )

    async def disconnect(self) -> None:
        """终止子进程并断开连接"""
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None
        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            except Exception as e:
                logger.bind(module="mcp.transport", event="stdio_disconnect_error").warning(
                    f"断开 stdio 连接时出错: {e}"
                )
            finally:
                self._process = None
                self._connected = False
                logger.bind(module="mcp.transport", event="stdio_disconnected").info(
                    "MCP Server 进程已终止"
                )

    async def send(self, message: Dict[str, Any]) -> None:
        """
        向子进程 stdin 发送 JSON-RPC 消息。
        消息以换行符分隔。
        """
        if not self.is_connected or self._process is None or self._process.stdin is None:
            raise MCPTransportError("未连接到 MCP Server")
        try:
            data = json.dumps(message) + "\n"
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as e:
            raise MCPTransportError(f"发送消息失败: {e}")

    async def receive(self, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """
        从子进程 stdout 读取 JSON-RPC 响应消息。
        :param timeout: 超时时间（秒）
        :return: 解析后的消息字典
        """
        if not self.is_connected or self._process is None or self._process.stdout is None:
            raise MCPTransportError("未连接到 MCP Server")
        try:
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=timeout,
            )
            if not line:
                raise MCPTransportError("MCP Server 进程已关闭输出流")
            return json.loads(line.decode("utf-8").strip())
        except asyncio.TimeoutError:
            raise MCPTransportError(f"接收消息超时（{timeout}秒）")
        except json.JSONDecodeError as e:
            raise MCPTransportError(f"解析响应 JSON 失败: {e}")


class SSETransport(MCPTransport):
    """
    SSE 传输层实现。
    通过 HTTP SSE 连接远程 MCP Server，使用 httpx 异步客户端。
    """

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        """
        初始化 SSE 传输层。
        :param url: MCP Server SSE 端点地址
        :param headers: 额外请求头
        """
        self._url = url.rstrip("/")
        self._headers = headers or {}
        self._connected = False
        self._client = None
        self._message_endpoint: Optional[str] = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    async def connect(self) -> None:
        """建立 HTTP SSE 连接"""
        if self._connected:
            return
        try:
            import httpx
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(DEFAULT_TIMEOUT))
            # 通过 GET 请求建立 SSE 连接，获取消息端点
            self._message_endpoint = f"{self._url}/message"
            self._connected = True
            logger.bind(module="mcp.transport", event="sse_connected").info(
                f"SSE 连接已建立: {self._url}"
            )
        except ImportError:
            raise MCPTransportError("SSE 传输需要 httpx 库，请执行: pip install httpx")
        except Exception as e:
            raise MCPTransportError(f"建立 SSE 连接失败: {e}")

    async def disconnect(self) -> None:
        """关闭 HTTP 客户端连接"""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.bind(module="mcp.transport", event="sse_disconnect_error").warning(
                    f"关闭 SSE 连接时出错: {e}"
                )
            finally:
                self._client = None
                self._connected = False
                self._message_endpoint = None
                logger.bind(module="mcp.transport", event="sse_disconnected").info(
                    "SSE 连接已关闭"
                )

    async def send(self, message: Dict[str, Any]) -> None:
        """
        通过 HTTP POST 发送 JSON-RPC 消息到 MCP Server。
        """
        if not self.is_connected or self._client is None or self._message_endpoint is None:
            raise MCPTransportError("未连接到远程 MCP Server")
        try:
            response = await self._client.post(
                self._message_endpoint,
                json=message,
                headers=self._headers,
            )
            response.raise_for_status()
        except Exception as e:
            raise MCPTransportError(f"SSE 发送消息失败: {e}")

    async def receive(self, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """
        SSE 模式下不支持独立接收。
        若调用方未使用 send_and_receive，返回明确错误字典以兼容接口契约。
        """
        raise MCPTransportError(
            "SSE 模式下 receive() 不可单独调用，请使用 send_and_receive() 方法"
        )

    async def send_and_receive(self, message: Dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """
        SSE 模式下发送请求并接收响应的统一方法。
        :param message: JSON-RPC 请求消息
        :param timeout: 超时时间
        :return: 解析后的响应字典
        """
        if not self.is_connected or self._client is None or self._message_endpoint is None:
            raise MCPTransportError("未连接到远程 MCP Server")
        try:
            import httpx
            response = await self._client.post(
                self._message_endpoint,
                json=message,
                headers=self._headers,
                timeout=httpx.Timeout(timeout),
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise MCPTransportError(f"SSE 请求失败: {e}")
