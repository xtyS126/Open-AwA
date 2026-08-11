"""工作台项目与当前上下文 ORM 契约测试。"""

from importlib import import_module

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint


def _load_models():
    """延迟加载待实现模型，使 RED 以测试失败而非收集错误呈现。"""
    module = import_module("db.models.workbench")
    return module.WorkbenchProject, module.WorkbenchContext


def test_workbench_project_columns_and_defaults_match_contract():
    """项目表应精确保存所有权、双路径、启用状态和 UTC 时间。"""
    project_model, _ = _load_models()
    table = project_model.__table__

    assert table.name == "workbench_projects"
    assert set(table.c.keys()) == {
        "id",
        "user_id",
        "display_name",
        "registered_root",
        "canonical_root",
        "is_enabled",
        "created_at",
        "updated_at",
        "last_opened_at",
    }
    assert isinstance(table.c.id.type, String)
    assert table.c.id.type.length is None
    assert table.c.id.primary_key is True
    assert table.c.id.nullable is False
    assert table.c.id.default is not None

    assert isinstance(table.c.user_id.type, String)
    assert table.c.user_id.type.length is None
    assert table.c.user_id.nullable is False
    assert isinstance(table.c.display_name.type, String)
    assert table.c.display_name.type.length == 200
    assert table.c.display_name.nullable is False
    assert isinstance(table.c.registered_root.type, Text)
    assert table.c.registered_root.nullable is False
    assert isinstance(table.c.canonical_root.type, Text)
    assert table.c.canonical_root.nullable is False
    assert isinstance(table.c.is_enabled.type, Boolean)
    assert table.c.is_enabled.nullable is False
    assert table.c.is_enabled.default is not None
    assert table.c.is_enabled.server_default is not None

    for column_name in ("created_at", "updated_at", "last_opened_at"):
        column = table.c[column_name]
        assert isinstance(column.type, DateTime)
        assert column.type.timezone is True
    assert table.c.created_at.nullable is False
    assert table.c.created_at.default is not None
    assert table.c.updated_at.nullable is False
    assert table.c.updated_at.default is not None
    assert table.c.updated_at.onupdate is not None
    assert table.c.last_opened_at.nullable is True


def test_workbench_project_ownership_constraints_and_index_match_contract():
    """项目所有权应级联删除，并按用户与规范根唯一。"""
    project_model, _ = _load_models()
    table = project_model.__table__

    user_fk = next(iter(table.c.user_id.foreign_keys))
    assert user_fk.target_fullname == "users.id"
    assert user_fk.ondelete == "CASCADE"

    unique_constraints = {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert unique_constraints == {
        (
            "uq_workbench_projects_user_canonical_root",
            ("user_id", "canonical_root"),
        )
    }

    indexes = {
        (index.name, tuple(column.name for column in index.columns), index.unique)
        for index in table.indexes
    }
    assert indexes == {
        (
            "ix_workbench_projects_user_enabled_opened",
            ("user_id", "is_enabled", "last_opened_at"),
            False,
        )
    }


def test_workbench_context_columns_and_delete_actions_match_contract():
    """每用户上下文应唯一，用户删除级联且项目删除置空。"""
    _, context_model = _load_models()
    table = context_model.__table__

    assert table.name == "workbench_contexts"
    assert set(table.c.keys()) == {"user_id", "current_project_id", "updated_at"}
    assert isinstance(table.c.user_id.type, String)
    assert table.c.user_id.type.length is None
    assert table.c.user_id.primary_key is True
    assert table.c.user_id.nullable is False
    assert isinstance(table.c.current_project_id.type, String)
    assert table.c.current_project_id.type.length is None
    assert table.c.current_project_id.nullable is True
    assert isinstance(table.c.updated_at.type, DateTime)
    assert table.c.updated_at.type.timezone is True
    assert table.c.updated_at.nullable is False
    assert table.c.updated_at.default is not None
    assert table.c.updated_at.onupdate is not None

    user_fk = next(iter(table.c.user_id.foreign_keys))
    project_fk = next(iter(table.c.current_project_id.foreign_keys))
    assert user_fk.target_fullname == "users.id"
    assert user_fk.ondelete == "CASCADE"
    assert project_fk.target_fullname == "workbench_projects.id"
    assert project_fk.ondelete == "SET NULL"

