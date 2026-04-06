"""
微信技能适配器模块化重构包
提供微信消息处理、状态持久化、API通信、监控循环等功能
"""

from skills.weixin.config import WeixinRuntimeConfig
from skills.weixin.errors import WeixinAdapterError
from skills.weixin.adapter import WeixinSkillAdapter
from skills.weixin.monitor import (
    WeixinMonitor,
    MonitorStatus,
    MonitorConfig,
    MonitorState,
    start_monitor,
    stop_monitor,
    get_monitor_status,
    get_all_monitors,
)

__all__ = [
    "WeixinRuntimeConfig",
    "WeixinAdapterError",
    "WeixinSkillAdapter",
    "WeixinMonitor",
    "MonitorStatus",
    "MonitorConfig",
    "MonitorState",
    "start_monitor",
    "stop_monitor",
    "get_monitor_status",
    "get_all_monitors",
]
