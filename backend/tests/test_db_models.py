"""
数据库 ORM 模型单元测试，使用 SQLite 内存数据库验证模型创建、查询、更新、约束和级联行为。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import (
    Base,
    User,
    LoginDevice,
    Skill,
    Plugin,
    Conversation,
    ShortTermMemory,
    ScheduledTask,
    ScheduledTaskExecution,
    Workflow,
    WorkflowStep,
    init_db,
)


@pytest.fixture
def db_session():
    """
    创建独立的内存数据库会话，每个测试用例使用全新的数据库实例，
    测试结束后销毁 engine，避免测试之间互相污染。
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 启用外键约束
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
    init_db(bind_engine=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ==================== User 模型测试 ====================

def test_user_create_success(db_session):
    """正常创建 User 记录并验证字段值。"""
    user = User(
        id="user-001",
        username="alice",
        password_hash="hashed_abc",
        role="admin",
        nickname="Alice",
        email="alice@example.com",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.id == "user-001"
    assert user.username == "alice"
    assert user.password_hash == "hashed_abc"
    assert user.role == "admin"
    assert user.nickname == "Alice"
    assert user.email == "alice@example.com"
    assert user.avatar_url is None
    assert user.phone is None
    assert user.profile_data is None  # Optional[JSON] 未传值时默认为 None
    assert isinstance(user.created_at, datetime)
    assert isinstance(user.updated_at, datetime)


def test_user_query_by_id(db_session):
    """通过主键查询 User 记录。"""
    user = User(id="user-002", username="bob", password_hash="hash_bob")
    db_session.add(user)
    db_session.commit()

    found = db_session.query(User).filter(User.id == "user-002").first()
    assert found is not None
    assert found.username == "bob"


def test_user_update_fields(db_session):
    """更新 User 的 nick 和 email 字段。"""
    user = User(id="user-003", username="charlie", password_hash="hash_charlie")
    db_session.add(user)
    db_session.commit()

    user.nickname = "Charlie Updated"
    user.email = "charlie_new@example.com"
    db_session.commit()
    db_session.refresh(user)

    assert user.nickname == "Charlie Updated"
    assert user.email == "charlie_new@example.com"


def test_user_default_role(db_session):
    """User 不传 role 时应使用默认值 'user'。"""
    user = User(id="user-004", username="dave", password_hash="hash_dave")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.role == "user"


def test_user_created_at_auto_fill(db_session):
    """创建 User 时 created_at 和 updated_at 应自动填充为当前时间。"""
    before = datetime.now(timezone.utc)
    user = User(id="user-005", username="eve", password_hash="hash_eve")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    after = datetime.now(timezone.utc)

    # SQLite 不保存时区信息，读取回的 datetime 为 offset-naive
    created = user.created_at.replace(tzinfo=timezone.utc)
    updated = user.updated_at.replace(tzinfo=timezone.utc)
    assert before <= created <= after
    assert before <= updated <= after


def test_user_updated_at_on_update(db_session):
    """更新 User 时 updated_at 应自动变更为最新时间。"""
    user = User(id="user-006", username="frank", password_hash="hash_frank")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    original_updated_at = user.updated_at

    # 等待一小段时间确保时间差可观测
    import time
    time.sleep(0.1)

    user.nickname = "Frank Updated"
    db_session.commit()
    db_session.refresh(user)

    assert user.updated_at > original_updated_at


# ==================== User 唯一约束测试 ====================

def test_username_unique_constraint(db_session):
    """插入重复 username 时应抛出 IntegrityError。"""
    user1 = User(id="user-007", username="george", password_hash="hash_1")
    user2 = User(id="user-008", username="george", password_hash="hash_2")
    db_session.add(user1)
    db_session.commit()

    db_session.add(user2)
    with pytest.raises(IntegrityError):
        db_session.commit()


# ==================== LoginDevice 级联删除测试 ====================

def test_login_device_cascade_delete(db_session):
    """删除 User 时关联的 LoginDevice 应被级联删除。"""
    user = User(id="user-009", username="hannah", password_hash="hash_hannah")
    db_session.add(user)
    db_session.commit()

    device1 = LoginDevice(user_id="user-009", device_type="mobile", ip_address="10.0.0.1")
    device2 = LoginDevice(user_id="user-009", device_type="desktop", ip_address="10.0.0.2")
    db_session.add_all([device1, device2])
    db_session.commit()

    # 验证两个设备都已创建
    assert db_session.query(LoginDevice).filter(LoginDevice.user_id == "user-009").count() == 2

    # 删除 User
    db_session.delete(user)
    db_session.commit()

    # 设备应被级联删除
    assert db_session.query(LoginDevice).filter(LoginDevice.user_id == "user-009").count() == 0


# ==================== ScheduledTask 外键约束测试 ====================

def test_scheduled_task_foreign_key_constraint(db_session):
    """ScheduledTask 引用不存在的 user_id 时应抛出 IntegrityError。"""
    task = ScheduledTask(
        user_id="non-existent-user",
        title="测试任务",
        prompt="测试提示词",
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(task)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_scheduled_task_create_with_valid_user(db_session):
    """ScheduledTask 关联存在的 User 时应正常创建。"""
    user = User(id="user-010", username="ivan", password_hash="hash_ivan")
    db_session.add(user)
    db_session.commit()

    task = ScheduledTask(
        user_id="user-010",
        title="每日报告",
        prompt="生成今日报告",
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        task_type="ai_prompt",
        is_daily=True,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    assert task.id is not None
    assert task.user_id == "user-010"
    assert task.title == "每日报告"
    assert task.status == "pending"
    assert task.is_daily is True


def test_scheduled_task_cascade_on_user_delete(db_session):
    """删除 User 时关联的 ScheduledTask 应被级联删除。"""
    user = User(id="user-011", username="jack", password_hash="hash_jack")
    db_session.add(user)
    db_session.commit()

    task = ScheduledTask(
        user_id="user-011",
        title="级联测试任务",
        prompt="级联删除验证",
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(task)
    db_session.commit()

    task_id = task.id
    assert db_session.query(ScheduledTask).filter(ScheduledTask.id == task_id).count() == 1

    db_session.delete(user)
    db_session.commit()

    assert db_session.query(ScheduledTask).filter(ScheduledTask.id == task_id).count() == 0


# ==================== ScheduledTaskExecution 级联删除测试 ====================

def test_scheduled_task_execution_cascade_on_task_delete(db_session):
    """删除 ScheduledTask 时关联的 ScheduledTaskExecution 应被级联删除。"""
    user = User(id="user-012", username="kate", password_hash="hash_kate")
    db_session.add(user)
    db_session.commit()

    task = ScheduledTask(
        user_id="user-012",
        title="级联删除测试",
        prompt="测试提示词",
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    db_session.add(task)
    db_session.commit()

    execution = ScheduledTaskExecution(
        task_id=task.id,
        user_id="user-012",
        task_title=task.title,
        prompt=task.prompt,
        scheduled_for=task.scheduled_at,
    )
    db_session.add(execution)
    db_session.commit()

    exec_id = execution.id
    assert db_session.query(ScheduledTaskExecution).filter(ScheduledTaskExecution.id == exec_id).count() == 1

    db_session.delete(task)
    db_session.commit()

    assert db_session.query(ScheduledTaskExecution).filter(ScheduledTaskExecution.id == exec_id).count() == 0


# ==================== Conversation 模型测试 ====================

def test_conversation_create_success(db_session):
    """正常创建 Conversation 记录。"""
    conv = Conversation(
        session_id="session-001",
        user_id="user-001",
        title="测试会话",
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    assert conv.id is not None
    assert conv.session_id == "session-001"
    assert conv.user_id == "user-001"
    assert conv.title == "测试会话"
    assert conv.summary == ""
    assert conv.message_count == 0
    assert conv.deleted_at is None
    assert conv.restored_at is None
    assert conv.purge_after is None
    assert isinstance(conv.conversation_metadata, dict)


def test_conversation_query_by_session_id(db_session):
    """通过 session_id 查询 Conversation。"""
    conv = Conversation(session_id="session-002", user_id="user-002", title="会话2")
    db_session.add(conv)
    db_session.commit()

    found = db_session.query(Conversation).filter(Conversation.session_id == "session-002").first()
    assert found is not None
    assert found.title == "会话2"


def test_conversation_soft_delete(db_session):
    """软删除：设置 deleted_at 时间戳标记会话为已删除。"""
    conv = Conversation(session_id="session-003", user_id="user-003", title="待删除会话")
    db_session.add(conv)
    db_session.commit()

    now = datetime.now(timezone.utc)
    conv.deleted_at = now
    db_session.commit()
    db_session.refresh(conv)

    # SQLite 不保存时区，读取回的 datetime 需补齐时区再比较
    deleted = conv.deleted_at.replace(tzinfo=timezone.utc)
    assert deleted == now

    # 查询非删除会话时应排除
    active = db_session.query(Conversation).filter(Conversation.deleted_at.is_(None)).all()
    assert all(c.deleted_at is None for c in active)
    assert conv not in active


def test_conversation_session_id_unique_constraint(db_session):
    """重复 session_id 应抛出 IntegrityError。"""
    conv1 = Conversation(session_id="session-004", user_id="user-004", title="第一个")
    conv2 = Conversation(session_id="session-004", user_id="user-005", title="第二个")
    db_session.add(conv1)
    db_session.commit()

    db_session.add(conv2)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_conversation_dates_auto_fill(db_session):
    """Conversation 创建时 created_at 和 updated_at 应自动填充。"""
    before = datetime.now(timezone.utc)
    conv = Conversation(session_id="session-005", user_id="user-005", title="日期测试")
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)
    after = datetime.now(timezone.utc)

    # SQLite 不保存时区信息，读取回的 datetime 为 offset-naive
    created = conv.created_at.replace(tzinfo=timezone.utc)
    updated = conv.updated_at.replace(tzinfo=timezone.utc)
    assert before <= created <= after
    assert before <= updated <= after


def test_conversation_updated_at_on_update(db_session):
    """更新 Conversation 时 updated_at 应自动更新。"""
    conv = Conversation(session_id="session-006", user_id="user-006", title="原始标题")
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    original_updated = conv.updated_at

    import time
    time.sleep(0.1)

    conv.title = "修改后的标题"
    conv.message_count = 5
    db_session.commit()
    db_session.refresh(conv)

    assert conv.updated_at > original_updated
    assert conv.title == "修改后的标题"
    assert conv.message_count == 5


def test_conversation_update_last_message_info(db_session):
    """更新会话的最后消息预览和角色信息。"""
    conv = Conversation(session_id="session-007", user_id="user-007")
    db_session.add(conv)
    db_session.commit()

    now = datetime.now(timezone.utc)
    conv.last_message_preview = "你好，这是一条测试消息..."
    conv.last_message_role = "user"
    conv.last_message_at = now
    db_session.commit()
    db_session.refresh(conv)

    # SQLite 不保存时区，读取回的 datetime 需补齐时区再比较
    last_at = conv.last_message_at.replace(tzinfo=timezone.utc)
    assert last_at == now
    assert conv.last_message_preview == "你好，这是一条测试消息..."
    assert conv.last_message_role == "user"


# ==================== Conversation JSON 列测试 ====================

def test_conversation_metadata_json_access(db_session):
    """conversation_metadata JSON 列应支持字典读写。"""
    conv = Conversation(
        session_id="session-008",
        user_id="user-008",
        conversation_metadata={"language": "zh-CN", "tags": ["tech", "ai"]},
    )
    db_session.add(conv)
    db_session.commit()
    db_session.refresh(conv)

    assert conv.conversation_metadata["language"] == "zh-CN"
    assert "tech" in conv.conversation_metadata["tags"]
    assert len(conv.conversation_metadata["tags"]) == 2


# ==================== Skill JSON 列测试 ====================

def test_skill_json_columns(db_session):
    """Skill 的 config、tags、dependencies JSON 列应正确存取。"""
    skill = Skill(
        id="skill-001",
        name="代码分析器",
        version="1.0.0",
        description="分析代码质量并提供建议",
        config={"max_length": 1000, "languages": ["python", "javascript"]},
        category="dev",
        tags=["code", "analysis", "quality"],
        dependencies=["pylint>=2.0", "eslint>=8.0"],
        author="测试团队",
    )
    db_session.add(skill)
    db_session.commit()
    db_session.refresh(skill)

    assert skill.config["max_length"] == 1000
    assert "python" in skill.config["languages"]
    assert skill.tags == ["code", "analysis", "quality"]
    assert "pylint>=2.0" in skill.dependencies
    assert skill.enabled is True
    assert skill.usage_count == 0


# ==================== TaskAgentSession 测试 ====================

def test_workflow_create_and_query(db_session):
    """Workflow 模型的创建和查询。"""
    wf = Workflow(
        user_id="user-001",
        name="自动化报告",
        description="每日自动生成报告",
        definition={"steps": [{"id": "step1", "type": "tool", "tool": "report"}]},
        format="json",
    )
    db_session.add(wf)
    db_session.commit()
    db_session.refresh(wf)

    assert wf.id is not None
    assert wf.user_id == "user-001"
    assert wf.name == "自动化报告"
    assert wf.enabled is True
    assert wf.definition["steps"][0]["id"] == "step1"


def test_workflow_step_create(db_session):
    """WorkflowStep 模型的创建和查询。"""
    step = WorkflowStep(
        workflow_id=1,
        step_key="step_01",
        name="数据采集",
        step_type="tool",
        step_order=0,
        definition={"tool": "scraper", "action": "fetch"},
    )
    db_session.add(step)
    db_session.commit()
    db_session.refresh(step)

    assert step.id is not None
    assert step.workflow_id == 1
    assert step.step_key == "step_01"
    assert step.step_type == "tool"
    assert step.step_order == 0
    assert step.definition["tool"] == "scraper"


# ==================== ShortTermMemory 测试 ====================

def test_short_term_memory_create(db_session):
    """ShortTermMemory 模型的创建和查询。"""
    mem = ShortTermMemory(
        session_id="session-001",
        role="user",
        content="帮我查一下天气",
        reasoning_content="用户需要天气信息，可能是为了出行计划",
        tool_events=[{"tool": "weather", "action": "query", "params": {"city": "北京"}}],
    )
    db_session.add(mem)
    db_session.commit()
    db_session.refresh(mem)

    assert mem.id is not None
    assert mem.session_id == "session-001"
    assert mem.role == "user"
    assert mem.content == "帮我查一下天气"
    assert mem.reasoning_content == "用户需要天气信息，可能是为了出行计划"
    assert len(mem.tool_events) == 1
    assert mem.tool_events[0]["tool"] == "weather"
    assert isinstance(mem.timestamp, datetime)
