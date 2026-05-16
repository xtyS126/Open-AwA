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
    "list_checkpoints": ("checkpoint", "list_checkpoints"),
    "restore_checkpoint": ("checkpoint", "restore_checkpoint"),
    "todo_write": ("todo_manager", "todo_write"),
    "notify": ("notify", "notify"),
    "browser_screenshot": ("browser_extended", "screenshot"),
    "browser_snapshot": ("browser_extended", "snapshot"),
    "browser_navigate": ("browser_extended", "navigate"),
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
    {
        "type": "function",
        "function": {
            "name": "builtin_list_checkpoints",
            "description": "列出当前会话或全部文件修改检查点（不含文件内容，仅摘要信息）。可用于查看哪些文件被工具修改或删除过",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_path": {
                        "type": "string",
                        "description": "按会话路径过滤检查点（可选，不传则返回全部）",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_restore_checkpoint",
            "description": "根据检查点 ID 恢复文件到修改/删除前的状态。仅在确定需要回退时使用",
            "parameters": {
                "type": "object",
                "properties": {
                    "checkpoint_id": {
                        "type": "string",
                        "description": "要恢复的检查点 ID（从 list_checkpoints 获取）",
                    },
                },
                "required": ["checkpoint_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_notify",
            "description": "向用户发送通知提醒。仅在用户明确要求提醒/通知时使用，普通任务完成不需要调用。支持 desktop（桌面弹窗）和 bridge_owner（微信消息）两种通道。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "通知标题（简短描述）"},
                    "body": {"type": "string", "description": "通知正文内容（详细信息）"},
                    "channels": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["desktop", "bridge_owner", "auto"]},
                        "description": "通知投递通道列表。desktop=浏览器弹窗, bridge_owner=微信消息, auto=自动选择。默认 desktop。",
                    },
                    "audience": {
                        "type": "string",
                        "enum": ["owner"],
                        "description": "通知接收者，必须是 owner",
                    },
                },
                "required": ["title", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_todo_write",
            "description": "创建和管理任务列表。使用替换式协议，每次调用传入完整的 todos 数组来更新所有任务状态。支持 pending、in_progress、completed 三种状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "description": "完整的任务列表，每个任务包含 id（唯一标识）、content（任务描述）、status（状态：pending/in_progress/completed）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "任务唯一标识（建议使用数字字符串如 '1', '2'）"},
                                "content": {"type": "string", "description": "任务内容描述"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                    "description": "任务状态：pending=待处理, in_progress=进行中, completed=已完成",
                                },
                            },
                            "required": ["id", "content", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_browser_screenshot",
            "description": "截取网页的全页面截图，返回 base64 编码的 PNG 图像。需要 Playwright 支持。用于查看网页的实际渲染效果、UI 检查、异常截图等场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要截图的网页 URL（必须 http/https）"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_browser_snapshot",
            "description": "获取网页的文本内容快照。使用 Playwright 获取 JS 渲染后的页面文本（比 fetch_url 更适合 JS 密集型页面）。自动过滤 script/style 标签。Playwright 不可用时自动降级为 httpx。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要分析的网页 URL（必须 http/https）"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "builtin_browser_navigate",
            "description": "导航到指定 URL 并获取页面渲染后的内容（同 snapshot）。适用于需要浏览特定页面的场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要导航到的网页 URL（必须 http/https）"},
                },
                "required": ["url"],
            },
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
        elif tool_name == "checkpoint":
            from .checkpoint import CheckpointStore

            # 从 config 获取检查点目录，默认使用 desk\checkpoints
            import os as _os
            checkpoints_dir = (config or {}).get(
                "checkpoints_dir",
                _os.path.join(_os.getcwd(), "desk", "checkpoints"),
            )
            instance = CheckpointStore(checkpoints_dir=checkpoints_dir)
        elif tool_name == "todo_manager":
            from .todo import TodoManager

            session_dir = (config or {}).get("session_dir")
            instance = TodoManager(session_dir=session_dir)
        elif tool_name == "notify":
            from .notify import NotifyTool

            # 尝试从 config 获取回调函数，支持依赖注入
            emit_desktop = (config or {}).get("emit_desktop") if config else None
            send_bridge_owner = (config or {}).get("send_bridge_owner") if config else None
            instance = NotifyTool(emit_desktop=emit_desktop, send_bridge_owner=send_bridge_owner)
        elif tool_name == "browser_extended":
            from .browser_extended import BrowserExtendedSkill

            instance = BrowserExtendedSkill(config=config)
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
        for tool_name in ["file_manager", "terminal_executor", "web_search", "local_search", "memory_manager", "checkpoint", "notify", "todo_manager", "browser_extended"]:
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
