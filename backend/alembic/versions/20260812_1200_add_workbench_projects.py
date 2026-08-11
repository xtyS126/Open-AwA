"""新增工作台项目与当前项目上下文表。

Revision ID: add_workbench_projects
Revises: add_consolidation_tables
Create Date: 2026-08-12 12:00:00
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "add_workbench_projects"
down_revision = "add_consolidation_tables"
branch_labels = None
depends_on = None


_PROJECTS_TABLE = "workbench_projects"
_CONTEXTS_TABLE = "workbench_contexts"
_WORKBENCH_TABLES = frozenset({_PROJECTS_TABLE, _CONTEXTS_TABLE})


def _normalize_default(value: Any) -> str | None:
    """统一 SQLite 对默认值的括号与引号表示。"""
    if value is None:
        return None
    normalized = str(value).strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return normalized.strip("'\"").upper()


def _type_signature(column_type: sa.types.TypeEngine) -> tuple[str, int | None]:
    """将 inspector 类型压缩为迁移契约所需的语义签名。"""
    if isinstance(column_type, sa.Text):
        return ("text", None)
    if isinstance(column_type, sa.String):
        return ("string", column_type.length)
    if isinstance(column_type, sa.Boolean):
        return ("boolean", None)
    if isinstance(column_type, sa.DateTime):
        # SQLite DDL 不保存 timezone 标志，ORM 测试单独锁定 timezone=True。
        return ("datetime", None)
    return (type(column_type).__name__.lower(), None)


_EXPECTED_COLUMNS = {
    _PROJECTS_TABLE: {
        "id": (("string", None), False, None, True),
        "user_id": (("string", None), False, None, False),
        "display_name": (("string", 200), False, None, False),
        "registered_root": (("text", None), False, None, False),
        "canonical_root": (("text", None), False, None, False),
        "is_enabled": (("boolean", None), False, "1", False),
        "created_at": (("datetime", None), False, None, False),
        "updated_at": (("datetime", None), False, None, False),
        "last_opened_at": (("datetime", None), True, None, False),
    },
    _CONTEXTS_TABLE: {
        "user_id": (("string", None), False, None, True),
        "current_project_id": (("string", None), True, None, False),
        "updated_at": (("datetime", None), False, None, False),
    },
}

_EXPECTED_PRIMARY_KEYS = {
    _PROJECTS_TABLE: ("id",),
    _CONTEXTS_TABLE: ("user_id",),
}

_EXPECTED_FOREIGN_KEYS = {
    _PROJECTS_TABLE: {
        (("user_id",), "users", ("id",), "CASCADE"),
    },
    _CONTEXTS_TABLE: {
        (("user_id",), "users", ("id",), "CASCADE"),
        (
            ("current_project_id",),
            _PROJECTS_TABLE,
            ("id",),
            "SET NULL",
        ),
    },
}

_EXPECTED_UNIQUE_CONSTRAINTS = {
    _PROJECTS_TABLE: {
        (
            "uq_workbench_projects_user_canonical_root",
            ("user_id", "canonical_root"),
        ),
    },
    _CONTEXTS_TABLE: set(),
}

_EXPECTED_INDEXES = {
    _PROJECTS_TABLE: {
        (
            "ix_workbench_projects_user_enabled_opened",
            ("user_id", "is_enabled", "last_opened_at"),
            False,
        ),
    },
    _CONTEXTS_TABLE: set(),
}


def _schema_mismatches(inspector: sa.Inspector) -> list[str]:
    """完整比较已存在两表与本 revision 的 schema 契约。"""
    mismatches: list[str] = []
    for table_name in (_PROJECTS_TABLE, _CONTEXTS_TABLE):
        actual_columns = {
            column["name"]: (
                _type_signature(column["type"]),
                bool(column["nullable"]),
                _normalize_default(column.get("default")),
                bool(column.get("primary_key")),
            )
            for column in inspector.get_columns(table_name)
        }
        if actual_columns != _EXPECTED_COLUMNS[table_name]:
            mismatches.append(f"{table_name}.columns")

        actual_primary_key = tuple(
            inspector.get_pk_constraint(table_name).get("constrained_columns") or ()
        )
        if actual_primary_key != _EXPECTED_PRIMARY_KEYS[table_name]:
            mismatches.append(f"{table_name}.primary_key")

        actual_foreign_keys = {
            (
                tuple(foreign_key.get("constrained_columns") or ()),
                foreign_key.get("referred_table"),
                tuple(foreign_key.get("referred_columns") or ()),
                str((foreign_key.get("options") or {}).get("ondelete") or "").upper(),
            )
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        if actual_foreign_keys != _EXPECTED_FOREIGN_KEYS[table_name]:
            mismatches.append(f"{table_name}.foreign_keys")

        actual_unique_constraints = {
            (
                constraint.get("name"),
                tuple(constraint.get("column_names") or ()),
            )
            for constraint in inspector.get_unique_constraints(table_name)
        }
        if actual_unique_constraints != _EXPECTED_UNIQUE_CONSTRAINTS[table_name]:
            mismatches.append(f"{table_name}.unique_constraints")

        actual_indexes = {
            (
                index.get("name"),
                tuple(index.get("column_names") or ()),
                bool(index.get("unique")),
            )
            for index in inspector.get_indexes(table_name)
        }
        if actual_indexes != _EXPECTED_INDEXES[table_name]:
            mismatches.append(f"{table_name}.indexes")

    return mismatches


def _create_workbench_tables() -> None:
    """按父子依赖顺序创建两张工作台表。"""
    op.create_table(
        _PROJECTS_TABLE,
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("registered_root", sa.Text(), nullable=False),
        sa.Column("canonical_root", sa.Text(), nullable=False),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "canonical_root",
            name="uq_workbench_projects_user_canonical_root",
        ),
    )
    op.create_index(
        "ix_workbench_projects_user_enabled_opened",
        _PROJECTS_TABLE,
        ["user_id", "is_enabled", "last_opened_at"],
        unique=False,
    )

    op.create_table(
        _CONTEXTS_TABLE,
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("current_project_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["current_project_id"],
            ["workbench_projects.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )


def upgrade() -> None:
    """创建新表，或严格接管 runtime 已创建的完整等价 schema。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = _WORKBENCH_TABLES.intersection(inspector.get_table_names())

    if not existing_tables:
        _create_workbench_tables()
        return

    if existing_tables != _WORKBENCH_TABLES:
        raise RuntimeError(
            "Workbench schema 部分存在，拒绝自动修复；请先恢复两表一致状态"
        )

    mismatches = _schema_mismatches(inspector)
    if mismatches:
        details = ", ".join(mismatches)
        raise RuntimeError(f"Workbench schema 不一致，拒绝接管: {details}")


def downgrade() -> None:
    """按子表优先顺序删除工作台 schema，不触碰任何磁盘目录。"""
    op.drop_table(_CONTEXTS_TABLE)
    op.drop_index(
        "ix_workbench_projects_user_enabled_opened",
        table_name=_PROJECTS_TABLE,
    )
    # SQLite 的表内唯一约束随表一起删除，不单独执行约束删除。
    op.drop_table(_PROJECTS_TABLE)
