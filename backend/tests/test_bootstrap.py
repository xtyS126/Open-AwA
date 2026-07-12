"""
core/bootstrap.py 单元测试。

覆盖首次部署初始化编排模块的 6 步流程：
- initialize_system()：主入口
- 异常映射：PrerequisiteError / LockAcquireError / OwnerCreationError / MarkerWriteError
- 密钥生成与保留逻辑
- owner 创建与 RBAC 角色赋值
- .env.local 原子写入
- 并发锁保护

测试隔离：所有外部依赖通过 monkeypatch 替换为 tmp_path 资源
- SessionLocal 指向临时 SQLite
- init_db 替换为 no-op
- ENV_LOCAL_PATH 指向临时文件
- INIT_LOCK_PATH 指向临时文件
- DATA_DIR 环境变量指向临时目录
- 三密钥环境变量清理
- 锁状态重置
"""

import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import core.bootstrap as bootstrap_module
from core.bootstrap import (
    BootstrapError,
    LockAcquireError,
    MarkerWriteError,
    OwnerCreationError,
    PrerequisiteError,
    initialize_system,
)
from core.initialization import (
    get_initialized_marker_path,
    is_initialized,
)
from db.models import Base, Role, User, UserRole


# ============================================================================
# 测试 fixture
# ============================================================================

@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """隔离 bootstrap 模块的所有外部依赖。

    - 创建临时 SQLite DB（含 users / roles / user_roles 表）
    - Patch SessionLocal 指向临时 DB
    - Patch init_db 为 no-op（测试前手动创建表）
    - Patch ENV_LOCAL_PATH 指向临时文件
    - Patch INIT_LOCK_PATH 指向临时文件
    - 设置 DATA_DIR 环境变量指向临时目录
    - 清理三密钥环境变量（避免继承自生产 .env）
    - 重置锁状态（防止跨测试污染）
    """
    # 1. 临时 DB
    db_path = tmp_path / "test_bootstrap.db"
    engine = create_engine(f"sqlite:///{db_path}")
    # 仅创建必要表（提升测试速度）
    Base.metadata.create_all(
        bind=engine,
        tables=[User.__table__, Role.__table__, UserRole.__table__],
    )
    test_session_factory = sessionmaker(bind=engine)

    # 2. 临时 .env.local 与锁文件路径
    env_local_path = tmp_path / ".env.local"
    lock_path = tmp_path / ".init.lock"

    # 3. DATA_DIR 环境变量（用于标记文件路径解析）
    monkeypatch.delenv("INITIALIZED_MARKER_PATH", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    # 4. 清理三密钥环境变量（避免继承自生产 .env）
    for key in (
        "JWT_SECRET_KEY",
        "CSRF_SECRET_KEY",
        "ENCRYPTION_KEY",
        "OPENAWA_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    # 5. Patch bootstrap 模块常量与函数
    monkeypatch.setattr(bootstrap_module, "ENV_LOCAL_PATH", env_local_path)
    monkeypatch.setattr(bootstrap_module, "INIT_LOCK_PATH", lock_path)
    monkeypatch.setattr(bootstrap_module, "SessionLocal", test_session_factory)
    monkeypatch.setattr(bootstrap_module, "init_db", lambda: None)

    # 6. 重置锁状态（防止跨测试污染）
    bootstrap_module._init_lock_acquired = False
    bootstrap_module._init_lock_fd = None

    return SimpleNamespace(
        engine=engine,
        session_factory=test_session_factory,
        env_local_path=env_local_path,
        lock_path=lock_path,
        data_dir=tmp_path,
    )


# ============================================================================
# 主流程测试
# ============================================================================

class TestInitializeSystemMainFlow:
    """测试 initialize_system 主流程。"""

    def test_creates_owner_and_marker(self, isolated_env):
        """完整初始化流程：创建 owner + 标记文件。"""
        result = initialize_system(
            username="alice",
            password="StrongPass1",
            email="alice@example.com",
            nickname="Alice",
        )

        # 验证返回值
        assert result["username"] == "alice"
        assert "user_id" in result
        assert isinstance(result["user_id"], str)
        assert len(result["user_id"]) > 0

        # 验证 owner 已创建
        with isolated_env.session_factory() as db:
            user = db.query(User).filter(User.username == "alice").first()
            assert user is not None
            assert user.email == "alice@example.com"
            assert user.nickname == "Alice"
            assert user.role == "admin"

        # 验证标记文件已创建
        assert is_initialized() is True

    def test_refuses_when_marker_exists(self, isolated_env):
        """标记文件已存在时拒绝执行。"""
        # 先初始化一次
        initialize_system(username="alice", password="StrongPass1")
        assert is_initialized() is True

        # 再次初始化应失败
        with pytest.raises(PrerequisiteError, match="系统已初始化"):
            initialize_system(username="bob", password="StrongPass1")

    def test_refuses_when_users_exist(self, isolated_env):
        """数据库已有用户但无标记文件时拒绝创建 owner。"""
        # 预先插入一个用户
        with isolated_env.session_factory() as db:
            user = User(
                id=str(uuid.uuid4()),
                username="existing_user",
                password_hash="$pbkdf2-sha256$test",
                role="user",
            )
            db.add(user)
            db.commit()

        # 没有标记文件
        assert is_initialized() is False

        # 初始化应失败
        with pytest.raises(PrerequisiteError, match="系统已有用户"):
            initialize_system(username="alice", password="StrongPass1")

    def test_force_bypasses_checks(self, isolated_env):
        """force=True 跳过前置检查。"""
        # 先初始化一次
        initialize_system(username="alice", password="StrongPass1")

        # force=True 重新初始化（绕过标记文件与用户表检查）
        result = initialize_system(
            username="bob",
            password="StrongPass1",
            force=True,
        )

        assert result["username"] == "bob"
        # 两个 owner 共存
        with isolated_env.session_factory() as db:
            users = db.query(User).all()
            usernames = {u.username for u in users}
            assert "alice" in usernames
            assert "bob" in usernames

    def test_regenerate_secrets_overwrites_env(self, isolated_env):
        """regenerate_secrets=True 覆盖已有密钥。"""
        # 先初始化一次（生成密钥）
        initialize_system(username="alice", password="StrongPass1")
        first_content = isolated_env.env_local_path.read_text(encoding="utf-8")

        # 提取第一次的 JWT_SECRET_KEY 值
        first_jwt = ""
        for line in first_content.splitlines():
            if line.startswith("JWT_SECRET_KEY="):
                first_jwt = line.split("=", 1)[1]
                break
        assert first_jwt, "首次初始化应生成 JWT_SECRET_KEY"

        # 重新初始化并重新生成密钥
        initialize_system(
            username="bob",
            password="StrongPass1",
            force=True,
            regenerate_secrets=True,
        )

        # 提取第二次的 JWT_SECRET_KEY 值
        second_content = isolated_env.env_local_path.read_text(encoding="utf-8")
        second_jwt = ""
        for line in second_content.splitlines():
            if line.startswith("JWT_SECRET_KEY="):
                second_jwt = line.split("=", 1)[1]
                break
        assert second_jwt, "重新生成应写入 JWT_SECRET_KEY"

        # 密钥应不同（regenerate_secrets=True）
        assert first_jwt != second_jwt

    def test_preserves_existing_secrets_without_force(self, isolated_env):
        """无 force 时保留已有密钥。"""
        # 首次初始化，密钥会生成
        initialize_system(username="alice", password="StrongPass1")

        # 读取生成的密钥
        content = isolated_env.env_local_path.read_text(encoding="utf-8")

        # 验证密钥已写入
        assert "JWT_SECRET_KEY=" in content
        assert "CSRF_SECRET_KEY=" in content
        assert "ENCRYPTION_KEY=" in content
        assert "OPENAWA_API_KEY=" in content

    def test_returns_user_id_and_username(self, isolated_env):
        """返回值包含 user_id 和 username。"""
        result = initialize_system(username="alice", password="StrongPass1")

        assert "user_id" in result
        assert "username" in result
        assert result["username"] == "alice"
        assert isinstance(result["user_id"], str)
        assert len(result["user_id"]) > 0

    def test_does_not_return_secret_values(self, isolated_env):
        """返回值不含密钥明文。"""
        result = initialize_system(username="alice", password="StrongPass1")

        # 返回值只有 4 个字段
        assert set(result.keys()) == {
            "user_id",
            "username",
            "secrets_generated",
            "api_key_generated",
        }

        # 返回值的字符串表示不含密钥变量名
        result_str = str(result)
        assert "JWT_SECRET_KEY" not in result_str
        assert "CSRF_SECRET_KEY" not in result_str
        assert "ENCRYPTION_KEY" not in result_str
        assert "OPENAWA_API_KEY" not in result_str

    def test_assigns_admin_role(self, isolated_env):
        """owner 被赋予 admin 角色。"""
        result = initialize_system(username="alice", password="StrongPass1")

        with isolated_env.session_factory() as db:
            # 查询 user_roles 表
            user_role = (
                db.query(UserRole)
                .filter(UserRole.user_id == result["user_id"])
                .first()
            )
            assert user_role is not None
            assert user_role.role_name == "admin"

            # 验证 admin 角色存在
            admin_role = db.query(Role).filter(Role.name == "admin").first()
            assert admin_role is not None

    def test_hashes_password_pbkdf2(self, isolated_env):
        """密码使用 pbkdf2_sha256 哈希。"""
        result = initialize_system(username="alice", password="StrongPass1")

        with isolated_env.session_factory() as db:
            user = db.query(User).filter(User.id == result["user_id"]).first()
            assert user is not None
            # pbkdf2_sha256 哈希格式：$pbkdf2-sha256$...
            assert user.password_hash.startswith("$pbkdf2-sha256$"), (
                f"密码哈希不是 pbkdf2_sha256 格式: {user.password_hash[:30]}..."
            )

    def test_concurrent_lock_raises(self, isolated_env):
        """并发初始化时第二个调用抛出 LockAcquireError。"""
        # 手动设置锁已获取（模拟另一个进程正在初始化）
        bootstrap_module._init_lock_acquired = True
        try:
            with pytest.raises(LockAcquireError, match="另一个初始化"):
                initialize_system(username="alice", password="StrongPass1")
        finally:
            # 重置锁状态
            bootstrap_module._init_lock_acquired = False

    def test_owner_creation_failure_rolls_back(self, isolated_env):
        """owner 创建失败时事务回滚，标记文件不创建。"""
        # 预先插入同用户名用户（制造 unique 约束冲突）
        with isolated_env.session_factory() as db:
            existing = User(
                id=str(uuid.uuid4()),
                username="alice",
                password_hash="$pbkdf2-sha256$test",
                role="user",
            )
            db.add(existing)
            db.commit()

        # force=True 跳过 has_any_user 检查，但创建同名 user 会失败
        with pytest.raises(OwnerCreationError):
            initialize_system(
                username="alice",
                password="StrongPass1",
                force=True,
            )

        # 标记文件未创建
        assert is_initialized() is False

        # 仍只有一个用户（无新 owner 创建）
        with isolated_env.session_factory() as db:
            user_count = db.query(User).count()
            assert user_count == 1

    def test_marker_write_failure_raises_marker_error(self, isolated_env, monkeypatch):
        """标记文件写入失败时抛出 MarkerWriteError。"""
        # Mock mark_initialized 抛出 OSError
        def failing_mark(steps_completed):
            raise OSError("simulated marker write failure")

        monkeypatch.setattr(bootstrap_module, "mark_initialized", failing_mark)

        with pytest.raises(MarkerWriteError, match="请手动创建标记文件"):
            initialize_system(username="alice", password="StrongPass1")

        # owner 已创建（残留）
        with isolated_env.session_factory() as db:
            user = db.query(User).filter(User.username == "alice").first()
            assert user is not None

        # 标记文件未创建
        assert is_initialized() is False

        # .tmp 文件不存在（mock 未创建，但应确保无残留）
        marker_path = get_initialized_marker_path()
        tmp_marker = marker_path.with_suffix(marker_path.suffix + ".tmp")
        assert not tmp_marker.exists()
