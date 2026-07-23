"""B 站登录凭据数据类。

将 schema.json 中的 ``bilibili_cookie`` 字符串解析为结构化对象，
便于 ``BilibiliClient`` 注入 Cookie 头与 WBI 签名时使用。

参考实现：``bili-sync/crates/bili_sync/src/bilibili/credential.rs``
（Rust 版用 ``Cookie`` crate 解析 Set-Cookie 头，本项目的
Cookie 已在 schema 中以纯字符串形式存储，因此改用简单的
``;`` 分隔键值对解析）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Credential(BaseModel):
    """B 站登录凭据。

    封装调用需要登录的 B 站 API 所需的四个关键字段，
    其中 ``sessdata`` / ``bili_jct`` / ``dede_user_id`` 必填，
    ``buvid3`` 可选（仅在 QR 登录流程中通过 ``getbuvid`` 端点获取）。
    """

    sessdata: str = Field(default="", description="SESSDATA Cookie 值，登录态核心凭证")
    bili_jct: str = Field(default="", description="bili_jct Cookie 值，CSRF 防护用")
    dede_user_id: str = Field(default="", description="DedeUserID Cookie 值，用户 mid")
    buvid3: str = Field(default="", description="buvid3 浏览器指纹，部分接口需要")

    @classmethod
    def from_cookie_string(cls, cookie_str: str) -> "Credential":
        """从 Cookie 字符串解析为 Credential 对象。

        支持形如 ``SESSDATA=xxx; bili_jct=yyy; DedeUserID=zzz; buvid3=www``
        的标准 Cookie 头格式。未识别到对应键时字段留空。

        Args:
            cookie_str: 原始 Cookie 字符串，可为空。

        Returns:
            解析后的 Credential 对象（即使 Cookie 缺失也返回空对象，不抛异常，
            由调用方决定是否需要凭据）。
        """
        if not cookie_str:
            return cls()
        pairs: dict[str, str] = {}
        for chunk in cookie_str.split(";"):
            chunk = chunk.strip()
            if not chunk or "=" not in chunk:
                continue
            key, _, value = chunk.partition("=")
            pairs[key.strip()] = value.strip()
        return cls(
            sessdata=pairs.get("SESSDATA", ""),
            bili_jct=pairs.get("bili_jct", ""),
            dede_user_id=pairs.get("DedeUserID", ""),
            buvid3=pairs.get("buvid3", ""),
        )

    def to_cookie_dict(self) -> dict[str, str]:
        """转换为 httpx cookies 参数所需的 dict。

        仅包含非空字段，避免向请求注入空值 Cookie。

        Returns:
            ``{SESSDATA: ..., bili_jct: ..., DedeUserID: ..., buvid3: ...}`` 形式的 dict。
        """
        result: dict[str, str] = {
            "SESSDATA": self.sessdata,
            "bili_jct": self.bili_jct,
            "DedeUserID": self.dede_user_id,
        }
        if self.buvid3:
            result["buvid3"] = self.buvid3
        return {k: v for k, v in result.items() if v}

    def to_cookie_header(self) -> str:
        """拼接为 Cookie 请求头字符串。

        用于 httpx ``headers={"Cookie": ...}`` 注入方式，
        与 ``to_cookie_dict`` 等价但格式不同。
        """
        pairs = self.to_cookie_dict()
        return "; ".join(f"{k}={v}" for k, v in pairs.items())

    def is_valid(self) -> bool:
        """判断凭据是否具备调用登录态 API 的最低要求。

        Returns:
            ``sessdata`` 与 ``bili_jct`` 同时非空时返回 True。
        """
        return bool(self.sessdata and self.bili_jct)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        """重写以避免在日志/调试输出中泄露完整 Cookie 值。

        默认行为与 BaseModel 一致；调用方可通过 ``mask=True`` 启用脱敏。
        """
        mask = bool(kwargs.pop("mask", False))
        dumped = super().model_dump(**kwargs)
        if not mask:
            return dumped
        masked: dict[str, Any] = {}
        for key, value in dumped.items():
            if isinstance(value, str) and len(value) > 8:
                masked[key] = value[:4] + "***" + value[-4:]
            else:
                masked[key] = value
        return masked
