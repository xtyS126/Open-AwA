"""
Alembic 迁移环境配置。
从 db.models 导入 Base metadata，支持自动生成迁移脚本。
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 添加 backend 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Alembic Config 对象
config = context.config

# 从环境变量或 alembic.ini 读取数据库 URL
database_url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
config.set_main_option("sqlalchemy.url", database_url)

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 导入所有模型，确保 Base.metadata 包含所有表
from db.models import Base  # noqa: E402
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    离线模式迁移 — 生成 SQL 而不连接数据库。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式迁移 — 连接数据库并执行迁移。
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
