"""执行层提示与消息构建协作者。

集中负责运行态能力、用户画像、长短期记忆、自动执行结果和历史消息的
系统提示拼装。该模块不发起模型调用，也不执行工具。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from soul.profile import OnionProfile


def _load_onion_profile(user_id: str, db: Session) -> Optional[OnionProfile]:
    """加载用户画像；未建立画像时返回空值，加载失败时传播异常。"""
    if not user_id or db is None:
        return None

    from soul.persistence import load_profile

    return load_profile(db, user_id)


def _build_profile_context(user_id: str, db: Session) -> str:
    """构建 OnionProfile 五层摘要。"""
    profile = _load_onion_profile(user_id, db)
    if profile is None:
        return ""

    parts = ["[用户画像]"]
    layer_labels = {
        "surface": "行为偏好",
        "interest": "兴趣偏好",
        "role": "角色认同",
        "values": "价值观",
        "core": "人格特征",
    }
    for layer_name, label in layer_labels.items():
        layer = getattr(profile, layer_name, None)
        if layer is None:
            continue
        description = getattr(layer, "description", None)
        if description:
            parts.append(f"- {label}: {description}")
    return "\n".join(parts) if len(parts) > 1 else ""


def _build_onion_fact_set(onion_profile: Optional[OnionProfile]) -> set:
    """构建画像结构化事实集合，供高置信度事实去重。"""
    if onion_profile is None:
        return set()

    fact_set: set = set()
    for layer_name in ("surface", "interest", "role", "values", "core"):
        layer = getattr(onion_profile, layer_name, None)
        if layer is None:
            continue
        structured_data = getattr(layer, "structured_data", None)
        if not isinstance(structured_data, dict):
            continue
        for key, value in structured_data.items():
            if key is not None:
                fact_set.add((str(key), str(value)))
    return fact_set


def _build_profile_facts_context(
    user_id: str,
    db: Session,
    onion_profile: Optional[OnionProfile] = None,
) -> str:
    """构建去重后的高置信度画像事实摘要。"""
    if not user_id or db is None:
        return ""

    from db.models import ProfileFact

    facts = (
        db.query(ProfileFact)
        .filter(
            ProfileFact.user_id == user_id,
            ProfileFact.is_active.is_(True),
            ProfileFact.confidence >= 0.7,
        )
        .order_by(ProfileFact.confidence.desc())
        .limit(20)
        .all()
    )

    if not facts:
        return ""

    onion_fact_set = _build_onion_fact_set(onion_profile)
    parts = ["[用户画像事实]"]
    for fact in facts:
        fact_key = getattr(fact, "fact_key", "")
        fact_value = getattr(fact, "fact_value", "")
        confidence = getattr(fact, "confidence", 0.0)
        if not fact_key or not fact_value:
            continue
        if (fact_key, str(fact_value)) in onion_fact_set:
            continue
        parts.append(
            f"- {fact_key}: {fact_value} (置信度: {float(confidence):.0%})"
        )
    return "\n".join(parts) if len(parts) > 1 else ""


def build_recent_short_term_memories_prompt(
    memory_manager: Any,
    context: Dict[str, Any],
) -> str:
    """构建近期短期记忆提示片段。"""
    if memory_manager is None:
        return ""

    user_id = context.get("user_id")
    if not user_id:
        return ""

    workspace_id = context.get("workspace_id", "default")
    memories = memory_manager._get_recent_short_term_memories_sync(
        user_id,
        limit=20,
        workspace_id=workspace_id,
    )

    if not memories:
        return ""

    lines = ["[近期对话记忆]"]
    for memory in reversed(memories):
        role = getattr(memory, "role", "user") or "user"
        if role not in ("user", "assistant"):
            continue
        session_id = getattr(memory, "session_id", "") or ""
        content = str(getattr(memory, "content", "") or "").strip()
        if not content:
            continue
        content_preview = content[:100]
        if len(content) > 100:
            content_preview += "..."
        session_short = session_id[:8] if session_id else "unknown"
        lines.append(f"[{session_short}] {role}: {content_preview}")
    return "\n".join(lines) if len(lines) > 1 else ""


class ExecutionPromptBuilder:
    """构建执行层传给模型的系统提示和消息列表。"""

    def build_agent_capability_system_prompt(
        self,
        context: Dict[str, Any],
    ) -> str:
        """根据运行态能力摘要构建系统提示。"""
        capabilities = context.get("agent_capabilities")
        if not isinstance(capabilities, dict):
            return ""

        lines = [
            "你是 Open-AwA 平台中的 AI Agent，不是孤立的纯文本聊天模型。",
            "回答关于自身能力的问题时，必须以当前运行态能力清单为准。",
            "不要笼统声称自己不能调用 MCP、技能或插件；要区分平台是否支持、当前会话是否启用、当前是否已有可用工具。",
        ]
        self._append_skills(lines, capabilities)
        self._append_plugins(lines, capabilities)
        self._append_models(lines, capabilities)
        self._append_mcp(lines, capabilities)
        lines.extend(
            [
                "规则：",
                "1. 不要捏造已经执行过的技能、插件或 MCP 调用。",
                "2. 不要回答“我没有调用技能/插件/MCP 的能力”这类绝对否定句。",
                "3. 当某类能力当前不可用时，要说明是当前会话未启用、未连接或未暴露，而不是说平台完全不支持。",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _append_skills(lines: list[str], capabilities: Dict[str, Any]) -> None:
        skills_enabled = bool(capabilities.get("skills_enabled", False))
        skills = (
            capabilities.get("skills")
            if isinstance(capabilities.get("skills"), list)
            else []
        )
        if not skills_enabled:
            lines.append("当前会话已关闭技能自动调度。")
            return
        if not skills:
            lines.append("当前会话未发现可用技能。")
            return
        lines.append("当前会话可用技能：")
        for skill in skills[:12]:
            if isinstance(skill, dict):
                lines.append(
                    f"- 技能 {skill.get('name', '')}: {skill.get('description', '')}"
                )

    @staticmethod
    def _append_plugins(lines: list[str], capabilities: Dict[str, Any]) -> None:
        plugins_enabled = bool(capabilities.get("plugins_enabled", False))
        plugins = (
            capabilities.get("plugins")
            if isinstance(capabilities.get("plugins"), list)
            else []
        )
        if not plugins_enabled:
            lines.append("当前会话已关闭插件自动调度。")
            return
        if not plugins:
            lines.append("当前会话未发现可用插件。")
            return
        lines.append("当前会话可用插件：")
        for plugin in plugins[:12]:
            if not isinstance(plugin, dict):
                continue
            tools = (
                plugin.get("tools")
                if isinstance(plugin.get("tools"), list)
                else []
            )
            tool_names = [
                str(tool.get("name", "")).strip()
                for tool in tools
                if isinstance(tool, dict) and str(tool.get("name", "")).strip()
            ]
            tool_text = "、".join(tool_names) if tool_names else "无显式工具"
            lines.append(
                f"- 插件 {plugin.get('name', '')}: {plugin.get('description', '')}。"
                f"工具: {tool_text}。如需了解参数，优先查看 help 工具。"
            )

    @staticmethod
    def _append_models(lines: list[str], capabilities: Dict[str, Any]) -> None:
        catalog = (
            capabilities.get("configured_models")
            if isinstance(capabilities.get("configured_models"), dict)
            else {}
        )
        entries = (
            catalog.get("entries")
            if isinstance(catalog.get("entries"), list)
            else []
        )
        if not entries:
            lines.append(
                "当前未提供已配置模型目录；派生子代理时若省略 provider/model，将回退到系统默认模型配置。"
            )
            return
        lines.append("当前可用于派生子代理的已配置模型：")
        for entry in entries[:12]:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label", "")).strip()
            if label:
                lines.append(f"- {label}")
        lines.append(
            "调用 task_spawn_agent 时，优先同时传 provider 和 model；也支持把 model 写成 provider:model。"
            "仅传 provider 时，系统会自动选用该 provider 的默认或已选模型。"
        )

        # 生图模型目录：仅供图像生成（SD / GPT-Image / Qwen-Image 系列），用途描述辅助准确选型
        image_entries = (
            catalog.get("image_entries")
            if isinstance(catalog.get("image_entries"), list)
            else []
        )
        if image_entries:
            lines.append("可用生图模型（仅用于图像生成，不可作为聊天模型；需要生图时选择合适模型调用生图工具）：")
            for entry in image_entries[:12]:
                if not isinstance(entry, dict):
                    continue
                label = str(entry.get("label", "")).strip()
                if not label:
                    continue
                usage = str(entry.get("usage", "")).strip()
                lines.append(f"- {label}" + (f"（用途/限制：{usage}）" if usage else ""))

    @staticmethod
    def _append_mcp(lines: list[str], capabilities: Dict[str, Any]) -> None:
        mcp = (
            capabilities.get("mcp")
            if isinstance(capabilities.get("mcp"), dict)
            else {}
        )
        if not mcp.get("platform_supported", False):
            return

        connected_servers = (
            mcp.get("connected_servers")
            if isinstance(mcp.get("connected_servers"), list)
            else []
        )
        tools = mcp.get("tools") if isinstance(mcp.get("tools"), list) else []
        if tools:
            lines.append("平台当前已连接的 MCP 工具：")
            for tool in tools[:12]:
                if isinstance(tool, dict):
                    lines.append(
                        f"- MCP {tool.get('server_name', tool.get('server_id', ''))}/"
                        f"{tool.get('name', '')}: {tool.get('description', '')}"
                    )
        elif connected_servers:
            names = [
                str(server.get("name", "")).strip()
                for server in connected_servers[:12]
                if isinstance(server, dict)
                and str(server.get("name", "")).strip()
            ]
            suffix = "：" + "、".join(names) if names else "。"
            lines.append(
                "平台已连接 MCP Server，但当前没有可直接说明的 MCP 工具摘要"
                + suffix
            )
        else:
            lines.append("平台支持 MCP Server 管理与工具发现，但当前没有已连接的 MCP Server。")

        if not mcp.get("chat_dispatch_enabled", False):
            lines.append(
                "注意：当前聊天链路未直接暴露自动 MCP 调度。不要谎称已经调用了某个 MCP 工具；"
                "如果用户询问能力，应说明平台支持 MCP，但本轮会话是否可直接调用取决于"
                "已连接 Server 和执行链路配置。"
            )

    def build_auto_execution_system_prompt(
        self,
        auto_execution_results: Dict[str, Any],
    ) -> str:
        """把已自动执行的技能和插件结果整理为系统提示。"""
        lines: list[str] = []
        skills = auto_execution_results.get("skills", []) or []
        plugins = auto_execution_results.get("plugins", []) or []
        if not skills and not plugins:
            return ""

        if skills:
            lines.append("平台已在生成当前回答前自动执行了部分技能：")
            for skill in skills:
                lines.append(f"- {skill.get('skill_name', 'unknown')}")
            lines.append("")

        for plugin in plugins:
            plugin_name = plugin.get("plugin_name", "unknown")
            tool = plugin.get("tool", "unknown")
            result = plugin.get("result", {}) or {}
            if result.get("summary_mode") == "current_model":
                self._append_current_model_plugin_summary(
                    lines,
                    plugin_name,
                    tool,
                    result,
                )
            else:
                if not lines:
                    lines.append("平台已在生成当前回答前自动执行了部分技能或插件：")
                lines.append(f"- {plugin_name}/{tool}")

        if lines and "不要输出 JSON" not in lines[-1]:
            lines.extend(["", "不要再输出任何插件、技能或 MCP 调用 JSON。"])
        return "\n".join(lines).strip()

    @staticmethod
    def _append_current_model_plugin_summary(
        lines: list[str],
        plugin_name: str,
        tool: str,
        result: Dict[str, Any],
    ) -> None:
        lines.extend(
            [
                f"平台已在生成当前回答前自动执行了插件 {plugin_name}/{tool}：",
                "",
            ]
        )
        for key in ("summary_role", "summary_guidance"):
            if result.get(key):
                lines.append(result[key])
        for key, title in (
            ("summary_output_rules", "输出规则："),
            ("summary_priority_rules", "优先级规则："),
        ):
            if result.get(key):
                lines.extend(["", title])
                lines.extend(f"- {rule}" for rule in result[key])
        if result.get("summary_context"):
            lines.extend(["", result["summary_context"]])
        if result.get("digest"):
            lines.extend(["", "推文摘要："])
            lines.extend(f"- {item}" for item in result["digest"])
        if result.get("top_tweets"):
            lines.extend(["", "高价值候选推文："])
            lines.extend(
                f"- {tweet.get('text', '')}" for tweet in result["top_tweets"]
            )
        lines.extend(
            [
                "",
                "不要输出 JSON、代码块或额外调度指令，直接基于以上素材回答用户。",
            ]
        )

    @staticmethod
    def build_relevant_memories_system_prompt(context: Dict[str, Any]) -> str:
        """把检索到的长期记忆整理为系统提示。"""
        memories = context.get("vector_retrieved_memories")
        if not isinstance(memories, list) or not memories:
            return ""

        lines = ["以下是与当前用户请求可能相关的长期记忆，回答时可参考但不要逐字复述："]
        for idx, memory in enumerate(memories, start=1):
            if not isinstance(memory, dict):
                continue
            content = str(memory.get("content", "")).strip()
            if not content:
                continue
            meta_parts: list[str] = []
            importance = memory.get("importance")
            confidence = memory.get("confidence")
            if isinstance(importance, (int, float)):
                meta_parts.append(f"重要度={float(importance):.2f}")
            if isinstance(confidence, (int, float)):
                meta_parts.append(f"置信度={float(confidence):.2f}")
            meta_text = f"（{', '.join(meta_parts)}）" if meta_parts else ""
            lines.append(f"{idx}. {content}{meta_text}")
        return "\n".join(lines)

    @staticmethod
    def build_recent_short_term_memories_system_prompt(
        memory_manager: Any,
        context: Dict[str, Any],
    ) -> str:
        """委托短期记忆纯函数生成提示。"""
        return build_recent_short_term_memories_prompt(memory_manager, context)

    def build_messages(
        self,
        prompt: str,
        context: Dict[str, Any],
        memory_manager: Any = None,
    ) -> list[Dict[str, Any]]:
        """按稳定优先级拼装模型消息列表。"""
        messages: list[Dict[str, Any]] = []
        self._append_system_message(
            messages,
            self.build_agent_capability_system_prompt(context),
        )
        self._append_profile(messages, context)
        self._append_system_message(
            messages,
            self.build_relevant_memories_system_prompt(context),
        )
        self._append_system_message(
            messages,
            self.build_recent_short_term_memories_system_prompt(
                memory_manager,
                context,
            ),
        )

        auto_execution_results = context.get("auto_execution_results")
        if auto_execution_results:
            self._append_system_message(
                messages,
                self.build_auto_execution_system_prompt(auto_execution_results),
            )

        for message in context.get("conversation_history", []) or []:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        multimodal_content = context.get("_multimodal_content")
        messages.append(
            {
                "role": "user",
                "content": multimodal_content if multimodal_content else prompt,
            }
        )
        return messages

    @staticmethod
    def _append_system_message(
        messages: list[Dict[str, Any]],
        content: str,
    ) -> None:
        if content:
            messages.append({"role": "system", "content": content})

    @staticmethod
    def _append_profile(
        messages: list[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> None:
        user_id = context.get("user_id")
        db = context.get("db")
        onion_profile = _load_onion_profile(user_id, db)
        profile_context = _build_profile_context(user_id, db)
        facts_context = _build_profile_facts_context(
            user_id,
            db,
            onion_profile=onion_profile,
        )
        profile_block = "\n\n".join(
            part for part in (profile_context, facts_context) if part
        )
        if profile_block:
            messages.append({"role": "system", "content": profile_block})
