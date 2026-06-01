"""
guidance 内置技能 — 结构化引导和提示词模板。
为常见任务提供标准化的操作指引和模板。
"""
from typing import Any, Optional
from loguru import logger

SKILL_NAME = "guidance"
SKILL_DESCRIPTION = "为安装、配置和常见任务提供结构化引导和提示词模板"

# 引导模板库
TEMPLATES = {
    "setup": {
        "title": "环境安装与配置引导",
        "steps": [
            "检查 Python 3.11+ 是否安装: python --version",
            "安装依赖: pip install -r requirements.txt",
            "配置环境变量: 编辑 .env 文件设置 SECRET_KEY 和模型 API Key",
            "初始化数据库: openawa migrate",
            "启动服务: openawa serve",
        ],
    },
    "model_config": {
        "title": "模型配置引导",
        "steps": [
            "获取 API Key (DashScope/OpenAI/Anthropic)",
            "在控制台 设置 → 模型 页面配置提供商",
            "启用所需模型",
            "在聊天页面选择模型开始对话",
        ],
    },
    "skill_create": {
        "title": "创建自定义技能引导",
        "steps": [
            "确定技能的功能和名称",
            "使用 /make-skill 命令从对话中生成技能",
            "或手动创建 backend/skills/builtin/your_skill.py",
            "实现 execute 函数，遵循 SkillExecutor 协议",
            "在技能管理页面启用技能",
        ],
    },
    "debug": {
        "title": "问题排查引导",
        "steps": [
            "运行 openawa doctor 进行系统诊断",
            "检查日志: logs/ 目录下的日志文件",
            "验证 API Key 是否正确配置",
            "检查数据库连接: openawa doctor --fix",
            "查看控制台: http://localhost:8000/docs 检查 API 状态",
        ],
    },
}


async def execute(
    topic: str = "setup",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    获取指定主题的结构化引导。

    Args:
        topic: 引导主题（setup/model_config/skill_create/debug）

    Returns:
        引导内容和步骤
    """
    template = TEMPLATES.get(topic)
    if not template:
        available = ", ".join(TEMPLATES.keys())
        return {
            "success": False,
            "error": f"未知引导主题: {topic}",
            "available_topics": available,
        }

    logger.bind(event="guidance_skill", topic=topic).info("提供引导")

    return {
        "success": True,
        "topic": topic,
        "title": template["title"],
        "steps": template["steps"],
        "steps_count": len(template["steps"]),
    }
