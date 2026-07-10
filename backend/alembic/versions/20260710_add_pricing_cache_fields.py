"""add pricing cache and modality fields

Revision ID: add_pricing_cache_fields
Revises: add_discussion_search_builtin
Create Date: 2026-07-10 00:00:00

本迁移为 cherry-studio token 计费方案移植的基础 schema 扩展：
为 model_pricing 表新增缓存定价、多模态计费、模型元信息、能力与模态列表、
最大输出 token 数等 10 个字段，全部 nullable 以保证向后兼容。
"""
from alembic import op
import sqlalchemy as sa


# Alembic 修订标识符
revision = "add_pricing_cache_fields"
down_revision = "add_discussion_search_builtin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    正向迁移：为 model_pricing 表追加 10 个 nullable 字段。
    字段全部允许 NULL，旧记录无需回填即可完成迁移。
    """
    # 缓存读写 token 单价（USD/百万 token）
    op.add_column(
        "model_pricing",
        sa.Column("cache_read_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "model_pricing",
        sa.Column("cache_write_price", sa.Float(), nullable=True),
    )
    # 多模态计费：按图/按分钟单价
    op.add_column(
        "model_pricing",
        sa.Column("per_image_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "model_pricing",
        sa.Column("per_minute_price", sa.Float(), nullable=True),
    )
    # 模型元信息：所有方、模型族
    op.add_column(
        "model_pricing",
        sa.Column("owned_by", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "model_pricing",
        sa.Column("family", sa.String(length=64), nullable=True),
    )
    # 能力与模态列表（JSON 数组）
    op.add_column(
        "model_pricing",
        sa.Column("capabilities", sa.JSON(), nullable=True),
    )
    op.add_column(
        "model_pricing",
        sa.Column("input_modalities", sa.JSON(), nullable=True),
    )
    op.add_column(
        "model_pricing",
        sa.Column("output_modalities", sa.JSON(), nullable=True),
    )
    # 最大输出 token 数
    op.add_column(
        "model_pricing",
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """回滚：按 upgrade 相反顺序移除 10 个字段。"""
    op.drop_column("model_pricing", "max_output_tokens")
    op.drop_column("model_pricing", "output_modalities")
    op.drop_column("model_pricing", "input_modalities")
    op.drop_column("model_pricing", "capabilities")
    op.drop_column("model_pricing", "family")
    op.drop_column("model_pricing", "owned_by")
    op.drop_column("model_pricing", "per_minute_price")
    op.drop_column("model_pricing", "per_image_price")
    op.drop_column("model_pricing", "cache_write_price")
    op.drop_column("model_pricing", "cache_read_price")
