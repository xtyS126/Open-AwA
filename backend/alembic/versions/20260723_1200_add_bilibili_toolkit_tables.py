"""add bilibili toolkit tables

Revision ID: add_bilibili_toolkit_tables
Revises: merge_heads_add_pricing_legacy
Create Date: 2026-07-23 12:00:00

本迁移为 bili-sync 移植 spec 阶段 13 的数据库 schema 扩展：
创建 4 张 Bilibili Toolkit 表，承载视频同步下载链路的持久化数据：
1. bilibili_toolkit_videos：视频元数据（bvid 唯一索引）
2. bilibili_toolkit_pages：分 P 信息（video_id 外键 + video_id/cid 联合唯一）
3. bilibili_toolkit_subscriptions：订阅源（type/source_id 联合唯一 + type/enabled 索引）
4. bilibili_toolkit_download_tasks：下载子任务记录（status 索引 + video/page/subtask 联合唯一）

download_status 字段为 5 子任务 × 4 态位图（详见 plugins/bilibili_toolkit_builtin/status.py），
filter_option / rule 字段以 Text 存 JSON 字符串，运行时由调用方 json.loads 解析。
"""
from alembic import op
import sqlalchemy as sa


# Alembic 修订标识符
revision = "add_bilibili_toolkit_tables"
down_revision = "merge_heads_add_pricing_legacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """正向迁移：创建 4 张 Bilibili Toolkit 表与索引。"""
    # 1. 视频元数据表
    op.create_table(
        "bilibili_toolkit_videos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bvid", sa.String(length=32), nullable=False),
        sa.Column("aid", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("cover", sa.String(length=1024), nullable=True),
        sa.Column("upper_mid", sa.Integer(), nullable=False),
        sa.Column("upper_name", sa.String(length=128), nullable=False),
        sa.Column("pages_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("pubtime", sa.Integer(), nullable=False),
        sa.Column("fav_time", sa.Integer(), nullable=True),
        sa.Column("download_status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("bvid", name="uq_bilibili_toolkit_videos_bvid"),
    )
    op.create_index(
        "ix_bilibili_toolkit_videos_bvid",
        "bilibili_toolkit_videos",
        ["bvid"],
        unique=True,
    )
    op.create_index(
        "ix_bilibili_toolkit_videos_upper_mid",
        "bilibili_toolkit_videos",
        ["upper_mid"],
    )

    # 2. 分 P 信息表
    op.create_table(
        "bilibili_toolkit_pages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "video_id",
            sa.Integer(),
            sa.ForeignKey("bilibili_toolkit_videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cid", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("download_status", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "video_id",
            "cid",
            name="uq_bilibili_toolkit_pages_video_cid",
        ),
    )
    op.create_index(
        "ix_bilibili_toolkit_pages_video_id",
        "bilibili_toolkit_pages",
        ["video_id"],
    )

    # 3. 订阅源表
    op.create_table(
        "bilibili_toolkit_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("rule", sa.Text(), nullable=True),
        sa.Column("filter_option", sa.Text(), nullable=True),
        sa.Column("latest_row_at", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "type",
            "source_id",
            name="uq_bilibili_toolkit_subscriptions_type_source",
        ),
    )
    op.create_index(
        "ix_bilibili_toolkit_subscriptions_type_enabled",
        "bilibili_toolkit_subscriptions",
        ["type", "enabled"],
    )

    # 4. 下载子任务表
    op.create_table(
        "bilibili_toolkit_download_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "video_id",
            sa.Integer(),
            sa.ForeignKey("bilibili_toolkit_videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            sa.Integer(),
            sa.ForeignKey("bilibili_toolkit_pages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("subtask", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "video_id",
            "page_id",
            "subtask",
            name="uq_bilibili_toolkit_tasks_video_page_subtask",
        ),
    )
    op.create_index(
        "ix_bilibili_toolkit_download_tasks_video_id",
        "bilibili_toolkit_download_tasks",
        ["video_id"],
    )
    op.create_index(
        "ix_bilibili_toolkit_download_tasks_page_id",
        "bilibili_toolkit_download_tasks",
        ["page_id"],
    )
    op.create_index(
        "ix_bilibili_toolkit_download_tasks_status",
        "bilibili_toolkit_download_tasks",
        ["status"],
    )


def downgrade() -> None:
    """回滚：按 upgrade 相反顺序删除 4 张表与索引。"""
    # 4. 删除下载子任务表
    op.drop_index(
        "ix_bilibili_toolkit_download_tasks_status",
        table_name="bilibili_toolkit_download_tasks",
    )
    op.drop_index(
        "ix_bilibili_toolkit_download_tasks_page_id",
        table_name="bilibili_toolkit_download_tasks",
    )
    op.drop_index(
        "ix_bilibili_toolkit_download_tasks_video_id",
        table_name="bilibili_toolkit_download_tasks",
    )
    op.drop_table("bilibili_toolkit_download_tasks")

    # 3. 删除订阅源表
    op.drop_index(
        "ix_bilibili_toolkit_subscriptions_type_enabled",
        table_name="bilibili_toolkit_subscriptions",
    )
    op.drop_table("bilibili_toolkit_subscriptions")

    # 2. 删除分 P 信息表
    op.drop_index(
        "ix_bilibili_toolkit_pages_video_id",
        table_name="bilibili_toolkit_pages",
    )
    op.drop_table("bilibili_toolkit_pages")

    # 1. 删除视频元数据表
    op.drop_index(
        "ix_bilibili_toolkit_videos_upper_mid",
        table_name="bilibili_toolkit_videos",
    )
    op.drop_index(
        "ix_bilibili_toolkit_videos_bvid",
        table_name="bilibili_toolkit_videos",
    )
    op.drop_table("bilibili_toolkit_videos")
