"""
后端服务主入口，负责应用初始化、中间件注册、路由挂载与基础健康检查。
阅读本文件时，建议优先关注启动顺序、生命周期管理、请求链路上下文以及全局异常处理方式。
"""

from contextlib import asynccontextmanager
import asyncio
import errno
import inspect
import os
import time
from typing import Optional

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

from api.routes import auth, chat, skills, plugins, memory, prompts, behavior, experiences, conversation, experience_files, logs, mcp, models, workflows, scheduled_tasks, soul, discussions, search_config  # [NEW] Task 3+9: 讨论任务 + 搜索配置路由
from api.routes.data import router as data_router
from api.dependencies import get_current_user
from api.routes.diary import router as diary_router
from api.routes.marketplace import router as marketplace_router
from api.routes.security import router as security_router
from api.routes.security_enhanced import router as security_enhanced_router
from api.routes.cot_audit import router as cot_audit_router
from api.routes.weixin import router as weixin_router
from api.routes.tools import router as tools_router
from api.routes.subagents import router as subagents_router
from api.routes.user import router as user_router
from api.routes.user_profile import router as user_profile_router
from api.routes.system import router as system_router
from api.routes.task_runtime import router as task_runtime_router
from api.routes.test_runner import router as test_runner_router
from api.routes.workspace import router as workspace_router
from api.routes.coding import router as coding_router
from api.routes.inbox import router as inbox_router
from api.routes.magic_commands import router as magic_commands_router
from api.routes.heartbeat import router as heartbeat_router
from api.routes.tts import router as tts_router
from api.routes.tasks import router as tasks_router
from api.routes.roles import router as roles_router
from api.routes.role_market import router as role_market_router
from api.routes.terminal import router as terminal_router
from api.routes.im import router as im_router
from api.routes.acp import router as acp_router
from api.routes.preview_proxy import router as preview_proxy_router
from api.routes.notifications import router as notifications_router

from billing.routers import billing
from config.logging import (
    REQUEST_ID_HEADER,
    clear_request_id,
    generate_request_id,
    init_logging,
    sanitize_for_logging,
    set_request_id,
)
from core.metrics import prometheus_registry
from core.model_service import (
    CLIENT_VERSION_HEADER,
    SERVER_VERSION_HEADER,
    VERSION_STATUS_HEADER,
    build_standard_error,
    close_shared_client,
    negotiate_version_status,
)
from core.litellm_adapter import is_litellm_available
from core.scheduled_task_manager import scheduled_task_manager
from core.startup.profiler import StartupProfiler
from config.security import generate_csrf_token, verify_csrf_token
from config.settings import is_production_environment, settings
from db.models import engine, init_db


init_logging(
    log_level=settings.LOG_LEVEL,
    service_name=settings.LOG_SERVICE_NAME,
    log_serialize=settings.LOG_SERIALIZE,
    log_dir=settings.LOG_DIR,
    log_file_rotation=settings.LOG_FILE_ROTATION,
    log_file_retention=settings.LOG_FILE_RETENTION,
    log_file_compression=settings.LOG_FILE_COMPRESSION,
)

def _resolve_allowed_origins() -> list[str]:
    """
    统一解析 CORS 白名单。
    生产环境必须显式配置，避免默认开发域名带入生产。
    """
    raw_origins = os.getenv("ALLOWED_ORIGINS", "")
    origins = [item.strip() for item in raw_origins.split(",") if item.strip()]
    if origins:
        return origins

    if is_production_environment(os.getenv("ENVIRONMENT", "development")):
        raise ValueError("ALLOWED_ORIGINS environment variable is required in production environment")

    return ["http://localhost:5173", "http://localhost:8000"]


ALLOWED_ORIGINS = _resolve_allowed_origins()
logger.bind(event="cors_configured", module="main", allowed_origins=sanitize_for_logging(ALLOWED_ORIGINS)).info("cors configured")


def _resolve_allow_origin_regex() -> Optional[str]:
    """
    解析局域网跨域访问开关。

    当环境变量 ALLOW_LAN_ACCESS=true 时，返回匹配私有网段 IP 的正则表达式，
    使局域网内设备（手机/平板/桌面等）可通过本机 IP 访问后端服务，实现多端互通。

    安全策略（SEC-21）：
      CORS 同时启用 allow_credentials=True 时，宽松的 LAN 正则会放大
      DNS rebinding 与同网段恶意站点攻击的风险，因此正则仅匹配常见的
      家庭/办公网段，避免覆盖整个 RFC 1918 私有地址空间。

    匹配范围（收紧后）：
      - localhost / 127.0.0.1：本地回环，用于开发与 HMR
      - 192.168.0.0/24、192.168.1.0/24：常见家庭路由器默认网段
    不再覆盖 10.0.0.0/8、172.16.0.0/12 与完整 192.168.0.0/16，
    如需访问其他网段，请通过 ALLOWED_ORIGINS 显式配置具体 origin。
    支持 http/https 协议与任意端口，格式严格为 http(s)://host(:port)。
    未开启时返回 None，仅依赖显式白名单 ALLOWED_ORIGINS。
    """
    if os.getenv("ALLOW_LAN_ACCESS", "").lower() != "true":
        return None
    # 仅允许本地回环与最常见的家庭网段，避免与 allow_credentials=True 组合
    # 时形成跨域凭据泄露面；其他网段需通过 ALLOWED_ORIGINS 显式白名单
    return (
        r"^https?://("
        r"localhost|127\.0\.0\.1|"
        r"192\.168\.(0|1)\.\d{1,3}"
        r")(:\d+)?$"
    )


ALLOW_LAN_ORIGIN_REGEX = _resolve_allow_origin_regex()
if ALLOW_LAN_ORIGIN_REGEX:
    logger.bind(event="lan_access_enabled", module="main").info(
        "局域网跨域访问已开启，允许私有网段 IP 的多端接入"
    )


# ==================== 启动步骤拆分 ====================
# 将原 lifespan 中的初始化逻辑按职责拆分为独立函数：
#   1. 基础设施（LiteLLM 依赖检测）
#   2. 数据初始化（DB 建表、计费、RBAC、用户同步）
#   3. 插件系统（市场种子、插件发现与加载）
#   4. 后台任务（定时任务、微信自动回复）
#
# 每步失败有独立日志和错误上下文，便于排障和单元测试。


def _check_model_provider_availability() -> None:
    """检查是否至少有一个模型供应商配置了有效的 API Key。

    优先查询数据库 provider_credentials 表（spec 重构后 API Key 统一存数据库），
    同时保留 .env 环境变量检查作为向后兼容补充。
    未配置任何 Key 时发出警告（不阻塞启动），方便开发者第一时间发现配置缺失。
    """
    configured = []

    # 1. 查询数据库 provider_credentials 表中有效凭据（is_active 且 api_key 非空且非 enc: 旧密文）
    try:
        from db.models import SessionLocal
        from sqlalchemy import text as _sql_text
        db = SessionLocal()
        try:
            # 统计有效 provider：api_key 非空且不以 enc: 开头（enc: 旧密文已失效）
            result = db.execute(
                _sql_text(
                    "SELECT provider FROM provider_credentials "
                    "WHERE is_active = 1 AND api_key IS NOT NULL AND api_key != '' "
                    "AND api_key NOT LIKE 'enc:%'"
                )
            )
            for row in result:
                configured.append(str(row[0]))
        finally:
            db.close()
    except Exception as exc:
        # 数据库尚未初始化（表不存在）或查询失败时降级为 DEBUG，不阻塞启动
        logger.bind(event="provider_check_db_skipped", module="main").debug(
            f"数据库凭据查询跳过（表可能尚未初始化）: {exc}"
        )

    # 2. 补充检查 .env 环境变量（向后兼容，数据库无凭据时作为兜底提示）
    provider_keys = {
        "openai": settings.OPENAI_API_KEY,
        "anthropic": settings.ANTHROPIC_API_KEY,
        "deepseek": settings.DEEPSEEK_API_KEY,
    }
    for name, key in provider_keys.items():
        if key is not None and name not in configured:
            raw = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)
            if raw.strip():
                configured.append(name)

    if not configured:
        logger.bind(event="no_model_provider_configured", module="main").warning(
            "未检测到任何已配置 API Key 的模型供应商。"
            "请在设置页录入供应商 API Key，或在 .env 中配置 OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY。"
        )
    else:
        logger.bind(event="provider_check", module="main").info(
            f"已检测到 {len(configured)} 个已配置的模型供应商: {', '.join(configured)}"
        )


def _ensure_api_key() -> None:
    """校验 OPENAWA_API_KEY 已配置，未配置时拒绝启动。

    密钥必须通过以下方式之一提供：
    1. 环境变量 OPENAWA_API_KEY
    2. backend/.env.local 文件中的 OPENAWA_API_KEY=...
    3. 运行 python generate_api_key.py 手动生成
    """
    # 优先从 settings 读取（已由 pydantic-settings 从 .env.local 加载），降级到 os.getenv
    api_key = settings.OPENAWA_API_KEY.get_secret_value().strip()
    if not api_key:
        api_key = os.getenv("OPENAWA_API_KEY", "").strip()

    if api_key and len(api_key) >= 32:
        if not settings.OPENAWA_API_KEY.get_secret_value().strip():
            from pydantic import SecretStr
            object.__setattr__(settings, "OPENAWA_API_KEY", SecretStr(api_key))
        logger.bind(event="api_key_configured", module="main").info(
            "OPENAWA_API_KEY 已加载"
        )
        return

    if api_key and len(api_key) < 32:
        raise SystemExit(
            "\n[错误] OPENAWA_API_KEY 长度不足，至少需要 32 字符。\n"
            "请运行 python generate_api_key.py 生成新的访问密钥，\n"
            "或设置环境变量 OPENAWA_API_KEY 为至少 32 字符的随机字符串。\n"
        )

    # 未配置密钥 → 拒绝启动
    raise SystemExit(
        "\n[错误] 未配置访问密钥 (OPENAWA_API_KEY)，服务拒绝启动。\n\n"
        "请运行以下命令生成访问密钥：\n"
        "  cd backend && python generate_api_key.py\n\n"
        "或手动设置环境变量：\n"
        "  $env:OPENAWA_API_KEY=\"your-secret-key-here\"  (PowerShell)\n"
        "  export OPENAWA_API_KEY=\"your-secret-key-here\"   (Bash)\n"
    )


async def _startup_infrastructure(profiler: StartupProfiler) -> None:
    """基础设施层初始化：依赖检测、模型供应商可用性检查。"""
    with profiler.step("litellm_check"):
        if is_litellm_available():
            logger.bind(event="litellm_available", module="main").info("LiteLLM dependency detected, unified LLM gateway enabled")
        else:
            logger.bind(event="litellm_missing", module="main").warning(
                "LiteLLM dependency not installed. "
                "Please run `pip install litellm` to enable unified LLM gateway. "
                "Model API requests will fail until LiteLLM is installed."
            )

    # 检查至少有一个模型供应商配置了有效凭据
    with profiler.step("provider_credential_check"):
        # 同步函数包装为 to_thread，避免阻塞事件循环（影响健康检查并发响应）
        await asyncio.to_thread(_check_model_provider_availability)

    # API Key 初始化（未设置时自动生成并持久化到 .env.local）
    with profiler.step("api_key_init"):
        _ensure_api_key()


async def _scan_legacy_encrypted_keys(db_session) -> None:
    """启动时扫描 provider_credentials 和 model_configurations 两表中的 enc: 旧密文，记录 WARNING 日志。

    旧算法密文(enc:)在密钥拆分后已无法解密，需提示用户重新录入。
    扫描失败时仅记录 ERROR 日志，不阻塞服务启动（解密路径已对 enc: 旧密文做兜底失效处理）。
    不自动清空数据库中的旧密文，保留数据以便用户在设置页查看后重新录入。
    """
    from sqlalchemy import text

    try:
        # 统计 provider_credentials 表中以 enc: 开头的旧密文记录数
        provider_result = db_session.execute(
            text("SELECT COUNT(*) FROM provider_credentials WHERE api_key LIKE 'enc:%'")
        )
        provider_count = int(provider_result.scalar() or 0)

        # 统计 model_configurations 表中以 enc: 开头的旧密文记录数（legacy 字段，保留兼容）
        model_result = db_session.execute(
            text("SELECT COUNT(*) FROM model_configurations WHERE api_key LIKE 'enc:%'")
        )
        model_count = int(model_result.scalar() or 0)

        total = provider_count + model_count

        if total > 0:
            logger.bind(
                event="legacy_encrypted_keys_detected",
                module="startup",
                provider_count=provider_count,
                model_count=model_count,
                total=total,
            ).warning(
                f"检测到 {total} 条旧算法密文(enc:)，已标记失效，请通知用户在设置页重新录入 API Key"
                f"（provider_credentials={provider_count}，model_configurations={model_count}）"
            )
        else:
            logger.bind(
                event="legacy_encrypted_keys_clean",
                module="startup",
            ).info("未检测到旧算法密文，密钥迁移状态正常")
    except Exception as exc:
        # 扫描失败不阻塞启动，解密路径已对 enc: 旧密文做兜底失效处理
        logger.bind(
            event="legacy_encrypted_keys_scan_error",
            module="startup",
        ).error(f"扫描旧算法密文失败，跳过告警（不阻塞启动）: {exc}")


async def _startup_data_init(profiler: StartupProfiler) -> None:
    """数据层初始化：DB 建表、计费配置、RBAC 角色、Owner 用户创建。"""
    from db.models import SessionLocal

    # rate_limit_store 不依赖 DB（memory 后端），即使跳过 DB 初始化也能正常工作
    from security.rate_limit_store import init_rate_limit_store
    with profiler.step("rate_limit_store_init"):
        init_rate_limit_store(
            backend=settings.RATE_LIMIT_BACKEND,
            db_session_factory=SessionLocal,
        )

    if os.getenv("SKIP_INIT_DB"):
        return

    with profiler.step("db_init"):
        try:
            init_db()
            logger.bind(event="db_initialized", module="main").info("database initialized")
        except Exception as exc:
            # 针对 SQLite 常见的 readonly/locked 错误给出明确诊断提示
            exc_msg = str(exc).lower()
            if "readonly" in exc_msg or "locked" in exc_msg or "database is locked" in exc_msg:
                logger.bind(event="db_init_error", module="main").error(
                    f"数据库初始化失败（数据库被占用或只读）: {exc}\n"
                    "常见原因：1) 另一个后端实例正在运行并占用数据库锁；"
                    "2) 数据库文件或所在目录无写权限；"
                    "3) WAL 文件(-wal/-shm)残留且被锁定。"
                    "请检查是否有残留 python main.py 进程，或清理 openawa.db-wal/openawa.db-shm 后重试。"
                )
            else:
                logger.bind(event="db_init_error", module="main").error(f"数据库初始化失败: {exc}")
            raise RuntimeError(f"数据库初始化失败，服务无法启动: {exc}") from exc

    # 初始化预设角色
    with profiler.step("preset_roles_init"):
        try:
            from core.role_engine import RoleEngine
            _preset_db = SessionLocal()
            try:
                # 同步 DB 调用包装为 to_thread，避免阻塞事件循环
                added = await asyncio.to_thread(RoleEngine.ensure_presets_in_db, _preset_db)
                if added > 0:
                    logger.bind(event="preset_roles_initialized", module="startup").info(f"初始化 {added} 个预设角色")
            finally:
                _preset_db.close()
        except Exception as e:
            logger.bind(event="preset_roles_init_error", module="startup").warning(f"预设角色初始化失败: {e}")

    with profiler.step("billing_tables"):
        logger.bind(event="billing_tables_initialized", module="main").info("billing tables initialized")

    from billing.pricing_manager import PricingManager
    with profiler.step("pricing_init"):
        db = SessionLocal()
        try:
            pricing_manager = PricingManager(db)
            # 同步 DB 调用包装为 to_thread，避免阻塞事件循环
            await asyncio.to_thread(pricing_manager.ensure_configuration_schema)
            count = await asyncio.to_thread(pricing_manager.initialize_default_pricing)
            if count > 0:
                logger.bind(event="pricing_initialized", module="main", count=count).info("initialized model pricing entries")
            config_count = await asyncio.to_thread(pricing_manager.initialize_default_configurations)
            if config_count > 0:
                logger.bind(event="configurations_initialized", module="main", count=config_count).info("initialized default model configurations")
            removed = await asyncio.to_thread(pricing_manager.remove_legacy_default_configurations)
            if removed > 0:
                logger.bind(event="legacy_pricing_removed", module="main", removed=removed).info("removed legacy default model configurations")
        finally:
            db.close()

    # 扫描历史 enc: 旧密文并记录告警，提示用户重新录入（扫描失败不阻塞启动）
    with profiler.step("legacy_encrypted_keys_scan"):
        db = SessionLocal()
        try:
            await _scan_legacy_encrypted_keys(db)
        finally:
            db.close()

    from security.rbac import RBACManager
    with profiler.step("rbac_init"):
        db = SessionLocal()
        try:
            rbac = RBACManager(db)
            # 同步 DB 调用包装为 to_thread，避免阻塞事件循环
            await asyncio.to_thread(rbac.ensure_built_in_roles)
        finally:
            db.close()

    from core.owner import ensure_owner_user
    with profiler.step("owner_user_init"):
        db = SessionLocal()
        try:
            # 同步 DB 调用包装为 to_thread，避免阻塞事件循环
            owner = await asyncio.to_thread(ensure_owner_user, db)
            # 确保 owner 拥有 admin 角色
            rbac = RBACManager(db)
            await rbac.set_user_role(owner.id, "admin")
            logger.bind(
                event="owner_user_initialized",
                module="main",
                username=owner.username,
                user_id=owner.id,
            ).info("owner user initialized with admin role")
        finally:
            db.close()


async def _startup_plugin_system(profiler: StartupProfiler) -> None:
    """插件系统初始化：市场种子、插件发现、已启用插件加载。"""
    from db.models import SessionLocal

    with profiler.step("marketplace_discover"):
        from plugins.marketplace.registry import marketplace_registry
        # 同步磁盘 I/O + DB 查询包装为 to_thread，避免阻塞事件循环
        await asyncio.to_thread(
            marketplace_registry.discover_from_plugins_dir,
            db_session_factory=SessionLocal
        )

    with profiler.step("plugin_discover"):
        from plugins.plugin_manager import PluginManager
        from plugins import plugin_instance
        plugin_instance.init(PluginManager(db_session_factory=SessionLocal))
        pm = plugin_instance.get()
        # 同步磁盘扫描包装为 to_thread
        await asyncio.to_thread(pm.discover_plugins)

    if os.getenv("SKIP_INIT_DB"):
        return

    with profiler.step("plugin_load_enabled"):
        from db.models import Plugin as PluginModel, Skill
        import uuid
        db = SessionLocal()
        try:
            # 迁移：删除已由 system-tools 插件接管的内置技能记录
            # 批量查询避免循环内单条查询（N+1 问题）
            skills_to_remove = ["file_manager", "terminal_executor"]
            old_skills = db.query(Skill).filter(Skill.name.in_(skills_to_remove)).all()
            for old_skill in old_skills:
                db.delete(old_skill)
                logger.bind(event="skill_migrated", module="main", skill=old_skill.name).info(
                    f"已迁移内置技能 {old_skill.name} 至 system-tools 插件"
                )
            db.commit()

            # 注册 system-tools 系统内置插件（如不存在）
            existing_plugin = db.query(PluginModel).filter(PluginModel.name == "system-tools").first()
            if not existing_plugin:
                new_plugin = PluginModel(
                    id=str(uuid.uuid4()),
                    name="system-tools",
                    version="1.0.0",
                    enabled=True,
                    config={},
                    category="builtin",
                    author="Open-AwA Team",
                    source="builtin",
                    dependencies=[],
                )
                db.add(new_plugin)
                db.commit()
                logger.bind(event="builtin_plugin_seeded", module="main", plugin="system-tools").info(
                    "已注册系统内置插件 system-tools"
                )

            # 注册 openbiliclaw-builtin 系统内置插件（如不存在）
            # 该插件声明 is_uninstallable=True，禁止通过 API 卸载或禁用
            existing_openbiliclaw = db.query(PluginModel).filter(
                PluginModel.name == "openbiliclaw-builtin"
            ).first()
            if not existing_openbiliclaw:
                new_openbiliclaw = PluginModel(
                    id=str(uuid.uuid4()),
                    name="openbiliclaw-builtin",
                    version="0.3.147",
                    enabled=True,
                    config={},
                    category="builtin",
                    author="OpenBiliClaw Team",
                    source="builtin",
                    is_uninstallable=True,
                    dependencies=[],
                )
                db.add(new_openbiliclaw)
                db.commit()
                logger.bind(
                    event="builtin_plugin_seeded",
                    module="main",
                    plugin="openbiliclaw-builtin",
                ).info("已注册系统内置插件 openbiliclaw-builtin")

            # 注册 user-profile-builtin 系统内置插件（如不存在）
            # 该插件封装 ProfileExtractor/ProfileLifecycle/ProfileInjector，
            # 暴露画像提取/摘要/刷新/清理 4 个工具供 Agent 调用
            existing_user_profile = db.query(PluginModel).filter(
                PluginModel.name == "user-profile-builtin"
            ).first()
            if not existing_user_profile:
                new_user_profile = PluginModel(
                    id=str(uuid.uuid4()),
                    name="user-profile-builtin",
                    version="1.0.0",
                    enabled=True,
                    config={},
                    category="builtin",
                    author="Open-AwA Team",
                    source="builtin",
                    is_uninstallable=False,
                    dependencies=[],
                )
                db.add(new_user_profile)
                db.commit()
                logger.bind(
                    event="builtin_plugin_seeded",
                    module="main",
                    plugin="user-profile-builtin",
                ).info("已注册系统内置插件 user-profile-builtin")
        except Exception as exc:
            logger.bind(event="builtin_plugin_seed_error", module="main").warning(f"内置插件注册失败: {exc}")
            db.rollback()
        finally:
            db.close()

        pm = plugin_instance.get()
        # 导入内置插件依赖缺失异常，用于在加载循环中单独捕获
        from plugins.openbiliclaw_builtin.plugin import BuiltinPluginDependencyError
        db = SessionLocal()
        try:
            enabled_plugins = db.query(PluginModel).filter(PluginModel.enabled == True).all()
            for p in enabled_plugins:
                if p.name in pm.plugin_metadata:
                    try:
                        # 同步插件加载（importlib + 初始化）包装为 to_thread，避免阻塞事件循环
                        await asyncio.to_thread(pm.load_plugin, p.name)
                        logger.bind(event="plugin_loaded", module="main", plugin=p.name).info(
                            f"plugin loaded: {p.name}"
                        )
                        # 内置插件不需要权限审批，跳过 restore_plugin_permissions
                        if p.source == "builtin":
                            # 检查内置插件是否以 loaded_with_warnings 状态加载
                            loaded_instance = pm.loaded_plugins.get(p.name)
                            if loaded_instance is not None and hasattr(
                                loaded_instance, "get_dependency_warnings"
                            ):
                                warnings_list = loaded_instance.get_dependency_warnings()
                                if warnings_list:
                                    logger.bind(
                                        event="plugin_loaded_with_warnings",
                                        module="main",
                                        plugin=p.name,
                                        warning_count=len(warnings_list),
                                    ).info(
                                        f"内置插件 {p.name} 以 loaded_with_warnings 状态加载，"
                                        f"warnings={len(warnings_list)}"
                                    )
                        else:
                            granted = p.granted_permissions or []
                            if granted:
                                pm.restore_plugin_permissions(p.name, granted)
                    except BuiltinPluginDependencyError as dep_exc:
                        # 内置插件依赖缺失：仅记录 WARNING，不阻塞启动
                        logger.bind(
                            event="builtin_plugin_dependency_missing",
                            module="main",
                            plugin=p.name,
                            missing_packages=dep_exc.missing_packages,
                        ).warning(
                            f"内置插件 {p.name} 依赖缺失，跳过加载: "
                            f"missing_packages={dep_exc.missing_packages}"
                        )
                    except Exception as exc:
                        logger.bind(event="plugin_load_error", module="main", plugin=p.name).warning(
                            f"plugin load failed: {exc}"
                        )
            logger.bind(event="plugins_initialized", module="main", count=len(pm.loaded_plugins)).info(
                "plugin system initialized"
            )
        finally:
            db.close()


async def _startup_background_tasks(profiler: StartupProfiler) -> None:
    """后台任务初始化：定时任务管理器、微信自动回复。"""
    from db.models import SessionLocal

    with profiler.step("scheduled_task_start"):
        await scheduled_task_manager.start()

    if os.getenv("SKIP_INIT_DB"):
        return

    with profiler.step("weixin_auto_reply"):
        from db.models import WeixinBinding
        from api.services.weixin_auto_reply import get_auto_reply_manager
        db = SessionLocal()
        try:
            # 同步 DB 查询包装为 to_thread，避免阻塞事件循环
            def _query_bindings():
                return db.query(WeixinBinding).filter(
                    WeixinBinding.binding_status == "bound",
                    WeixinBinding.auto_start_reply == True
                ).all()
            bindings = await asyncio.to_thread(_query_bindings)
            if bindings:
                manager = get_auto_reply_manager()
                for binding in bindings:
                    try:
                        await manager.start(binding.user_id)
                        logger.bind(event="weixin_auto_reply_autostart", module="main", user_id=binding.user_id).info("自动启动微信自动回复")
                    except ValueError as e:
                        logger.bind(event="weixin_auto_reply_autostart_failed", module="main", user_id=binding.user_id).warning(f"自动启动微信自动回复失败（配置错误）: {e}")
                    except Exception as e:
                        logger.bind(event="weixin_auto_reply_autostart_error", module="main", user_id=binding.user_id).error(f"自动启动微信自动回复异常: {e}")
        finally:
            db.close()


async def _startup_autonomous_mode(profiler: StartupProfiler) -> None:
    """初始化自主运行模式（仅通过 .env 配置）。"""
    try:
        from core.autonomous import init_autonomous_mode, get_autonomous_manager
        manager = init_autonomous_mode()
        if manager:
            profiler.record("autonomous_mode")
            logger.warning("自主运行模式已激活 - 安全注意事项见 docs/superpowers/specs/")
    except Exception:
        logger.bind(event="autonomous_init_failed", module="main").error(
            "自主运行模式初始化失败，请检查 .env 配置"
        )
        raise


async def _startup_acp_service(profiler: StartupProfiler) -> None:
    """初始化 ACP (Agent Client Protocol) 服务。

    扫描 acp_host.agents.discover_agents() 返回的所有内置 agent 配置，
    为每个 agent 调用 init_acp_service 注册 ACPService 实例到模块级单例注册表。
    实际的 ACP 子进程会话在首次 prompt 时通过 ACPService.run_turn 创建。
    启动失败时仅记录日志，不阻塞主流程（acp SDK 未安装时也走降级路径）。
    """
    with profiler.step("acp_service_init"):
        try:
            from acp_host import init_acp_service
            from acp_host.core import ACPConfig
            from acp_host.agents import discover_agents

            agents = discover_agents()
            if not agents:
                logger.bind(event="acp_no_agents", module="startup").warning(
                    "未发现任何 ACP agent 配置，跳过 ACP 服务初始化"
                )
                return
            acp_config = ACPConfig(agents=agents)
            for agent_id in acp_config.agents.keys():
                init_acp_service(agent_id, acp_config)
            logger.bind(
                event="acp_services_initialized",
                module="startup",
                agent_count=len(agents),
                agents=list(agents.keys()),
            ).info(f"ACP 服务已初始化 {len(agents)} 个 agent")
        except Exception as exc:
            # acp SDK 缺失或 agent 配置加载失败时仅记录日志，不阻塞启动
            logger.bind(
                event="acp_init_failed",
                module="startup",
                error_type=type(exc).__name__,
                error_message=str(exc),
            ).warning(f"ACP 服务初始化失败（不阻塞启动）: {exc}")


async def _shutdown_acp_service() -> None:
    """关闭 ACP 服务，清理所有已注册的 ACPService 实例。

    遍历 discover_agents() 返回的 agent_id 调用 close_acp_service。
    单个 agent 关闭失败不影响其他 agent 的清理。
    """
    try:
        from acp_host import close_acp_service
        from acp_host.agents import discover_agents

        agents = discover_agents()
        for agent_id in agents.keys():
            try:
                close_acp_service(agent_id)
            except Exception as exc:
                logger.warning(f"关闭 ACP agent '{agent_id}' 失败: {exc}")
        logger.bind(event="acp_services_closed", module="shutdown").info("ACP 服务已关闭")
    except Exception as exc:
        logger.warning(f"ACP 服务关闭异常: {exc}")


def _startup_mcp_sse_origin(profiler: StartupProfiler) -> None:
    """配置 MCP SSE 传输层的 origin 白名单。

    通过环境变量 MCP_SSE_ALLOWED_ORIGINS（逗号分隔）配置允许的 origin 列表，
    防止跨域攻击。未配置时记录 WARNING 日志提示安全风险，并保持白名单为空
    （SSETransport 在白名单为空时允许所有 origin，仅适用于开发环境）。
    """
    with profiler.step("mcp_sse_origin_config"):
        from mcp.transport import SSETransport

        raw_origins = os.getenv("MCP_SSE_ALLOWED_ORIGINS", "")
        origins = [item.strip() for item in raw_origins.split(",") if item.strip()]
        SSETransport.set_allowed_origins(origins)
        if origins:
            logger.bind(
                event="mcp_sse_origin_configured",
                module="main",
                origin_count=len(origins),
            ).info(
                f"MCP SSE origin 白名单已配置，共 {len(origins)} 个 origin"
            )
        else:
            logger.bind(
                event="mcp_sse_origin_not_configured",
                module="main",
            ).warning(
                "未配置 MCP_SSE_ALLOWED_ORIGINS 环境变量，MCP SSE 传输将允许所有 origin。"
                "生产环境必须显式配置白名单以防止跨域攻击。"
            )


async def _shutdown_autonomous_mode() -> None:
    """关闭自主模式管理器。"""
    try:
        from core.autonomous import get_autonomous_manager
        manager = get_autonomous_manager()
        if manager:
            await manager.shutdown()
    except Exception as e:
        logger.warning(f"自主模式关闭异常: {e}")


async def _shutdown_data_collector() -> None:
    """关闭数据收集器。"""
    try:
        from data.collector import data_collector
        await data_collector.stop()
    except Exception as e:
        logger.bind(event="data_collector_stop_error", module="shutdown").warning(f"数据收集器关闭失败: {e}")


async def lifespan(app: FastAPI):
    """
    管理应用启动与关闭阶段的全局生命周期。
    启动步骤已拆分为四个独立函数：基础设施 → 数据初始化 → 插件系统 → 后台任务。
    每步失败有独立日志和错误上下文，便于排障。
    """
    logger.bind(event="app_startup", module="main").info("starting up openawa")

    profiler = StartupProfiler()
    profiler.start()

    try:
        await _startup_infrastructure(profiler)
        await _startup_data_init(profiler)
        await _startup_plugin_system(profiler)
        await _startup_background_tasks(profiler)
        # 17. 自主运行模式初始化（在所有其他初始化之后）
        await _startup_autonomous_mode(profiler)
        # 18. ACP 服务初始化（数据库初始化之后，按 agent 注册 ACPService 实例）
        await _startup_acp_service(profiler)
        # 19. 初始化数据收集器
        try:
            from data.collector import data_collector
            await data_collector.start()
            logger.bind(event="data_collector_initialized", module="startup").info("数据收集器已初始化")
        except Exception as e:
            logger.bind(event="data_collector_init_error", module="startup").warning(f"数据收集器初始化失败: {e}")
        # 20. 配置 MCP SSE 传输层 origin 白名单
        _startup_mcp_sse_origin(profiler)
    except Exception:
        logger.bind(event="app_startup_failed", module="main").error("启动过程发生异常，服务将终止")
        raise

    profiler.finish()

    yield
    # 关闭流程：每个步骤独立 try/except，确保一个失败不影响其他步骤
    shutdown_errors: list[str] = []
    for step_name, step_fn in (
        ("autonomous_mode", _shutdown_autonomous_mode),
        ("acp_service", _shutdown_acp_service),
        ("data_collector", _shutdown_data_collector),
        ("scheduled_task_manager", scheduled_task_manager.stop),
        ("shared_http_client", close_shared_client),
    ):
        try:
            await step_fn()
        except Exception as exc:
            shutdown_errors.append(f"{step_name}: {exc}")
            logger.bind(event="shutdown_error", module="main", step=step_name).error(
                f"关闭步骤 {step_name} 失败: {exc}"
            )
    if shutdown_errors:
        logger.bind(event="shutdown_errors", module="main", errors=shutdown_errors).warning(
            f"关闭过程中 {len(shutdown_errors)} 个步骤失败"
        )
    logger.bind(event="app_shutdown", module="main").info("shutting down openawa")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI Agent Framework - Similar to OpenClaw",
    lifespan=lifespan,
)

# CSRF 保护 — per-session 签名 token 模式
# 参考: Django CSRF 中间件 https://github.com/django/django/blob/main/django/middleware/csrf.py
_CSRF_HEADER_NAME = "X-CSRF-Token"
# 不需要 CSRF 校验的路径前缀（公开只读接口）
_CSRF_EXEMPT_PATHS = {"/api/auth/login", "/api/logs/client-errors", "/api/auth/csrf-token"}
# 需要 CSRF 校验的请求方法
_CSRF_CHECKED_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

# CSRF 签名密钥由 security._derive_csrf_signing_key() 从 SECRET_KEY 派生
# 确保多 Worker 部署时签名一致（不再使用进程级随机密钥）


async def _extract_user_id_from_request(request: Request) -> Optional[str]:
    """
    从请求中提取认证用户 ID（用于 CSRF 校验时与 token 中绑定的用户比对）。

    优先从 JWT payload 的 uid 字段直接读取（高效路径），
    其次回退到通过 username 查 DB 的兼容路径（支持旧版不含 uid 的令牌）。

    User.id 为字符串类型，所有路径统一返回 str 或 None。
    不会抛出异常，解析失败返回 None。
    """
    from config.security import decode_access_token, ACCESS_TOKEN_COOKIE_NAME

    token: Optional[str] = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME, "")
    if not token:
        return None

    payload = decode_access_token(token)
    if payload is None:
        return None

    # 优先从 JWT payload 直接读取 uid（高效路径，User.id 为字符串类型）
    uid = payload.get("uid")
    if isinstance(uid, str) and uid:
        return uid

    # 兼容旧版令牌：通过 username 查 DB（降级路径）
    username = payload.get("sub")
    if not isinstance(username, str):
        return None

    try:
        import asyncio
        from api.dependencies import _load_user_by_username

        user = await asyncio.to_thread(_load_user_by_username, username)
        return user.id if user else None
    except Exception as e:
        logger.warning("通过用户名查询用户失败（兼容旧版令牌降级路径）: {0}", e)
        return None


@app.get("/api/auth/csrf-token")
async def get_csrf_token(request: Request):
    """
    返回当前用户会话的 CSRF token（需认证）。

    前端在登录后调用此接口获取 per-session CSRF token，
    存储在 JS 内存中，在状态变更请求时通过 X-CSRF-Token header 发送。
    """
    user_id = await _extract_user_id_from_request(request)
    if user_id is None:
        raise FastAPIHTTPException(status_code=401, detail="Authentication required")
    csrf_token = generate_csrf_token(user_id)
    return {"csrf_token": csrf_token}


@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    """
    Per-session 签名 Token 模式的 CSRF 保护中间件。

    对 POST/PUT/DELETE/PATCH 请求校验 X-CSRF-Token header：
    1. 验证 token 签名和有效期
    2. 提取 token 中绑定的 user_id
    3. 与请求中认证用户的 user_id 比对，确保一一对应

    Bearer token 认证的请求自动跳过 CSRF 校验（CSRF 仅对 Cookie 认证有意义）。
    WebSocket 连接和豁免路径跳过校验。
    """
    path = request.url.path
    method = request.method

    # WebSocket 连接跳过 CSRF 校验（通过 token query 参数认证）
    if "websocket" in path.lower() or request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    # 测试环境跳过 CSRF 校验（仅通过 pytest conftest 设置的专用环境变量开启）
    if os.getenv("SKIP_CSRF_FOR_TEST", "").lower() == "true":
        return await call_next(request)

    # 对 Bearer token 认证的请求进行 CSRF 豁免判断：
    # 安全策略：仅当请求未携带任何 Cookie 时才豁免 CSRF 校验。
    # 原因：CSRF 攻击依赖浏览器自动携带 Cookie，若请求无 Cookie，则 CSRF 无攻击面。
    # 不再尝试通过格式检测区分 JWT / API Key（旧的 JWT 格式检测可被构造绕过，
    # 例如构造 3 段含非 base64 字符的 Bearer token 即可被判定为 "API Key" 而绕过 CSRF）。
    # 若请求同时携带 Cookie（可能存在基于 Cookie 的会话），即使有 Bearer header 也继续校验 CSRF。
    auth_header = request.headers.get("Authorization", "")
    has_cookie = bool(request.headers.get("cookie", ""))
    if auth_header.startswith("Bearer ") and not has_cookie:
        # 纯 Bearer 认证（无 Cookie），CSRF 无攻击面，豁免校验
        return await call_next(request)
    # 其余情况（无 Authorization、或同时携带 Cookie）继续走下面的 CSRF 校验流程

    if method in _CSRF_CHECKED_METHODS and path not in _CSRF_EXEMPT_PATHS:
        header_token = request.headers.get(_CSRF_HEADER_NAME, "")
        if not header_token:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "missing_csrf_token",
                    "message": "缺少 CSRF token",
                    "detail": "Missing X-CSRF-Token header",
                },
            )

        # 验证 CSRF token 签名和有效期
        csrf_payload = verify_csrf_token(header_token)
        if csrf_payload is None:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "invalid_csrf_token",
                    "message": "CSRF token 无效或已过期",
                    "detail": "CSRF token verification failed",
                },
            )

        # 提取请求中的认证用户 ID 并与 CSRF token 中绑定的用户比对
        request_user_id = await _extract_user_id_from_request(request)
        if request_user_id is None or request_user_id != csrf_payload["sub"]:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "csrf_user_mismatch",
                    "message": "CSRF token 与当前用户不匹配",
                    "detail": "CSRF token user mismatch",
                },
            )

    response = await call_next(request)
    return response


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """
    为每个 HTTP 请求建立统一的请求上下文与链路追踪信息。
    中间件会生成或继承请求 ID、写入请求状态与日志上下文、在响应头回传请求 ID，并记录请求开始、结束与异常日志。
    """
    incoming_request_id = request.headers.get(REQUEST_ID_HEADER, "")
    incoming_client_version = request.headers.get(CLIENT_VERSION_HEADER, "")
    request_id = str(incoming_request_id or generate_request_id()).strip() or generate_request_id()
    version_status = negotiate_version_status(incoming_client_version, settings.VERSION)
    set_request_id(request_id)
    request.state.request_id = request_id
    request.state.client_version = incoming_client_version
    request.state.version_status = version_status

    path = request.url.path
    method = request.method

    logger.bind(
        event="http_request_started",
        module="api",
        request_id=request_id,
        http_method=method,
        path=path,
    ).debug("request started")

    start_time = time.monotonic()

    try:
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[SERVER_VERSION_HEADER] = settings.VERSION
        response.headers[VERSION_STATUS_HEADER] = version_status
        if incoming_client_version:
            response.headers[CLIENT_VERSION_HEADER] = incoming_client_version
        logger.bind(
            event="http_request_completed",
            module="api",
            request_id=request_id,
            http_method=method,
            path=path,
            status=response.status_code,
            duration_ms=duration_ms,
        ).info(f"{method} {path} -> {response.status_code} ({duration_ms}ms) rid={request_id}")
        return response
    except Exception as exc:
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        logger.bind(
            event="http_request_failed",
            module="api",
            request_id=request_id,
            http_method=method,
            path=path,
            error_type=type(exc).__name__,
            error_message=sanitize_for_logging(str(exc)),
            duration_ms=duration_ms,
        ).exception("request failed")
        raise
    finally:
        clear_request_id()


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    """
    将显式 HTTP 异常统一包装为带错误码与 request_id 的结构。
    """

    request_id = getattr(request.state, "request_id", "") or generate_request_id()
    error = build_standard_error(
        code=f"http_{exc.status_code}",
        message=str(exc.detail),
        request_id=request_id,
        status_code=exc.status_code,
        retryable=exc.status_code >= 500,
    )
    response = JSONResponse(status_code=exc.status_code, content={"error": error})
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers[SERVER_VERSION_HEADER] = settings.VERSION
    response.headers[VERSION_STATUS_HEADER] = getattr(request.state, "version_status", "server_only")
    client_version = getattr(request.state, "client_version", "")
    if client_version:
        response.headers[CLIENT_VERSION_HEADER] = client_version
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    处理unhandled、exception、handler相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    request_id = getattr(request.state, "request_id", "") or generate_request_id()
    logger.bind(
        event="unhandled_exception",
        module="api",
        request_id=request_id,
        http_method=request.method,
        path=request.url.path,
        error_type=type(exc).__name__,
        error_message=sanitize_for_logging(str(exc)),
    ).exception("unhandled exception")

    error = build_standard_error(
        code="internal_server_error",
        message="Internal server error",
        request_id=request_id,
        status_code=500,
        retryable=False,
    )
    response = JSONResponse(
        status_code=500,
        content={"error": error},
    )
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers[SERVER_VERSION_HEADER] = settings.VERSION
    response.headers[VERSION_STATUS_HEADER] = getattr(request.state, "version_status", "server_only")
    client_version = getattr(request.state, "client_version", "")
    if client_version:
        response.headers[CLIENT_VERSION_HEADER] = client_version
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOW_LAN_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER, CLIENT_VERSION_HEADER, _CSRF_HEADER_NAME],
)

# Content-Security-Policy 中间件 — 添加安全头防止 XSS 和数据注入攻击
# 预生成 CSP 字符串缓存，避免每个请求重新拼接字符串（性能优化）
def _build_csp_header() -> str:
    """根据 DEBUG_MODE 构建 CSP 头字符串，启动时调用一次缓存。"""
    _debug = os.getenv("DEBUG_MODE", "").lower() == "true"
    style_src = "'self' 'unsafe-inline' https://fonts.googleapis.com" if _debug else "'self' https://fonts.googleapis.com"
    return (
        "default-src 'self'; "
        f"script-src 'self'; "
        f"style-src {style_src}; "
        "font-src 'self' https://fonts.gstatic.com; "
        # img-src 收敛：移除 https: 通配，仅允许同源 + data:（base64 内联）+ blob:（运行时生成）
        # 外部图片需经后端代理走域名白名单，避免任意 HTTPS 站点加载引入追踪/XSS 攻击面
        "img-src 'self' data: blob:; "
        # 仅允许同源与本地回环 WebSocket，禁止页面连接任意 ws/wss 源
        # 保留 ws://localhost:* 与 ws://127.0.0.1:* 用于 Vite HMR 与本地 PTY/预览服务
        "connect-src 'self' ws://localhost:* ws://127.0.0.1:* wss://localhost:* wss://127.0.0.1:*; "
        "frame-src 'self'; "
        "frame-ancestors 'self'; "
        "worker-src 'self'; "
        "child-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


_CSP_HEADER_VALUE = _build_csp_header()

# 预生成额外安全响应头缓存（与 CSP 一样在启动时构建一次）
# 这些头是 OWASP 推荐的最低安全基线，防御点击劫持/MIME 嗅探/Referer 泄露等
_DEBUG_MODE_FOR_HEADERS = os.getenv("DEBUG_MODE", "").lower() == "true"
_SECURITY_HEADERS: dict = {
    "X-Content-Type-Options": "nosniff",  # 禁止浏览器 MIME 嗅探
    "X-Frame-Options": "DENY",  # 禁止页面被嵌入 iframe（防点击劫持，CSP frame-ancestors 的旧浏览器后备）
    "Referrer-Policy": "strict-origin-when-cross-origin",  # 跨域请求仅发送 origin，不泄露完整 URL
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",  # 禁用敏感浏览器 API
}
# HSTS 仅在生产 TLS 环境启用（开发环境 http 会导致浏览器标记不安全）
if not _DEBUG_MODE_FOR_HEADERS:
    _SECURITY_HEADERS["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


@app.middleware("http")
async def _add_csp_header(request: Request, call_next):
    """
    为所有响应添加 Content-Security-Policy 头与其他安全响应头。
    CSP 作为 XSS 攻击的第二道防线，在默认 React 转义基础上提供额外保护。
    script-src 禁止 unsafe-inline，通过 Trusted Types + nonce 方案防御 XSS。
    style-src 在调试模式下保留 unsafe-inline 以兼容 React 热更新样式注入。

    性能：CSP 字符串在启动时预生成并缓存，避免每个请求重复拼接。
    """
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _CSP_HEADER_VALUE
    for key, value in _SECURITY_HEADERS.items():
        response.headers[key] = value
    return response

# Rate Limiting 配置
# 使用代理感知的 key_func，仅当请求来自受信代理时才信任 X-Forwarded-For / X-Real-IP 头，
# 防止客户端伪造代理头绕过速率限制。
_TRUSTED_PROXY_NETWORKS: list = []
try:
    import ipaddress as _ipaddress_mod
    _raw_proxies = str(settings.TRUSTED_PROXIES or "").strip()
    if _raw_proxies:
        for _entry in _raw_proxies.split(","):
            _entry = _entry.strip()
            if _entry:
                try:
                    _TRUSTED_PROXY_NETWORKS.append(_ipaddress_mod.ip_network(_entry, strict=False))
                except ValueError:
                    logger.bind(event="invalid_trusted_proxy", module="main", entry=_entry).warning(
                        f"无效的受信代理条目，已跳过: {_entry}"
                    )
except ImportError:
    pass


def _get_client_ip(request: Request) -> str:
    """从请求中提取真实客户端 IP。
    仅当直连 IP 属于受信代理时，才读取 X-Forwarded-For / X-Real-IP 头；
    否则直接返回直连 IP，防止客户端伪造代理头绕过速率限制。
    """
    # 获取直连 IP（反向代理场景下为代理 IP）
    direct_ip = get_remote_address(request)
    if not _TRUSTED_PROXY_NETWORKS:
        return direct_ip

    try:
        _addr = _ipaddress_mod.ip_address(direct_ip)
        _trusted = any(_addr in _net for _net in _TRUSTED_PROXY_NETWORKS)
    except (ValueError, TypeError):
        _trusted = False

    if not _trusted:
        return direct_ip

    # 受信代理：从 X-Forwarded-For 获取客户端真实 IP
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    # 其次使用 X-Real-IP
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip()
    return direct_ip

limiter = Limiter(key_func=_get_client_ip, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(chat.router, prefix=settings.API_V1_STR)
# 微信相关路由已合并至 skills 路由模块中（/skills/weixin/*）
app.include_router(skills.router, prefix=settings.API_V1_STR)
app.include_router(plugins.router, prefix=settings.API_V1_STR)
app.include_router(memory.router, prefix=settings.API_V1_STR)
app.include_router(workflows.router, prefix=settings.API_V1_STR)
app.include_router(scheduled_tasks.router, prefix=settings.API_V1_STR)
app.include_router(soul.router)
app.include_router(diary_router, prefix=settings.API_V1_STR)
app.include_router(prompts.router, prefix=settings.API_V1_STR)
app.include_router(behavior.router, prefix=settings.API_V1_STR)
app.include_router(experiences.router, prefix=settings.API_V1_STR)
app.include_router(experience_files.router, prefix=settings.API_V1_STR)
app.include_router(conversation.router, prefix=settings.API_V1_STR)
app.include_router(logs.router, prefix=settings.API_V1_STR)
app.include_router(mcp.router)
app.include_router(models.router)
app.include_router(billing.router)
app.include_router(marketplace_router)
app.include_router(security_router)
app.include_router(security_enhanced_router)
app.include_router(cot_audit_router)
app.include_router(weixin_router)
app.include_router(tools_router)
app.include_router(subagents_router)
app.include_router(task_runtime_router)
app.include_router(user_router, prefix=settings.API_V1_STR)
app.include_router(user_profile_router, prefix=settings.API_V1_STR)
app.include_router(system_router)
app.include_router(test_runner_router)
app.include_router(workspace_router)
app.include_router(heartbeat_router)
app.include_router(coding_router)
app.include_router(inbox_router)
app.include_router(magic_commands_router, prefix=settings.API_V1_STR)
app.include_router(tts_router)
app.include_router(tasks_router)
app.include_router(roles_router, prefix=settings.API_V1_STR)
app.include_router(role_market_router, prefix=settings.API_V1_STR)
app.include_router(data_router, prefix=settings.API_V1_STR)
app.include_router(terminal_router, prefix=settings.API_V1_STR)
app.include_router(im_router, prefix=settings.API_V1_STR)
# ACP 路由前缀已内置在 router 定义中（/api/acp），无需 settings.API_V1_STR 前缀
app.include_router(acp_router)
# 本地开发服务器反向代理，前缀 /api/preview 已内置在 router 定义中
app.include_router(preview_proxy_router)
# 通知 HTTP API，前缀 /api/notifications 已内置在 router 定义中
app.include_router(notifications_router)
# [NEW] Task 3: 多 Agent 讨论任务路由，前缀 /api/discussions 已内置在 router 定义中
app.include_router(discussions.router)
app.include_router(search_config.router)  # [NEW] Task 9: 搜索配置路由
# [NOTE] Task 3 SubTask 3.9: DiscussionOrchestrator 未提供独立的 init() 方法，
# 三个角色（critic/validator/approver）的 system prompt 已由 core/discussion/roles.py
# 静态定义，orchestrator 在 run_discussion_round 中按顺序调用 build_role_messages
# 构建 messages，无需在 lifespan 中显式注册内置角色 Agent。
# Orchestrator 单例由 api/routes/discussions.py 的 _get_orchestrator() 懒加载初始化。

# 用户头像静态文件目录
# 安全：原使用 StaticFiles 挂载允许任意访问 /api/user/avatar/<任意文件名>，
# 攻击者可枚举其他用户头像文件名（{user_id}_{timestamp}.ext）下载他人头像。
# 改为自定义认证路由，校验文件名归属后才返回内容。
from pathlib import Path as FsPath
_avatars_dir = FsPath("uploads/avatars")
_avatars_dir.mkdir(parents=True, exist_ok=True)


@app.get("/api/user/avatar/{filename}")
async def serve_user_avatar(
    filename: str,
    current_user=Depends(get_current_user),
):
    """
    安全：返回当前用户自己的头像文件。
    - 校验 filename 必须以 "{current_user.id}_" 开头，防止跨用户读取他人头像
    - 路径穿越防护：解析后必须仍在 _avatars_dir 内
    - 仅返回 jpg/png 图片文件
    """
    from fastapi.responses import FileResponse, JSONResponse

    # 文件名基础校验：不允许路径分隔符、空字节等
    if not filename or "/" in filename or "\\" in filename or "\x00" in filename:
        return JSONResponse({"detail": "非法文件名"}, status_code=400)

    # 归属校验：文件名必须以 "{current_user.id}_" 开头
    expected_prefix = f"{current_user.id}_"
    if not filename.startswith(expected_prefix):
        # 越权访问他人头像，统一返回 404 避免泄露存在性
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    # 后缀白名单
    lower_name = filename.lower()
    if not (lower_name.endswith(".jpg") or lower_name.endswith(".jpeg") or lower_name.endswith(".png")):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    # 路径穿越防护：解析后必须仍在 _avatars_dir 内
    target_path = (_avatars_dir / filename).resolve()
    try:
        target_path.relative_to(_avatars_dir.resolve())
    except ValueError:
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    if not target_path.is_file():
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    # 根据扩展名确定 MIME
    if lower_name.endswith(".png"):
        media_type = "image/png"
    else:
        media_type = "image/jpeg"
    return FileResponse(str(target_path), media_type=media_type)

# ---- 前端静态文件服务（生产模式）----
_project_root = FsPath(__file__).resolve().parent.parent
_FRONTEND_DIST = _project_root / "frontend" / "dist"
_HAS_FRONTEND = _FRONTEND_DIST.is_dir() and (_FRONTEND_DIST / "index.html").exists()

if _HAS_FRONTEND and is_production_environment(settings.ENVIRONMENT):
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="frontend_assets")

    @app.get("/{full_path:path}")
    async def serve_frontend_spa(full_path: str, request: Request):
        """
        SPA 回退路由：非 API 路径返回 index.html。
        """
        if full_path.startswith("api/") or full_path.startswith("ws/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index_path = _FRONTEND_DIST / "index.html"
        if not index_path.exists():
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Frontend not built"}, status_code=503)
        from fastapi.responses import FileResponse
        return FileResponse(str(index_path), media_type="text/html")


# 静态资源缓存策略：为带哈希的文件名设置长期缓存
@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    # 带哈希的静态资源（JS/CSS/字体/图片）设置 1 年缓存
    if any(ext in path for ext in ('.js', '.css', '.woff', '.woff2', '.ttf', '.png', '.jpg', '.svg', '.ico')):
        # Vite/Rollup 输出的文件名包含哈希（如 index-a1b2c3d4.js），可安全长期缓存
        if any(c.isdigit() for c in path.split('/')[-1].split('.')[0][-8:]):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@app.get("/")
async def root():
    """
    根路径健康探活端点，返回项目名称、版本和运行状态。
    """
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """
    轻量级健康检查端点，无需认证。用于负载均衡器和监控系统的存活探测。
    """
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics(current_user = Depends(get_current_user)):
    """
    导出简易 Prometheus 指标，便于基础观测与排障。
    需要认证访问，防止运行指标、请求量和错误统计被未授权获取。
    """

    return PlainTextResponse(
        prometheus_registry.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/api/endpoints")
async def list_endpoints(request: Request, current_user=Depends(get_current_user)):
    """
    服务发现端点，返回后端所有可用服务入口清单。

    供多端客户端（Web/移动端/桌面端）在连接前动态获取服务拓扑，
    包括 WebSocket、SSE、REST 端点路径与特性开关。
    安全：完整服务拓扑会暴露内部 API 结构，攻击者可据此规划针对性攻击，
    因此仅允许已认证的管理员用户访问，普通用户无法获取该清单。
    """
    # 仅管理员可查看完整 API 拓扑，防止未授权用户枚举服务入口
    if current_user.role != "admin":
        raise FastAPIHTTPException(status_code=403, detail="仅管理员可查看 API 拓扑")

    scheme = request.url.scheme
    host = request.url.netloc
    ws_scheme = "wss" if scheme == "https" else "ws"
    api_prefix = settings.API_V1_STR

    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "base_url": f"{scheme}://{host}",
        "ws_base_url": f"{ws_scheme}://{host}",
        "api_prefix": api_prefix,
        "endpoints": {
            "websocket": [
                {
                    "path": f"{api_prefix}/chat/ws/{{session_id}}",
                    "auth": "query:token",
                    "desc": "聊天会话实时通讯，支持同会话多设备同步",
                },
                {
                    "path": f"{api_prefix}/weixin/ws",
                    "auth": "query:token",
                    "desc": "微信消息实时推送",
                },
                {
                    "path": f"{api_prefix}/terminal/ws/{{session_id}}",
                    "auth": "query:token",
                    "desc": "终端会话 WebSocket",
                },
            ],
            "sse": [
                {
                    "path": f"{api_prefix}/security/permissions/stream",
                    "auth": "query:api_key",
                    "desc": "权限请求 SSE 推流，支持同用户多设备订阅",
                },
            ],
            "rest": [
                {"prefix": f"{api_prefix}/auth", "desc": "认证与会话"},
                {"prefix": f"{api_prefix}/chat", "desc": "聊天与会话历史"},
                {"prefix": f"{api_prefix}/conversation", "desc": "会话管理"},
                {"prefix": f"{api_prefix}/memory", "desc": "记忆管理"},
                {"prefix": f"{api_prefix}/skills", "desc": "技能引擎"},
                {"prefix": f"{api_prefix}/plugins", "desc": "插件系统"},
                {"prefix": f"{api_prefix}/im", "desc": "IM 渠道管理"},
                {"prefix": f"{api_prefix}/billing", "desc": "计费与用量"},
                {"prefix": f"{api_prefix}/user", "desc": "用户与个人资料"},
                {"prefix": f"{api_prefix}/roles", "desc": "角色管理"},
                {"prefix": f"{api_prefix}/tasks", "desc": "任务管理"},
                {"prefix": f"{api_prefix}/tts", "desc": "语音合成"},
            ],
        },
        "features": {
            "lan_access": ALLOW_LAN_ORIGIN_REGEX is not None,
            "ssl": settings.is_ssl_enabled(),
            "multi_device_sync": True,
        },
    }


def get_server_host() -> str:
    """
    读取后端服务监听主机配置。
    优先使用环境变量中的 BACKEND_HOST，其次兼容 HOST，未配置时回退到默认值。
    """
    return (os.getenv("BACKEND_HOST") or os.getenv("HOST") or "0.0.0.0").strip() or "0.0.0.0"


def get_server_port() -> int:
    """
    读取后端服务监听端口配置。
    优先使用环境变量中的 BACKEND_PORT，其次兼容 PORT，未配置时回退到默认值。
    如果端口值不是合法整数，则抛出带明确信息的异常，便于快速排查配置问题。
    """
    raw_port = (os.getenv("BACKEND_PORT") or os.getenv("PORT") or "8000").strip() or "8000"
    try:
        return int(raw_port)
    except ValueError as exc:
        raise ValueError(f"无效的端口配置: {raw_port}") from exc


def _run_uvicorn_server(uvicorn_module, host: str, port: int, debug_mode: bool = False) -> None:
    """
    统一封装 uvicorn.run 调用。
    真实启动时保留默认日志参数，测试中的精简桩函数也能兼容。
    当 settings 中配置了 SSL 证书和私钥时自动启用 HTTPS。
    """
    run_kwargs = {
        "host": host,
        "port": port,
        "access_log": debug_mode,
        "log_level": "debug" if debug_mode else "warning",
        # WebSocket 消息大小上限 1MB，防止恶意客户端发送超大帧导致内存耗尽 DoS
        "ws_max_size": 1024 * 1024,
    }

    # HTTPS 配置：证书和私钥同时存在时自动启用 TLS
    if settings.is_ssl_enabled():
        run_kwargs["ssl_certfile"] = settings.SSL_CERTFILE
        run_kwargs["ssl_keyfile"] = settings.SSL_KEYFILE
        if settings.SSL_KEYFILE_PASSWORD:
            run_kwargs["ssl_keyfile_password"] = settings.SSL_KEYFILE_PASSWORD
        if settings.SSL_CA_CERTS:
            run_kwargs["ssl_ca_certs"] = settings.SSL_CA_CERTS

    # uvicorn 的热重载依赖导入字符串形式的 app 目标，直接传入 app 对象时无法启用 reload。
    # 这里在调试模式下切换为模块导入路径，便于通过修改 DEBUG_MODE 快速开启本地调试体验。
    app_target = "main:app" if debug_mode else app
    if debug_mode:
        run_kwargs["reload"] = True

    try:
        signature = inspect.signature(uvicorn_module.run)
    except (TypeError, ValueError):
        signature = None

    if signature is not None:
        has_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if not has_var_kwargs:
            run_kwargs = {
                key: value
                for key, value in run_kwargs.items()
                if key in signature.parameters
            }

    uvicorn_module.run(app_target, **run_kwargs)


def run_server(debug_mode: bool = False) -> None:
    """
    启动后端 HTTP 服务并处理常见启动异常。
    发生端口占用时输出更友好的提示，帮助调用方快速定位冲突端口或调整配置。
    """
    import uvicorn

    host = get_server_host()
    port = get_server_port()
    logger.bind(
        event="server_starting",
        module="main",
        host=host,
        port=port,
        debug_mode=debug_mode,
        use_tls=settings.is_ssl_enabled(),
    ).info("starting backend server")
    try:
        _run_uvicorn_server(uvicorn, host, port, debug_mode=debug_mode)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            message = f"后端服务启动失败：端口 {port} 已被占用，请关闭占用进程或通过 BACKEND_PORT/PORT 更换端口后重试。"
            logger.bind(event="server_bind_conflict", module="main", host=host, port=port).error(message)
            raise RuntimeError(message) from exc
        raise


if __name__ == "__main__":
    # 调试模式仅通过环境变量显式开启，生产环境默认关闭。
    # 设置 DEBUG_MODE=true 可启用 uvicorn reload/access_log 与调试级日志。
    DEBUG_MODE = os.getenv("DEBUG_MODE", "").lower() == "true"
    if DEBUG_MODE:
        logger.bind(event="debug_mode_enabled", module="main").warning("调试模式已开启，生产环境请确保 DEBUG_MODE 未设置")
    run_server(debug_mode=DEBUG_MODE)
