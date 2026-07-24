"""add long term memory quality fields

Revision ID: add_long_term_memory_quality_fields
Revises: add_bilibili_toolkit_tables
Create Date: 2026-07-24 12:00:00

本迁移为 spec memory-quality-and-short-term-recovery 阶段 8 的数据库 schema 扩展：
为 long_term_memory 表添加 3 个字段，承载记忆质量与状态机能力：

1. state: 四状态机 active/validated/archived/deprecated
   - active: 新写入的初始状态
   - validated: 用户通过探针确认后晋升，confidence 提升至 0.9
   - archived: 长期未访问或低质量，不再注入 LLM 上下文但仍可检索
   - deprecated: 用户主动遗忘，不再被检索返回，数据保留用于审计
2. similarity_hash: 内容去重指纹（SHA-256 截断 32 字符），用于快速判断完全相同内容是否已写入
3. extracted_from: 来源短期记忆 ID 列表（JSON），供 consolidation_runner 追溯来源链路

字段与现有 archive_status 并行存在（archive_status 保留向后兼容），新增 state 作为
状态机的权威字段；similarity_hash 与 extracted_from 此前存在 memory_metadata JSON 中，
本次提升为独立列以支持索引查询与高效过滤。

已有数据 state 默认 'active'，similarity_hash / extracted_from 由后台任务回填。
"""
from alembic import op
import sqlalchemy as sa


# Alembic 修订标识符
revision = "add_long_term_memory_quality_fields"
down_revision = "add_bilibili_toolkit_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """正向迁移：为 long_term_memory 表添加 state / similarity_hash / extracted_from 三字段。"""
    # 1. 四状态机字段：active/validated/archived/deprecated
    # 默认 'active'，已有数据通过 server_default 自动填充
    op.add_column(
        "long_term_memory",
        sa.Column(
            "state",
            sa.String(length=20),
            nullable=False,
            server_default="active",
            comment="状态机：active/validated/archived/deprecated",
        ),
    )
    op.create_index("ix_ltm_state", "long_term_memory", ["state"])

    # 2. 去重指纹字段： nullable，已有数据由后台任务回填
    op.add_column(
        "long_term_memory",
        sa.Column(
            "similarity_hash",
            sa.String(length=64),
            nullable=True,
            comment="内容去重指纹",
        ),
    )
    op.create_index("ix_ltm_similarity_hash", "long_term_memory", ["similarity_hash"])

    # 3. 来源短期记忆 ID 列表：JSON 字段，nullable
    op.add_column(
        "long_term_memory",
        sa.Column(
            "extracted_from",
            sa.JSON(),
            nullable=True,
            comment="来源短期记忆 ID 列表",
        ),
    )


def downgrade() -> None:
    """回滚迁移：按相反顺序移除字段与索引。"""
    op.drop_column("long_term_memory", "extracted_from")
    op.drop_index("ix_ltm_similarity_hash", table_name="long_term_memory")
    op.drop_column("long_term_memory", "similarity_hash")
    op.drop_index("ix_ltm_state", table_name="long_term_memory")
    op.drop_column("long_term_memory", "state")
