"""add consolidation tables

Revision ID: add_consolidation_tables
Revises: add_long_term_memory_quality_fields
Create Date: 2026-07-24 13:00:00

本迁移为 spec memory-quality-and-short-term-recovery 阶段 7 的数据库 schema 扩展：
新增两张表支撑记忆巩固运行器的增量读取与指纹跳过能力：

1. consolidation_state: 每用户一行水位线状态
   - last_short_term_memory_id: 上次巩固处理到的短期记忆 ID
   - last_run_at: 上次巩固运行时间
   - conversation_count_since_run: 自上次巩固以来的对话轮次计数
   - last_error: 上次失败原因（便于诊断）

2. consolidation_fingerprints: 已处理短期记忆的指纹记录
   - fingerprint: 短期记忆内容指纹（SHA-256 截断），用于跳过重复处理
   - short_term_memory_id: 关联短期记忆 ID
   - consolidated_memory_id: 巩固生成的长期记忆 ID（可空）

设计借鉴：
- OpenBiliClaw 的 CognitionCycle watermark 增量读取
- openhanako 的 fingerprint 跳过 + 断点续跑 Set
"""
from alembic import op
import sqlalchemy as sa


# Alembic 修订标识符
revision = "add_consolidation_tables"
down_revision = "add_long_term_memory_quality_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """正向迁移：创建 consolidation_state 与 consolidation_fingerprints 两张表。"""
    # 1. 巩固水位线状态表（每用户一行）
    op.create_table(
        "consolidation_state",
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("workspace_id", sa.String(length=50), nullable=True),
        sa.Column("last_short_term_memory_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("conversation_count_since_run", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_consolidation_state_workspace_id",
        "consolidation_state",
        ["workspace_id"],
    )

    # 2. 巩固指纹记录表
    op.create_table(
        "consolidation_fingerprints",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("workspace_id", sa.String(length=50), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("short_term_memory_id", sa.Integer(), nullable=False),
        sa.Column("consolidated_memory_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_consolidation_fingerprints_user_id",
        "consolidation_fingerprints",
        ["user_id"],
    )
    op.create_index(
        "ix_consolidation_fingerprints_workspace_id",
        "consolidation_fingerprints",
        ["workspace_id"],
    )
    op.create_index(
        "ix_consolidation_fingerprints_fingerprint",
        "consolidation_fingerprints",
        ["fingerprint"],
    )
    op.create_index(
        "ix_consolidation_fingerprints_short_term_memory_id",
        "consolidation_fingerprints",
        ["short_term_memory_id"],
    )
    op.create_index(
        "ix_consolidation_fingerprints_created_at",
        "consolidation_fingerprints",
        ["created_at"],
    )
    # 复合索引：按用户查询指纹 + 按用户查询短期记忆 ID
    op.create_index(
        "ix_cf_user_fp",
        "consolidation_fingerprints",
        ["user_id", "fingerprint"],
    )
    op.create_index(
        "ix_cf_user_stm",
        "consolidation_fingerprints",
        ["user_id", "short_term_memory_id"],
    )


def downgrade() -> None:
    """回滚迁移：按相反顺序删除索引与表。"""
    op.drop_index("ix_cf_user_stm", table_name="consolidation_fingerprints")
    op.drop_index("ix_cf_user_fp", table_name="consolidation_fingerprints")
    op.drop_index(
        "ix_consolidation_fingerprints_created_at",
        table_name="consolidation_fingerprints",
    )
    op.drop_index(
        "ix_consolidation_fingerprints_short_term_memory_id",
        table_name="consolidation_fingerprints",
    )
    op.drop_index(
        "ix_consolidation_fingerprints_fingerprint",
        table_name="consolidation_fingerprints",
    )
    op.drop_index(
        "ix_consolidation_fingerprints_workspace_id",
        table_name="consolidation_fingerprints",
    )
    op.drop_index(
        "ix_consolidation_fingerprints_user_id",
        table_name="consolidation_fingerprints",
    )
    op.drop_table("consolidation_fingerprints")

    op.drop_index(
        "ix_consolidation_state_workspace_id",
        table_name="consolidation_state",
    )
    op.drop_table("consolidation_state")
