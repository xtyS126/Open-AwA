"""
AI 角色引擎模块，负责角色配置的加载、注入、权限约束和知识库绑定。
"""

import uuid
from typing import Any, Dict, List, Optional
from loguru import logger
from sqlalchemy.orm import Session
from db.models import AgentRole


# 预设角色模板
PRESET_ROLES: List[Dict[str, Any]] = [
    {
        "id": "preset-code-reviewer",
        "name": "代码审查专家",
        "description": "严格审查代码质量、安全性和性能",
        "system_prompt": "你是一位严格的代码审查专家。审查代码时关注：1) 安全漏洞 2) 性能问题 3) 代码规范 4) 可维护性。给出具体的改进建议。",
        "personality": {"tone": "strict", "verbosity": "concise", "creativity": 0.2, "formality": 0.9},
        "expertise": {"domains": ["coding"], "languages": ["python", "typescript", "go"], "specialties": ["code-review"]},
        "allowed_tools": ["file_read", "file_write", "terminal", "search"],
        "allowed_skills": [],
        "model_config": {"preferred_model": "", "fallback_model": "", "temperature": 0.3, "max_tokens": 4096},
        "is_preset": True,
    },
    {
        "id": "preset-office-assistant",
        "name": "办公助手",
        "description": "高效处理文档、邮件、日程等日常办公事务",
        "system_prompt": "你是一位高效的办公助手。帮助用户处理文档撰写、邮件回复、日程安排等日常办公事务。回复简洁高效，重点突出。",
        "personality": {"tone": "casual", "verbosity": "concise", "creativity": 0.3, "formality": 0.5},
        "expertise": {"domains": ["writing", "scheduling"], "languages": [], "specialties": ["email", "document"]},
        "allowed_tools": ["file_read", "file_write", "search", "web_search"],
        "allowed_skills": [],
        "model_config": {"preferred_model": "", "fallback_model": "", "temperature": 0.5, "max_tokens": 4096},
        "is_preset": True,
    },
    {
        "id": "preset-tech-advisor",
        "name": "技术顾问",
        "description": "深度分析架构设计和技术选型",
        "system_prompt": "你是一位资深技术顾问。帮助用户进行架构设计分析、技术选型评估、系统方案对比。分析全面深入，给出有理有据的建议。",
        "personality": {"tone": "professional", "verbosity": "detailed", "creativity": 0.5, "formality": 0.8},
        "expertise": {"domains": ["architecture", "analysis"], "languages": ["python", "typescript", "go", "rust"], "specialties": ["system-design", "tech-selection"]},
        "allowed_tools": ["file_read", "search", "web_search", "terminal"],
        "allowed_skills": [],
        "model_config": {"preferred_model": "", "fallback_model": "", "temperature": 0.6, "max_tokens": 8192},
        "is_preset": True,
    },
    {
        "id": "preset-data-analyst",
        "name": "数据分析师",
        "description": "专注数据处理、可视化和统计分析",
        "system_prompt": "你是一位专业的数据分析师。帮助用户进行数据清洗、统计分析、可视化图表制作。注重数据准确性和分析逻辑的严谨性。",
        "personality": {"tone": "professional", "verbosity": "normal", "creativity": 0.4, "formality": 0.7},
        "expertise": {"domains": ["data-analysis", "visualization"], "languages": ["python", "sql"], "specialties": ["statistics", "chart"]},
        "allowed_tools": ["file_read", "file_write", "terminal", "search"],
        "allowed_skills": [],
        "model_config": {"preferred_model": "", "fallback_model": "", "temperature": 0.4, "max_tokens": 4096},
        "is_preset": True,
    },
    {
        "id": "preset-creative-writer",
        "name": "创意写作",
        "description": "富有创意的文案和内容创作",
        "system_prompt": "你是一位富有创意的写作助手。帮助用户进行文案创作、内容策划、故事构思。风格灵活多变，善于捕捉用户需求并给出新颖的表达。",
        "personality": {"tone": "friendly", "verbosity": "detailed", "creativity": 0.9, "formality": 0.3},
        "expertise": {"domains": ["writing", "creative"], "languages": [], "specialties": ["copywriting", "storytelling"]},
        "allowed_tools": ["file_read", "file_write", "search", "web_search"],
        "allowed_skills": [],
        "model_config": {"preferred_model": "", "fallback_model": "", "temperature": 0.8, "max_tokens": 4096},
        "is_preset": True,
    },
]


class RoleEngine:
    """
    AI 角色引擎，负责角色的加载、注入和约束。

    工作流：
    1. 加载角色配置（从数据库或预设模板）
    2. 注入 system_prompt 到 Agent 上下文
    3. 约束工具权限（只允许 allowed_tools + allowed_skills）
    4. 应用模型配置（preferred_model, temperature, max_tokens）
    5. 绑定知识库（从 knowledge_base_ids 加载上下文）
    """

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def load_role(self, role_id: str) -> Optional[AgentRole]:
        """从数据库加载角色配置。"""
        if self._db is None:
            logger.bind(event="role_engine_no_db", module="role_engine").warning(
                "数据库会话未初始化，无法加载角色"
            )
            return None
        return self._db.query(AgentRole).filter(AgentRole.id == role_id).first()

    def apply_role_to_context(
        self, role: AgentRole, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """将角色配置应用到 Agent 执行上下文。"""
        # 1. 注入 system_prompt
        context["system_prompt_override"] = role.system_prompt

        # 2. 应用 personality 参数
        personality = role.personality or {}
        if personality:
            context["personality"] = personality

        # 3. 约束工具权限
        allowed_tools = role.allowed_tools or []
        allowed_skills = role.allowed_skills or []
        if allowed_tools:
            context["allowed_tools_override"] = allowed_tools
        if allowed_skills:
            context["allowed_skills_override"] = allowed_skills

        # 4. 应用模型配置
        model_config = role.model_config or {}
        if model_config:
            context["model_config_override"] = model_config

        # 5. 绑定知识库
        knowledge_base_ids = role.knowledge_base_ids or []
        if knowledge_base_ids:
            context["knowledge_base_ids"] = knowledge_base_ids

        # 6. 记录角色信息
        context["role_id"] = role.id
        context["role_name"] = role.name

        return context

    def filter_tools_by_role(
        self, role: AgentRole, all_tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """根据角色权限过滤可用工具列表。"""
        allowed_tools = role.allowed_tools or []
        if not allowed_tools:
            return all_tools

        filtered = []
        for tool in all_tools:
            tool_name = tool.get("function", {}).get("name", "")
            if tool_name in allowed_tools:
                filtered.append(tool)
        return filtered

    @staticmethod
    def get_preset_roles() -> List[Dict[str, Any]]:
        """获取预设角色模板列表。"""
        return PRESET_ROLES.copy()

    @staticmethod
    def ensure_presets_in_db(db: Session) -> int:
        """确保预设角色已写入数据库，返回新增数量。"""
        added = 0
        for preset in PRESET_ROLES:
            existing = db.query(AgentRole).filter(AgentRole.id == preset["id"]).first()
            if not existing:
                role = AgentRole(**preset)
                db.add(role)
                added += 1
        if added > 0:
            db.commit()
        return added
