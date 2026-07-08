"""
数据库 schema 迁移函数集合。

本模块集中存放 init_db 在启动时调用的 15+ 个 _migrate_xxx 函数，
用于为旧版本数据库补齐缺失的列、索引与表。迁移逻辑幂等，可重复执行。

设计说明：
- 迁移函数内部引用各域模型类（如 ProfileFact、Conversation 等），
  通过顶部 import 静态绑定；这些模型在模块加载时已完成 Base 注册，
  不会与 base.py 形成循环依赖（base.py 仅在 init_db 函数体内延迟导入本模块）。
- 项目已引入 Alembic 治理（见 backend/alembic/），但生产 init_db 仍依赖
  本模块的幂等迁移以保证旧库平滑升级。新增 schema 变更应同时落 Alembic revision
  与本模块的兜底迁移，直到全量切流到 Alembic 后再移除对应 _migrate_xxx。
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict

import yaml
from loguru import logger
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from db.models.base import engine
from db.models.conversation import Conversation, ConversationRecord, ShortTermMemory
from db.models.user import ProfileExtractionLog, ProfileFact


def _migrate_profile_facts_table(use_engine=None):
    """
    迁移：创建 profile_facts 和 profile_extraction_logs 表（如不存在）。
    支持传入自定义 engine，确保迁移操作落到正确数据库。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    with target_engine.begin() as connection:
        if "profile_facts" not in table_names:
            ProfileFact.__table__.create(target_engine)
            logger.info("已创建 profile_facts 表")
        if "profile_extraction_logs" not in table_names:
            ProfileExtractionLog.__table__.create(target_engine)
            logger.info("已创建 profile_extraction_logs 表")


def _migrate_conversation_record_metadata_column(use_engine=None):
    """
    迁移 conversation_records 表的 metadata 列到 record_metadata 列。
    支持传入自定义 engine，确保在测试或多库场景下迁移操作落到正确数据库。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "conversation_records" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("conversation_records")}
    with target_engine.begin() as connection:
        if "record_metadata" not in columns and "metadata" in columns:
            connection.execute(text("ALTER TABLE conversation_records RENAME COLUMN metadata TO record_metadata"))
            logger.info("Migrated conversation_records.metadata column to record_metadata")
        elif "record_metadata" in columns and "metadata" in columns:
            connection.execute(
                text(
                    "UPDATE conversation_records "
                    "SET record_metadata = COALESCE(record_metadata, metadata)"
                )
            )
            logger.info("Merged data from conversation_records.metadata into record_metadata")


def _migrate_plugin_columns(use_engine=None):
    """
    迁移 plugins 表，补齐缺失的列。
    支持传入自定义 engine，确保迁移操作落到正确数据库。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "plugins" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("plugins")}
    with target_engine.begin() as connection:
        if "category" not in columns:
            connection.execute(text("ALTER TABLE plugins ADD COLUMN category VARCHAR DEFAULT 'general'"))
        if "author" not in columns:
            connection.execute(text("ALTER TABLE plugins ADD COLUMN author VARCHAR DEFAULT ''"))
        if "source" not in columns:
            connection.execute(text("ALTER TABLE plugins ADD COLUMN source VARCHAR DEFAULT ''"))
        if "dependencies" not in columns:
            connection.execute(text("ALTER TABLE plugins ADD COLUMN dependencies TEXT DEFAULT ''"))
        if "installed_at" not in columns:
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(text("ALTER TABLE plugins ADD COLUMN installed_at DATETIME"))
            connection.execute(text("UPDATE plugins SET installed_at = :installed_at WHERE installed_at IS NULL"), {"installed_at": now})
        if "granted_permissions" not in columns:
            connection.execute(text("ALTER TABLE plugins ADD COLUMN granted_permissions TEXT DEFAULT '[]'"))
        if "is_uninstallable" not in columns:
            # 补齐 is_uninstallable 列：标识内置插件不可卸载（与 Plugin.is_uninstallable 模型字段对齐）
            # 旧数据库缺该列时，main.py startup 查询 PluginModel 会抛 OperationalError
            connection.execute(text("ALTER TABLE plugins ADD COLUMN is_uninstallable BOOLEAN DEFAULT 0 NOT NULL"))
            logger.bind(event="plugin_column_added", module="db", column="is_uninstallable").info(
                "已为 plugins 表补齐 is_uninstallable 列"
            )


def _migrate_long_term_memory_user_id(use_engine=None):
    """
    为 long_term_memory 表补齐 user_id 列，实现多租户隔离。
    支持传入自定义 engine，确保迁移操作落到正确数据库。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "long_term_memory" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("long_term_memory")}
    if "user_id" not in columns:
        with target_engine.begin() as connection:
            connection.execute(text("ALTER TABLE long_term_memory ADD COLUMN user_id VARCHAR"))
            logger.info("Migrated long_term_memory: added user_id column for multi-tenant isolation")


def _migrate_long_term_memory_enhancements(use_engine=None):
    """
    为长期记忆补齐质量评估、归档和元数据字段，支持增强记忆工作流。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "long_term_memory" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("long_term_memory")}
    with target_engine.begin() as connection:
        if "confidence" not in columns:
            connection.execute(text("ALTER TABLE long_term_memory ADD COLUMN confidence FLOAT DEFAULT 0.5"))
            connection.execute(text("UPDATE long_term_memory SET confidence = 0.5 WHERE confidence IS NULL"))
        if "quality_score" not in columns:
            connection.execute(text("ALTER TABLE long_term_memory ADD COLUMN quality_score FLOAT DEFAULT 0.0"))
            connection.execute(text("UPDATE long_term_memory SET quality_score = 0.0 WHERE quality_score IS NULL"))
        if "archive_status" not in columns:
            connection.execute(text("ALTER TABLE long_term_memory ADD COLUMN archive_status VARCHAR(50) DEFAULT 'active'"))
            connection.execute(text("UPDATE long_term_memory SET archive_status = 'active' WHERE archive_status IS NULL OR archive_status = ''"))
        if "memory_metadata" not in columns:
            connection.execute(text("ALTER TABLE long_term_memory ADD COLUMN memory_metadata TEXT DEFAULT '{}'"))
            connection.execute(text("UPDATE long_term_memory SET memory_metadata = '{}' WHERE memory_metadata IS NULL OR memory_metadata = ''"))


def _migrate_audit_log_columns(use_engine=None):
    """
    为 audit_logs 表补齐 details、ip_address、created_at 列，
    同时将旧的 timestamp 列数据迁移到 created_at。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "audit_logs" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("audit_logs")}
    with target_engine.begin() as connection:
        if "details" not in columns:
            connection.execute(text("ALTER TABLE audit_logs ADD COLUMN details TEXT"))
        if "ip_address" not in columns:
            connection.execute(text("ALTER TABLE audit_logs ADD COLUMN ip_address VARCHAR(50)"))
        if "created_at" not in columns:
            connection.execute(text("ALTER TABLE audit_logs ADD COLUMN created_at DATETIME"))
            if "timestamp" in columns:
                connection.execute(text("UPDATE audit_logs SET created_at = timestamp WHERE created_at IS NULL"))
            logger.info("Migrated audit_logs: added created_at column")


def _normalize_legacy_json_column_value(raw_value: Any, expected_type: type, default_value: Any) -> str:
    """
    将历史遗留的 JSON 文本、YAML 文本或空值统一转换为合法 JSON 字符串。
    skills 表在早期版本中曾直接存储 YAML，若继续按 JSON 列读取会在 ORM 阶段报错。
    """
    def _dump_json(value: Any) -> str:
        """
        统一 JSON 序列化策略。
        历史 YAML 中可能含有 date/datetime 等 Python 标量，这里转成字符串以保证迁移可落库。
        """
        return json.dumps(value, ensure_ascii=False, default=str)

    if raw_value is None:
        return _dump_json(default_value)
    if isinstance(raw_value, expected_type):
        return _dump_json(raw_value)

    text_value = str(raw_value).strip()
    if not text_value:
        return json.dumps(default_value, ensure_ascii=False)

    try:
        loaded = json.loads(text_value)
    except Exception:
        loaded = None
    if isinstance(loaded, expected_type):
        return _dump_json(loaded)

    try:
        loaded = yaml.safe_load(text_value)
    except Exception:
        loaded = None
    if isinstance(loaded, expected_type):
        return _dump_json(loaded)

    return _dump_json(default_value)


def _migrate_skill_json_columns(use_engine=None):
    """
    将 skills 表中的历史 YAML/文本配置迁移为合法 JSON，避免 ORM 读取时抛出 JSONDecodeError。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "skills" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("skills")}
    required_columns = {"id", "config", "tags", "dependencies"}
    if not required_columns.issubset(columns):
        return

    with target_engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id, config, tags, dependencies FROM skills")
        ).mappings().all()
        for row in rows:
            normalized_config = _normalize_legacy_json_column_value(
                row.get("config"),
                dict,
                {},
            )
            normalized_tags = _normalize_legacy_json_column_value(
                row.get("tags"),
                list,
                [],
            )
            normalized_dependencies = _normalize_legacy_json_column_value(
                row.get("dependencies"),
                list,
                [],
            )
            connection.execute(
                text(
                    "UPDATE skills "
                    "SET config = :config, tags = :tags, dependencies = :dependencies "
                    "WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "config": normalized_config,
                    "tags": normalized_tags,
                    "dependencies": normalized_dependencies,
                },
            )


def _migrate_conversation_record_sidechain_columns(use_engine=None):
    """
    为 conversation_records 表补齐旁路链相关字段：uuid、parent_uuid、is_sidechain。
    这些字段用于 JSONL 旁路日志与数据库记录的关联，以及子 Agent 旁路链回溯。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "conversation_records" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("conversation_records")}
    with target_engine.begin() as connection:
        if "uuid" not in columns:
            connection.execute(text("ALTER TABLE conversation_records ADD COLUMN uuid VARCHAR"))
        if "parent_uuid" not in columns:
            connection.execute(text("ALTER TABLE conversation_records ADD COLUMN parent_uuid VARCHAR"))
        if "is_sidechain" not in columns:
            connection.execute(text("ALTER TABLE conversation_records ADD COLUMN is_sidechain BOOLEAN DEFAULT 0"))
            connection.execute(text("UPDATE conversation_records SET is_sidechain = 0 WHERE is_sidechain IS NULL"))


def _migrate_conversation_columns(use_engine=None):
    """
    为 conversations 表补齐会话聚合所需字段，并从历史记录中回填缺失会话。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "conversations" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("conversations")}
    with target_engine.begin() as connection:
        if "summary" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN summary TEXT DEFAULT ''"))
        if "last_message_preview" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN last_message_preview TEXT DEFAULT ''"))
        if "last_message_role" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN last_message_role VARCHAR(20)"))
        if "message_count" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN message_count INTEGER DEFAULT 0"))
            connection.execute(text("UPDATE conversations SET message_count = 0 WHERE message_count IS NULL"))
        if "created_at" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN created_at DATETIME"))
            connection.execute(text("UPDATE conversations SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        if "updated_at" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN updated_at DATETIME"))
            connection.execute(text("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
        if "last_message_at" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN last_message_at DATETIME"))
        if "deleted_at" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN deleted_at DATETIME"))
        if "restored_at" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN restored_at DATETIME"))
        if "purge_after" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN purge_after DATETIME"))
        if "conversation_metadata" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN conversation_metadata TEXT DEFAULT '{}'"))
            connection.execute(
                text(
                    "UPDATE conversations "
                    "SET conversation_metadata = '{}' "
                    "WHERE conversation_metadata IS NULL OR conversation_metadata = ''"
                )
            )

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=target_engine)
    db = session_factory()
    try:
        existing_session_ids = {
            session_id
            for session_id, in db.query(Conversation.session_id).all()
        }
        latest_records = (
            db.query(ConversationRecord)
            .order_by(ConversationRecord.timestamp.asc())
            .all()
        )
        pending_rows: Dict[str, Conversation] = {}
        for record in latest_records:
            if record.session_id in existing_session_ids:
                continue
            preview = (record.user_message or "").strip()
            title = preview.splitlines()[0][:80] if preview else "新对话"
            conversation = pending_rows.get(record.session_id)
            if conversation is None:
                conversation = Conversation(
                    session_id=record.session_id,
                    user_id=record.user_id,
                    title=title or "新对话",
                    summary=preview[:200],
                    last_message_preview=preview[:500],
                    last_message_role="user",
                    message_count=0,
                    created_at=record.timestamp or datetime.now(timezone.utc),
                    updated_at=record.timestamp or datetime.now(timezone.utc),
                    last_message_at=record.timestamp,
                    conversation_metadata={},
                )
                pending_rows[record.session_id] = conversation
            else:
                conversation.last_message_preview = preview[:500]
                conversation.summary = preview[:200]
                conversation.last_message_at = record.timestamp
                conversation.updated_at = record.timestamp or conversation.updated_at

        if pending_rows:
            short_term_counts = {
                session_id: count
                for session_id, count in db.query(
                    ShortTermMemory.session_id,
                    text("COUNT(*)")
                ).group_by(ShortTermMemory.session_id).all()
            }
            for conversation in pending_rows.values():
                conversation.message_count = int(short_term_counts.get(conversation.session_id, 0))
                db.add(conversation)
            db.commit()
    finally:
        db.close()


def _migrate_user_profile_columns(use_engine=None):
    """
    为 users 表补齐用户画像相关字段（头像、昵称、邮箱、电话、画像数据）。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "users" not in table_names:
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    with target_engine.begin() as connection:
        if "avatar_url" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500)"))
        if "nickname" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN nickname VARCHAR(100)"))
        if "email" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(200)"))
        if "phone" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(50)"))
        if "profile_data" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN profile_data TEXT DEFAULT '{}'"))


def _migrate_task_runtime_columns(use_engine=None):
    """
    为 task runtime 相关表补齐历史缺失列，兼容旧版本地数据库。
    当前重点修复 task_items 缺失 started_at/completed_at 时导致任务创建失败的问题。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()

    if "task_items" in table_names:
        columns = {column["name"] for column in inspector.get_columns("task_items")}
        with target_engine.begin() as connection:
            if "started_at" not in columns:
                connection.execute(text("ALTER TABLE task_items ADD COLUMN started_at DATETIME"))
            if "completed_at" not in columns:
                connection.execute(text("ALTER TABLE task_items ADD COLUMN completed_at DATETIME"))


def _migrate_scheduled_task_daily_columns(use_engine=None):
    """
    为 scheduled_tasks 表补齐每日执行相关字段。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "scheduled_tasks" not in table_names:
        return
    columns = {column["name"] for column in inspector.get_columns("scheduled_tasks")}
    with target_engine.begin() as connection:
        if "is_daily" not in columns:
            connection.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN is_daily BOOLEAN DEFAULT 0"))
        if "cron_expression" not in columns:
            connection.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN cron_expression VARCHAR(100)"))
        if "weekdays" not in columns:
            connection.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN weekdays VARCHAR(50)"))
        if "daily_time" not in columns:
            connection.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN daily_time VARCHAR(10)"))


def _migrate_permission_saved(use_engine=None):
    """
    确保 permission_saved 表存在。
    通常由 init_db 开头的 create_all 统一创建，此处作为防御性兜底。
    仅创建 permission_saved 表，避免 create_all 引入不合预期的副作用。
    """
    # 延迟导入：避免与 db.permission_models 形成模块级循环依赖
    from db.permission_models import PermissionSaved

    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "permission_saved" not in table_names:
        PermissionSaved.__table__.create(bind=target_engine, checkfirst=True)
        logger.info("已创建 permission_saved 表用于持久化权限决策")


def _migrate_short_term_memory_rich_fields(use_engine=None):
    """
    为 short_term_memory 表补齐富文本字段：思维链内容和工具调用事件列表。
    用于在历史记录恢复时保留思维链和工具调用展示数据。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "short_term_memory" not in table_names:
        return
    columns = {column["name"] for column in inspector.get_columns("short_term_memory")}
    with target_engine.begin() as connection:
        if "reasoning_content" not in columns:
            connection.execute(text("ALTER TABLE short_term_memory ADD COLUMN reasoning_content TEXT"))
            logger.info("Migrated short_term_memory: added reasoning_content column")
        if "tool_events" not in columns:
            connection.execute(text("ALTER TABLE short_term_memory ADD COLUMN tool_events TEXT"))
            logger.info("Migrated short_term_memory: added tool_events column")


def _migrate_agent_roles(inspector, conn) -> None:
    """迁移：创建 agent_roles 表。"""
    if "agent_roles" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE agent_roles (
                id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT DEFAULT '',
                avatar_url VARCHAR(500) DEFAULT '',
                system_prompt TEXT NOT NULL,
                personality JSON DEFAULT '{}',
                expertise JSON DEFAULT '{}',
                knowledge_base_ids JSON DEFAULT '[]',
                allowed_tools JSON DEFAULT '[]',
                allowed_skills JSON DEFAULT '[]',
                model_config JSON DEFAULT '{}',
                creator_id INTEGER REFERENCES users(id),
                is_public BOOLEAN DEFAULT 0,
                usage_count INTEGER DEFAULT 0,
                is_preset BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))


def _migrate_conversation_data(inspector, conn) -> None:
    """迁移：创建 conversation_data 表。"""
    if "conversation_data" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE conversation_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id VARCHAR(64),
                role_id VARCHAR(64) DEFAULT '',
                user_message TEXT,
                assistant_message TEXT,
                tools_used JSON DEFAULT '[]',
                model_used VARCHAR(100) DEFAULT '',
                token_count JSON DEFAULT '{}',
                response_time_ms INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX ix_conversation_data_conversation_id ON conversation_data(conversation_id)"))
        conn.execute(text("CREATE INDEX ix_conversation_data_created_at ON conversation_data(created_at)"))


def _migrate_tool_call_data(inspector, conn) -> None:
    """迁移：创建 tool_call_data 表。"""
    if "tool_call_data" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE tool_call_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id VARCHAR(64),
                role_id VARCHAR(64) DEFAULT '',
                tool_name VARCHAR(100),
                tool_params JSON,
                result_summary TEXT DEFAULT '',
                success BOOLEAN,
                duration_ms INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX ix_tool_call_data_conversation_id ON tool_call_data(conversation_id)"))
        conn.execute(text("CREATE INDEX ix_tool_call_data_created_at ON tool_call_data(created_at)"))


def _migrate_execution_trace(inspector, conn) -> None:
    """迁移：创建 execution_trace 表。"""
    if "execution_trace" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE execution_trace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id VARCHAR(64),
                role_id VARCHAR(64) DEFAULT '',
                plan_steps JSON,
                executed_steps JSON,
                error_steps JSON DEFAULT '[]',
                retry_count INTEGER DEFAULT 0,
                rollback_count INTEGER DEFAULT 0,
                total_duration_ms INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX ix_execution_trace_conversation_id ON execution_trace(conversation_id)"))
        conn.execute(text("CREATE INDEX ix_execution_trace_created_at ON execution_trace(created_at)"))


def _migrate_role_switch_event(inspector, conn) -> None:
    """迁移：创建 role_switch_event 表。"""
    if "role_switch_event" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE role_switch_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_role_id VARCHAR(64) DEFAULT '',
                to_role_id VARCHAR(64),
                reason TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX ix_role_switch_event_created_at ON role_switch_event(created_at)"))


def _migrate_user_feedback_add_columns(inspector, conn) -> None:
    """迁移：为 user_feedback 表添加 conversation_id、role_id、feedback_type 列。"""
    columns = [col["name"] for col in inspector.get_columns("user_feedback")]
    if "conversation_id" not in columns:
        conn.execute(text("ALTER TABLE user_feedback ADD COLUMN conversation_id VARCHAR(64) DEFAULT ''"))
    if "role_id" not in columns:
        conn.execute(text("ALTER TABLE user_feedback ADD COLUMN role_id VARCHAR(64) DEFAULT ''"))
    if "feedback_type" not in columns:
        conn.execute(text("ALTER TABLE user_feedback ADD COLUMN feedback_type VARCHAR(20) DEFAULT ''"))


def _migrate_user_role_fk(use_engine=None):
    """
    清理 user_roles 中引用不存在角色的孤立记录，并确保新数据库包含外键约束。
    SQLite 不支持 ALTER TABLE ADD CONSTRAINT，因此仅在数据层面做完整性清理。
    外键约束在 Base.metadata.create_all() 创建新表时生效。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()

    if "user_roles" not in table_names or "roles" not in table_names:
        return

    with target_engine.begin() as connection:
        # 清理引用不存在角色的孤立记录
        result = connection.execute(
            text(
                "DELETE FROM user_roles WHERE role_name NOT IN "
                "(SELECT name FROM roles)"
            )
        )
        if result.rowcount > 0:
            logger.info(
                f"已清理 {result.rowcount} 条引用不存在角色的孤立 user_roles 记录"
            )


def _migrate_workspace_columns(use_engine=None):
    """
    为现有表补齐 workspace_id 列，支持多智能体工作区隔离。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()

    migrations = [
        ("short_term_memory", "workspace_id", "VARCHAR(50) DEFAULT 'default'"),
        ("long_term_memory", "workspace_id", "VARCHAR(50) DEFAULT 'default'"),
    ]

    for table_name, col_name, col_type in migrations:
        if table_name not in table_names:
            continue
        columns = {c["name"] for c in inspector.get_columns(table_name)}
        if col_name not in columns:
            with target_engine.begin() as connection:
                connection.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
                ))
                logger.info(f"Migrated {table_name}: added {col_name} column")


def _migrate_model_configuration_new_params(use_engine=None):
    """
    为 model_configurations 表补齐 frequency_penalty、presence_penalty、timeout、retry_count 字段，
    支持每个模型的独立参数配置。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "model_configurations" not in table_names:
        return

    columns = {c["name"] for c in inspector.get_columns("model_configurations")}
    # 需要新增的字段及类型
    new_columns = [
        ("frequency_penalty", "FLOAT"),
        ("presence_penalty", "FLOAT"),
        ("timeout", "INTEGER"),
        ("retry_count", "INTEGER"),
    ]
    with target_engine.begin() as connection:
        for col_name, col_type in new_columns:
            if col_name not in columns:
                connection.execute(text(
                    f"ALTER TABLE model_configurations ADD COLUMN {col_name} {col_type}"
                ))
                logger.info(f"Migrated model_configurations: added {col_name} column")
