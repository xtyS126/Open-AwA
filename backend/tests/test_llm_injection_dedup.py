"""
LLM 注入去重测试。
覆盖 _build_profile_facts_context 的事实去重逻辑：
- 高置信度事实已在 OnionProfile 中则不重复注入
- 未传入 onion_profile 时保持原行为
- 低置信度事实不注入
"""

from __future__ import annotations

from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.executor import _build_profile_facts_context
from db.models import Base, ProfileFact
from soul.profile import LayerData, OnionProfile


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """创建独立内存数据库会话，每个用例使用全新数据库实例。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_fact(
    fact_id: str,
    user_id: str,
    category: str,
    fact_key: str,
    fact_value: str,
    confidence: float = 0.9,
    is_active: bool = True,
) -> ProfileFact:
    """构造 ProfileFact 测试对象。"""
    return ProfileFact(
        id=fact_id,
        user_id=user_id,
        category=category,
        fact_key=fact_key,
        fact_value=fact_value,
        confidence=confidence,
        is_active=is_active,
        source_type="inferred",
    )


def test_build_profile_facts_context_dedup(db_session: Session) -> None:
    """高置信度事实已在 OnionProfile 中则不重复注入。"""
    user_id = "user-dedup"
    # 两条高置信度事实：lang 已在 OnionProfile 中，fruit 不在
    facts = [
        _make_fact("f1", user_id, "behavior", "lang", "Python", confidence=0.9),
        _make_fact("f2", user_id, "preference", "fruit", "Mango", confidence=0.85),
    ]
    db_session.add_all(facts)
    db_session.commit()

    # OnionProfile 的 surface 层已包含 lang=Python
    onion_profile = OnionProfile(
        user_id=user_id,
        surface=LayerData(
            description="Python",
            structured_data={"lang": "Python"},
            confidence=0.9,
        ),
    )

    result = _build_profile_facts_context(user_id, db_session, onion_profile=onion_profile)

    # lang=Python 已在 OnionProfile 中，应被去重，不出现在事实列表中
    assert "lang" not in result or "Python" not in result.split("lang")[-1].split("\n")[0]
    # 更精确的断言：结果中不应包含 "lang: Python"
    assert "lang: Python" not in result
    # fruit=Mango 不在 OnionProfile 中，应保留
    assert "fruit: Mango" in result


def test_build_profile_facts_context_no_onion_profile(db_session: Session) -> None:
    """未传入 onion_profile 时保持原行为，所有高置信度事实均注入。"""
    user_id = "user-no-onion"
    facts = [
        _make_fact("f1", user_id, "behavior", "lang", "Python", confidence=0.9),
        _make_fact("f2", user_id, "preference", "fruit", "Mango", confidence=0.85),
    ]
    db_session.add_all(facts)
    db_session.commit()

    # 不传 onion_profile，保持原行为（不去重）
    result = _build_profile_facts_context(user_id, db_session, onion_profile=None)

    # 两条高置信度事实都应出现
    assert "lang: Python" in result
    assert "fruit: Mango" in result


def test_build_profile_facts_context_low_confidence_excluded(db_session: Session) -> None:
    """低置信度事实不注入（confidence < 0.7 被过滤）。"""
    user_id = "user-low-conf"
    facts = [
        _make_fact("f1", user_id, "behavior", "lang", "Python", confidence=0.9),
        _make_fact("f2", user_id, "preference", "fruit", "Mango", confidence=0.5),
        _make_fact("f3", user_id, "identity", "role", "Engineer", confidence=0.69),
    ]
    db_session.add_all(facts)
    db_session.commit()

    result = _build_profile_facts_context(user_id, db_session, onion_profile=None)

    # 高置信度事实应出现
    assert "lang: Python" in result
    # 低置信度事实不应出现（< 0.7）
    assert "fruit: Mango" not in result
    assert "role: Engineer" not in result
