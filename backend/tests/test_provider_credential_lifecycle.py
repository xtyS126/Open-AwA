"""
Provider 凭据生命周期回归测试。

覆盖凭据独立存在时的硬删除语义，以及已认证用户主动查看完整密钥的契约。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from billing.models import ProviderCredential
from billing.routers.billing import delete_provider, get_provider_plain_api_key
from config.security import encrypt_secret_value
from db.models import Base


@pytest.fixture
def db_session():
    """创建隔离的内存数据库会话。"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_delete_provider_succeeds_when_only_credential_exists(db_session) -> None:
    """仅剩凭据时仍应硬删除成功，不能改变状态后再返回 404。"""
    db_session.add(
        ProviderCredential(
            provider="credential-only",
            api_key=encrypt_secret_value("test-secret-for-delete"),
            is_active=True,
        )
    )
    db_session.commit()

    result = await delete_provider(
        "credential-only",
        db=db_session,
        current_user=SimpleNamespace(id="test-user"),
    )

    assert result == {
        "success": True,
        "provider": "credential-only",
        "deleted_count": 0,
        "credential_deleted": True,
    }
    assert (
        db_session.query(ProviderCredential)
        .filter(ProviderCredential.provider == "credential-only")
        .count()
        == 0
    )


@pytest.mark.asyncio
async def test_plain_key_endpoint_returns_complete_decrypted_value(db_session) -> None:
    """用户主动查看时必须返回完整密钥，而不是脱敏或截断值。"""
    expected_key = "sk-test-complete-provider-key-0123456789"
    db_session.add(
        ProviderCredential(
            provider="plain-key",
            api_key=encrypt_secret_value(expected_key),
            is_active=True,
        )
    )
    db_session.commit()

    result = await get_provider_plain_api_key(
        "plain-key",
        db=db_session,
        current_user=SimpleNamespace(id="test-user"),
    )

    assert result == {
        "api_key": expected_key,
        "has_api_key": True,
        "api_key_status": "active",
    }
