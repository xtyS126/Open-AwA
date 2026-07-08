"""
backend_mobile.routes 包

移动端内嵌后端的路由模块集合。
每个模块对应一个功能域，与桌面版 backend/api/routes/ 的差异：
- 移除桌面专属功能（ACP/Terminal/TTS/Plugins 热更新）
- 简化依赖（不依赖插件系统、向量库、LSP）
- 数据库使用应用私有目录的 SQLite
"""

from . import system, auth, chat, user, security

__all__ = ["system", "auth", "chat", "user", "security"]
