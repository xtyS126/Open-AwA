"""
统一错误码注册表。

将散落在各处的错误码字符串集中注册，并提供默认元信息（retryable / status_code /
用户友好消息），便于：
1. 前后端共享同一份错误码契约，前端按 code 决策重试与展示，不再字符串匹配 message
2. 新增错误码时只需在注册表追加一条，避免遗漏同步前端
3. build_standard_error 在 code 命中注册表时自动填充默认值，保证调用方最小改动

约束：
- 错误码字符串使用 snake_case，全小写
- 注册表条目的 default_retryable / default_status_code 仅在调用方未显式传值时生效
- 调用方显式传入的 retryable / status_code 优先级高于注册表默认值
"""

from typing import Any, Dict, Optional


class ErrorCode:
    """
    错误码常量集中定义。

    所有字段均为 snake_case 字符串，前后端共享同一份契约。
    新增错误码时必须在此处追加常量并同步在 REGISTRY 中注册元信息。
    """

    # ===== 通用错误 =====
    INTERNAL_SERVER_ERROR = "internal_server_error"
    UNKNOWN_ERROR = "unknown_error"

    # ===== 网络与超时 =====
    REQUEST_TIMEOUT = "request_timeout"
    NETWORK_ERROR = "network_error"

    # ===== 数据库 =====
    DATABASE_UNAVAILABLE = "database_unavailable"

    # ===== 认证与授权 =====
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    AUTHENTICATION_FAILED = "authentication_failed"
    CSRF_TOKEN_INVALID = "csrf_token_invalid"

    # ===== LLM 相关 =====
    LLM_API_KEY_STALE = "llm_api_key_stale"
    LLM_RATE_LIMITED = "llm_rate_limited"
    LLM_PROVIDER_UNAVAILABLE = "llm_provider_unavailable"
    LLM_CONTEXT_LENGTH_EXCEEDED = "llm_context_length_exceeded"
    LLM_CALL_FAILED = "llm_call_failed"

    # ===== 故障转移 =====
    FAILOVER_TOTAL_TIMEOUT = "failover_total_timeout"
    FAILOVER_ALL_CANDIDATES_FAILED = "failover_all_candidates_failed"

    # ===== 系统初始化 =====
    SYSTEM_ALREADY_INITIALIZED = "system_already_initialized"
    WEAK_PASSWORD = "weak_password"
    PREREQUISITE_FAILED = "prerequisite_failed"
    INIT_LOCK_CONTENTION = "init_lock_contention"

    # ===== 资源不存在 =====
    RESOURCE_NOT_FOUND = "resource_not_found"
    CONVERSATION_NOT_FOUND = "conversation_not_found"

    # ===== 输入校验 =====
    VALIDATION_ERROR = "validation_error"
    INVALID_INPUT = "invalid_input"

    # ===== 限流 =====
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"


# 错误码元信息注册表
# - default_retryable: 该错误码默认是否可重试（调用方可显式覆盖）
# - default_status_code: 该错误码默认 HTTP 状态码（调用方可显式覆盖）
# - user_message: 该错误码对应的用户友好提示（前端可直接展示）
REGISTRY: Dict[str, Dict[str, Any]] = {
    ErrorCode.INTERNAL_SERVER_ERROR: {
        "default_retryable": False,
        "default_status_code": 500,
        "user_message": "服务器内部错误，请稍后重试",
    },
    ErrorCode.UNKNOWN_ERROR: {
        "default_retryable": False,
        "default_status_code": 500,
        "user_message": "未知错误",
    },
    ErrorCode.REQUEST_TIMEOUT: {
        "default_retryable": True,
        "default_status_code": 504,
        "user_message": "请求处理超时，请稍后重试",
    },
    ErrorCode.NETWORK_ERROR: {
        "default_retryable": True,
        "default_status_code": 503,
        "user_message": "网络连接失败，请检查网络后重试",
    },
    ErrorCode.DATABASE_UNAVAILABLE: {
        "default_retryable": True,
        "default_status_code": 503,
        "user_message": "数据服务暂不可用，请稍后重试",
    },
    ErrorCode.UNAUTHORIZED: {
        "default_retryable": False,
        "default_status_code": 401,
        "user_message": "未登录或会话已过期",
    },
    ErrorCode.FORBIDDEN: {
        "default_retryable": False,
        "default_status_code": 403,
        "user_message": "无权访问该资源",
    },
    ErrorCode.AUTHENTICATION_FAILED: {
        "default_retryable": False,
        "default_status_code": 401,
        "user_message": "认证失败",
    },
    ErrorCode.CSRF_TOKEN_INVALID: {
        "default_retryable": False,
        "default_status_code": 403,
        "user_message": "CSRF 校验失败，请刷新页面后重试",
    },
    ErrorCode.LLM_API_KEY_STALE: {
        "default_retryable": False,
        "default_status_code": 401,
        "user_message": "模型服务 API Key 已失效，请在设置页重新录入",
    },
    ErrorCode.LLM_RATE_LIMITED: {
        "default_retryable": True,
        "default_status_code": 429,
        "user_message": "模型服务限流，请稍后重试",
    },
    ErrorCode.LLM_PROVIDER_UNAVAILABLE: {
        "default_retryable": True,
        "default_status_code": 503,
        "user_message": "模型服务暂不可用，请稍后重试",
    },
    ErrorCode.LLM_CONTEXT_LENGTH_EXCEEDED: {
        "default_retryable": False,
        "default_status_code": 400,
        "user_message": "对话上下文超长，请新建会话或精简消息",
    },
    ErrorCode.LLM_CALL_FAILED: {
        "default_retryable": False,
        "default_status_code": 502,
        "user_message": "模型调用失败",
    },
    ErrorCode.FAILOVER_TOTAL_TIMEOUT: {
        "default_retryable": True,
        "default_status_code": 504,
        "user_message": "故障转移链路总超时，请稍后重试",
    },
    ErrorCode.FAILOVER_ALL_CANDIDATES_FAILED: {
        "default_retryable": True,
        "default_status_code": 503,
        "user_message": "所有候选模型均不可用，请稍后重试",
    },
    ErrorCode.SYSTEM_ALREADY_INITIALIZED: {
        "default_retryable": False,
        "default_status_code": 409,
        "user_message": "系统已初始化",
    },
    ErrorCode.WEAK_PASSWORD: {
        "default_retryable": False,
        "default_status_code": 400,
        "user_message": "密码强度不足",
    },
    ErrorCode.PREREQUISITE_FAILED: {
        "default_retryable": False,
        "default_status_code": 412,
        "user_message": "前置条件未满足",
    },
    ErrorCode.INIT_LOCK_CONTENTION: {
        "default_retryable": True,
        "default_status_code": 503,
        "user_message": "初始化锁竞争，请稍后重试",
    },
    ErrorCode.RESOURCE_NOT_FOUND: {
        "default_retryable": False,
        "default_status_code": 404,
        "user_message": "资源不存在",
    },
    ErrorCode.CONVERSATION_NOT_FOUND: {
        "default_retryable": False,
        "default_status_code": 404,
        "user_message": "会话不存在",
    },
    ErrorCode.VALIDATION_ERROR: {
        "default_retryable": False,
        "default_status_code": 422,
        "user_message": "输入校验失败",
    },
    ErrorCode.INVALID_INPUT: {
        "default_retryable": False,
        "default_status_code": 400,
        "user_message": "输入不合法",
    },
    ErrorCode.RATE_LIMIT_EXCEEDED: {
        "default_retryable": True,
        "default_status_code": 429,
        "user_message": "请求过于频繁，请稍后重试",
    },
}


def get_error_code_meta(code: str) -> Dict[str, Any]:
    """
    获取错误码元信息。

    未注册的 code 返回空字典，调用方据此判断是否应用默认值。
    返回的字典为副本，调用方可安全修改。
    """
    meta = REGISTRY.get(str(code or ""))
    if meta is None:
        return {}
    return dict(meta)


def resolve_defaults(
    code: str,
    retryable: Optional[bool] = None,
    status_code: Optional[int] = None,
) -> Dict[str, Any]:
    """
    根据错误码注册表解析默认 retryable / status_code。

    优先级：调用方显式传值 > 注册表默认值 > 兜底默认值。

    返回 dict，包含:
      - retryable: bool
      - status_code: Optional[int]（仅在注册表或调用方提供时有该键）
    """
    meta = get_error_code_meta(code)
    resolved: Dict[str, Any] = {}
    # retryable 解析：显式 > 注册表 > 兜底 False
    if retryable is not None:
        resolved["retryable"] = bool(retryable)
    elif "default_retryable" in meta:
        resolved["retryable"] = bool(meta["default_retryable"])
    else:
        resolved["retryable"] = False
    # status_code 解析：显式 > 注册表 > 不设置
    if status_code is not None:
        resolved["status_code"] = int(status_code)
    elif "default_status_code" in meta:
        resolved["status_code"] = int(meta["default_status_code"])
    return resolved
