"""
事务一致性测试。
覆盖 maybe_extract 与 CRUD 接口中的事务收敛行为：
- extract + 桥接均成功时统一 commit
- 桥接失败时 ProfileFact 也回滚
- CRUD 接口中桥接失败时 ProfileFact 更新也回滚
"""

from __future__ import annotations

from typing import Any, Dict, Generator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
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


class _MockExtractor:
    """
    模拟 ProfileExtractor，跳过 LLM 调用。
    直接写入一条 ProfileFact（flush 不 commit）并返回包含 decisions 的结果，
    供 maybe_extract 桥接到 OnionProfile 增量持久化。
    """

    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    async def extract(
        self,
        session_ids: Optional[List[str]] = None,
        trigger_type: str = "auto",
        model_name: str = "gpt-4o-mini",
        commit: bool = True,
    ) -> Dict[str, Any]:
        """模拟提取：写入一条 ProfileFact 并返回 decisions。"""
        fact = ProfileFact(
            id="mock-fact-txn",
            user_id=self.user_id,
            category="behavior",
            fact_key="lang",
            fact_value="Python",
            confidence=0.85,
            source_type="inferred",
        )
        self.db.add(fact)
        # flush 让变更在当前事务可见，不 commit，等待 maybe_extract 统一提交
        self.db.flush()
        return {
            "status": "success",
            "facts_added": 1,
            "decisions": [{
                "category": "behavior",
                "fact_key": "lang",
                "fact_value": "Python",
                "action": "add",
            }],
        }


def _mock_probe_generator() -> MagicMock:
    """构造返回空探针列表的 mock probe generator，避免探针生成副作用。"""
    mock_gen = MagicMock()
    mock_gen.generate_probes = AsyncMock(return_value=[])
    return mock_gen


async def test_maybe_extract_transaction_success(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """extract + 桥接均成功时统一 commit，ProfileFact 与 OnionProfile 同时落库。"""
    user_id = "user-txn-ok"

    with patch(
        "plugins.user_profile_builtin.profile_extractor.ProfileExtractor", _MockExtractor
    ), patch(
        "soul.probe_generator.get_probe_generator", return_value=_mock_probe_generator()
    ):
        result = await coordinator.maybe_extract(user_id, db_session, force=True)

    # 提取结果应为成功
    assert result is not None
    assert result["status"] == "success"

    # ProfileFact 应已落库（统一 commit 后可见）
    fact = db_session.query(ProfileFact).filter(
        ProfileFact.user_id == user_id,
        ProfileFact.id == "mock-fact-txn",
    ).first()
    assert fact is not None
    assert fact.fact_value == "Python"

    # OnionProfile 应已落库（桥接成功后统一 commit）
    profile = load_profile(db_session, user_id)
    assert profile is not None
    assert "Python" in profile.surface.description
    assert profile.surface.structured_data.get("lang") == "Python"


async def test_maybe_extract_transaction_rollback(
    db_session: Session, coordinator: ProfileExtractionCoordinator
) -> None:
    """桥接失败时 ProfileFact 也回滚，两者保持事务一致性。"""
    user_id = "user-txn-rollback"

    # 模拟 save_profile 抛出数据库异常，触发桥接失败
    with patch(
        "plugins.user_profile_builtin.profile_extractor.ProfileExtractor", _MockExtractor
    ), patch(
        "soul.probe_generator.get_probe_generator", return_value=_mock_probe_generator()
    ), patch(
        "soul.persistence.save_profile",
        side_effect=SQLAlchemyError("simulated database failure"),
    ):
        result = await coordinator.maybe_extract(user_id, db_session, force=True)

    # 提取结果应为失败
    assert result is not None
    assert result["status"] == "failed"

    # ProfileFact 应已回滚（不在数据库中）
    fact = db_session.query(ProfileFact).filter(
        ProfileFact.user_id == user_id,
    ).first()
    assert fact is None

    # OnionProfile 应未写入（load_profile 返回 None）
    profile = load_profile(db_session, user_id)
    assert profile is None


async def test_crud_fact_transaction_rollback(
    db_session: Session,
) -> None:
    """CRUD 接口中桥接失败时 ProfileFact 更新也回滚。"""
    from api.routes.user_profile import FactUpdate, update_profile_fact

    user_id = "user-crud-rollback"

    # 预置一条 ProfileFact
    fact = ProfileFact(
        id="fact-crud-1",
        user_id=user_id,
        category="behavior",
        fact_key="lang",
        fact_value="OriginalValue",
        confidence=0.7,
        source_type="inferred",
    )
    db_session.add(fact)
    db_session.commit()

    class DummyUser:
        id = user_id
        username = "tester"

    # 模拟 save_profile 抛出数据库异常，触发桥接失败
    with patch(
        "soul.persistence.save_profile",
        side_effect=SQLAlchemyError("simulated database failure"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await update_profile_fact(
                fact_id="fact-crud-1",
                payload=FactUpdate(fact_value="NewValue"),
                db=db_session,
                current_user=DummyUser(),
            )

    # 路由应返回 500
    assert exc_info.value.status_code == 500

    # ProfileFact 更新应已回滚（值仍为 OriginalValue）
    db_session.expire_all()
    fresh_fact = db_session.query(ProfileFact).filter(
        ProfileFact.id == "fact-crud-1",
    ).first()
    assert fresh_fact is not None
    assert fresh_fact.fact_value == "OriginalValue"
    assert fresh_fact.confidence == 0.7
