"""
魔法命令系统 — 以 / 开头的特殊指令，直接控制对话状态。
支持 /compact、/new、/clear、/make-skill、/make-plan、/stop 及插件注册的自定义命令。
"""
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
        """处理 /make-skill 命令 — 从当前对话生成可复用技能。"""
        import json
        import re
        from pathlib import Path
        from memory.manager import MemoryManager

        session_id = context.get("session_id", "")
        workspace_id = context.get("workspace_id", "default")

        # 从短期记忆中提取对话历史
        memory_manager = MemoryManager()
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

        # 生成技能名称建议
        from skills.pool_manager import SkillPoolManager
        pool = SkillPoolManager()
        existing = set(pool.get_manifest().get("skills", {}).keys())

        # LLM 生成提示词
        prompt = f"""基于以下对话历史，生成一个可复用的AI技能配置。

对话内容:
{conversation_text[:3000]}

请以 JSON 格式输出技能定义（仅输出 JSON，不要其他内容）:
{{
    "name": "技能名称（英文，简短）",
    "description": "技能描述（一句话中文）",
    "instructions": "当技能被触发时模型需遵循的详细规则（Markdown 格式）",
    "trigger_keywords": ["触发关键词1", "触发关键词2"],
    "inputs": {{}},
    "outputs": {{}}
}}

注意:
1. 技能名称不要与已有技能重复
2. 指令内容要具体、可操作
3. 名称使用 snake_case"""

        # 通过 LLM 生成技能配置
        try:
            from core.model_service import get_model_service
            model_service = get_model_service()
            llm_response = await model_service.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.7,
            )
            content = llm_response.get("content", "") if isinstance(llm_response, dict) else str(llm_response)
        except Exception:
            # LLM 不可用时使用启发式生成
            skill_name = "custom_skill"
            instructions = f"# 技能说明\n基于对话生成的技能。\n\n## 对话摘要\n{conversation_text[:500]}"
            content = json.dumps({
                "name": skill_name,
                "description": "从对话中自定义生成的技能",
                "instructions": instructions,
                "trigger_keywords": [],
            })

        # 解析 LLM 输出
        try:
            # 尝试提取 JSON 块
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                skill_def = json.loads(json_match.group())
            else:
                skill_def = json.loads(content)
        except json.JSONDecodeError:
            skill_name = "custom_" + re.sub(r'[^a-z0-9_]', '', conversation_text[:20].lower())
            skill_def = {
                "name": skill_name,
                "description": "从对话中自定义生成的技能",
                "instructions": conversation_text[:1000],
                "trigger_keywords": [],
            }

        skill_name = skill_def.get("name", "custom_skill")
        if skill_name in existing:
            skill_name = f"{skill_name}_v2"

        # 将技能保存到技能池
        skill_dir = pool.pool_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        # 生成 SKILL.md
        skill_md = f"""# {skill_name}

## 描述
{skill_def.get('description', '从对话中生成的技能')}

## 触发关键词
{', '.join(skill_def.get('trigger_keywords', [])) or '无'}

## 指令
{skill_def.get('instructions', conversation_text[:500])}
"""
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        # 生成 skill.json
        (skill_dir / "skill.json").write_text(json.dumps(skill_def, ensure_ascii=False, indent=2), encoding="utf-8")

        # 更新技能池清单
        manifest = pool.get_manifest()
        manifest.setdefault("skills", {})[skill_name] = {
            "description": skill_def.get("description", ""),
            "version": "1.0.0",
            "source": "generated",
            "enabled": True,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        pool._save_manifest(manifest)

        return {
            "action": "make_skill",
            "success": True,
            "message": f"技能 '{skill_name}' 已生成并保存",
            "skill_name": skill_name,
            "skill_dir": str(skill_dir),
            "requires_confirmation": False,
        }

    async def _handle_make_plan(self, context: dict) -> dict:
        """处理 /make-plan 命令 — 基于当前对话生成结构化执行计划。"""
        from memory.manager import MemoryManager

        session_id = context.get("session_id", "")
        workspace_id = context.get("workspace_id", "default")
        memory_manager = MemoryManager()
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

        prompt = f"""基于以下对话上下文，生成一个结构化的执行计划（JSON 格式，仅输出 JSON）:

对话内容:
{conversation_text[:3000]}

输出格式:
{{
    "title": "计划标题",
    "description": "计划简述",
    "steps": [
        {{"order": 1, "title": "步骤1标题", "description": "详细描述", "estimated_time": "预估时间"}},
        {{"order": 2, "title": "步骤2标题", "description": "详细描述", "estimated_time": "预估时间"}}
    ],
    "expected_outcome": "预期成果"
}}"""
        try:
            from core.model_service import get_model_service
            model_service = get_model_service()
            llm_response = await model_service.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.5,
            )
            content = llm_response.get("content", "") if isinstance(llm_response, dict) else str(llm_response)
        except Exception:
            return {
                "action": "make_plan",
                "success": True,
                "plan": {
                    "title": "待定计划",
                    "steps": [{"order": 1, "title": "分析需求", "description": conversation_text[:200]}],
                },
            }

        import re as _re
        import json as _json
        try:
            json_match = _re.search(r'\{[\s\S]*\}', content)
            plan = _json.loads(json_match.group()) if json_match else _json.loads(content)
        except _json.JSONDecodeError:
            plan = {"title": "待定计划", "raw_output": content}

        return {
            "action": "make_plan",
            "success": True,
            "message": f"执行计划已生成: {plan.get('title', '')}",
            "plan": plan,
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
