"""add user_profiles persistence fields and profile_extraction_state table

Revision ID: add_user_profiles_and_extraction_state
Revises: add_pricing_cache_fields
Create Date: 2026-07-10 00:01:00

本迁移为 SoulEngine 用户画像持久化层奠定数据基础：
1. 为 user_profiles 表新增 profile_json（OnionProfile 序列化文本）与 version（版本号）字段
2. 创建 profile_extraction_state 表（每用户单行提取状态：计数器/阈值/probe_flags）
3. 清空 profile_facts 表（PRD 要求重建，旧事实将基于新画像结构重新提取）

幂等性说明：通过 inspect 检查列/表存在性，确保多次执行不会报错。
"""
from alembic import op
import sqlalchemy as sa


# Alembic 修订标识符
revision = "add_user_profiles_and_extraction_state"
down_revision = "add_pricing_cache_fields"
branch_labels = None
depends_on = None


def _has_table(bind, table_name: str) -> bool:
    """检查指定表名是否已存在。"""
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(bind, table_name: str, column_name: str) -> bool:
    """检查指定表是否已包含指定列。"""
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
    return column_name in existing_columns


def upgrade() -> None:
    """
    正向迁移：
    1. 为 user_profiles 表追加 profile_json / version 字段（带 server_default 保证旧记录回填）
    2. 创建 profile_extraction_state 表
    3. 清空 profile_facts 表（重建画像事实）
    """
    bind = op.get_bind()

    # 1. user_profiles 表追加 profile_json 字段（OnionProfile JSON 文本主存储）
    if not _has_column(bind, "user_profiles", "profile_json"):
        op.add_column(
            "user_profiles",
            sa.Column(
                "profile_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            ),
        )

    # 2. user_profiles 表追加 version 字段（乐观锁/缓存失效依据）
    if not _has_column(bind, "user_profiles", "version"):
        op.add_column(
            "user_profiles",
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )

    # 3. 创建 profile_extraction_state 表（每用户单行提取状态记录）
    if not _has_table(bind, "profile_extraction_state"):
        op.create_table(
            "profile_extraction_state",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.String(length=64),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "turns_since_last_extract",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "n_threshold",
                sa.Integer(),
                nullable=False,
                server_default="5",
            ),
            sa.Column("last_extracted_at", sa.DateTime(), nullable=True),
            sa.Column(
                "probe_flags",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        op.create_index(
            "ix_profile_extraction_state_user_id",
            "profile_extraction_state",
            ["user_id"],
            unique=True,
        )

    # 4. 清空 profile_facts 表（PRD 要求：画像结构变更后重建事实）
    # 注意：仅删除数据，不删除表结构；后续提取会基于新 OnionProfile 重新填充
    if _has_table(bind, "profile_facts"):
        op.execute("DELETE FROM profile_facts")


def downgrade() -> None:
    """
    回滚：
    1. 删除 profile_extraction_state 表
    2. 移除 user_profiles 表的 version / profile_json 字段
    3. profile_facts 数据无法回滚（已 DELETE），保持表结构不变

    注意：downgrade 不会恢复 profile_facts 中的历史数据，请谨慎执行。
    """
    bind = op.get_bind()

    # 1. 删除 profile_extraction_state 表
    if _has_table(bind, "profile_extraction_state"):
        op.drop_index(
            "ix_profile_extraction_state_user_id",
            table_name="profile_extraction_state",
        )
        op.drop_table("profile_extraction_state")

    # 2. 移除 user_profiles 表的 version 字段
    if _has_column(bind, "user_profiles", "version"):
        op.drop_column("user_profiles", "version")

    # 3. 移除 user_profiles 表的 profile_json 字段
    if _has_column(bind, "user_profiles", "profile_json"):
        op.drop_column("user_profiles", "profile_json")
