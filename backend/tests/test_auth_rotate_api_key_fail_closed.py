"""
API Key 轮转 fail-closed 测试（删除兜底后的错误路径）。

覆盖：
- 清除 owner 缓存失败时返回 500：旧 Key 在 TTL 内继续有效属于安全敏感状态，
  禁止记录 warning 后伪装轮转成功（auth.py rotate_api_key）。
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api.routes.auth as auth_module
from api.routes.auth import rotate_api_key


async def test_rotate_api_key_raises_500_when_owner_cache_invalidation_fails(
    monkeypatch, tmp_path
):
    """清除 owner 缓存失败 -> 500，轮转不伪装成功。"""
    # 将 .env.local 定向到临时目录，避免污染真实环境
    monkeypatch.setattr(auth_module, "__file__", str(tmp_path / "auth.py"))
    env_local = tmp_path / ".env.local"
    env_local.write_text(
        "OPENAWA_API_KEY=sk-old-key-12345678901234567890123456789012\n",
        encoding="utf-8",
    )

    # 阻止真实全局 settings 被修改（本用例仅验证失败路径，不改变运行时密钥）
    fake_settings = SimpleNamespace(OPENAWA_API_KEY="sk-unused")
    monkeypatch.setattr(auth_module, "settings", fake_settings)

    def _boom():
        raise RuntimeError("owner cache invalidate failed")

    # 路由在函数体内 import core.owner.invalidate_owner_cache，patch 模块属性即可生效
    monkeypatch.setattr("core.owner.invalidate_owner_cache", _boom)

    request = MagicMock()
    request.state.request_id = "test-request-id"
    request_body = MagicMock()
    request_body.confirm = True
    current_user = MagicMock()
    current_user.id = "admin-1"

    with pytest.raises(HTTPException) as exc_info:
        await rotate_api_key(request, request_body, current_user=current_user)

    assert exc_info.value.status_code == 500
    assert "旧 Key" in str(exc_info.value.detail)
    # 新 Key 已先于缓存清除写入文件，失败时保持持久化（与运行时配置一致）
    assert "OPENAWA_API_KEY=sk-" in env_local.read_text(encoding="utf-8")
