"""
本地用户配置加载器的单元测试。
覆盖用户配置文件的加载、校验、同步和禁用逻辑。
"""

import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.local_users import _load_users_config, sync_local_users_to_db
from config.security import get_password_hash, verify_password
from db.models import Base, User


@pytest.fixture
def db_session(tmp_path):
    """创建临时内存数据库会话"""
    db_path = tmp_path / "test_local_users.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def users_yaml(tmp_path):
    """创建临时用户配置文件的辅助工具"""
    config_path = tmp_path / "users.yaml"

    def _write(data):
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)
        return config_path

    return _write


class TestLoadUsersConfig:
    """测试 _load_users_config 函数"""

    def test_load_valid_config(self, users_yaml):
        """加载合法配置应返回正确用户列表"""
        path = users_yaml({
            "users": [
                {"username": "alice", "password": "pass1234", "role": "admin"},
                {"username": "bob", "password": "pass5678", "role": "user"},
            ]
        })
        result = _load_users_config(path)
        assert len(result) == 2
        assert result[0]["username"] == "alice"
        assert result[0]["role"] == "admin"
        assert result[1]["username"] == "bob"
        assert result[1]["role"] == "user"

    def test_missing_config_file(self, tmp_path):
        """配置文件不存在时返回空列表"""
        result = _load_users_config(tmp_path / "nonexistent.yaml")
        assert result == []

    def test_invalid_yaml(self, tmp_path):
        """YAML 语法错误时返回空列表"""
        path = tmp_path / "bad.yaml"
        path.write_text("users:\n  - [invalid yaml{{{", encoding="utf-8")
        result = _load_users_config(path)
        assert result == []

    def test_top_level_not_dict(self, tmp_path):
        """顶层不是字典时返回空列表"""
        path = tmp_path / "list.yaml"
        path.write_text("- item1\n- item2\n", encoding="utf-8")
        result = _load_users_config(path)
        assert result == []

    def test_users_not_list(self, users_yaml):
        """users 字段不是列表时返回空列表"""
        path = users_yaml({"users": "not_a_list"})
        result = _load_users_config(path)
        assert result == []

    def test_skip_non_dict_entry(self, users_yaml):
        """跳过非字典类型的用户条目"""
        path = users_yaml({
            "users": [
                "just_a_string",
                {"username": "valid", "password": "pass1234", "role": "user"},
            ]
        })
        result = _load_users_config(path)
        assert len(result) == 1
        assert result[0]["username"] == "valid"

    def test_skip_empty_username(self, users_yaml):
        """跳过 username 为空的条目"""
        path = users_yaml({
            "users": [
                {"username": "", "password": "pass1234", "role": "user"},
                {"username": "valid", "password": "pass1234", "role": "user"},
            ]
        })
        result = _load_users_config(path)
        assert len(result) == 1

    def test_skip_short_password(self, users_yaml):
        """跳过密码过短的条目"""
        path = users_yaml({
            "users": [
                {"username": "short", "password": "ab", "role": "user"},
                {"username": "valid", "password": "pass1234", "role": "user"},
            ]
        })
        result = _load_users_config(path)
        assert len(result) == 1

    def test_skip_duplicate_username(self, users_yaml):
        """跳过重复的 username"""
        path = users_yaml({
            "users": [
                {"username": "dup", "password": "pass1234", "role": "user"},
                {"username": "dup", "password": "pass5678", "role": "admin"},
            ]
        })
        result = _load_users_config(path)
        assert len(result) == 1
        assert result[0]["password"] == "pass1234"

    def test_invalid_role_fallback(self, users_yaml):
        """无效角色回退为 user"""
        path = users_yaml({
            "users": [
                {"username": "test", "password": "pass1234", "role": "superadmin"},
            ]
        })
        result = _load_users_config(path)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_default_role_is_user(self, users_yaml):
        """未指定角色时默认为 user"""
        path = users_yaml({
            "users": [
                {"username": "test", "password": "pass1234"},
            ]
        })
        result = _load_users_config(path)
        assert len(result) == 1
        assert result[0]["role"] == "user"


class TestSyncLocalUsersToDb:
    """测试 sync_local_users_to_db 函数"""

    def test_create_new_users(self, db_session, users_yaml):
        """同步时应创建新用户"""
        path = users_yaml({
            "users": [
                {"username": "alice", "password": "pass1234", "role": "admin"},
                {"username": "bob", "password": "pass5678", "role": "user"},
            ]
        })
        stats = sync_local_users_to_db(db_session, path)
        assert stats["created"] == 2
        assert stats["updated"] == 0
        assert stats["disabled"] == 0

        alice = db_session.query(User).filter(User.username == "alice").first()
        assert alice is not None
        assert alice.role == "admin"
        assert verify_password("pass1234", alice.password_hash)

    def test_update_existing_user_role(self, db_session, users_yaml):
        """同步时应更新已有用户的角色"""
        # 先创建用户
        user = User(
            id=str(uuid.uuid4()),
            username="alice",
            password_hash=get_password_hash("pass1234"),
            role="user",
        )
        db_session.add(user)
        db_session.commit()

        # 配置中角色变为 admin
        path = users_yaml({
            "users": [
                {"username": "alice", "password": "pass1234", "role": "admin"},
            ]
        })
        stats = sync_local_users_to_db(db_session, path)
        assert stats["created"] == 0
        assert stats["updated"] == 1

        db_session.refresh(user)
        assert user.role == "admin"

    def test_update_existing_user_password(self, db_session, users_yaml):
        """同步时应更新已有用户的密码"""
        user = User(
            id=str(uuid.uuid4()),
            username="alice",
            password_hash=get_password_hash("old_password"),
            role="user",
        )
        db_session.add(user)
        db_session.commit()

        path = users_yaml({
            "users": [
                {"username": "alice", "password": "new_password", "role": "user"},
            ]
        })
        stats = sync_local_users_to_db(db_session, path)
        assert stats["updated"] == 1

        db_session.refresh(user)
        assert verify_password("new_password", user.password_hash)

    def test_disable_removed_users(self, db_session, users_yaml):
        """配置中不存在的用户应被禁用"""
        user = User(
            id=str(uuid.uuid4()),
            username="removed_user",
            password_hash=get_password_hash("pass1234"),
            role="user",
        )
        db_session.add(user)
        db_session.commit()

        # 配置中只有 alice，removed_user 应被禁用
        path = users_yaml({
            "users": [
                {"username": "alice", "password": "pass1234", "role": "user"},
            ]
        })
        stats = sync_local_users_to_db(db_session, path)
        assert stats["created"] == 1
        assert stats["disabled"] == 1

        db_session.refresh(user)
        assert user.role == "disabled"

    def test_empty_config_skips_sync(self, db_session, tmp_path):
        """空配置文件不会做任何操作"""
        path = tmp_path / "empty.yaml"
        path.write_text("users: []\n", encoding="utf-8")
        stats = sync_local_users_to_db(db_session, path)
        assert stats == {"created": 0, "updated": 0, "disabled": 0}

    def test_no_change_for_identical_config(self, db_session, users_yaml):
        """配置与数据库一致时不产生任何变更"""
        user = User(
            id=str(uuid.uuid4()),
            username="alice",
            password_hash=get_password_hash("pass1234"),
            role="admin",
        )
        db_session.add(user)
        db_session.commit()

        path = users_yaml({
            "users": [
                {"username": "alice", "password": "pass1234", "role": "admin"},
            ]
        })
        stats = sync_local_users_to_db(db_session, path)
        assert stats["created"] == 0
        assert stats["updated"] == 0
        assert stats["disabled"] == 0
