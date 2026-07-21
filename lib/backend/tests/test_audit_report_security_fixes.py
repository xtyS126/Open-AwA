"""审核报告安全修复的行为测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from api.routes import chat
from api.routes.chat import _get_user_id_for_rate_limit, _validate_chat_upload_magic_bytes
from security.audit import AuditLogger


def test_chat_upload_rejects_fake_pdf() -> None:
    """PDF 扩展名不能绕过内容签名校验。"""
    assert not _validate_chat_upload_magic_bytes(b"not a pdf", ".pdf")
    assert _validate_chat_upload_magic_bytes(b"%PDF-1.7\n", ".pdf")


def test_chat_upload_rejects_binary_text_disguised_as_csv() -> None:
    """文本扩展名不能接收包含空字节的二进制内容。"""
    assert not _validate_chat_upload_magic_bytes(b"\x00MZ", ".csv")
    assert _validate_chat_upload_magic_bytes("name,value\nopenawa,1\n".encode("utf-8"), ".csv")


def test_rate_limit_uses_ip_when_token_decode_fails(monkeypatch) -> None:
    """令牌解析异常时限流必须稳定降级到客户端 IP。"""
    monkeypatch.setattr(chat, "decode_access_token", lambda token: (_ for _ in ()).throw(ValueError("bad token")))
    request = SimpleNamespace(
        headers={"Authorization": "Bearer malformed"},
        client=SimpleNamespace(host="203.0.113.8"),
    )

    assert _get_user_id_for_rate_limit(request) == "203.0.113.8"


@pytest.mark.asyncio
async def test_file_audit_operation_forwards_source_ip() -> None:
    """文件操作审计必须把来源 IP 传入底层日志记录。"""
    audit_logger = AuditLogger(SimpleNamespace())
    audit_logger.log = AsyncMock(return_value=None)

    await audit_logger.log_file_operation(
        user_id="user-1",
        operation="write",
        file_path="workspace/note.md",
        result="success",
        ip_address="203.0.113.8",
    )

    audit_logger.log.assert_awaited_once_with(
        user_id="user-1",
        action="file:write",
        resource="workspace/note.md",
        result="success",
        ip_address="203.0.113.8",
    )
