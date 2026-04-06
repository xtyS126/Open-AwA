"""
微信运行时配置模块
定义微信适配器的配置数据结构
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_QR_BASE_URL = DEFAULT_BASE_URL
DEFAULT_BOT_TYPE = "3"
DEFAULT_CHANNEL_VERSION = "1.0.2"
SESSION_EXPIRED_ERRCODE = -14
SESSION_PAUSE_DURATION_SECONDS = 60 * 60


@dataclass
class WeixinRuntimeConfig:
    """
    微信运行时配置类
    封装微信适配器运行所需的配置参数
    
    属性:
        account_id: 账号ID
        token: Bot认证令牌
        base_url: API服务器地址
        bot_type: 机器人类型，默认为"3"
        channel_version: 渠道版本
        timeout_seconds: 请求超时时间（秒）
        user_id: 微信用户ID
        binding_status: 绑定状态（unbound/pending/bound）
    """
    account_id: str
    token: str
    base_url: str
    bot_type: str
    channel_version: str
    timeout_seconds: int
    user_id: str = ""
    binding_status: str = "unbound"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WeixinRuntimeConfig:
        """
        从字典创建配置实例
        
        参数:
            data: 包含配置信息的字典
            
        返回:
            WeixinRuntimeConfig实例
        """
        return cls(
            account_id=str(data.get("account_id", "")).strip(),
            token=str(data.get("token", "")).strip(),
            base_url=str(data.get("base_url", DEFAULT_BASE_URL)).strip().rstrip("/"),
            bot_type=str(data.get("bot_type", DEFAULT_BOT_TYPE)),
            channel_version=str(data.get("channel_version", DEFAULT_CHANNEL_VERSION)),
            timeout_seconds=max(5, int(data.get("timeout_seconds", 15))),
            user_id=str(data.get("user_id", "")).strip(),
            binding_status=str(data.get("binding_status", "unbound")).strip(),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        将配置转换为字典
        
        返回:
            包含所有配置字段的字典
        """
        return {
            "account_id": self.account_id,
            "token": self.token,
            "base_url": self.base_url,
            "bot_type": self.bot_type,
            "channel_version": self.channel_version,
            "timeout_seconds": self.timeout_seconds,
            "user_id": self.user_id,
            "binding_status": self.binding_status,
        }
