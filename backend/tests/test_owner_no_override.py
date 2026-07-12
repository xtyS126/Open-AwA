"""
owner 用户防重复创建回归测试。

覆盖场景（spec § test_owner_no_override.py 8 用例）：
1. DB 已有用户时跳过创建分支，仅缓存第一个用户
2. DB 空 + 环境变量 OPENAWA_OWNER_PASSWORD 设置时创建 owner
3. DB 空 + 无密码环境变量时使用随机密码并记录 WARNING 引导用户走 POST /api/system/init
4. DB 有多个用户时缓存按 created_at 排序的第一个
5. _owner_cache 已设置时不查询数据库
6. 环境变量用户名与 DB 用户名不一致时记录 WARNING
7. 跳过创建分支时不修改已有用户的 password_hash
8. lifespan 检测到未初始化时记录 WARNING 日志 system_not_initialized

测试隔离：
- 每个用例前调用 invalidate_owner_cache() 清除 owner 缓存
- 使用独立临时数据库（tmp_path + sqlite）
- 使用 monkeypatch.setenv/delenv 隔离环境变量，不污染全局
- 使用 _LOG_BUFFER 捕获日志事件做断言
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 导入 main 触发 init_logging()，安装 _LOG_BUFFER 的 loguru sink
# 否则 _LOG_BUFFER 不会捕获日志条目（仅默认 stderr sink 工作）
import main  # noqa: F401

from config.logging import _LOG_BUFFER
from config.security import get_password_hash
from core.initialization import has_any_user
from core.owner import ensure_owner_user, invalidate_owner_cache
from db.models import User


# ============================================================================
# 测试 fixture
# ============================================================================

@pytest.fixture
def db_session(tmp_path):
    """创建独立临时数据库会话，仅创建 User 表避免其他表干扰。"""
    db_path = tmp_path / "test_owner.db"
    engine = create_engine(f"sqlite:///{db_path}")
    # 仅创建 User 表，避免其他表 schema 干扰
    User.__table__.create(bind=engine, checkfirst=True)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    yield session
    session.close()


@pytest.fixture
def clean_env(monkeypatch):
    """清理 owner 相关环境变量，每个用例独立。"""
    for key in (
        "OPENAWA_OWNER_USERNAME",
        "OPENAWA_OWNER_PASSWORD",
        "OPENAWA_OWNER_NICKNAME",
        "OPENAWA_OWNER_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.fixture(autouse=True)
def reset_owner_cache_and_logs():
    """每个用例前清除 owner 缓存与日志缓冲。"""
    invalidate_owner_cache()
    _LOG_BUFFER.clear()
    yield
    invalidate_owner_cache()
    _LOG_BUFFER.clear()


# ============================================================================
# 辅助函数
# ============================================================================

def _create_user(session, username: str, password: str = "OldPass123",
                 created_at: datetime | None = None) -> User:
    """在数据库中直接插入一个用户（绕过 ensure_owner_user）。"""
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=get_password_hash(password),
        role="admin",
    )
    if created_at is not None:
        user.created_at = created_at
    session.add(user)
    session.commit()
    return user


def _find_log_event(event_name: str) -> dict | None:
    """从 _LOG_BUFFER 中查找指定 event 的日志条目。"""
    for entry in _LOG_BUFFER:
        if entry.get("event") == event_name:
            return entry
    return None


def _get_extra(entry: dict) -> dict:
    """从日志条目中提取 extra 字典（loguru bind 的字段都存在这里）。"""
    return entry.get("extra") or {}


# ============================================================================
# 测试用例
# ============================================================================

class TestEnsureOwnerUserNoOverride:
    """验证 ensure_owner_user 的防重复创建逻辑。"""

    def test_skips_when_users_exist(self, db_session, clean_env):
        """用例 1：DB 已有用户时跳过创建分支，记录 INFO 日志 owner_skipped_existing。"""
        existing = _create_user(db_session, "alice", password="AlicePass1")

        owner = ensure_owner_user(db_session)

        # 返回的是已有用户，不创建新用户
        assert owner.id == existing.id
        assert owner.username == "alice"
        # 数据库仍只有 1 个用户
        assert db_session.query(User).count() == 1
        # INFO 日志已记录
        log_entry = _find_log_event("owner_skipped_existing")
        assert log_entry is not None, "应记录 owner_skipped_existing 日志"
        extra = _get_extra(log_entry)
        assert extra.get("username") == "alice"

    def test_fallback_creates_owner_when_no_users(self, db_session, clean_env, monkeypatch):
        """用例 2：DB 空 + 环境变量设置时走 fallback 创建 owner。"""
        monkeypatch.setenv("OPENAWA_OWNER_USERNAME", "admin")
        monkeypatch.setenv("OPENAWA_OWNER_PASSWORD", "AdminPass1")

        owner = ensure_owner_user(db_session)

        assert owner.username == "admin"
        assert owner.role == "admin"
        assert owner.password_hash  # 已哈希
        # 数据库新增了 1 个用户
        assert db_session.query(User).count() == 1
        # 记录创建日志
        log_entry = _find_log_event("owner_created")
        assert log_entry is not None
        extra = _get_extra(log_entry)
        assert extra.get("username") == "admin"

    def test_fallback_random_password_warning(self, db_session, clean_env, monkeypatch):
        """用例 3：DB 空 + 无密码环境变量时使用随机密码并记录 WARNING。"""
        monkeypatch.setenv("OPENAWA_OWNER_USERNAME", "admin")
        # 不设置 OPENAWA_OWNER_PASSWORD

        owner = ensure_owner_user(db_session)

        assert owner.username == "admin"
        # WARNING 日志含 "建议通过 POST /api/system/init"
        log_entry = _find_log_event("owner_fallback_random_password")
        assert log_entry is not None, "应记录 owner_fallback_random_password 日志"
        log_message = log_entry.get("message", "")
        assert "建议通过 POST /api/system/init" in log_message, (
            "WARNING 日志应引导用户通过 POST /api/system/init 完成初始化"
        )

    def test_caches_first_user_by_created_at(self, db_session, clean_env):
        """用例 4：DB 有多个用户时缓存 created_at 最早的一个。"""
        # 创建两个用户，alice 比 bob 早
        early_time = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
        late_time = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)
        alice = _create_user(db_session, "alice", created_at=early_time)
        bob = _create_user(db_session, "bob", created_at=late_time)

        owner = ensure_owner_user(db_session)

        # 缓存的是 created_at 最早的 alice
        assert owner.id == alice.id
        assert owner.username == "alice"
        # bob 未被选中
        assert owner.id != bob.id

    def test_cache_hit_skips_db_query(self, db_session, clean_env):
        """用例 5：_owner_cache 已设置时不查询数据库。"""
        existing = _create_user(db_session, "alice")
        # 第一次调用填充缓存
        owner1 = ensure_owner_user(db_session)
        assert owner1.id == existing.id

        # 删除所有用户后再次调用，缓存应命中不查 DB
        db_session.query(User).delete()
        db_session.commit()

        owner2 = ensure_owner_user(db_session)
        # 仍是缓存的 alice
        assert owner2.id == existing.id
        assert owner2.username == "alice"

    def test_username_mismatch_warning(self, db_session, clean_env, monkeypatch):
        """用例 6：env 用户名与 DB 不一致时记录 WARNING owner_username_mismatch。"""
        _create_user(db_session, "alice")
        # 环境变量设置不同的用户名
        monkeypatch.setenv("OPENAWA_OWNER_USERNAME", "admin")

        owner = ensure_owner_user(db_session)

        # 仍使用 DB 中的 alice
        assert owner.username == "alice"
        # WARNING 日志记录用户名不一致
        log_entry = _find_log_event("owner_username_mismatch")
        assert log_entry is not None, "应记录 owner_username_mismatch 日志"
        extra = _get_extra(log_entry)
        assert extra.get("env_username") == "admin"
        assert extra.get("db_username") == "alice"

    def test_does_not_modify_existing_user_password(self, db_session, clean_env):
        """用例 7：跳过创建分支时不修改已有用户的 password_hash。"""
        existing = _create_user(db_session, "alice", password="AliceOriginal1")
        original_hash = existing.password_hash

        owner = ensure_owner_user(db_session)

        assert owner.id == existing.id
        # password_hash 未被修改
        assert owner.password_hash == original_hash
        # 数据库中的记录也未变
        db_user = db_session.query(User).filter(User.username == "alice").first()
        assert db_user.password_hash == original_hash


class TestLifespanInitDetection:
    """验证 lifespan 启动时的初始化状态检测与日志记录。"""

    def test_logs_warning_when_not_initialized(self, monkeypatch, tmp_path):
        """用例 8：marker 不存在时记录 WARNING 日志 system_not_initialized。"""
        # 使用 tmp_path 作为 DATA_DIR，确保 marker 文件不存在
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.delenv("INITIALIZED_MARKER_PATH", raising=False)

        # 调用提取的检测函数
        from main import _detect_and_log_initialization_status
        _detect_and_log_initialization_status()

        # 应记录 system_not_initialized WARNING 日志
        log_entry = _find_log_event("system_not_initialized")
        assert log_entry is not None, "未初始化时应记录 system_not_initialized WARNING 日志"
        assert "POST /api/system/init" in log_entry.get("message", "")
