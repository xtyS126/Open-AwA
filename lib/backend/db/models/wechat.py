"""
微信域 ORM 模型：微信账号绑定、自动回复规则。
所有模型继承 db.models.base.Base，与主业务模型共享同一 Metadata。
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class WeixinBinding(Base):
    """
    微信绑定模型，存储用户与微信账号的绑定关系及连接参数。
    binding_status 取值: unbound / bound / expired
    """
    __tablename__ = "weixin_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    weixin_account_id: Mapped[str] = mapped_column(String(200), nullable=False)
    token: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), default="https://ilinkai.weixin.qq.com")
    bot_type: Mapped[str] = mapped_column(String(10), default="3")
    channel_version: Mapped[str] = mapped_column(String(20), default="1.0.2")
    binding_status: Mapped[str] = mapped_column(String(50), default="unbound")
    weixin_user_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=15)
    auto_start_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class WeixinAutoReplyRule(Base):
    """
    微信自动回复规则模型，支持关键词和正则匹配。
    """
    __tablename__ = "weixin_auto_reply_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)
    match_type: Mapped[str] = mapped_column(String(20), default="keyword") # keyword, regex
    match_pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    reply_content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class WeixinMediaAsset(Base):
    """微信入站多媒体资产，敏感 CDN 参数仅以密文保存在服务端。"""
    __tablename__ = "weixin_media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    message_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    media_format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    encrypted_query_param: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_aes_key: Mapped[str] = mapped_column(Text, nullable=False)
    transcript: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transcript_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
