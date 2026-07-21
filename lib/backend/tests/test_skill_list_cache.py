"""
SkillRegistry.list_all 缓存单元测试。

覆盖 backend/skills/skill_registry.py 的 list_all 缓存逻辑：
- 首次 list_all（无 filters）查数据库并填充缓存
- 第二次 list_all（无 filters）命中缓存
- enable/disable/increment_usage 后缓存失效
- 带 filters 的 list_all 不走缓存，每次查 DB

使用独立内存 SQLite 数据库，避免污染主库。
"""

import sys
import uuid
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.models import Base, Skill
from skills.skill_registry import SkillRegistry


# 模块级独立内存数据库
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


def _reset_skills() -> None:
    """每个用例前清空 skills 表。"""
    db = _TestingSessionLocal()
    try:
        db.query(Skill).delete()
        db.commit()
    finally:
        db.close()


def setup_function() -> None:
    _reset_skills()


def teardown_function() -> None:
    _reset_skills()


def _insert_skill(name: str, *, enabled: bool = True, usage_count: int = 0) -> Skill:
    """插入一条 Skill 记录用于测试。"""
    db = _TestingSessionLocal()
    try:
        skill = Skill(
            id=str(uuid.uuid4()),
            name=name,
            version="1.0.0",
            description=f"测试技能 {name}",
            config={},
            category="general",
            tags=[],
            dependencies=[],
            author="tester",
            enabled=enabled,
            usage_count=usage_count,
        )
        db.add(skill)
        db.commit()
        db.refresh(skill)
        db.expunge(skill)
        return skill
    finally:
        db.close()


def _make_registry() -> SkillRegistry:
    """创建 SkillRegistry，绑定独立测试数据库会话。"""
    db = _TestingSessionLocal()
    return SkillRegistry(db)


def _close_registry(registry: SkillRegistry) -> None:
    """关闭 registry 持有的 db 会话。"""
    try:
        registry.db.close()
    except Exception:
        pass


def test_first_list_all_queries_db_and_fills_cache() -> None:
    """首次 list_all（无 filters）应查数据库并填充缓存。"""
    _insert_skill("skill-1")
    _insert_skill("skill-2")

    registry = _make_registry()
    try:
        assert registry._list_cache is None

        skills = registry.list_all()

        assert len(skills) == 2
        # 缓存应被填充
        assert registry._list_cache is not None
        assert len(registry._list_cache) == 2
    finally:
        _close_registry(registry)


def test_second_list_all_hits_cache() -> None:
    """第二次 list_all（无 filters）应命中缓存，不再次查 DB。"""
    _insert_skill("skill-1")

    registry = _make_registry()
    try:
        first_call = registry.list_all()
        assert len(first_call) == 1

        # 在第一次调用后，向 DB 插入新技能（缓存不知情）
        _insert_skill("skill-2")

        # 第二次调用应命中缓存，仍返回 1 条（缓存未失效）
        second_call = registry.list_all()
        assert len(second_call) == 1
        assert second_call[0].name == "skill-1"
        # 缓存对象应未变（同一引用）
        assert registry._list_cache is not None
        assert len(registry._list_cache) == 1
    finally:
        _close_registry(registry)


def test_enable_invalidates_cache() -> None:
    """enable 后缓存应失效，下次 list_all 重新查 DB。"""
    _insert_skill("skill-1", enabled=False)
    registry = _make_registry()
    try:
        registry.list_all()
        assert registry._list_cache is not None

        # 启用技能，触发缓存失效
        result = registry.enable("skill-1")
        assert result is True
        assert registry._list_cache is None

        # 下次 list_all 应重新查 DB
        skills = registry.list_all()
        assert len(skills) == 1
        assert skills[0].enabled is True
    finally:
        _close_registry(registry)


def test_disable_invalidates_cache() -> None:
    """disable 后缓存应失效。"""
    _insert_skill("skill-1", enabled=True)
    registry = _make_registry()
    try:
        registry.list_all()
        assert registry._list_cache is not None

        result = registry.disable("skill-1")
        assert result is True
        assert registry._list_cache is None

        skills = registry.list_all()
        assert len(skills) == 1
        assert skills[0].enabled is False
    finally:
        _close_registry(registry)


def test_increment_usage_invalidates_cache() -> None:
    """increment_usage 后缓存应失效。"""
    _insert_skill("skill-1", usage_count=0)
    registry = _make_registry()
    try:
        registry.list_all()
        assert registry._list_cache is not None

        result = registry.increment_usage("skill-1")
        assert result is True
        assert registry._list_cache is None

        skills = registry.list_all()
        assert len(skills) == 1
        assert skills[0].usage_count == 1
    finally:
        _close_registry(registry)


def test_list_all_with_filters_does_not_use_cache() -> None:
    """带 filters 的 list_all 不走缓存路径，每次都查 DB。"""
    _insert_skill("skill-1", enabled=True)
    _insert_skill("skill-2", enabled=False)

    registry = _make_registry()
    try:
        # 第一次带 filters 查询
        enabled_skills = registry.list_all(filters={"enabled": True})
        assert len(enabled_skills) == 1
        assert enabled_skills[0].name == "skill-1"
        # 带 filters 时不应填充 _list_cache
        assert registry._list_cache is None

        # 第二次带不同 filters 查询
        disabled_skills = registry.list_all(filters={"enabled": False})
        assert len(disabled_skills) == 1
        assert disabled_skills[0].name == "skill-2"
        assert registry._list_cache is None
    finally:
        _close_registry(registry)


def test_list_all_with_filters_does_not_pollute_cache() -> None:
    """带 filters 查询后，无 filters 的 list_all 仍应正常填充缓存。"""
    _insert_skill("skill-1", enabled=True)
    _insert_skill("skill-2", enabled=False)

    registry = _make_registry()
    try:
        # 先带 filters 查询
        registry.list_all(filters={"enabled": True})
        assert registry._list_cache is None

        # 再无 filters 查询，应填充缓存
        all_skills = registry.list_all()
        assert len(all_skills) == 2
        assert registry._list_cache is not None
        assert len(registry._list_cache) == 2
    finally:
        _close_registry(registry)


def test_register_invalidates_cache() -> None:
    """register 新技能后缓存应失效。

    注：register 内部构造 Skill 时漏传 tags/dependencies/author 字段，
    会触发 NOT NULL 约束（源码已知缺陷，不在本测试修复范围）。
    这里 mock 掉 db.add/commit/refresh，仅验证缓存失效行为。
    """
    _insert_skill("skill-1")
    registry = _make_registry()
    try:
        registry.list_all()
        assert registry._list_cache is not None

        # mock db 操作避免触发 register 内部的 NOT NULL 约束缺陷
        registry.db.add = MagicMock()
        registry.db.commit = MagicMock()
        registry.db.refresh = MagicMock()

        registry.register({
            "name": "skill-2",
            "version": "1.0.0",
            "description": "新技能",
            "config": {},
            "enabled": True,
        })
        # register 应主动失效 list_all 缓存
        assert registry._list_cache is None
    finally:
        _close_registry(registry)


def test_unregister_invalidates_cache() -> None:
    """unregister 删除技能后缓存应失效。"""
    _insert_skill("skill-1")
    _insert_skill("skill-2")
    registry = _make_registry()
    try:
        registry.list_all()
        assert registry._list_cache is not None

        result = registry.unregister("skill-1")
        assert result is True
        assert registry._list_cache is None

        skills = registry.list_all()
        assert len(skills) == 1
        assert skills[0].name == "skill-2"
    finally:
        _close_registry(registry)
