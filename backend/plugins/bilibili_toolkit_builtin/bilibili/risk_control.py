"""B 站风控信号检测。

B 站在检测到异常请求（IP 频次过高、WBI 签名错误等）时会返回特定信号：

- HTTP 412 Precondition Failed：请求频率过高，明确的 IP 级风控
- HTTP 403 Forbidden：偶发的下载流限流（bili-sync 注释中说明
  ``目前偶尔出现在下载视频音频流时，由于是偶尔出现且过一段时间消失``）
- 业务 code ``-352``：风控错误码
- ``data.v_voucher`` 字段非空：WBI 密钥过期或限流的轻量挑战

任一信号触发时，调用方应立即终止本轮下载/扫描，等待下一轮调度重试。

参考实现：``bili-sync/crates/bili_sync/src/bilibili/mod.rs`` 的
``Validate`` trait 与 ``ErrorForStatusExt`` trait。
"""

from __future__ import annotations

from typing import Any

import httpx


class RiskControlError(Exception):
    """B 站风控触发异常。

    携带 ``reason``（风控类型）与 ``code``（HTTP 状态码或业务码）字段，
    供 workflow 层判断是否终止本轮所有视频源处理。

    Attributes:
        reason: 风控原因，取值为 ``http_status`` / ``risk_code`` / ``voucher``。
        code: 风控码。``http_status`` 时为 HTTP 状态码；
              ``risk_code`` 时为 -352；``voucher`` 时为 0。
        raw_response: 原始响应文本（用于调试），可能为空字符串。
    """

    def __init__(
        self,
        reason: str,
        code: int,
        *,
        raw_response: str = "",
    ) -> None:
        message = f"B 站风控触发: reason={reason}, code={code}"
        if raw_response:
            # 截断避免日志过长
            preview = raw_response[:200] if len(raw_response) > 200 else raw_response
            message = f"{message}, raw={preview}"
        super().__init__(message)
        self.reason: str = reason
        self.code: int = code
        self.raw_response: str = raw_response


def check_response(response: httpx.Response) -> None:
    """检测 httpx 响应中的风控信号，触发时抛出 :class:`RiskControlError`。

    检测顺序：
    1. HTTP 412 / 403 → ``reason="http_status"``
    2. 业务 ``code == -352`` → ``reason="risk_code"``
    3. ``data.v_voucher`` 非空 → ``reason="voucher"``

    任一信号命中即抛异常，不继续检测后续信号。

    Args:
        response: httpx 响应对象。如果响应体不是 JSON，跳过业务码检测。

    Raises:
        RiskControlError: 检测到风控信号时抛出。
    """
    status = response.status_code
    if status in (412, 403):
        raise RiskControlError(
            reason="http_status",
            code=status,
            raw_response=_safe_text(response),
        )

    # 仅在响应体为 JSON 时检测业务码（protobuf 等二进制响应跳过）
    payload = _safe_json(response)
    if payload is None:
        return

    code = payload.get("code")
    if isinstance(code, (int, float)) and code == -352:
        raise RiskControlError(
            reason="risk_code",
            code=-352,
            raw_response=_safe_text(response),
        )

    data = payload.get("data")
    if isinstance(data, dict) and data.get("v_voucher"):
        raise RiskControlError(
            reason="voucher",
            code=0,
            raw_response=_safe_text(response),
        )


def is_risk_control_error(exc: BaseException) -> bool:
    """判断异常是否为 :class:`RiskControlError`。

    用于 workflow 层 ``except`` 子句中区分风控异常与其他异常。
    """
    return isinstance(exc, RiskControlError)


def _safe_json(response: httpx.Response) -> dict[str, Any] | None:
    """安全地解析响应为 JSON，失败时返回 None。

    响应非 JSON、空、或已读取过（stream 已关闭）时均返回 None，
    不抛异常以便 ``check_response`` 跳过业务码检测。
    """
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        return None
    try:
        parsed = response.json()
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _safe_text(response: httpx.Response) -> str:
    """安全地获取响应文本，失败时返回空字符串。

    避免在风控检测路径中因 ``response.text`` 抛二次异常。
    """
    try:
        return response.text
    except Exception:
        return ""
