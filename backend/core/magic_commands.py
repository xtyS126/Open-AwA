"""
魔法命令系统 — 以 / 开头的特殊指令，直接控制对话状态。
支持 /compact、/new、/clear、/make-skill、/make-plan、/stop 及插件注册的自定义命令。
"""
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class MagicCommand:
    """魔法命令定义。"""
    name: str
    description: str
    handler: Callable
    requires_wait: bool = False
    saves_memory: bool = False
    clears_context: bool = False
    plugin_id: Optional[str] = None  # 插件注册的命令


class MagicCommandRegistry:
    """
    魔法命令注册表。
    管理内置和插件注册的命令，解析用户输入并分发给对应处理器。
    """

    def __init__(self):
        self._commands: dict[str, MagicCommand] = {}
        self._register_builtin_commands()

    def _register_builtin_commands(self):
        """注册内置魔法命令。"""
        self.register(MagicCommand(
            name="compact",
            description="压缩当前对话上下文，生成摘要并保存到长期记忆",
            handler=self._handle_compact,
            requires_wait=True,
            saves_memory=True,
        ))
        self.register(MagicCommand(
            name="new",
            description="清空上下文并开始新对话（后台保存记忆）",
            handler=self._handle_new,
            saves_memory=True,
            clears_context=True,
        ))
        self.register(MagicCommand(
            name="clear",
            description="仅清空上下文，不保存记忆",
            handler=self._handle_clear,
            clears_context=True,
        ))
        self.register(MagicCommand(
            name="stop",
            description="停止当前任务执行",
            handler=self._handle_stop,
        ))
        self.register(MagicCommand(
            name="make-skill",
            description="从当前对话中生成可复用的技能",
            handler=self._handle_make_skill,
            requires_wait=True,
        ))
        self.register(MagicCommand(
            name="make-plan",
            description="基于当前对话生成结构化执行计划",
            handler=self._handle_make_plan,
            requires_wait=True,
        ))
        self.register(MagicCommand(
            name="restart",
            description="重启当前服务",
            handler=self._handle_restart,
        ))

    def register(self, command: MagicCommand):
        """注册魔法命令。"""
        self._commands[command.name] = command
        logger.bind(event="magic_command_registered", name=command.name).debug("魔法命令已注册")

    def unregister(self, name: str):
        """注销魔法命令。"""
        self._commands.pop(name, None)

    def get_command(self, name: str) -> Optional[MagicCommand]:
        """获取指定命令。"""
        return self._commands.get(name)

    def list_commands(self) -> list[dict]:
        """列出所有命令。"""
        return [
            {
                "name": cmd.name,
                "description": cmd.description,
                "requires_wait": cmd.requires_wait,
                "saves_memory": cmd.saves_memory,
                "clears_context": cmd.clears_context,
                "plugin_id": cmd.plugin_id,
            }
            for cmd in self._commands.values()
        ]

    @staticmethod
    def parse_message(message: str) -> tuple[Optional[str], Optional[str], str]:
        """
        解析消息中是否包含魔法命令。
        格式: /command [args] 或仅 /command

        Returns:
            (command_name, command_args, remaining_message)
        """
        text = message.strip()
        if not text.startswith("/"):
            return None, None, text

        # 提取命令名和参数
        parts = text.split(maxsplit=1)
        cmd_part = parts[0][1:]  # 去掉 /
        args = parts[1] if len(parts) > 1 else ""
        return cmd_part, args, ""

    # ---- 内置命令处理器 ----

    async def _handle_compact(self, context: dict) -> dict:
        """处理 /compact 命令。"""
        return {
            "action": "compact",
            "message": "压缩当前对话上下文，生成摘要并保存记忆",
            "requires_confirmation": True,
        }

    async def _handle_new(self, context: dict) -> dict:
        """处理 /new 命令。"""
        return {
            "action": "new_session",
            "message": "开始新对话，历史已保存",
            "clear_context": True,
        }

    async def _handle_clear(self, context: dict) -> dict:
        """处理 /clear 命令。"""
        return {
            "action": "clear_context",
            "message": "上下文已清空（未保存到记忆）",
            "clear_context": True,
            "save_to_memory": False,
        }

    async def _handle_stop(self, context: dict) -> dict:
        """处理 /stop 命令。"""
        return {
            "action": "stop",
            "message": "任务已停止",
        }

    async def _handle_make_skill(self, context: dict) -> dict:
        """处理 /make-skill 命令。"""
        return {
            "action": "make_skill",
            "message": "正在从当前对话生成技能...",
            "mode": "generate_from_session",
        }

    async def _handle_make_plan(self, context: dict) -> dict:
        """处理 /make-plan 命令。"""
        return {
            "action": "make_plan",
            "message": "正在生成结构化执行计划...",
        }

    async def _handle_restart(self, context: dict) -> dict:
        """处理 /restart 命令。"""
        return {
            "action": "restart",
            "message": "服务即将重启",
            "requires_confirmation": True,
        }


# 全局单例
_magic_command_registry: Optional[MagicCommandRegistry] = None


def get_magic_command_registry() -> MagicCommandRegistry:
    """获取魔法命令注册表单例。"""
    global _magic_command_registry
    if _magic_command_registry is None:
        _magic_command_registry = MagicCommandRegistry()
    return _magic_command_registry
