"""
数据库基础设施模块：声明式基类、引擎、会话工厂、事件监听与初始化入口。

本模块只承载 SQLAlchemy 引擎层与 Base 声明式基类，不包含任何业务模型定义。
业务模型按域拆分到 user.py / conversation.py / skill.py / plugin.py / task.py /
security.py / billing.py / wechat.py / workspace.py 子模块中，统一继承本模块的 Base。
运行时数据库 schema 迁移逻辑（_migrate_xxx 系列）拆分到 migrations.py。
"""

import time
from typing import Any

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config.settings import settings


# ---- 引擎与会话工厂 ----

# SQLite 连接参数：禁用 check_same_thread 以支持 FastAPI 异步多线程，
# 同时设置 busy_timeout 减少 database is locked 错误
_sqlite_connect_args: dict[str, Any] = {}
if "sqlite" in settings.DATABASE_URL:
    _sqlite_connect_args = {
        "check_same_thread": False,
        # WAL 模式提升并发读写性能；busy_timeout 减少 database is locked 错误
        "timeout": 30,
    }

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_sqlite_connect_args,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=3600,
    # SQLite 需要 WAL 模式在引擎级别设置（PRAGMA journal_mode=WAL）
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---- SQLite 连接 PRAGMA 事件 ----
# 使用 'checkout' 事件确保每次从连接池获取时都设置 PRAGMA
# （'connect' 仅在新连接创建时触发，连接池复用时会被跳过）
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine, "checkout")
    def _setup_sqlite_connection(dbapi_connection, connection_record, connection_proxy):
        """确保每次 checkout 的连接都启用 WAL、外键约束和繁忙超时。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# ---- 慢查询与错误事件监听 ----
# 慢查询阈值从 settings 读取，支持不同部署环境调优
_SLOW_QUERY_THRESHOLD_MS = settings.SLOW_QUERY_THRESHOLD_MS


@event.listens_for(engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """在 SQL 执行前记录起始时间"""
    conn.info.setdefault("query_start_time", []).append(time.perf_counter())


@event.listens_for(engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """SQL 执行完成后检测慢查询"""
    start_times = conn.info.get("query_start_time")
    if not start_times:
        return
    start = start_times.pop()
    duration_ms = int((time.perf_counter() - start) * 1000)
    if duration_ms >= _SLOW_QUERY_THRESHOLD_MS:
        logger.bind(
            event="slow_query",
            module="db",
            duration_ms=duration_ms,
        ).warning(f"慢查询 ({duration_ms}ms): {statement[:200]}")


@event.listens_for(engine, "handle_error")
def _handle_db_error(exception_context):
    """数据库层面异常捕获"""
    logger.bind(
        event="db_engine_error",
        module="db",
        error_type=type(exception_context.original_exception).__name__,
    ).opt(exception=True).error(f"数据库引擎错误: {exception_context.original_exception}")


# ---- 声明式基类 ----
class Base(DeclarativeBase):
    """
    SQLAlchemy 声明式基类，所有 ORM 模型的公共父类。
    业务模型按域拆分到子模块，统一继承本类，共享同一套 Metadata。
    """
    pass


# ---- 会话依赖 ----
def get_db():
    """
    获取db相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。

    注意：SessionLocal 与 logger 通过 db.models 命名空间动态查找，
    便于测试通过 monkeypatch 替换 db.models.SessionLocal / db.models.logger。
    """
    # 延迟引用 db.models 命名空间的 SessionLocal 与 logger，
    # 便于测试通过 monkeypatch 替换 db.models.SessionLocal / db.models.logger
    import db.models as _models
    _SessionLocal = _models.SessionLocal
    _logger = _models.logger

    db = _SessionLocal()
    try:
        yield db
    except HTTPException as e:
        # 鉴权拒绝（401/403）：正常的请求级拒绝，不应误记为错误
        if e.status_code in {401, 403}:
            _logger.bind(
                event="db_session_http_exception",
                module="db",
                status_code=e.status_code,
                error_type=type(e).__name__,
            ).info(f"数据库会话提前结束（鉴权拒绝）: {e.detail}")
        elif e.status_code >= 500:
            # 服务端错误：应引起关注
            _logger.bind(
                event="db_session_http_exception",
                module="db",
                status_code=e.status_code,
                error_type=type(e).__name__,
            ).error(f"数据库会话提前结束（服务端错误）: {e.detail}")
        else:
            _logger.bind(
                event="db_session_http_exception",
                module="db",
                status_code=e.status_code,
                error_type=type(e).__name__,
            ).warning(f"数据库会话提前结束（HTTP 异常）: {e.detail}")
        db.rollback()
        raise
    except (KeyboardInterrupt, SystemExit):
        # 系统信号：不回滚，让进程正常退出
        db.close()
        raise
    except Exception as e:
        _logger.bind(
            event="db_session_error",
            module="db",
            error_type=type(e).__name__,
        ).opt(exception=True).error(f"数据库会话异常: {e}")
        db.rollback()
        raise
    finally:
        if db.is_active:
            db.close()


# ---- 索引补齐 ----
def _ensure_missing_indexes(use_engine=None):
    """
    为已有表幂等补充索引。

    背景：Base.metadata.create_all 仅在创建新表时应用 index=True 标记，
    对已存在的表不会自动追加索引。这里通过 CREATE INDEX IF NOT EXISTS
    为高频查询字段补充索引，避免全表扫描。

    覆盖场景：
    - audit_logs.created_at：审计日志按时间范围查询
    - conversation_data.role_id / tool_call_data.role_id / execution_trace.role_id：
      按角色聚合分析对话与工具调用数据
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = set(inspector.get_table_names())

    # (表名, 索引名, 列名) 三元组列表
    pending_indexes: list[tuple[str, str, str]] = []
    if "audit_logs" in table_names:
        pending_indexes.append(("audit_logs", "ix_audit_logs_created_at", "created_at"))
    if "conversation_data" in table_names:
        pending_indexes.append(("conversation_data", "ix_conversation_data_role_id", "role_id"))
    if "tool_call_data" in table_names:
        pending_indexes.append(("tool_call_data", "ix_tool_call_data_role_id", "role_id"))
    if "execution_trace" in table_names:
        pending_indexes.append(("execution_trace", "ix_execution_trace_role_id", "role_id"))

    if not pending_indexes:
        return

    with target_engine.begin() as conn:
        for table_name, index_name, column_name in pending_indexes:
            # 检查索引是否已存在，避免重复创建报错
            existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
            if index_name in existing_indexes:
                continue
            try:
                # SQLite/PostgreSQL 均支持 IF NOT EXISTS 语法
                conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})")
                )
                logger.info(f"已为表 {table_name} 创建索引 {index_name} ({column_name})")
            except Exception as exc:
                # 索引创建失败不应阻塞启动，记录警告后继续
                logger.warning(f"创建索引 {index_name} 失败: {exc}")


# ---- 初始化入口 ----
def init_db(bind_engine=None):
    """
    初始化数据库表结构并执行必要的迁移操作。
    支持自定义 engine，便于测试环境使用独立数据库。

    迁移函数定义在 db.models.migrations，此处延迟导入避免循环依赖
    （migrations 内部需要引用各域模型类，而各域模型类继承 base.Base）。
    """
    from db.models import migrations as _migrations

    use_engine = bind_engine or engine
    # 计费模型已统一使用 db.models.Base，与主业务模型共享同一 Metadata
    Base.metadata.create_all(bind=use_engine)
    _migrations._migrate_workbench_tables(use_engine=use_engine)
    _migrations._migrate_conversation_record_metadata_column(use_engine=use_engine)
    _migrations._migrate_conversation_record_sidechain_columns(use_engine=use_engine)
    _migrations._migrate_plugin_columns(use_engine=use_engine)
    _migrations._migrate_long_term_memory_user_id(use_engine=use_engine)
    _migrations._migrate_long_term_memory_enhancements(use_engine=use_engine)
    _migrations._migrate_audit_log_columns(use_engine=use_engine)
    _migrations._migrate_skill_json_columns(use_engine=use_engine)
    _migrations._migrate_conversation_columns(use_engine=use_engine)
    _migrations._migrate_user_profile_columns(use_engine=use_engine)
    _migrations._migrate_task_runtime_columns(use_engine=use_engine)
    _migrations._migrate_scheduled_task_daily_columns(use_engine=use_engine)
    _migrations._migrate_short_term_memory_rich_fields(use_engine=use_engine)
    _migrations._migrate_workspace_columns(use_engine=use_engine)
    _migrations._migrate_profile_facts_table(use_engine=use_engine)
    _migrations._migrate_user_role_fk(use_engine=use_engine)
    _migrations._migrate_model_configuration_new_params(use_engine=use_engine)
    _migrations._migrate_permission_saved(use_engine=use_engine)
    # Agent 角色与数据收集相关迁移
    _inspector = inspect(use_engine)
    with use_engine.begin() as _conn:
        _migrations._migrate_agent_roles(_inspector, _conn)
        _migrations._migrate_conversation_data(_inspector, _conn)
        _migrations._migrate_tool_call_data(_inspector, _conn)
        _migrations._migrate_execution_trace(_inspector, _conn)
        _migrations._migrate_role_switch_event(_inspector, _conn)
        _migrations._migrate_user_feedback_add_columns(_inspector, _conn)
        _migrations._migrate_agent_role_is_companion(_inspector, _conn)
    # 索引补齐：为高频查询字段补充索引（幂等，已存在则跳过）
    _ensure_missing_indexes(use_engine=use_engine)
