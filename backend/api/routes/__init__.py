"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from api.routes import soul
from api.routes import search_config  # noqa: F401  Task 9: 搜索配置路由
from api.routes import discussions  # noqa: F401  Task 3: 多 Agent 讨论任务路由
