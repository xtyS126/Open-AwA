"""
pytest 全局配置：测试启动前设置测试专用环境变量，禁用 CSRF 校验等安全中间件。
"""

import os
import sys
import tempfile
from pathlib import Path

# 测试专用环境变量名，避免与通用 TESTING 变量冲突
_CSRF_TEST_ENV = "SKIP_CSRF_FOR_TEST"
_TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"openawa-pytest-{os.getpid()}.db"
_TEST_VECTOR_DB_PATH = Path(tempfile.gettempdir()) / f"openawa-pytest-qdrant-{os.getpid()}"
_TEST_LOG_PATH = Path(tempfile.gettempdir()) / f"openawa-pytest-logs-{os.getpid()}"
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


def pytest_configure(config):
    """在所有测试收集/运行之前设置测试用环境变量，仅影响 pytest 进程。"""
    os.environ[_CSRF_TEST_ENV] = "true"
    os.environ["TESTING"] = "true"
    # 全局 app 的 lifespan 会直接使用模块级数据库引擎，必须在收集测试模块前隔离默认数据库
    os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DATABASE_PATH.as_posix()}"
    # MemoryManager 会在 Agent 构造时创建嵌入式 Qdrant，必须隔离默认向量目录，避免访问用户数据或受保护锁文件
    os.environ["VECTOR_DB_PATH"] = str(_TEST_VECTOR_DB_PATH)
    # 文件日志必须与正在运行的服务隔离，避免 Windows 轮转时争用同一个文件
    os.environ["LOG_DIR"] = str(_TEST_LOG_PATH)
    # 安全测试必须使用受限模式，不能继承开发机的宽松命令配置
    os.environ["AGENT_WORKSPACE_UNRESTRICTED_COMMANDS"] = "false"
    # ACP 路由测试只允许后端测试工作区，不放宽生产环境的默认白名单
    os.environ["ACP_ALLOWED_WORKDIRS"] = str(_BACKEND_ROOT)
    # 默认使用 hash 嵌入提供方，避免 VectorStoreManager 在未配置 OPENAI_API_KEY 时
    # 回退到 SentenceTransformerEmbeddingProvider 触发 sentence-transformers ImportError
    # 想测试 sentence-transformers 路径的用例可在 fixture 内显式覆盖此变量
    os.environ.setdefault("MEMORY_EMBEDDING_PROVIDER", "hash")
    # 显式声明测试环境的 MCP SSE origin 白名单（fail-closed 契约：未配置则拒绝启动）。
    # 测试 WebView/TestClient 以 localhost 发起 SSE 请求，白名单必须显式配置而非继承
    # 生产环境变量；test_mcp_sse_origin.py 用例内部会按需覆盖此变量，不受影响
    os.environ.setdefault("MCP_SSE_ALLOWED_ORIGINS", "https://localhost")
    # 与生产启动顺序一致：先初始化默认数据库表结构，再允许构造 VectorStoreManager
    # （其构造会同步 vector_model_config 表配置，该同步失败已改为显式抛错）
    from db.models import init_db

    init_db()


def _reset_loaded_runtime_state() -> None:
    """清理已加载模块的运行时单例状态，阻断跨用例污染。"""
    main_module = sys.modules.get("main")
    app = getattr(main_module, "app", None) if main_module is not None else None
    if app is not None:
        app.dependency_overrides.clear()

    task_registry_module = sys.modules.get("core.agent_task_registry")
    active_tasks = getattr(task_registry_module, "_active_agent_tasks", None)
    if isinstance(active_tasks, dict):
        active_tasks.clear()

    registry_module = sys.modules.get("core.agent_registry")
    registry = getattr(registry_module, "_registry_instance", None)
    if registry is not None:
        registry.clear_all()

    acp_route_module = sys.modules.get("api.routes.acp")
    acp_sessions = getattr(acp_route_module, "_acp_user_sessions", None)
    if isinstance(acp_sessions, dict):
        acp_sessions.clear()

    acp_service_module = sys.modules.get("acp_host.service")
    shutdown_acp_services = getattr(acp_service_module, "_shutdown_acp_services", None)
    if callable(shutdown_acp_services):
        shutdown_acp_services()

    plugin_instance_module = sys.modules.get("plugins.plugin_instance")
    reset_plugin_instance = getattr(plugin_instance_module, "reset", None)
    if callable(reset_plugin_instance):
        reset_plugin_instance()

    ws_module = sys.modules.get("api.services.ws_manager")
    ws_manager = getattr(ws_module, "ws_manager", None)
    if ws_manager is not None:
        ws_manager.stop_heartbeat()
        ws_manager._session_connections.clear()
        ws_manager._user_sessions.clear()
        ws_manager._last_activity.clear()

    # MemoryManager 持有类级 _shared_vector_store 单例（VectorStoreManager），
    # 跨用例共享会导致 Qdrant 嵌入式文件锁冲突与跨用例数据污染。
    # 必须在 teardown 时关闭并清空，强制下个用例重新构造 VectorStoreManager。
    memory_manager_module = sys.modules.get("memory.manager")
    memory_manager_cls = getattr(memory_manager_module, "MemoryManager", None) if memory_manager_module else None
    if memory_manager_cls is not None:
        existing_store = getattr(memory_manager_cls, "_shared_vector_store", None)
        if existing_store is not None:
            try:
                existing_store.close()
            except Exception:
                pass
            memory_manager_cls._shared_vector_store = None


def pytest_runtest_setup(item):
    """每个用例设置 fixture 前清理共享运行时状态。"""
    _reset_loaded_runtime_state()


def pytest_runtest_teardown(item, nextitem):
    """每个用例结束后再次清理共享运行时状态。"""
    _reset_loaded_runtime_state()
