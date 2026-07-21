"""合并迁移分支并补齐模型定价旧字段。

Revision ID: merge_heads_add_pricing_legacy
Revises: add_weixin_media_assets, add_user_profiles_and_extraction_state
Create Date: 2026-07-22 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "merge_heads_add_pricing_legacy"
down_revision = ("add_weixin_media_assets", "add_user_profiles_and_extraction_state")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """通过版本化迁移补齐旧数据库缺少的模型能力字段。"""
    op.add_column(
        "model_pricing",
        sa.Column("supports_vision", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "model_pricing",
        sa.Column("is_multimodal", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("model_pricing", sa.Column("input_modality", sa.Text(), nullable=True))
    op.add_column("model_pricing", sa.Column("output_modality", sa.Text(), nullable=True))


def downgrade() -> None:
    """按相反顺序移除本迁移新增字段。"""
    op.drop_column("model_pricing", "output_modality")
    op.drop_column("model_pricing", "input_modality")
    op.drop_column("model_pricing", "is_multimodal")
    op.drop_column("model_pricing", "supports_vision")
