"""新增微信多媒体资产表

Revision ID: add_weixin_media_assets
Revises: add_pricing_cache_fields
创建时间: 2026-07-13 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "add_weixin_media_assets"
down_revision = "add_pricing_cache_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weixin_media_assets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("media_format", sa.String(length=32), nullable=True),
        sa.Column("encrypted_query_param", sa.Text(), nullable=False),
        sa.Column("encrypted_aes_key", sa.Text(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("transcript_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index("ix_weixin_media_assets_user_id", "weixin_media_assets", ["user_id"])
    op.create_index("ix_weixin_media_assets_message_id", "weixin_media_assets", ["message_id"])
    op.create_index("ix_weixin_media_assets_transcript_status", "weixin_media_assets", ["transcript_status"])
    op.create_index("ix_weixin_media_assets_created_at", "weixin_media_assets", ["created_at"])


def downgrade() -> None:
    op.drop_table("weixin_media_assets")
