"""
安全域 ORM 模型：审计日志、登录限流、行为埋点、自定义角色、IP 黑白名单、
异常事件、CSRF token、JWT 黑名单、推理审计。
所有模型继承 db.models.base.Base，与主业务模型共享同一 Metadata。
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class AuditLog(Base):
    """
    审计日志模型，记录用户对资源的操作历史，包含操作详情和来源 IP。
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    resource: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    result: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # created_at 索引：审计日志按时间范围查询是高频场景，缺索引会导致全表扫描
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class LoginRateLimit(Base):
    """
    登录限流记录模型，持久化存储登录失败计数和封禁状态。
    支持多 worker 部署时限流状态共享，替代进程内存字典方案。
    每条记录以 rate_limit_key（IP + 用户名哈希）唯一标识。
    """
    __tablename__ = "login_rate_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rate_limit_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    first_attempt_at: Mapped[float] = mapped_column(Float, default=0.0)
    blocked_until: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class BehaviorLog(Base):
    """
    用户行为埋点日志，记录用户操作类型和详情。
    """
    __tablename__ = "behavior_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    action_type: Mapped[str] = mapped_column(String)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (
        Index("ix_behavior_user_action_ts", "user_id", "action_type", "timestamp"),
    )


class TokenBlacklist(Base):
    """
    JWT 令牌黑名单模型，持久化存储已登出令牌，防止服务器重启后黑名单丢失。
    """
    __tablename__ = "token_blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


# -------- P2 安全增强：细粒度权限与主动防御 --------


class CustomRole(Base):
    """
    自定义角色模型，支持用户创建具有细粒度权限的角色。
    与内置 Role 表互补，permissions 字段存储 resource:action 格式的权限列表。
    """
    __tablename__ = "custom_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # 权限列表 JSON 数组，格式: ["plugin:install", "skill:execute", "model:use", "billing:view"]
    permissions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 创建者用户 ID
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class IpAccessList(Base):
    """
    IP 白名单/黑名单模型，支持单 IP 和 CIDR 网段。
    list_type: whitelist（白名单，优先级最高）/ blacklist（黑名单）
    """
    __tablename__ = "ip_access_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # IP 地址或 CIDR 网段，如 "192.168.1.1" 或 "10.0.0.0/8"
    ip_cidr: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    list_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    # whitelist / blacklist
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    # 过期时间，None 表示永不过期
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index("ix_ip_access_list_type_cidr", "list_type", "ip_cidr", unique=True),
    )


class AnomalyEvent(Base):
    """
    异常行为事件模型，记录检测到的异常请求模式。
    event_type: rate_burst（速率突发）/ repeated_failure（重复失败）/ suspicious_pattern（可疑模式）
    """
    __tablename__ = "anomaly_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    # 触发阈值描述，如 "100 requests in 60s"
    trigger_detail: Mapped[str] = mapped_column(Text, default="")
    # 实际观测值，如 "120 requests"
    observed_value: Mapped[str] = mapped_column(Text, default="")
    # 处置动作：warn/throttle/block
    action_taken: Mapped[str] = mapped_column(String(20), default="warn")
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class CsrfToken(Base):
    """
    CSRF token 模型，支持 token 自动轮换与一次性使用。
    """
    __tablename__ = "csrf_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# -------- P3 Chain-of-Thought 推理审计 --------


class ReasoningAudit(Base):
    """
    推理审计模型，记录每次推理过程的元数据、耗时与 token 统计。
    用于推理质量分析、性能优化和成本追踪。
    """
    __tablename__ = "reasoning_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 会话 ID，关联 short_term_memory
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 用户 ID
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    # 模型提供商
    provider: Mapped[str] = mapped_column(String(50), default="")
    # 模型名称
    model: Mapped[str] = mapped_column(String(100), default="")
    # 推理深度（0-5）
    thinking_depth: Mapped[int] = mapped_column(Integer, default=0)
    # 复杂度等级（simple/moderate/complex）
    complexity: Mapped[str] = mapped_column(String(20), default="simple")
    # 复杂度评分（0-100）
    complexity_score: Mapped[int] = mapped_column(Integer, default=0)
    # 是否用户手动覆盖深度
    is_user_override: Mapped[bool] = mapped_column(Boolean, default=False)
    # 推理内容长度（字符数）
    reasoning_length: Mapped[int] = mapped_column(Integer, default=0)
    # 推理 token 数（区分于输出 token）
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 输出 token 数
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 输入 token 数
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 推理耗时（毫秒）
    reasoning_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 总耗时（毫秒）
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 首 token 时间（毫秒，从请求开始到首个 token 返回）
    ttft_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 是否成功完成
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    # 错误信息（失败时）
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 审计元数据（JSON，存储评估原因等）
    audit_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
