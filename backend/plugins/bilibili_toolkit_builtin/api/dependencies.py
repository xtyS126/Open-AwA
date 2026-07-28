"""bilibili-toolkit-builtin 内置插件路由依赖装配。

复用 Open-AwA 既有依赖注入：
- ``get_db``：请求级 SQLAlchemy Session（同步 ORM 路径）
- ``get_current_user``：JWT/API Key/Cookie 多路径认证，返回 ``User`` ORM 对象

路由层通过 ``Depends(get_db)`` 与 ``Depends(get_current_user)`` 注入，
不重复实现认证与数据库会话管理，遵循项目依赖注入规范。
"""

from __future__ import annotations

# 重导出 Open-AwA 既有依赖，便于路由文件单点引用
from api.dependencies import get_current_user, get_db

__all__ = [
    "get_db",
    "get_current_user",
]
