"""
微信相关工具函数，提供绑定状态规范化、技能配置反序列化和二维码 URL 校验等通用能力。

这些函数从 api/routes/weixin.py、api/routes/skills.py、api/routes/weixin_skill.py
三个文件中提取，消除重复实现并统一行为。
"""

import json
from typing import Any, Dict, FrozenSet, Optional
from urllib.parse import urlparse

from loguru import logger

# 微信二维码图片代理允许的域名白名单，防止 SSRF 攻击
WEIXIN_QR_ALLOWED_DOMAINS: FrozenSet[str] = frozenset({
    "wx.qq.com",
    "weixin.qq.com",
    "open.weixin.qq.com",
    "ilinkai.weixin.qq.com",
    "mmbiz.qpic.cn",
    "mmbiz.qlogo.cn",
    "res.wx.qq.com",
})


def normalize_binding_status(
    binding_status: Optional[str],
    user_id: str = "",
    fallback: str = "unbound",
) -> str:
    """
    规范化微信绑定状态字符串。

    将上游返回的各种状态别名统一映射为标准状态值：
    - "bound": 已绑定（包括 confirmed、linked、success、succeeded）
    - "pending": 待确认（包括 confirming、waiting）
    - "unbound" 或 fallback: 未绑定或其他无法识别的状态

    参数:
        binding_status: 上游返回的原始绑定状态字符串
        user_id: 微信用户 ID，非空时倾向于判定为已绑定
        fallback: 无法识别状态时的默认返回值

    返回:
        规范化后的绑定状态字符串
    """
    normalized = str(binding_status or "").strip().lower()
    if normalized in {"bound", "confirmed", "linked", "success", "succeeded"}:
        return "bound"
    if normalized in {"pending", "confirming", "waiting"}:
        return "pending"
    if normalized in {"unbound", "failed", "none", ""}:
        return "bound" if user_id else fallback
    if user_id:
        return "bound"
    return fallback


def deserialize_skill_config(config_value: Any) -> Dict[str, Any]:
    """
    统一解析技能配置字段，兼容字典对象、JSON 字符串和历史遗留的 YAML 字符串。

    解析优先级：字典对象 > JSON 字符串 > YAML 字符串。
    所有解析失败的情况均静默返回空字典，不抛出异常。

    参数:
        config_value: 待解析的配置值，可能是字典、JSON 字符串、YAML 字符串或 None

    返回:
        解析后的配置字典，解析失败时返回空字典
    """
    if isinstance(config_value, dict):
        return dict(config_value)
    if config_value is None:
        return {}

    text = str(config_value or "").strip()
    if not text:
        return {}

    # 优先尝试 JSON 解析
    try:
        loaded = json.loads(text)
    except Exception as exc:
        # JSON 解析失败时降级为 None，记录 debug 便于排查配置格式问题
        # 后续会回退到 YAML 解析，无需 warning 级别
        logger.debug(f"[weixin_utils] JSON 解析失败，将尝试 YAML: {exc}")
        loaded = None
    if isinstance(loaded, dict):
        return loaded

    # 兼容历史遗留的 YAML 格式
    try:
        import yaml
        loaded = yaml.safe_load(text)
    except Exception as exc:
        # YAML 解析失败时降级为空字典，记录 debug 便于排查配置格式异常
        logger.debug(f"[weixin_utils] YAML 解析失败，降级为空字典: {exc}")
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def validate_qrcode_url(url: str) -> str:
    """
    校验二维码图片 URL 的安全性，防止 SSRF（服务器端请求伪造）攻击。

    校验规则：
    1. URL 不能为空
    2. 必须包含合法的域名
    3. 仅允许 HTTPS 协议，防止中间人攻击
    4. 域名必须在微信官方白名单内

    参数:
        url: 待校验的二维码图片 URL

    返回:
        规范化后的 URL 字符串（去除首尾空白）

    异常:
        ValueError: URL 不满足安全校验规则时抛出
    """
    normalized_url = str(url).strip()
    if not normalized_url:
        raise ValueError("二维码 URL 为空")

    parsed = urlparse(normalized_url)
    hostname = str(parsed.hostname or "").lower()

    # 拒绝无域名或协议不完整的 URL
    if not hostname:
        raise ValueError(f"二维码 URL 缺少合法域名: {normalized_url[:120]}")

    # 仅允许 HTTPS 协议避免中间人攻击
    if parsed.scheme != "https":
        raise ValueError(f"二维码 URL 仅允许 https 协议: {normalized_url[:120]}")

    # 校验域名白名单
    if hostname not in WEIXIN_QR_ALLOWED_DOMAINS:
        raise ValueError(f"二维码 URL 域名 '{hostname}' 不在允许的白名单中")

    return normalized_url
