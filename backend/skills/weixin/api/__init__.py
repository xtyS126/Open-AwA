"""
API通信模块
提供与微信iLink API的HTTP通信能力
"""

from backend.skills.weixin.api.client import (
    api_post,
    api_get,
)

__all__ = [
    "api_post",
    "api_get",
]
