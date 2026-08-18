# -*- coding: utf-8 -*-
"""
SKILL.md skill 的 AI 自主调用链路单元测试。

验证一个 execution-mode: prompt 的 SKILL.md 格式技能能否被 AI 自主调用：
1. SkillGuidance 能从注册表列出已安装的 SKILL.md skill
2. SkillGuidance.format_skills_guidance 生成的系统提示包含该 skill
3. SkillEngine.execute_skill（prompt 模式）能从 config.prompt 读取并返回指令文本

测试隔离：每个测试用例使用独立的内存 SQLite 数据库，不依赖全局状态。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Dict

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 兼容性兜底：当 pytest-cov 的 import hooks 激活时，bcrypt 的 PyO3 扩展可能
# 抛 "PyO3 modules compiled for CPython 3.8 or older may only be initialized
# once per interpreter process" 错误。本测试文件不涉及密码哈希，
# 安全地注入 mock bcrypt 规避环境依赖问题。
if "bcrypt" not in sys.modules:
    try:
        import bcrypt  # noqa: F401
    except ImportError:
        _mock_bcrypt = types.ModuleType("bcrypt")
        _mock_bcrypt.hashpw = lambda *a, **k: b"mock"
        _mock_bcrypt.checkpw = lambda *a, **k: True
        _mock_bcrypt.gensalt = lambda *a, **k: b"mock"
        _mock_bcrypt.__version__ = "mock"
        sys.modules["bcrypt"] = _mock_bcrypt

from core.skill_guidance import SkillGuidance  # noqa: E402
from db.models import Base, Skill  # noqa: E402
from skills.skill_engine import SkillEngine  # noqa: E402


# ==================== 测试常量：SKILL.md 格式技能样本 ====================

# SKILL.md 技能名称
SKILLMD_NAME = "commit-message-helper"

# SKILL.md frontmatter 中的 description 字段
SKILLMD_DESCRIPTION = "生成符合 Conventional Commits 规范的 Git 提交信息"

# SKILL.md 技能版本
SKILLMD_VERSION = "1.0.0"

# SKILL.md 正文（Markdown 指令），会被存入 config.prompt 字段
SKILLMD_PROMPT_BODY = """# Commit Message Helper

你是一个 Git 提交信息生成助手。请根据用户提供的 diff 内容，生成符合 Conventional Commits 规范的提交信息。

## 规则
1. 格式：`<type>(<scope>): <subject>`
2. type 必须是：feat / fix / docs / style / refactor / perf / test / chore / ci 之一
3. subject 不超过 50 字符，使用祈使句（英文）或动宾短语（中文）
4. 可选 body 用于补充动机与上下文

## 示例
feat(auth): 添加 OAuth2 登录支持
fix(billing): 修复计费金额小数位截断问题
"""


def _build_skillmd_config() -> Dict[str, Any]:
    """构造 SKILL.md 格式技能的 config 字典（对应 frontmatter + 正文）。"""
    return {
        "name": SKILLMD_NAME,
        "version": SKILLMD_VERSION,
        "description": SKILLMD_DESCRIPTION,
        "execution_mode": "prompt",
        "instructions": SKILLMD_PROMPT_BODY,
        "prompt": SKILLMD_PROMPT_BODY,
    }


# ==================== 公共 fixture ====================


@pytest.fixture()
def db_session():
    """创建独立的内存 SQLite 数据库会话，每个测试用例互相隔离。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def skillmd_record(db_session):
    """在数据库中插入一个 SKILL.md 格式技能记录。"""
    skill = Skill(
        id="test-skillmd-id",
        name=SKILLMD_NAME,
        version=SKILLMD_VERSION,
        description=SKILLMD_DESCRIPTION,
        config=_build_skillmd_config(),
        category="development",
        tags=[],
        dependencies=[],
        author="tester",
        enabled=True,
    )
    db_session.add(skill)
    db_session.commit()
    db_session.refresh(skill)
    return skill


@pytest.fixture()
def skill_engine(db_session, skillmd_record):
    """创建绑定到测试数据库的 SkillEngine（已预装 SKILL.md 技能）。"""
    return SkillEngine(db_session)


@pytest.fixture()
def skill_guidance(skill_engine):
    """创建绑定到 SkillEngine 的 SkillGuidance。"""
    return SkillGuidance(skill_engine=skill_engine)


# ==================== 测试 1：SkillGuidance 列出 SKILL.md skill ====================


class TestSkillGuidanceListsSkillmd:
    """SkillGuidance.get_available_skills 应列出已安装的 SKILL.md skill。"""

    @pytest.mark.asyncio
    async def test_get_available_skills_returns_skillmd(self, skill_guidance):
        """可用技能列表应包含 commit-message-helper 及其元数据。"""
        skills = await skill_guidance.get_available_skills()

        assert isinstance(skills, list)
        assert len(skills) >= 1

        target = next((s for s in skills if s["name"] == SKILLMD_NAME), None)
        assert target is not None, f"未在可用技能列表中找到 {SKILLMD_NAME}"
        assert target["description"] == SKILLMD_DESCRIPTION
        assert target["version"] == SKILLMD_VERSION
        assert target["enabled"] is True
        # SkillGuidance 输出字典应包含 is_builtin 和 usage_count 字段
        assert "is_builtin" in target
        assert "usage_count" in target

    @pytest.mark.asyncio
    async def test_get_available_skills_excludes_disabled(self, db_session, skill_guidance):
        """已禁用的技能不应出现在可用技能列表中。"""
        disabled_skill = Skill(
            id="test-disabled-skillmd-id",
            name="disabled-skillmd-skill",
            version="1.0.0",
            description="这个技能已被禁用，不应出现在可用列表中",
            config=_build_skillmd_config(),
            category="development",
            tags=[],
            dependencies=[],
            author="tester",
            enabled=False,
        )
        db_session.add(disabled_skill)
        db_session.commit()

        skills = await skill_guidance.get_available_skills()
        names = [s["name"] for s in skills]

        assert SKILLMD_NAME in names
        assert "disabled-skillmd-skill" not in names


# ==================== 测试 2：SkillGuidance.format_skills_guidance 生成系统提示 ====================


class TestSkillGuidanceFormatsSkillmd:
    """format_skills_guidance 生成的系统提示应包含 SKILL.md skill。"""

    @pytest.mark.asyncio
    async def test_format_skills_guidance_includes_skillmd(self, skill_guidance):
        """从注册表获取的技能列表经格式化后应包含技能名、描述和模板标题。"""
        skills = await skill_guidance.get_available_skills()
        guidance_text = skill_guidance.format_skills_guidance(
            skills, context_window=128000
        )

        # 模板标题
        assert "## 可用技能" in guidance_text
        # 技能名称
        assert SKILLMD_NAME in guidance_text
        # 技能描述
        assert SKILLMD_DESCRIPTION in guidance_text

    def test_format_skills_guidance_with_static_skill_list(self, skill_guidance):
        """直接传入静态技能列表，验证格式化输出。"""
        skills = [
            {
                "name": SKILLMD_NAME,
                "description": SKILLMD_DESCRIPTION,
                "version": SKILLMD_VERSION,
                "enabled": True,
                "is_builtin": False,
                "usage_count": 0,
            }
        ]
        guidance_text = skill_guidance.format_skills_guidance(
            skills, context_window=128000
        )

        assert "## 可用技能" in guidance_text
        assert SKILLMD_NAME in guidance_text
        assert SKILLMD_DESCRIPTION in guidance_text

    @pytest.mark.asyncio
    async def test_generate_guidance_returns_result_with_skillmd(self, skill_guidance):
        """generate_guidance 返回的 SkillGuidanceResult 应包含 SKILL.md 技能。"""
        result = await skill_guidance.generate_guidance(context_window=128000)

        assert result.available_count >= 1
        assert result.total_count >= 1
        assert SKILLMD_NAME in result.skills_text
        assert "## 可用技能" in result.skills_text


# ==================== 测试 4：SkillEngine prompt 模式执行 ====================


class TestSkillEnginePromptModeExecution:
    """SkillEngine.execute_skill 在 prompt 模式下应返回 SKILL.md 指令文本。"""

    @pytest.mark.asyncio
    async def test_execute_skill_returns_prompt_text(self, skill_engine):
        """prompt 模式执行应返回 success=True、execution_mode=prompt 及 prompt 字段。"""
        result = await skill_engine.execute_skill(
            skill_name=SKILLMD_NAME,
            inputs={},
            context={},
        )

        assert result["success"] is True
        assert result["skill_name"] == SKILLMD_NAME
        assert result["execution_mode"] == "prompt"
        # prompt 字段应包含 SKILL.md 指令正文
        assert "prompt" in result
        assert "Commit Message Helper" in result["prompt"]
        # 指令正文中的关键内容应被完整保留
        assert "Conventional Commits" in result["prompt"]
        # outputs 字段也应包含 prompt（保持与执行结果契约一致）
        assert result["outputs"]["prompt"] == result["prompt"]

    @pytest.mark.asyncio
    async def test_execute_skill_increments_usage_count(self, skill_engine):
        """prompt 模式执行成功后应增加 usage_count。"""
        before = skill_engine.registry.get(SKILLMD_NAME).usage_count
        await skill_engine.execute_skill(SKILLMD_NAME, inputs={}, context={})
        after = skill_engine.registry.get(SKILLMD_NAME).usage_count
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_execute_skill_template_variable_substitution(self, skill_engine):
        """prompt 中的 {variable} 占位符应被 context 中的值替换。"""
        # 在 config.prompt 中加入模板变量
        skill_record = skill_engine.registry.get(SKILLMD_NAME)
        skill_record.config = {
            **skill_record.config,
            "prompt": "请为以下范围生成提交信息: {scope}",
        }
        skill_engine.db_session.commit()
        # 清除 loader 缓存以使新配置生效
        skill_engine.loader._clear_cache()

        result = await skill_engine.execute_skill(
            skill_name=SKILLMD_NAME,
            inputs={},
            context={"scope": "auth 模块"},
        )

        assert result["success"] is True
        assert "auth 模块" in result["prompt"]
        assert "{scope}" not in result["prompt"]

    @pytest.mark.asyncio
    async def test_execute_skill_unknown_returns_failure(self, skill_engine):
        """调用未注册的技能应返回 success=False。"""
        result = await skill_engine.execute_skill(
            skill_name="nonexistent-skill",
            inputs={},
            context={},
        )
        assert result["success"] is False
        assert "not found" in result["error"].lower()
