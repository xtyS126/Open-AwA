"""
LSP 协议代理 — 管理 LSP 子进程并转发 JSON-RPC 请求。
支持 Python (pylsp) / TypeScript (typescript-language-server) 等语言服务器。
"""
import asyncio
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from loguru import logger


@dataclass
class LSPServerConfig:
    """LSP 服务器配置。"""
    language: str
    command: list[str]
    file_extensions: list[str] = field(default_factory=list)
    initialization_options: dict = field(default_factory=dict)


# 预定义 LSP 服务器配置
PRESET_SERVERS: dict[str, LSPServerConfig] = {
    "python": LSPServerConfig(
        language="python",
        command=["pylsp"],
        file_extensions=[".py"],
        initialization_options={},
    ),
    "typescript": LSPServerConfig(
        language="typescript",
        command=["typescript-language-server", "--stdio"],
        file_extensions=[".ts", ".tsx", ".js", ".jsx"],
        initialization_options={},
    ),
    "rust": LSPServerConfig(
        language="rust",
        command=["rust-analyzer"],
        file_extensions=[".rs"],
        initialization_options={},
    ),
    "go": LSPServerConfig(
        language="go",
        command=["gopls"],
        file_extensions=[".go"],
        initialization_options={},
    ),
}


class LSPProxy:
    """
    LSP 代理管理器。
    管理多个语言服务器的生命周期，转发 JSON-RPC 请求/响应。
    """

    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir).resolve()
        self._servers: dict[str, asyncio.subprocess.Process] = {}
        self._server_configs: dict[str, LSPServerConfig] = {}
        self._message_id: int = 0
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._reader_tasks: dict[str, asyncio.Task] = {}

    def is_available(self, language: str) -> bool:
        """检查指定语言的 LSP 服务器是否可用。"""
        config = PRESET_SERVERS.get(language)
        if not config:
            return False
        try:
            result = subprocess.run(
                config.command[0:1] + ["--version"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    async def start_server(self, language: str) -> bool:
        """
        启动指定语言的 LSP 服务器。
        """
        if language in self._servers:
            return True

        config = PRESET_SERVERS.get(language)
        if not config:
            logger.error(f"未知语言: {language}")
            return False

        # 检查命令是否可用
        if not self.is_available(language):
            logger.error(f"LSP 服务器不可用: {config.command[0]}")
            return False

        try:
            process = await asyncio.create_subprocess_exec(
                *config.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.project_dir),
            )

            self._servers[language] = process
            self._server_configs[language] = config

            # 启动读取循环
            task = asyncio.create_task(self._read_responses(language, process))
            self._reader_tasks[language] = task

            # 发送初始化请求
            init_result = await self._send_initialize(language, process)
            if init_result:
                await self._send_initialized(language, process)
                logger.bind(event="lsp_started", language=language).info("LSP 服务器已启动")
                return True
            else:
                await self.stop_server(language)
                return False

        except Exception as e:
            logger.bind(event="lsp_start_error", language=language, error=str(e)).error("LSP 启动失败")
            return False

    async def stop_server(self, language: str):
        """停止 LSP 服务器。"""
        process = self._servers.pop(language, None)
        self._server_configs.pop(language, None)
        task = self._reader_tasks.pop(language, None)

        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if process:
            try:
                # 发送 shutdown 请求
                self._message_id += 1
                shutdown_msg = json.dumps({
                    "jsonrpc": "2.0",
                    "id": self._message_id,
                    "method": "shutdown",
                })
                process.stdin.write((shutdown_msg + "\r\n").encode())
                await process.stdin.drain()

                # 发送 exit 通知
                exit_msg = json.dumps({"jsonrpc": "2.0", "method": "exit"})
                process.stdin.write((exit_msg + "\r\n").encode())
                await process.stdin.drain()

                await asyncio.wait_for(process.wait(), timeout=5)
            except (asyncio.TimeoutError, BrokenPipeError, ConnectionResetError):
                process.kill()
                await process.wait()

            logger.bind(event="lsp_stopped", language=language).info("LSP 服务器已停止")

    async def request(self, language: str, method: str, params: Any = None) -> dict:
        """
        向 LSP 服务器发送 JSON-RPC 请求并等待响应。
        """
        process = self._servers.get(language)
        if not process or process.returncode is not None:
            return {"error": f"LSP 服务器未运行: {language}"}

        self._message_id += 1
        msg_id = self._message_id

        request = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params or {},
        }

        # 创建 pending future
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[msg_id] = future

        try:
            payload = json.dumps(request)
            header = f"Content-Length: {len(payload)}\r\n\r\n"
            process.stdin.write((header + payload).encode())
            await process.stdin.drain()

            result = await asyncio.wait_for(future, timeout=30)
            return result
        except asyncio.TimeoutError:
            return {"error": "LSP 请求超时"}
        except (BrokenPipeError, ConnectionResetError):
            await self.stop_server(language)
            return {"error": "LSP 连接已断开"}
        finally:
            self._pending_requests.pop(msg_id, None)

    async def notify(self, language: str, method: str, params: Any = None):
        """向 LSP 服务器发送通知（无需响应）。"""
        process = self._servers.get(language)
        if not process or process.returncode is not None:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }

        try:
            payload = json.dumps(notification)
            header = f"Content-Length: {len(payload)}\r\n\r\n"
            process.stdin.write((header + payload).encode())
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            await self.stop_server(language)

    async def goto_definition(self, language: str, file_uri: str, line: int, character: int) -> dict:
        """跳转到定义。"""
        return await self.request(language, "textDocument/definition", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character},
        })

    async def find_references(self, language: str, file_uri: str, line: int, character: int) -> dict:
        """查找引用。"""
        return await self.request(language, "textDocument/references", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": True},
        })

    async def hover(self, language: str, file_uri: str, line: int, character: int) -> dict:
        """悬停信息。"""
        return await self.request(language, "textDocument/hover", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character},
        })

    async def completion(self, language: str, file_uri: str, line: int, character: int) -> dict:
        """代码补全。"""
        return await self.request(language, "textDocument/completion", {
            "textDocument": {"uri": file_uri},
            "position": {"line": line, "character": character},
        })

    async def open_document(self, language: str, file_uri: str, text: str):
        """通知 LSP 打开文档。"""
        config = self._server_configs.get(language)
        if not config:
            return
        ext = Path(file_uri).suffix
        lang_id = language if ext in config.file_extensions else language

        await self.notify(language, "textDocument/didOpen", {
            "textDocument": {
                "uri": file_uri,
                "languageId": lang_id,
                "version": 1,
                "text": text,
            },
        })

    def get_running_servers(self) -> list[dict]:
        """获取运行中的 LSP 服务器列表。"""
        return [
            {"language": lang, "available": True}
            for lang in self._servers
        ]

    def detect_language(self, file_path: str) -> Optional[str]:
        """根据文件扩展名检测语言。"""
        ext = Path(file_path).suffix.lower()
        for lang, config in PRESET_SERVERS.items():
            if ext in config.file_extensions:
                return lang
        return None

    # ---- 内部方法 ----

    async def _send_initialize(self, language: str, process: asyncio.subprocess.Process) -> bool:
        """发送 LSP initialize 请求。"""
        config = self._server_configs.get(language)
        if not config:
            return False

        root_uri = self.project_dir.as_uri()

        try:
            result = await self.request(language, "initialize", {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "capabilities": {
                    "textDocument": {
                        "hover": {"contentFormat": ["markdown", "plaintext"]},
                        "completion": {"completionItem": {"snippetSupport": True}},
                        "definition": {"linkSupport": True},
                        "references": {},
                        "documentSymbol": {},
                    },
                    "workspace": {"symbol": {}},
                },
                "initializationOptions": config.initialization_options,
            })
            return "error" not in result
        except Exception:
            return False

    async def _send_initialized(self, language: str, process: asyncio.subprocess.Process):
        """发送 initialized 通知。"""
        await self.notify(language, "initialized", {})

    async def _read_responses(self, language: str, process: asyncio.subprocess.Process):
        """持续读取 LSP 服务器的响应。"""
        buffer = b""
        try:
            while process.returncode is None:
                try:
                    chunk = await asyncio.wait_for(
                        process.stdout.read(4096), timeout=1
                    )
                    if not chunk:
                        break
                    buffer += chunk

                    # 解析 LSP 头部格式的消息
                    while b"\r\n\r\n" in buffer:
                        header_end = buffer.index(b"\r\n\r\n")
                        header = buffer[:header_end].decode()
                        buffer = buffer[header_end + 4:]

                        # 解析 Content-Length
                        content_length = 0
                        for line in header.split("\r\n"):
                            if line.lower().startswith("content-length:"):
                                content_length = int(line.split(":")[1].strip())
                                break

                        if content_length > 0 and len(buffer) >= content_length:
                            payload = buffer[:content_length].decode()
                            buffer = buffer[content_length:]

                            try:
                                msg = json.loads(payload)
                                msg_id = msg.get("id")
                                if msg_id and msg_id in self._pending_requests:
                                    self._pending_requests[msg_id].set_result(msg.get("result", msg))
                            except json.JSONDecodeError:
                                pass
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
        except Exception:
            pass
        finally:
            logger.bind(event="lsp_reader_stopped", language=language).info("LSP 读取循环已结束")
