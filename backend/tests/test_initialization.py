"""
core/initialization.py 单元测试。

覆盖首次部署检测模块的 5 个公共函数：
- get_initialized_marker_path()：路径解析优先级
- is_initialized()：标记文件存在性检查
- get_initialization_status()：完整状态字典返回
- mark_initialized()：原子写入与 .tmp 清理
- reset_initialization()：删除标记文件
- has_any_user()：数据库用户存在性检查

测试隔离：所有测试通过 monkeypatch + tmp_path 隔离 DATA_DIR，不污染 backend/data/
"""

import json
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.initialization import (
    INITIALIZED_MARKER_FILENAME,
    INITIALIZATION_VERSION,
    get_initialized_marker_path,
    get_initialization_status,
    has_any_user,
    is_initialized,
    mark_initialized,
    reset_initialization,
)
from db.models import Base, User


# ============================================================================
# 模块级 fixture
# ============================================================================

@pytest.fixture
def clean_marker_env(monkeypatch, tmp_path):
    """清空标记文件相关环境变量，使用 tmp_path 作为 DATA_DIR。"""
    monkeypatch.delenv("INITIALIZED_MARKER_PATH", raising=False)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def empty_db_session(tmp_path):
    """创建临时 SQLite 数据库会话，含 users 表。"""
    db_path = tmp_path / "test_init.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine, tables=[User.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ============================================================================
# get_initialized_marker_path 测试
# ============================================================================

class TestGetMarkerPath:
    """测试标记文件路径解析优先级。"""

    def test_explicit_marker_path_wins(self, monkeypatch, tmp_path):
        """INITIALIZED_MARKER_PATH 优先级最高。"""
        custom_path = tmp_path / "custom" / ".initialized"
        monkeypatch.setenv("INITIALIZED_MARKER_PATH", str(custom_path))
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "other"))

        result = get_initialized_marker_path()

        assert result == custom_path

    def test_data_dir_used_when_no_explicit_path(self, monkeypatch, tmp_path):
        """无 INITIALIZED_MARKER_PATH 时使用 DATA_DIR。"""
        monkeypatch.delenv("INITIALIZED_MARKER_PATH", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        result = get_initialized_marker_path()

        assert result == tmp_path / INITIALIZED_MARKER_FILENAME

    def test_default_used_when_no_env(self, monkeypatch):
        """两个环境变量都未设置时使用 backend/data/.initialized。"""
        monkeypatch.delenv("INITIALIZED_MARKER_PATH", raising=False)
        monkeypatch.delenv("DATA_DIR", raising=False)

        result = get_initialized_marker_path()

        assert result == Path("backend/data") / INITIALIZED_MARKER_FILENAME


# ============================================================================
# is_initialized 测试
# ============================================================================

class TestIsInitialized:
    """测试 is_initialized 函数。"""

    def test_returns_false_when_marker_absent(self, clean_marker_env):
        """标记文件不存在时返回 False。"""
        assert is_initialized() is False

    def test_returns_true_when_marker_exists(self, clean_marker_env):
        """标记文件存在时返回 True。"""
        mark_initialized([])

        assert is_initialized() is True

    def test_returns_false_when_marker_corrupt(self, clean_marker_env):
        """标记文件存在但 JSON 损坏时返回 False。"""
        marker_path = get_initialized_marker_path()
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text("not json", encoding="utf-8")

        assert is_initialized() is False  # 损坏文件视为未初始化

    def test_does_not_delete_corrupt_marker(self, clean_marker_env):
        """损坏的标记文件不被删除（保留供人工排查）。"""
        marker_path = get_initialized_marker_path()
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text("not json", encoding="utf-8")

        # 调用 is_initialized 触发损坏检测
        assert is_initialized() is False
        # 文件未被删除
        assert marker_path.exists() is True


# ============================================================================
# get_initialization_status 测试
# ============================================================================

class TestGetInitializationStatus:
    """测试 get_initialization_status 函数。"""

    def test_returns_not_initialized_structure_when_absent(self, clean_marker_env):
        """标记文件不存在时返回未初始化结构。"""
        status = get_initialization_status()

        assert status == {
            "initialized": False,
            "initialized_at": None,
            "version": None,
            "steps_completed": [],
        }

    def test_returns_correct_structure_when_initialized(self, clean_marker_env):
        """标记文件存在时返回完整结构。"""
        steps = ["prerequisite_check", "generate_secrets"]
        mark_initialized(steps)

        status = get_initialization_status()

        assert status["initialized"] is True
        assert isinstance(status["initialized_at"], str)
        assert status["version"] == INITIALIZATION_VERSION
        assert status["steps_completed"] == steps


# ============================================================================
# mark_initialized 测试
# ============================================================================

class TestMarkInitialized:
    """测试 mark_initialized 函数。"""

    def test_creates_marker_file(self, clean_marker_env):
        """调用后创建标记文件，含三字段。"""
        steps = ["step_a", "step_b"]
        mark_initialized(steps)

        marker_path = get_initialized_marker_path()
        assert marker_path.exists() is True

        data = json.loads(marker_path.read_text(encoding="utf-8"))
        assert "initialized_at" in data
        assert data["version"] == INITIALIZATION_VERSION
        assert data["steps_completed"] == steps

    def test_is_idempotent(self, clean_marker_env):
        """连续调用两次，文件仍只有一个，内容为最新。"""
        mark_initialized(["first"])
        mark_initialized(["second"])

        marker_path = get_initialized_marker_path()
        # 文件只有一个
        assert marker_path.exists() is True
        # 内容为第二次的值
        data = json.loads(marker_path.read_text(encoding="utf-8"))
        assert data["steps_completed"] == ["second"]

    def test_creates_data_dir_if_absent(self, monkeypatch, tmp_path):
        """DATA_DIR 目录不存在时自动创建。"""
        new_data_dir = tmp_path / "newdir" / "nested"
        monkeypatch.delenv("INITIALIZED_MARKER_PATH", raising=False)
        monkeypatch.setenv("DATA_DIR", str(new_data_dir))

        mark_initialized([])

        assert new_data_dir.exists() is True
        marker_path = new_data_dir / INITIALIZED_MARKER_FILENAME
        assert marker_path.exists() is True

    def test_atomic_write_cleans_tmp_on_failure(self, clean_marker_env, monkeypatch):
        """os.replace 失败时清理 .tmp 残留。"""
        marker_path = get_initialized_marker_path()

        # 模拟 os.replace 抛 OSError
        def fake_replace(src, dst):
            raise OSError("simulated failure")

        monkeypatch.setattr("core.initialization.os.replace", fake_replace)

        with pytest.raises(OSError):
            mark_initialized([])

        # .tmp 文件应被清理
        tmp_path = marker_path.with_suffix(marker_path.suffix + ".tmp")
        assert not tmp_path.exists()

    def test_iso8601_with_z_suffix(self, clean_marker_env):
        """initialized_at 字段为 ISO 8601 格式带 Z 后缀。"""
        mark_initialized([])

        status = get_initialization_status()
        initialized_at = status["initialized_at"]

        assert initialized_at is not None
        # 匹配 ISO 8601 带 Z 后缀（如 2026-07-12T08:30:00Z 或 2026-07-12T08:30:00.123456Z）
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"
        assert re.match(pattern, initialized_at), f"initialized_at 不符合 ISO 8601 格式: {initialized_at}"


# ============================================================================
# reset_initialization 测试
# ============================================================================

class TestResetInitialization:
    """测试 reset_initialization 函数。"""

    def test_removes_marker_when_exists(self, clean_marker_env):
        """标记文件存在时删除。"""
        mark_initialized([])
        marker_path = get_initialized_marker_path()
        assert marker_path.exists() is True

        reset_initialization()

        assert marker_path.exists() is False
        assert is_initialized() is False

    def test_silent_when_marker_absent(self, clean_marker_env):
        """标记文件不存在时不抛异常。"""
        # 不创建标记文件，调用应静默返回
        reset_initialization()
        assert is_initialized() is False


# ============================================================================
# has_any_user 测试
# ============================================================================

class TestHasAnyUser:
    """测试 has_any_user 函数。"""

    def test_returns_false_when_empty(self, empty_db_session):
        """空数据库返回 False。"""
        assert has_any_user(empty_db_session) is False

    def test_returns_true_when_user_exists(self, empty_db_session):
        """有用户时返回 True。"""
        # 插入一个用户
        user = User(
            id=str(uuid.uuid4()),
            username="alice",
            password_hash="$pbkdf2-sha256$test",
            role="user",
        )
        empty_db_session.add(user)
        empty_db_session.commit()

        assert has_any_user(empty_db_session) is True

    def test_does_not_modify_db(self, empty_db_session):
        """调用前后用户数量不变。"""
        # 插入两个用户
        for i in range(2):
            empty_db_session.add(User(
                id=str(uuid.uuid4()),
                username=f"user_{i}",
                password_hash="$pbkdf2-sha256$test",
                role="user",
            ))
        empty_db_session.commit()
        count_before = empty_db_session.query(User).count()

        # 调用 has_any_user
        has_any_user(empty_db_session)

        count_after = empty_db_session.query(User).count()
        assert count_before == count_after
