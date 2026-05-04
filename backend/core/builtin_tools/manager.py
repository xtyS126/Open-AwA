"""
内置工具管理器。
负责懒加载文件管理、终端执行和网页搜索工具实例，
并对外暴露 OpenAI 兼容的 function calling 工具定义。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger


# 内置工具名 → (管理器内部工具名, action) 映射
BUILTIN_TOOL_ACTION_MAP: Dict[str, tuple[str, str]] = {
    "read_file": ("file_manager", "read_file"),
    "write_file": ("file_manager", "write_file"),
    "list_files": ("file_manager", "list_files"),
    "delete_file": ("file_manager", "delete_file"),
    "file_exists": ("file_manager", "file_exists"),
    "create_directory": ("file_manager", "create_directory"),
    "run_command": ("terminal_executor", "run_command"),
    "get_system_status": ("terminal_executor", "get_status"),
    "web_search": ("web_search", "search"),
    "fetch_url": ("web_search", "fetch_url"),
    "local_search": ("local_search", "search"),
    "index_document": ("local_search", "index"),
    "index_directory": ("local_search", "index_directory"),
    "remove_document": ("local_search", "remove"),
    "search_stats": ("local_search", "stats"),
    "memory_remember": ("memory_manager", "remember"),
    "memory_recall": ("memory_manager", "recall"),
    "memory_forget": ("memory_manager", "forget"),
    "memory_list": ("memory_manager", "list"),
    "memory_stats": ("memory_manager", "stats"),
}

# 旧式 API（通过 tools/registry.py 和 workflow）使用的 action 到内部 tool_name 的反向映射
LEGACY_TOOL_ACTION_MAP: Dict[str, str] = {
    "file_manager": "file_manager",
    "terminal_executor": "terminal_executor",
    "web_search": "web_search",
    "local_search": "local_search",
}

# 内置工具的定义（OpenAI function calling 格式）
BUILTIN_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "builtin_read_file",
            "description": "读取指定路径的文件内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要读取的文件路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_write_file",
            "description": "将内容写入指定路径的文件，会自动创建父目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要写入的文件路径"},
                    "content": {"type": "string", "description": "要写入的内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_list_files",
            "description": "列出指定目录中的文件和子目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要列出的目录路径"},
                    "pattern": {
                        "type": "string",
                        "description": "文件匹配模式，默认为 *",
                        "default": "*",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_delete_file",
            "description": "删除指定路径的文件或目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的文件或目录路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_file_exists",
            "description": "检查指定路径的文件或目录是否存在",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要检查的文件或目录路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_create_directory",
            "description": "创建目录（含父目录）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要创建的目录路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_run_command",
            "description": "在受控终端环境中执行命令并返回输出",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的shell命令"},
                    "working_dir": {
                        "type": "string",
                        "description": "命令执行的工作目录（可选）",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "超时时间（秒），默认30",
                        "default": 30,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_get_system_status",
            "description": "获取当前系统状态信息（操作系统、Python版本、工作目录等）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_web_search",
            "description": "使用搜索引擎搜索网页内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数，默认10",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_local_search",
            "description": "在本地索引中搜索网页和文档内容（离线搜索，无需联网）",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数，默认20",
                        "default": 20,
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["tfidf", "exact", "prefix"],
                        "description": "搜索模式",
                        "default": "tfidf",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_index_document",
            "description": "将文档添加到本地搜索索引中",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "文档唯一标识"},
                    "title": {"type": "string", "description": "文档标题"},
                    "url": {"type": "string", "description": "文档URL"},
                    "content": {"type": "string", "description": "文档文本内容"},
                },
                "required": ["id", "title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_memory_remember",
            "description": "将一段重要信息存入长期记忆，下次对话时可通过 memory_recall 检索。适合存储用户偏好、决策结果、重要上下文等",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要记住的内容"},
                    "importance": {
                        "type": "number",
                        "description": "重要度 0.0-1.0，默认 0.5",
                        "default": 0.5,
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_memory_recall",
            "description": "根据关键词检索长期记忆（混合搜索：向量 + 关键词），返回匹配的记忆列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，默认 5，最大 20",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_memory_forget",
            "description": "删除指定 ID 的长期记忆",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "integer", "description": "要删除的记忆 ID"},
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_memory_list",
            "description": "列出最近存入的长期记忆摘要",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回条数，默认 10，最大 50",
                        "default": 10,
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "是否包含已归档记忆，默认 false",
                        "default": False,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_memory_stats",
            "description": "查看当前记忆系统的整体统计信息（总量、活跃数、归档数、平均置信度等）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class BuiltInToolManager:
    """
    内置工具管理器。
    对外统一暴露工具定义查询、工具执行与工具列表能力。
    """

    def __init__(self):
        self._instances: Dict[str, Any] = {}

    async def _initialize_tool(self, tool_name: str, config: Optional[Dict[str, Any]] = None) -> Any:
        """懒加载工具实例。config 仅首次初始化时生效。"""
        if tool_name in self._instances and not config:
            return self._instances[tool_name]

        if tool_name == "file_manager":
            from .file_manager import FileManagerSkill

            instance = FileManagerSkill(config or {})
        elif tool_name == "terminal_executor":
            from .terminal_executor import TerminalExecutorSkill

            instance = TerminalExecutorSkill(config or {})
        elif tool_name == "web_search":
            from .web_search import WebSearchSkill

            instance = WebSearchSkill(config or {})
        elif tool_name == "local_search":
            from .local_search import LocalSearchEngine

            instance = LocalSearchEngine(config or {})
        elif tool_name == "memory_manager":
            from .memory_tools import MemoryTools

            instance = MemoryTools()
        else:
            raise ValueError(f"未知内置工具: {tool_name}")

        await instance.initialize()
        self._instances[tool_name] = instance
        return instance

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """返回 OpenAI 兼容的 function calling 工具定义列表。"""
        return list(BUILTIN_TOOL_DEFINITIONS)

    async def execute_tool(
        self,
        func_name: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        action: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行内置工具。

        支持两种调用方式：
        1. 新式（function calling）: func_name="read_file", params={"path": "..."}
        2. 旧式（兼容 API 路由/workflow）: func_name="file_manager", action="read_file", params={...}
        """
        params = params or {}

        if action:
            # 旧式调用：func_name 是管理器内部工具名 (file_manager/terminal_executor/web_search)
            tool_name = func_name
            tool_action = action
        elif func_name in BUILTIN_TOOL_ACTION_MAP:
            # 新式调用：func_name 是扁平工具名 (read_file/run_command/web_search)
            tool_name, tool_action = BUILTIN_TOOL_ACTION_MAP[func_name]
        else:
            return {"success": False, "error": f"未知内置工具: {func_name}"}

        instance = await self._initialize_tool(tool_name, config=config)
        return await instance.execute(action=tool_action, **params)

    async def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """返回全部内置工具的定义与状态（供 /api/tools/list 使用）。"""
        tools = {}
        for tool_name in ["file_manager", "terminal_executor", "web_search", "local_search", "memory_manager"]:
            instance = await self._initialize_tool(tool_name)
            tools[tool_name] = {
                "name": tool_name,
                "display_name": getattr(instance, "name", tool_name),
                "description": getattr(instance, "description", ""),
                "version": getattr(instance, "version", "1.0.0"),
                "tools": instance.get_tools(),
            }
        return tools


builtin_tool_manager = BuiltInToolManager()
