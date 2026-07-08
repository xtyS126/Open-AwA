"""
LSP 协议代理 — 基于 multilspy（Microsoft 开源）封装多语言 LSP 客户端。
支持 Python / TypeScript / JavaScript / Rust / Go 等语言服务器，
由 multilspy 统一管理 JSON-RPC 通信与 server 进程生命周期，
替代原先自管的 Content-Length framing 与 PRESET_SERVERS 配置。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from loguru import logger

# multilspy 是可选依赖：缺失时降级为不可用状态，避免阻塞后端启动
try:
    from multilspy import LanguageServer
    from multilspy.multilspy_config import Language, MultilspyConfig
    from multilspy.multilspy_exceptions import MultilspyException
    from multilspy.multilspy_logger import MultilspyLogger

    _MULTILSPY_AVAILABLE = True
except ImportError:  # multilspy 未安装时优雅降级
    LanguageServer = None  # type: ignore[assignment]
    MultilspyConfig = None  # type: ignore[assignment]
    Language = None  # type: ignore[assignment]
    MultilspyLogger = None  # type: ignore[assignment]
    MultilspyException = Exception  # type: ignore[assignment]
    _MULTILSPY_AVAILABLE = False


# 文件扩展名 → multilspy 语言标识映射
# multilspy Language 枚举值：python / typescript / javascript / rust / go / java / kotlin / csharp / ruby / dart
_LANGUAGE_EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".rb": "ruby",
    ".dart": "dart",
}


def _is_language_supported(language: str) -> bool:
    """检查 multilspy 是否支持指定语言。"""
    if not _MULTILSPY_AVAILABLE:
        return False
    try:
        Language(language)  # type: ignore[misc]
        return True
    except (ValueError, TypeError):
        return False


class LSPProxy:
    """
    LSP 代理管理器（基于 multilspy）。

    管理多个语言服务器的生命周期，转发 hover / definition / references 等请求。
    对外保留原 API 签名（hover / goto_definition / find_references / completion /
    open_document / request / notify / start_server / stop_server / is_available /
    get_running_servers / detect_language），内部由 multilspy.LanguageServer 提供实现。
    """

    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir).resolve()
        # language -> LanguageServer 实例
        self._servers: dict[str, Any] = {}
        # language -> start_server 异步上下文管理器（用于显式 __aexit__ 关闭）
        self._contexts: dict[str, Any] = {}

    def is_available(self, language: str) -> bool:
        """检查指定语言的 LSP 服务器是否可用。

        multilspy 缺失或语言不在支持列表中时返回 False。
        注：multilspy 会按需自动下载/启动语言 server 二进制，
        此处仅校验语言支持范围，不保证运行期一定可用。
        """
        return _is_language_supported(language)

    async def start_server(self, language: str) -> bool:
        """启动指定语言的 LSP 服务器（multilspy 管理 server 进程）。"""
        if not _MULTILSPY_AVAILABLE:
            logger.bind(
                event="lsp_unavailable", reason="multilspy_not_installed"
            ).warning("multilspy 未安装，LSP 服务器无法启动")
            return False

        if language in self._servers:
            return True

        if not _is_language_supported(language):
            logger.bind(
                event="lsp_unsupported_language", language=language
            ).error(f"multilspy 不支持的语言: {language}")
            return False

        try:
            config = MultilspyConfig.from_dict({"code_language": language})
            lsp_logger = MultilspyLogger()
            server = LanguageServer.create(
                config, lsp_logger, str(self.project_dir)
            )
            # start_server 返回 @asynccontextmanager 装饰的异步上下文管理器，
            # 显式 __aenter__ 触发 server 进程启动，__aexit__ 触发关闭
            ctx = server.start_server()
            await ctx.__aenter__()
            self._servers[language] = server
            self._contexts[language] = ctx
            logger.bind(event="lsp_started", language=language).info(
                "LSP 服务器已启动"
            )
            return True
        except MultilspyException as exc:
            # multilspy 抛出的具体异常，记录后返回 False，避免影响调用方
            logger.bind(
                event="lsp_start_error", language=language, error=str(exc)
            ).error("LSP 启动失败")
            return False
        except Exception as exc:
            # 兜底：捕获未预期异常并记录，避免阻塞调用方
            logger.bind(
                event="lsp_start_error", language=language, error=str(exc)
            ).error("LSP 启动失败（未预期异常）")
            return False

    async def stop_server(self, language: str) -> None:
        """停止 LSP 服务器。"""
        ctx = self._contexts.pop(language, None)
        self._servers.pop(language, None)
        if ctx is None:
            return
        try:
            await ctx.__aexit__(None, None, None)
        except Exception as exc:
            logger.bind(
                event="lsp_stop_error", language=language, error=str(exc)
            ).warning("LSP 服务器关闭异常")
        logger.bind(event="lsp_stopped", language=language).info(
            "LSP 服务器已停止"
        )

    async def request(self, language: str, method: str, params: Any = None) -> dict:
        """向 LSP 服务器发送 JSON-RPC 请求并等待响应。

        multilspy 不暴露通用 JSON-RPC 接口，此处按 method 路由到具体 request_* 方法。
        未知 method 返回错误字典，保持与原 API 兼容（返回 dict）。
        """
        server = self._servers.get(language)
        if server is None:
            return {"error": f"LSP 服务器未运行: {language}"}

        params = params or {}
        text_document = params.get("textDocument", {}) or {}
        file_uri = text_document.get("uri", "")
        position = params.get("position", {}) or {}
        line = int(position.get("line", 0))
        character = int(position.get("character", 0))

        rel_path = self._uri_to_relative_path(file_uri)
        if rel_path is None:
            return {"error": f"无法解析文件 URI 或路径越权: {file_uri}"}

        try:
            if method == "textDocument/definition":
                result = await server.request_definition(rel_path, line, character)
                return {"result": self._serialize(result)}
            if method == "textDocument/references":
                result = await server.request_references(rel_path, line, character)
                return {"result": self._serialize(result)}
            if method == "textDocument/hover":
                result = await server.request_hover(rel_path, line, character)
                return {"result": self._serialize(result)}
            if method == "textDocument/completion":
                result = await server.request_completions(rel_path, line, character)
                return {"result": self._serialize(result)}
            if method == "textDocument/documentSymbol":
                result = await server.request_document_symbols(rel_path)
                return {"result": self._serialize(result)}
            return {"error": f"multilspy 不支持的 method: {method}"}
        except AssertionError as exc:
            # multilspy 在 LSP 返回 None（如光标位置无定义/引用）时以
            # `assert False, "Unexpected response from Language Server: None"` 抛出，
            # 此处视为"无结果"而非错误，返回 result=None 以匹配原语义
            logger.bind(
                event="lsp_no_result",
                language=language,
                method=method,
                error=str(exc),
            ).debug("LSP 请求无结果")
            return {"result": None}
        except MultilspyException as exc:
            # multilspy 具体异常：返回结构化错误，便于上层展示
            logger.bind(
                event="lsp_request_error",
                language=language,
                method=method,
                error=str(exc),
            ).warning("LSP 请求失败")
            return {"error": f"LSP 请求失败: {exc}"}
        except Exception as exc:
            # 兜底：记录未预期异常，避免单次请求异常拖垮整条调用链
            logger.bind(
                event="lsp_request_error",
                language=language,
                method=method,
                error=str(exc),
            ).error("LSP 请求异常（未预期）")
            return {"error": f"LSP 请求异常: {exc}"}

    async def notify(self, language: str, method: str, params: Any = None) -> None:
        """向 LSP 服务器发送通知。

        multilspy 内部自动管理 textDocument/didOpen / didChange / didClose 等通知，
        此处保留方法签名以兼容旧调用方，实际为空实现。
        """
        return None

    async def goto_definition(
        self, language: str, file_uri: str, line: int, character: int
    ) -> dict:
        """跳转到定义。"""
        return await self.request(
            language,
            "textDocument/definition",
            {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character},
            },
        )

    async def find_references(
        self, language: str, file_uri: str, line: int, character: int
    ) -> dict:
        """查找引用。"""
        return await self.request(
            language,
            "textDocument/references",
            {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character},
            },
        )

    async def hover(
        self, language: str, file_uri: str, line: int, character: int
    ) -> dict:
        """悬停信息。"""
        return await self.request(
            language,
            "textDocument/hover",
            {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character},
            },
        )

    async def completion(
        self, language: str, file_uri: str, line: int, character: int
    ) -> dict:
        """代码补全。"""
        return await self.request(
            language,
            "textDocument/completion",
            {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character},
            },
        )

    async def open_document(
        self, language: str, file_uri: str, text: str
    ) -> None:
        """通知 LSP 打开文档。

        multilspy 在 request_* 内部按需打开文件，此处保留签名兼容旧调用方。
        """
        return None

    def get_running_servers(self) -> list[dict]:
        """获取运行中的 LSP 服务器列表。"""
        return [{"language": lang, "available": True} for lang in self._servers]

    def detect_language(self, file_path: str) -> Optional[str]:
        """根据文件扩展名检测语言。"""
        ext = Path(file_path).suffix.lower()
        return _LANGUAGE_EXTENSION_MAP.get(ext)

    # ---- 内部方法 ----

    def _uri_to_relative_path(self, file_uri: str) -> Optional[str]:
        """将 file:// URI 或绝对路径转换为相对项目根目录的 POSIX 风格路径。

        multilspy 的 request_* 方法要求传入相对 repository_root_path 的路径。
        路径越权（不在项目目录内）时返回 None。
        """
        if not file_uri:
            return None

        if file_uri.startswith("file://"):
            try:
                parsed = urlparse(file_uri)
                abs_path = unquote(parsed.path)
                # Windows 下 file:///D:/foo 解析后为 /D:/foo，前导斜杠需剥离，
                # 否则 Path('/D:/foo') 会被当作当前盘符根目录，导致 relative_to 失败
                if (
                    len(abs_path) >= 3
                    and abs_path[0] == "/"
                    and abs_path[1].isalpha()
                    and abs_path[2] == ":"
                ):
                    abs_path = abs_path[1:]
            except (ValueError, TypeError):
                return None
        else:
            abs_path = file_uri

        try:
            abs_path_obj = Path(abs_path).resolve()
            rel = abs_path_obj.relative_to(self.project_dir)
            # 统一使用正斜杠（multilspy 内部以 POSIX 风格管理路径）
            return rel.as_posix()
        except (ValueError, OSError):
            return None

    @staticmethod
    def _serialize(obj: Any) -> Any:
        """将 multilspy 返回的 TypedDict / Enum / 自定义对象转为可 JSON 序列化的原生类型。"""
        if obj is None:
            return None
        if isinstance(obj, list):
            return [LSPProxy._serialize(item) for item in obj]
        if isinstance(obj, tuple):
            return [LSPProxy._serialize(item) for item in obj]
        if isinstance(obj, dict):
            return {key: LSPProxy._serialize(val) for key, val in obj.items()}
        # 基本类型直接返回
        if isinstance(obj, (str, int, float, bool)):
            return obj
        # Enum（含 IntEnum）取 value
        from enum import Enum

        if isinstance(obj, Enum):
            return obj.value
        # 其他对象：取 __dict__ 中的非私有字段
        if hasattr(obj, "__dict__"):
            return {
                key: LSPProxy._serialize(val)
                for key, val in vars(obj).items()
                if not key.startswith("_")
            }
        return str(obj)
