"""add discussion search builtin plugin

Revision ID: add_discussion_search_builtin
Revises:
Create Date: 2026-06-28 12:00:00

本迁移为多 Agent 讨论任务、搜索 Provider 配置、内置插件标记奠定数据基础：
1. 创建 discussion_tasks / discussion_votes / search_provider_configs 三张表
2. 为 plugins 表新增 is_uninstallable 字段（标识内置不可卸载插件）
3. seed 一条 duckduckgo 默认搜索配置
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


# Alembic 修订标识符
revision = "add_discussion_search_builtin"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    正向迁移：创建三张新表、为 plugins 表追加字段、seed 默认搜索配置。
    """
    # 1. 创建 discussion_tasks 表（多 Agent 讨论任务主表）
    op.create_table(
        "discussion_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        # 提议动作 JSON：{"type": "plugin_command"|"tool_call"|"subagent_delegate", "payload": {...}}
        sa.Column("proposed_action", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        # 状态枚举：created/discussing/pending_approval/approved/rejected/executing/completed/failed
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("max_rounds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_discussion_user_status", "discussion_tasks", ["user_id", "status"])
    op.create_index("idx_discussion_created_at", "discussion_tasks", ["created_at"])

    # 2. 创建 discussion_votes 表（每个角色每轮的投票记录）
    op.create_table(
        "discussion_votes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "discussion_id",
            sa.String(length=36),
            sa.ForeignKey("discussion_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 角色枚举：critic/validator/approver
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        # 投票决策枚举：approve/reject/abstain
        sa.Column("vote", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        # 该角色本轮发言消息序列
        sa.Column("transcript", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("discussion_id", "role", "round", name="uq_discussion_vote_role_round"),
    )

    # 3. 创建 search_provider_configs 表（搜索 Provider 配置）
    op.create_table(
        "search_provider_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # provider 枚举：duckduckgo/searxng/disabled
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=True),
        sa.Column("api_key", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        # 扩展配置：allow_private_network 等开关
        sa.Column("extra_config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_search_provider_enabled", "search_provider_configs", ["provider", "enabled"])

    # 4. 为 plugins 表新增 is_uninstallable 字段
    # server_default 确保已有行获得默认值，满足 NOT NULL 约束（SQLite 以 0 表示 False）
    op.add_column(
        "plugins",
        sa.Column(
            "is_uninstallable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="是否不可卸载（内置插件为 True）",
        ),
    )

    # 5. seed 默认 duckduckgo 搜索配置
    _now = datetime.now(timezone.utc)
    op.bulk_insert(
        sa.table(
            "search_provider_configs",
            sa.column("provider", sa.String),
            sa.column("base_url", sa.String),
            sa.column("api_key", sa.String),
            sa.column("enabled", sa.Boolean),
            sa.column("extra_config", sa.JSON),
            sa.column("created_at", sa.DateTime),
            sa.column("updated_at", sa.DateTime),
        ),
        [
            {
                "provider": "duckduckgo",
                "base_url": None,
                "api_key": None,
                "enabled": True,
                "extra_config": {},
                "created_at": _now,
                "updated_at": _now,
            }
        ],
    )


def downgrade() -> None:
    """回滚：移除 is_uninstallable 字段并按创建的相反顺序删除三张表。"""
    # 反向操作顺序与 upgrade 相反
    op.drop_column("plugins", "is_uninstallable")
    op.drop_index("idx_search_provider_enabled", table_name="search_provider_configs")
    op.drop_table("search_provider_configs")
    op.drop_table("discussion_votes")
    op.drop_index("idx_discussion_created_at", table_name="discussion_tasks")
    op.drop_index("idx_discussion_user_status", table_name="discussion_tasks")
    op.drop_table("discussion_tasks")
