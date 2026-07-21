# -*- coding: utf-8 -*-
"""
SKILL.md 格式 ZIP 技能包导入单元测试。

覆盖 /skills/install-from-package 端点的 SKILL.md 支持逻辑：
1. 上传 SKILL.md zip 包安装成功，列表/详情包含 instructions/prompt 与 execution_mode
2. 同时含 SKILL.md 和 skill.yaml 时优先 SKILL.md
3. 仅含 skill.yaml 时向后兼容
4. 无配置文件时返回 400
5. execution-mode: prompt 的 SKILL.md 正确写入 execution_mode
6. 同名 SKILL.md 重复安装返回 400

测试隔离：每个测试独立 fixture，使用 in-memory SQLite，不依赖全局状态。
"""

from __future__ import annotations

import io
import sys
import types
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 兼容性兜底：bcrypt 的 PyO3 扩展在某些环境下可能初始化失败。
# 本测试文件仅测试技能包导入路由，不涉及密码哈希，安全注入 mock 规避环境依赖。
if "bcrypt" not in sys.modules:
    try:
        import bcrypt  # noqa: F401
    except ImportError:
        _mock_bcrypt = types.ModuleType("bcrypt")
        _mock_bcrypt.hashpw = lambda *args, **kwargs: b"mock_hash"
        _mock_bcrypt.checkpw = lambda *args, **kwargs: True
        _mock_bcrypt.gensalt = lambda *args, **kwargs: b"mock_salt"
        _mock_bcrypt.__version__ = "mock"
        sys.modules["bcrypt"] = _mock_bcrypt

from api.dependencies import get_current_user, get_db
from api.routes.skills import router as skills_router
from db.models import Base


# ==================== 测试用户与依赖覆盖 ====================


class _DummyUser:
    """测试用 DummyUser，仅暴露 id/username/role 三个字段。"""

    def __init__(self, user_id: str, username: str) -> None:
        self.id = user_id
        self.username = username
        self.role = "user"


_USER_A = _DummyUser("user-a", "alice")


def _override_user(user: _DummyUser):
    """生成 get_current_user 的依赖覆盖函数。"""

    def _override() -> _DummyUser:
        return user

    return _override


# ==================== 公共 fixture ====================


@pytest.fixture()
def db_session():
    """
    创建独立的内存数据库会话。
    每个测试用例使用全新的数据库实例，避免测试之间互相污染。
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client_fixture(db_session):
    """
    构造仅注册 skills 路由的 FastAPI 测试客户端。
    覆盖 get_db 依赖返回内存会话，覆盖 get_current_user 返回普通用户。
    """
    app = FastAPI()
    app.include_router(skills_router)

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user(_USER_A)

    with TestClient(app) as client:
        yield client


# ==================== 辅助函数 ====================


FIXTURE_ZIP_PATH = Path(__file__).resolve().parent / "fixtures" / "sample-skillmd.zip"


def _make_zip(files: dict) -> bytes:
    """动态创建 zip 包。files: {filename: content_bytes}"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _read_fixture_zip() -> bytes:
    """读取预置的 sample-skillmd.zip fixture。"""
    return FIXTURE_ZIP_PATH.read_bytes()


def _make_skillmd_content(
    name: str = "commit-message-helper",
    description: str = "生成符合 Conventional Commits 规范的 Git 提交信息",
    version: str = "1.0.0",
    execution_mode: str = "prompt",
    category: str = "development",
    author: str = "Open-AwA",
    tags: list | None = None,
    body: str = "这是一个帮助生成提交信息的技能。",
) -> str:
    """构造 SKILL.md 文本内容。"""
    if tags is None:
        tags = ["git", "commit", "conventional-commits"]
    tags_yaml = "\n".join(f"  - {t}" for t in tags)
    return (
        "---\n"
        f"name: {name}\n"
        f'description: "{description}"\n'
        f"version: {version}\n"
        f"execution-mode: {execution_mode}\n"
        f"category: {category}\n"
        f"author: {author}\n"
        f"tags:\n{tags_yaml}\n"
        "---\n\n"
        f"# {name}\n\n{body}\n"
    )


def _make_yaml_content(
    name: str = "yaml-test-skill",
    version: str = "1.0.0",
    description: str = "YAML 格式测试技能",
    adapter: str = "default",
    category: str = "testing",
) -> str:
    """构造 skill.yaml 文本内容（向后兼容测试用）。"""
    return (
        f"name: {name}\n"
        f"version: {version}\n"
        f'description: "{description}"\n'
        f"adapter: {adapter}\n"
        f"category: {category}\n"
    )


def _upload_zip(client: TestClient, zip_bytes: bytes, filename: str = "test.zip"):
    """向 /skills/install-from-package 上传 zip 包。"""
    return client.post(
        "/skills/install-from-package",
        files={"file": (filename, zip_bytes, "application/zip")},
    )


# ==================== 测试用例 ====================


class TestInstallSkillmdZip:
    """SKILL.md 格式 ZIP 包导入端点测试。"""

    def test_install_skillmd_zip_success(self, client_fixture) -> None:
        """上传含 SKILL.md 的 zip 包应返回 200，并在技能列表中可见。"""
        zip_bytes = _read_fixture_zip()
        response = _upload_zip(client_fixture, zip_bytes, "sample-skillmd.zip")

        assert response.status_code == 200, response.text
        body = response.json()
        # 响应应含安装成功消息
        assert "安装成功" in body["message"]
        # 安装的技能名应为 commit-message-helper
        assert body["skill"]["name"] == "commit-message-helper"

        # GET /skills 列表应包含 commit-message-helper
        list_resp = client_fixture.get("/skills")
        assert list_resp.status_code == 200, list_resp.text
        skills = list_resp.json()
        names = [s["name"] for s in skills]
        assert "commit-message-helper" in names

        # 找到刚安装的技能，校验 config 含 instructions 与 prompt 键
        installed = next(s for s in skills if s["name"] == "commit-message-helper")
        config = installed["config"]
        assert "instructions" in config
        assert "prompt" in config
        # execution_mode 应映射为 prompt（下划线形式）
        assert config["execution_mode"] == "prompt"

    def test_install_prefers_skillmd_over_yaml(self, client_fixture) -> None:
        """同时含 SKILL.md 和 skill.yaml 时，应优先采用 SKILL.md 的 name。"""
        skillmd = _make_skillmd_content(name="skillmd-name", description="SKILL.md 优先")
        yaml_cfg = _make_yaml_content(
            name="yaml-name",
            description="YAML 配置",
        )
        zip_bytes = _make_zip(
            {
                "SKILL.md": skillmd.encode("utf-8"),
                "skill.yaml": yaml_cfg.encode("utf-8"),
            }
        )
        response = _upload_zip(client_fixture, zip_bytes)

        assert response.status_code == 200, response.text
        body = response.json()
        # 安装的应为 SKILL.md 中的 name
        assert body["skill"]["name"] == "skillmd-name"

        # 通过列表再次确认数据库中实际存的是 skillmd-name
        list_resp = client_fixture.get("/skills")
        assert list_resp.status_code == 200
        names = [s["name"] for s in list_resp.json()]
        assert "skillmd-name" in names
        assert "yaml-name" not in names

    def test_install_yaml_only_backward_compatible(self, client_fixture) -> None:
        """仅含 skill.yaml（含 name/version/description/adapter 四个必需字段）应安装成功。"""
        yaml_cfg = _make_yaml_content(
            name="yaml-test-skill",
            version="1.0.0",
            description="YAML 格式测试技能",
            adapter="default",
        )
        zip_bytes = _make_zip({"skill.yaml": yaml_cfg.encode("utf-8")})
        response = _upload_zip(client_fixture, zip_bytes)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["skill"]["name"] == "yaml-test-skill"
        assert "安装成功" in body["message"]

        # 列表应能查到
        list_resp = client_fixture.get("/skills")
        assert list_resp.status_code == 200
        names = [s["name"] for s in list_resp.json()]
        assert "yaml-test-skill" in names

    def test_install_no_config_file_returns_400(self, client_fixture) -> None:
        """无配置文件的 zip 应返回 400，错误消息含提示语。"""
        zip_bytes = _make_zip({"README.md": b"no config here"})
        response = _upload_zip(client_fixture, zip_bytes)

        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert "未找到 SKILL.md 或 skill.yaml" in detail

    def test_install_skillmd_execution_mode_prompt(self, client_fixture) -> None:
        """execution-mode: prompt 的 SKILL.md 应在详情 config 中体现 execution_mode=prompt。"""
        skillmd = _make_skillmd_content(
            name="prompt-mode-skill",
            description="prompt 模式技能",
            execution_mode="prompt",
        )
        zip_bytes = _make_zip({"SKILL.md": skillmd.encode("utf-8")})
        response = _upload_zip(client_fixture, zip_bytes)

        assert response.status_code == 200, response.text
        skill_id = response.json()["skill"]["id"]

        # GET /skills/{id} 返回的 config 中 execution_mode 应为 "prompt"
        detail_resp = client_fixture.get(f"/skills/{skill_id}")
        assert detail_resp.status_code == 200, detail_resp.text
        config = detail_resp.json()["config"]
        assert config["execution_mode"] == "prompt"

    def test_install_skillmd_duplicate_name_400(self, client_fixture) -> None:
        """先安装一个 SKILL.md 技能，再上传同名 SKILL.md zip 应返回 400 提示已存在。"""
        skillmd = _make_skillmd_content(
            name="dup-skill",
            description="重复安装测试技能",
        )
        zip_bytes = _make_zip({"SKILL.md": skillmd.encode("utf-8")})

        first = _upload_zip(client_fixture, zip_bytes)
        assert first.status_code == 200, first.text

        # 再次上传同名 zip 应被拒绝
        second = _upload_zip(client_fixture, zip_bytes)
        assert second.status_code == 400, second.text
        detail = second.json()["detail"]
        assert "已存在" in detail
