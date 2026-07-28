# -*- coding: utf-8 -*-
"""
问题反馈端点单元测试。

覆盖：
1. POST /api/feedback/issue 成功提交：返回 200 + ok=true + 非空 file_id
2. 非法 payload（空 title / 超长 content / 非法 issue_type）返回 422
3. 未认证返回 401

采用独立 FastAPI app + dependency_overrides 模式，避免触发全局 lifespan 与默认数据库。
write_issue 的目标目录重定向到临时目录，避免污染真实 var/data/issue_reports/。
"""

from __future__ import annotations

import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user
from api.routes.issue_feedback import router as issue_feedback_router
from issue_writer import writer as writer_module


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


def _deny_user():
    """模拟未认证：依赖函数抛 401。"""

    def _raise() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return _raise


# ==================== 公共 fixture ====================


@contextmanager
def _sync_client(user: Optional[_DummyUser] = _USER_A):
    """构造同步 TestClient，并将 write_issue 重定向到临时目录。

    避免污染真实 var/data/issue_reports/ 目录。
    """
    tmp_dir = Path(tempfile.mkdtemp())
    original_dir = writer_module._ISSUE_DIR
    writer_module._ISSUE_DIR = tmp_dir
    app = FastAPI()
    app.include_router(issue_feedback_router)
    if user is not None:
        app.dependency_overrides[get_current_user] = _override_user(user)
    else:
        app.dependency_overrides[get_current_user] = _deny_user()
    try:
        with TestClient(app) as client:
            yield client, tmp_dir
    finally:
        writer_module._ISSUE_DIR = original_dir


# ==================== 测试用例 ====================


class TestSubmitIssue:
    """POST /api/feedback/issue 提交问题反馈。"""

    def test_submit_issue_endpoint_success(self) -> None:
        """合法 payload 应返回 200 + ok=true + 非空 file_id。"""
        with _sync_client(_USER_A) as (client, tmp_dir):
            response = client.post(
                "/api/feedback/issue",
                json={
                    "issue_type": "bug",
                    "title": "测试问题",
                    "content": "测试内容",
                    "page_url": "/test",
                },
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert isinstance(body["file_id"], str)
        assert len(body["file_id"]) > 0
        # 验证文件确实写入临时目录
        files = list(tmp_dir.glob("*.json"))
        assert len(files) == 1

    @pytest.mark.parametrize(
        "payload",
        [
            # 空 title（违反 min_length=1）
            {"issue_type": "bug", "title": "", "content": "测试内容"},
            # 超长 content（超过 max_length=10000）
            {"issue_type": "bug", "title": "测试", "content": "x" * 10001},
            # 非法 issue_type（不在 Literal 中）
            {"issue_type": "critical", "title": "测试", "content": "测试内容"},
        ],
        ids=["empty_title", "long_content", "invalid_type"],
    )
    def test_submit_issue_endpoint_validation_failed(self, payload) -> None:
        """非法 payload 应返回 422（FastAPI 默认验证错误状态码）。"""
        with _sync_client(_USER_A) as (client, _):
            response = client.post("/api/feedback/issue", json=payload)

        assert response.status_code == 422, response.text

    def test_submit_issue_endpoint_unauthenticated(self) -> None:
        """未认证应返回 401。"""
        with _sync_client(None) as (client, _):
            response = client.post(
                "/api/feedback/issue",
                json={
                    "issue_type": "bug",
                    "title": "测试",
                    "content": "测试内容",
                },
            )

        assert response.status_code == 401, response.text
