"""
分类映射完整性测试。
验证 ProfileFact.category 到 OnionProfile 五层的映射完整性：
- emotional_state 不被丢弃，正确出现在 surface 层
- custom 不被丢弃，正确出现在 surface 层
- 所有 9 个分类都有对应的层，无遗漏
"""

from __future__ import annotations

from typing import Generator, List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base, ProfileFact
from plugins.user_profile_builtin.coordinator import ProfileExtractionCoordinator
from soul.persistence import load_profile


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


@pytest.fixture
def coordinator() -> ProfileExtractionCoordinator:
    """创建独立的协调器实例，避免模块级单例污染。"""
    return ProfileExtractionCoordinator()


def _make_fact(
    fact_id: str,
    user_id: str,
    category: str,
    fact_key: str,
    fact_value: str,
    confidence: float = 0.8,
) -> ProfileFact:
    """构造 ProfileFact 测试对象。"""
    return ProfileFact(
        id=fact_id,
        user_id=user_id,
        category=category,
        fact_key=fact_key,
        fact_value=fact_value,
        confidence=confidence,
        is_active=True,
        source_type="inferred",
    )


def test_emotional_state_not_dropped(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """emotional_state 事实出现在 OnionProfile surface 层，不被丢弃。"""
    user_id = "user-emo-complete"
    db_session.add(_make_fact("f1", user_id, "emotional_state", "mood", "Calm"))
    db_session.commit()

    coordinator._persist_onion_profile(db_session, user_id, changed_facts=None)

    profile = load_profile(db_session, user_id)
    assert profile is not None
    # emotional_state 应映射到 surface 层，不被丢弃
    assert "Calm" in profile.surface.description
    assert profile.surface.structured_data.get("mood") == "Calm"
    # 不应出现在其他层
    assert "Calm" not in profile.interest.description
    assert "Calm" not in profile.role.description
    assert "Calm" not in profile.values.description
    assert "Calm" not in profile.core.description


def test_custom_not_dropped(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """custom 事实出现在 OnionProfile surface 层，不被丢弃。"""
    user_id = "user-custom-complete"
    db_session.add(_make_fact("f1", user_id, "custom", "signature", "UniqueTrait"))
    db_session.commit()

    coordinator._persist_onion_profile(db_session, user_id, changed_facts=None)

    profile = load_profile(db_session, user_id)
    assert profile is not None
    # custom 应映射到 surface 层，不被丢弃
    assert "UniqueTrait" in profile.surface.description
    assert profile.surface.structured_data.get("signature") == "UniqueTrait"
    # 不应出现在其他层
    assert "UniqueTrait" not in profile.interest.description
    assert "UniqueTrait" not in profile.role.description
    assert "UniqueTrait" not in profile.values.description
    assert "UniqueTrait" not in profile.core.description


def test_all_categories_mapped(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """所有 ProfileFact 分类都有对应层，无事实被丢弃。"""
    user_id = "user-all-categories"

    # 9 个分类各一条事实
    # 期望映射关系（与 coordinator._CATEGORY_TO_LAYER 一致）:
    # behavior/context/emotional_state/custom -> surface
    # preference -> interest
    # identity/expertise -> role
    # goal/communication_style -> values
    facts: List[ProfileFact] = [
        _make_fact("f1", user_id, "behavior", "bk1", "BehaviorVal"),
        _make_fact("f2", user_id, "context", "ck1", "ContextVal"),
        _make_fact("f3", user_id, "emotional_state", "ek1", "EmotionVal"),
        _make_fact("f4", user_id, "custom", "xk1", "CustomVal"),
        _make_fact("f5", user_id, "preference", "pk1", "PreferenceVal"),
        _make_fact("f6", user_id, "identity", "ik1", "IdentityVal"),
        _make_fact("f7", user_id, "expertise", "exk1", "ExpertiseVal"),
        _make_fact("f8", user_id, "goal", "gk1", "GoalVal"),
        _make_fact("f9", user_id, "communication_style", "csk1", "CommStyleVal"),
    ]
    db_session.add_all(facts)
    db_session.commit()

    coordinator._persist_onion_profile(db_session, user_id, changed_facts=None)

    profile = load_profile(db_session, user_id)
    assert profile is not None

    # surface 层应包含 behavior/context/emotional_state/custom
    surface_values = profile.surface.structured_data
    assert surface_values.get("bk1") == "BehaviorVal"
    assert surface_values.get("ck1") == "ContextVal"
    assert surface_values.get("ek1") == "EmotionVal"
    assert surface_values.get("xk1") == "CustomVal"

    # interest 层应包含 preference
    assert profile.interest.structured_data.get("pk1") == "PreferenceVal"

    # role 层应包含 identity/expertise
    assert profile.role.structured_data.get("ik1") == "IdentityVal"
    assert profile.role.structured_data.get("exk1") == "ExpertiseVal"

    # values 层应包含 goal/communication_style
    assert profile.values.structured_data.get("gk1") == "GoalVal"
    assert profile.values.structured_data.get("csk1") == "CommStyleVal"

    # 所有事实的值都应出现在某层的 description 中（不被丢弃）
    all_descriptions: str = " ".join([
        profile.surface.description,
        profile.interest.description,
        profile.role.description,
        profile.values.description,
        profile.core.description,
    ])
    expected_values = [
        "BehaviorVal", "ContextVal", "EmotionVal", "CustomVal",
        "PreferenceVal", "IdentityVal", "ExpertiseVal",
        "GoalVal", "CommStyleVal",
    ]
    for val in expected_values:
        assert val in all_descriptions, f"分类映射遗漏：{val} 未出现在任何层"
