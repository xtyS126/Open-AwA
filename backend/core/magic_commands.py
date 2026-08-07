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
        self.register(MagicCommand(
            name="help",
            description="显示所有可用魔法命令及说明",
            handler=self._handle_help,
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
        """处理 /compact 命令 — 实际执行上下文压缩并保存到长期记忆。"""
        from core.compaction_manager import CompactionManager
        from core.context.token_budget import TokenBudget
        from core.executor import ExecutionLayer
        from memory.manager import MemoryManager

        session_id = context.get("session_id", "default")
        workspace_id = context.get("workspace_id", "default")
        model_name = context.get("model_name", "default")

        try:
            from db.models import SessionLocal
            memory_manager = MemoryManager(SessionLocal)
            memories = await memory_manager.get_short_term_memories(
                session_id=session_id, limit=100
            )
            history = [
                {"role": m.role, "content": m.content}
                for m in reversed(memories)
                if m.role in ("user", "assistant")
            ]

            budget = TokenBudget(model_name=model_name)
            current_tokens = budget.count_messages(history)

            # 使用 CompactionManager 进行压缩
            compaction = CompactionManager(model_context_window=budget.max_tokens)

            # 设置 LLM 调用函数：复用 ExecutionLayer 的配置解析与调用能力
            executor = ExecutionLayer()

            async def _compaction_llm_call(prompt: str, **kwargs) -> str:
                llm_db = SessionLocal()
                try:
                    llm_ctx: dict = {"model": model_name, "db": llm_db}
                    result = await executor._call_llm_api(prompt, llm_ctx)
                    if isinstance(result, dict) and result.get("ok"):
                        return result.get("response", "") or ""
                    # 摘要 LLM 调用失败必须显式抛出，由 /compact 如实报错
                    error_message = "未知错误"
                    if isinstance(result, dict):
                        error_obj = result.get("error") or {}
                        if isinstance(error_obj, dict):
                            error_message = str(error_obj.get("message") or "未知错误")
                        else:
                            error_message = str(error_obj)
                    else:
                        error_message = str(result)
                    logger.bind(module="magic_commands", event="compaction_llm_call_failed").debug(
                        f"压缩对话上下文时 LLM 调用失败: {error_message}"
                    )
                    raise RuntimeError(f"压缩摘要 LLM 调用失败: {error_message}")
                finally:
                    llm_db.close()

            compaction.set_llm_call(_compaction_llm_call)

            if compaction.should_compact(messages=history):
                result = await compaction.compact(messages=history)
                if result["compacted"]:
                    # 将压缩摘要保存到长期记忆
                    if result.get("summary"):
                        try:
                            await memory_manager.add_long_term_memory(
                                user_id=context.get("user_id", ""),
                                content=f"[对话压缩摘要] {result['summary'][:2000]}",
                                importance=0.5,
                                memory_metadata={
                                    "source": "compact_command",
                                    "session_id": session_id,
                                    "compressed_turns": len(history) - len(result["messages"]),
                                },
                            )
                        except Exception as mem_exc:
                            # 记忆保存失败不影响压缩结果，但需记录日志以便排查
                            logger.bind(
                                event="compact_memory_save_failed",
                                module="magic_commands",
                                session_id=session_id,
                                error=str(mem_exc),
                            ).warning(f"压缩摘要保存到长期记忆失败: {mem_exc}")

                    return {
                        "action": "compact",
                        "success": True,
                        "message": f"上下文已压缩，移除了 {len(history) - len(result['messages'])} 条历史消息",
                        "removed_count": len(history) - len(result["messages"]),
                        "summary": result["summary"][:500] if result["summary"] else "",
                        "stats": {
                            "original_tokens": current_tokens,
                            "max_tokens": budget.max_tokens,
                            "usage_ratio": round(current_tokens / budget.max_tokens, 3) if budget.max_tokens > 0 else 0,
                        },
                    }
                else:
                    # 摘要生成失败：如实返回失败状态，禁止伪装成功
                    return {
                        "action": "compact",
                        "success": False,
                        "message": f"摘要生成失败，未执行压缩: {result.get('error', '未知原因')}",
                        "error": result.get("error"),
                        "stats": {
                            "current_tokens": current_tokens,
                            "max_tokens": budget.max_tokens,
                            "usage_ratio": round(current_tokens / budget.max_tokens, 3) if budget.max_tokens > 0 else 0,
                        },
                    }
            else:
                return {
                    "action": "compact",
                    "success": True,
                    "message": "当前上下文未达到压缩阈值，无需压缩",
                    "stats": {
                        "current_tokens": current_tokens,
                        "max_tokens": budget.max_tokens,
                        "usage_ratio": round(current_tokens / budget.max_tokens, 3) if budget.max_tokens > 0 else 0,
                    },
                }
        except Exception as exc:
            return {
                "action": "compact",
                "success": False,
                "message": f"上下文压缩失败: {str(exc)}",
            }

    async def _handle_new(self, context: dict) -> dict:
        """处理 /new 命令 — 保存长期记忆后清空上下文。"""
        from memory.manager import MemoryManager

        session_id = context.get("session_id", "default")
        try:
            from db.models import SessionLocal
            memory_manager = MemoryManager(SessionLocal)
            await memory_manager.clear_short_term_memory(session_id=session_id)
        except Exception as exc:
            # 清空上下文失败必须如实报告，禁止伪装成已清空
            logger.warning(f"/new 清空上下文失败: {exc}")
            return {
                "action": "new_session",
                "success": False,
                "message": f"清空上下文失败: {exc}",
                "clear_context": False,
            }

        return {
            "action": "new_session",
            "success": True,
            "message": "开始新对话，历史已保存",
            "clear_context": True,
        }

    async def _handle_clear(self, context: dict) -> dict:
        """处理 /clear 命令 — 仅清空上下文，不保存。"""
        from memory.manager import MemoryManager

        session_id = context.get("session_id", "default")
        try:
            from db.models import SessionLocal
            memory_manager = MemoryManager(SessionLocal)
            await memory_manager.clear_short_term_memory(session_id=session_id)
        except Exception as exc:
            # 清空上下文失败必须如实报告，禁止伪装成已清空
            logger.warning(f"/clear 清空上下文失败: {exc}")
            return {
                "action": "clear_context",
                "success": False,
                "message": f"清空上下文失败: {exc}",
                "clear_context": False,
                "save_to_memory": False,
            }

        return {
            "action": "clear_context",
            "success": True,
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
        """处理 /make-skill 命令 — 从当前对话生成可复用技能。"""
        from memory.manager import MemoryManager
        from db.models import SessionLocal

        session_id = context.get("session_id", "")
        workspace_id = context.get("workspace_id", "default")

        # 从短期记忆中提取对话历史（使用 SessionLocal 确保线程安全）
        memory_manager = MemoryManager(SessionLocal)
        memories = memory_manager._get_short_term_memories_sync(
            session_id=session_id,
            workspace_id=workspace_id,
            limit=20,
        )

        # 构建对话摘要
        conversation_text = "\n".join([
            f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content', '')[:500]}"
            for m in memories
            if m.get('content')
        ])

        if not conversation_text.strip():
            return {
                "action": "make_skill",
                "success": False,
                "message": "当前对话内容不足以生成技能，请先进行更有深度的对话",
            }

        # LLM 生成路径当前不可用（model_service 已退役，等待 litellm 迁移）。
        # 必须如实报错，禁止用启发式内容冒充 LLM 生成结果
        logger.bind(module="magic_commands", event="skill_generation_llm_failed").debug(
            "LLM 技能生成路径不可用"
        )
        return {
            "action": "make_skill",
            "success": False,
            "message": "技能生成失败：LLM 生成路径当前不可用（等待模型服务迁移完成）",
        }

    async def _handle_make_plan(self, context: dict) -> dict:
        """处理 /make-plan 命令 — 基于当前对话生成结构化执行计划。"""
        from memory.manager import MemoryManager
        from db.models import SessionLocal

        session_id = context.get("session_id", "")
        workspace_id = context.get("workspace_id", "default")
        memory_manager = MemoryManager(SessionLocal)
        memories = memory_manager._get_short_term_memories_sync(
            session_id=session_id,
            workspace_id=workspace_id,
            limit=20,
        )

        conversation_text = "\n".join([
            f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content', '')[:300]}"
            for m in memories
            if m.get('content')
        ])

        if not conversation_text.strip():
            return {
                "action": "make_plan",
                "success": False,
                "message": "当前对话内容不足，请先进行有实质内容的对话",
            }

        # LLM 生成路径当前不可用（model_service 已退役，等待 litellm 迁移）。
        # 必须如实报错，禁止返回占位计划伪装成功
        logger.bind(module="magic_commands", event="plan_generation_llm_failed").debug(
            "LLM 计划生成路径不可用"
        )
        return {
            "action": "make_plan",
            "success": False,
            "message": "计划生成失败：LLM 生成路径当前不可用（等待模型服务迁移完成）",
        }

    async def _handle_restart(self, context: dict) -> dict:
        """处理 /restart 命令。"""
        return {
            "action": "restart",
            "message": "服务即将重启",
            "requires_confirmation": True,
        }

    async def _handle_help(self, context: dict) -> dict:
        """处理 /help 命令 — 显示所有可用魔法命令。"""
        commands = self.list_commands()
        lines = ["可用魔法命令：", ""]
        for cmd in commands:
            attrs = []
            if cmd.get("requires_wait"):
                attrs.append("[需等待]")
            if cmd.get("saves_memory"):
                attrs.append("[保存记忆]")
            if cmd.get("clears_context"):
                attrs.append("[清空上下文]")
            attr_str = " " + " ".join(attrs) if attrs else ""
            lines.append(f"  /{cmd['name']} — {cmd['description']}{attr_str}")
        return {
            "action": "help",
            "success": True,
            "message": "\n".join(lines),
            "commands": commands,
        }


# 全局单例
_magic_command_registry: Optional[MagicCommandRegistry] = None


def get_magic_command_registry() -> MagicCommandRegistry:
    """获取魔法命令注册表单例。"""
    global _magic_command_registry
    if _magic_command_registry is None:
        _magic_command_registry = MagicCommandRegistry()
    return _magic_command_registry
