"""
_persist_onion_profile 增量模式单元测试。
覆盖全量重建 fallback、增量 add/update/delete、emotional_state/custom 分类映射等场景。
验证 ProfileFact -> OnionProfile 五层桥接的正确性与增量保留未受影响层的设计。
"""

from __future__ import annotations

from typing import Generator

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


def test_persist_onion_profile_full_rebuild_no_changed_facts(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """不传 changed_facts 时走全量重建，五层按分类映射填充。"""
    user_id = "user-full-rebuild"
    facts = [
        _make_fact("f1", user_id, "behavior", "language", "Python"),
        _make_fact("f2", user_id, "preference", "fruit", "Apple"),
        _make_fact("f3", user_id, "identity", "role", "Engineer"),
        _make_fact("f4", user_id, "goal", "target", "Ship product"),
    ]
    db_session.add_all(facts)
    db_session.commit()

    # changed_facts=None 走全量重建 fallback
    coordinator._persist_onion_profile(db_session, user_id, changed_facts=None)

    profile = load_profile(db_session, user_id)
    assert profile is not None
    # behavior -> surface
    assert "Python" in profile.surface.description
    assert profile.surface.structured_data.get("language") == "Python"
    # preference -> interest
    assert "Apple" in profile.interest.description
    assert profile.interest.structured_data.get("fruit") == "Apple"
    # identity -> role
    assert "Engineer" in profile.role.description
    # goal -> values
    assert "Ship product" in profile.values.description
    # core 层无分类映射，应为空
    assert profile.core.description == ""


def test_persist_onion_profile_incremental_add(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """传入 add action 的 changed_facts，仅重建受影响层，未受影响层保留原数据。"""
    user_id = "user-inc-add"
    # 先建立 baseline：surface 与 interest 两层有数据
    baseline_facts = [
        _make_fact("f1", user_id, "behavior", "lang", "Python"),
        _make_fact("f2", user_id, "preference", "fruit", "Apple"),
    ]
    db_session.add_all(baseline_facts)
    db_session.commit()
    coordinator._persist_onion_profile(db_session, user_id, changed_facts=None)

    baseline = load_profile(db_session, user_id)
    assert baseline is not None
    assert "Python" in baseline.surface.description

    # 新增一条 preference 事实（映射到 interest 层）
    new_fact = _make_fact("f3", user_id, "preference", "drink", "Coffee")
    db_session.add(new_fact)
    db_session.commit()

    # 增量重建：仅 interest 层受影响
    coordinator._persist_onion_profile(
        db_session,
        user_id,
        changed_facts=[{
            "category": "preference",
            "fact_key": "drink",
            "fact_value": "Coffee",
            "action": "add",
        }],
    )

    profile = load_profile(db_session, user_id)
    assert profile is not None
    # interest 层应包含新增的 Coffee 与原有的 Apple（同层查询所有活跃事实）
    assert "Coffee" in profile.interest.description
    assert profile.interest.structured_data.get("drink") == "Coffee"
    assert "Apple" in profile.interest.description
    # surface 层未受影响，应保留 baseline 数据
    assert "Python" in profile.surface.description
    assert profile.surface.structured_data.get("lang") == "Python"


def test_persist_onion_profile_incremental_update(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """传入 update action，仅重建受影响层并反映更新值。"""
    user_id = "user-inc-upd"
    facts = [
        _make_fact("f1", user_id, "behavior", "lang", "Python"),
        _make_fact("f2", user_id, "preference", "fruit", "Apple"),
    ]
    db_session.add_all(facts)
    db_session.commit()
    coordinator._persist_onion_profile(db_session, user_id, changed_facts=None)

    # 更新 behavior 事实值
    fact = db_session.query(ProfileFact).filter(ProfileFact.id == "f1").first()
    fact.fact_value = "Rust"
    db_session.commit()

    # 增量重建：仅 surface 层受影响
    coordinator._persist_onion_profile(
        db_session,
        user_id,
        changed_facts=[{
            "category": "behavior",
            "fact_key": "lang",
            "fact_value": "Rust",
            "action": "update",
        }],
    )

    profile = load_profile(db_session, user_id)
    assert profile is not None
    # surface 层应反映更新后的值
    assert "Rust" in profile.surface.description
    assert "Python" not in profile.surface.description
    assert profile.surface.structured_data.get("lang") == "Rust"
    # interest 层未受影响，保留原值
    assert "Apple" in profile.interest.description


def test_persist_onion_profile_incremental_delete(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """传入 delete action，仅重建受影响层，被软删的事实不再出现。"""
    user_id = "user-inc-del"
    facts = [
        _make_fact("f1", user_id, "behavior", "lang", "Python"),
        _make_fact("f2", user_id, "behavior", "editor", "VSCode"),
        _make_fact("f3", user_id, "preference", "fruit", "Apple"),
    ]
    db_session.add_all(facts)
    db_session.commit()
    coordinator._persist_onion_profile(db_session, user_id, changed_facts=None)

    baseline = load_profile(db_session, user_id)
    assert baseline is not None
    assert "Python" in baseline.surface.description
    assert "VSCode" in baseline.surface.description

    # 软删除 lang 事实（is_active=False）
    fact = db_session.query(ProfileFact).filter(ProfileFact.id == "f1").first()
    fact.is_active = False
    db_session.commit()

    # 增量重建：仅 surface 层受影响
    coordinator._persist_onion_profile(
        db_session,
        user_id,
        changed_facts=[{
            "category": "behavior",
            "fact_key": "lang",
            "fact_value": "Python",
            "action": "delete",
        }],
    )

    profile = load_profile(db_session, user_id)
    assert profile is not None
    # surface 层不再包含被软删的 Python
    assert "Python" not in profile.surface.description
    assert "lang" not in profile.surface.structured_data
    # 同层其他活跃事实保留
    assert "VSCode" in profile.surface.description
    # interest 层未受影响
    assert "Apple" in profile.interest.description


def test_persist_onion_profile_emotional_state_mapping(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """emotional_state 分类映射到 surface 层，不被丢弃到 core 层。"""
    user_id = "user-emo"
    db_session.add(_make_fact("f1", user_id, "emotional_state", "mood", "Focused"))
    db_session.commit()

    coordinator._persist_onion_profile(
        db_session,
        user_id,
        changed_facts=[{
            "category": "emotional_state",
            "fact_key": "mood",
            "fact_value": "Focused",
            "action": "add",
        }],
    )

    profile = load_profile(db_session, user_id)
    assert profile is not None
    # emotional_state -> surface 层
    assert "Focused" in profile.surface.description
    assert profile.surface.structured_data.get("mood") == "Focused"
    # core 层不应包含 emotional_state（衰减快，不适合核心层）
    assert "Focused" not in profile.core.description
    assert profile.core.description == ""


def test_persist_onion_profile_custom_mapping(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """custom 分类映射到 surface 层，不被丢弃。"""
    user_id = "user-custom"
    db_session.add(_make_fact("f1", user_id, "custom", "hobby", "Astronomy"))
    db_session.commit()

    coordinator._persist_onion_profile(
        db_session,
        user_id,
        changed_facts=[{
            "category": "custom",
            "fact_key": "hobby",
            "fact_value": "Astronomy",
            "action": "add",
        }],
    )

    profile = load_profile(db_session, user_id)
    assert profile is not None
    # custom -> surface 层
    assert "Astronomy" in profile.surface.description
    assert profile.surface.structured_data.get("hobby") == "Astronomy"
    # 其他层不应包含
    assert "Astronomy" not in profile.interest.description
    assert "Astronomy" not in profile.role.description
