"""
微信技能模块
提供微信消息处理、CDN 上传下载、媒体转码等功能。
"""

from backend.skills.weixin_skill_adapter import WeixinSkillAdapter, WeixinRuntimeConfig, WeixinAdapterError

__all__ = [
    "WeixinSkillAdapter",
    "WeixinRuntimeConfig",
    "WeixinAdapterError",
]
