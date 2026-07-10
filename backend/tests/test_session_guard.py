"""
chat 路由 session 归属校验单元测试。

覆盖 backend/api/routes/_session_guard.py 的 assert_session_owner 行为：
- 空 session_id 与 'default' 跳过校验
- session 属于当前用户时不抛异常
- session 不属于当前用户时 raise HTTPException 403
- session 不存在时放行（与 WebSocket 路径一致，首次消息会创建记录）

测试使用独立内存 SQLite 数据库，不依赖全局 app lifespan，避免污染主库。
"""

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.routes._session_guard import assert_session_owner
from db.models import Base, ConversationRecord


# 模块级独立内存数据库：StaticPool 保证同一连接复用，create_all 在测试收集阶段建表
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

Base.metadata.create_all(bind=_engine)


def _reset_records() -> None:
    """每个用例前清空 ConversationRecord 表，避免用例间残留污染。"""
    db = _TestingSessionLocal()
    try:
        db.query(ConversationRecord).delete()
        db.commit()
    finally:
        db.close()


def setup_function() -> None:
    _reset_records()


def teardown_function() -> None:
    _reset_records()


def _make_record(session_id: str, user_id: str) -> None:
    """插入一条 ConversationRecord 用于归属校验。"""
    db = _TestingSessionLocal()
    try:
        db.add(
            ConversationRecord(
                session_id=session_id,
                user_id=user_id,
                node_type="chat",
                user_message="hello",
                status="success",
            )
        )
        db.commit()
    finally:
        db.close()


def test_assert_session_owner_skips_when_session_id_empty() -> None:
    """session_id 为空字符串时不应查库、不应抛异常。"""
    db = _TestingSessionLocal()
    try:
        # 不应抛异常
        assert_session_owner(db, "", user_id=123)
    finally:
        db.close()


def test_assert_session_owner_skips_default_session_id() -> None:
    """session_id == 'default' 时跳过校验（前端首次发消息时尚未创建会话）。"""
    db = _TestingSessionLocal()
    try:
        # 即使数据库中存在 user_id 不一致的 default 记录，也不应抛异常
        _make_record(session_id="default", user_id="other-user")
        assert_session_owner(db, "default", user_id=123)
    finally:
        db.close()


def test_assert_session_owner_passes_when_session_belongs_to_user() -> None:
    """session 属于当前用户时不应抛异常（user_id 类型差异不影响比对）。"""
    _make_record(session_id="sess-owner", user_id="123")
    db = _TestingSessionLocal()
    try:
        assert_session_owner(db, "sess-owner", user_id=123)
    finally:
        db.close()


def test_assert_session_owner_raises_403_when_session_belongs_to_other() -> None:
    """session 不属于当前用户时 raise HTTPException 403 session_owner_mismatch。"""
    _make_record(session_id="sess-other", user_id="user-2")
    db = _TestingSessionLocal()
    try:
        with pytest.raises(HTTPException) as exc_info:
            assert_session_owner(db, "sess-other", user_id=123)

        assert exc_info.value.status_code == 403
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail.get("code") == "session_owner_mismatch"
        assert "message" in detail
    finally:
        db.close()


def test_assert_session_owner_passes_when_session_not_found() -> None:
    """session 不存在时放行，与 WebSocket 路径一致（首次消息会创建记录）。"""
    db = _TestingSessionLocal()
    try:
        # 数据库为空，session_id 不存在任何记录
        assert_session_owner(db, "sess-not-exist", user_id=123)
    finally:
        db.close()
