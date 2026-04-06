"""
异步任务管理模块
提供任务创建、状态追踪、结果回调等功能
"""

from .manager import AsyncTask, TaskManager

__all__ = ["AsyncTask", "TaskManager"]
