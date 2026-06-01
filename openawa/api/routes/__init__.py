"""
API 路由重新导出模块。
从 backend.api.routes 导入，确保 openawa 包在 pip 安装模式下可正常工作。
"""
try:
    from backend.api.routes import auth, chat, skills, plugins, memory, prompts, behavior, experiences, conversation, experience_files, logs, mcp, models, workflows, scheduled_tasks
except ImportError:
    from api.routes import auth, chat, skills, plugins, memory, prompts, behavior, experiences, conversation, experience_files, logs, mcp, models, workflows, scheduled_tasks

# 单个路由模块
try:
    from backend.api.routes.diary import router as diary_router
except ImportError:
    from api.routes.diary import router as diary_router

try:
    from backend.api.routes.marketplace import router as marketplace_router
except ImportError:
    from api.routes.marketplace import router as marketplace_router

try:
    from backend.api.routes.security import router as security_router
except ImportError:
    from api.routes.security import router as security_router

try:
    from backend.api.routes.weixin import router as weixin_router
except ImportError:
    from api.routes.weixin import router as weixin_router

try:
    from backend.api.routes.tools import router as tools_router
except ImportError:
    from api.routes.tools import router as tools_router

try:
    from backend.api.routes.subagents import router as subagents_router
except ImportError:
    from api.routes.subagents import router as subagents_router

try:
    from backend.api.routes.user import router as user_router
except ImportError:
    from api.routes.user import router as user_router

try:
    from backend.api.routes.system import router as system_router
except ImportError:
    from api.routes.system import router as system_router

try:
    from backend.api.routes.task_runtime import router as task_runtime_router
except ImportError:
    from api.routes.task_runtime import router as task_runtime_router

try:
    from backend.api.routes.test_runner import router as test_runner_router
except ImportError:
    from api.routes.test_runner import router as test_runner_router

try:
    from backend.api.routes.workspace import router as workspace_router
except ImportError:
    from api.routes.workspace import router as workspace_router

try:
    from backend.api.routes.coding import router as coding_router
except ImportError:
    from api.routes.coding import router as coding_router
