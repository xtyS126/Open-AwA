"""WorkbenchProject 三轨 schema 与 Alembic 桥接测试。"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from db.models import Base, User, init_db


_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PREVIOUS_REVISION = "add_consolidation_tables"
_WORKBENCH_REVISION = "add_workbench_projects"
_TABLES = ("workbench_projects", "workbench_contexts")


def _load_workbench_contract():
    """延迟加载待实现模型与 runtime migration。"""
    model_module = import_module("db.models.workbench")
    migration_module = import_module("db.models.migrations")
    return (
        model_module.WorkbenchProject,
        model_module.WorkbenchContext,
        migration_module._migrate_workbench_tables,
    )


def _sqlite_engine(database_path: Path) -> Engine:
    """创建强制启用外键的临时 SQLite 引擎。"""
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _alembic_config(database_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """将 Alembic 严格绑定到当前用例临时数据库。"""
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(_BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _create_old_database(engine: Engine, *, with_user: bool) -> None:
    """创建只含旧 head 标记与 users 表的最小旧数据库。"""
    User.__table__.create(engine, checkfirst=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(64) NOT NULL PRIMARY KEY)"
            )
        )
        connection.execute(
            text("INSERT INTO alembic_version(version_num) VALUES (:revision)"),
            {"revision": _PREVIOUS_REVISION},
        )
    if with_user:
        with Session(engine) as session:
            session.add(
                User(
                    id="migration-user",
                    username="migration-user",
                    password_hash="not-a-real-password-hash",
                )
            )
            session.commit()


def _normalized_default(value: Any) -> str | None:
    """统一 SQLite inspector 对默认值的括号与引号表示。"""
    if value is None:
        return None
    normalized = str(value).strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return normalized.strip("'\"").upper()


def _table_contract(engine: Engine, table_name: str) -> dict[str, Any]:
    """提取可跨三条建表路径比较的完整 schema 契约。"""
    inspector = inspect(engine)
    columns = {
        column["name"]: {
            "type": str(column["type"]).upper(),
            "nullable": bool(column["nullable"]),
            "default": _normalized_default(column.get("default")),
            "primary_key": bool(column.get("primary_key")),
        }
        for column in inspector.get_columns(table_name)
    }
    primary_key = tuple(inspector.get_pk_constraint(table_name).get("constrained_columns") or ())
    foreign_keys = sorted(
        (
            tuple(foreign_key.get("constrained_columns") or ()),
            foreign_key.get("referred_table"),
            tuple(foreign_key.get("referred_columns") or ()),
            str((foreign_key.get("options") or {}).get("ondelete") or "").upper(),
        )
        for foreign_key in inspector.get_foreign_keys(table_name)
    )
    unique_constraints = sorted(
        (
            constraint.get("name"),
            tuple(constraint.get("column_names") or ()),
        )
        for constraint in inspector.get_unique_constraints(table_name)
    )
    indexes = sorted(
        (
            index.get("name"),
            tuple(index.get("column_names") or ()),
            bool(index.get("unique")),
        )
        for index in inspector.get_indexes(table_name)
    )
    return {
        "columns": columns,
        "primary_key": primary_key,
        "foreign_keys": foreign_keys,
        "unique_constraints": unique_constraints,
        "indexes": indexes,
    }


def _workbench_contract(engine: Engine) -> dict[str, dict[str, Any]]:
    """提取两张工作台表的完整 schema。"""
    return {table_name: _table_contract(engine, table_name) for table_name in _TABLES}


def _current_revision(engine: Engine) -> str:
    """读取临时数据库当前 Alembic revision。"""
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def test_workbench_revision_is_the_only_static_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """新 revision 应成为唯一静态 head。"""
    config = _alembic_config(tmp_path / "static-head.db", monkeypatch)
    assert ScriptDirectory.from_config(config).get_heads() == [_WORKBENCH_REVISION]


def test_alembic_upgrade_downgrade_and_reupgrade_preserve_old_data_and_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """升降级只改变登记 schema，不触碰旧用户或磁盘项目。"""
    database_path = tmp_path / "roundtrip.db"
    marker_dir = tmp_path / "registered-project"
    marker_dir.mkdir()
    marker_file = marker_dir / "keep.txt"
    marker_file.write_text("must survive migration", encoding="utf-8")
    engine = _sqlite_engine(database_path)
    _create_old_database(engine, with_user=True)
    config = _alembic_config(database_path, monkeypatch)

    command.upgrade(config, "head")
    assert _current_revision(engine) == _WORKBENCH_REVISION
    assert set(_TABLES).issubset(inspect(engine).get_table_names())
    upgraded_contract = _workbench_contract(engine)

    command.downgrade(config, _PREVIOUS_REVISION)
    assert _current_revision(engine) == _PREVIOUS_REVISION
    assert set(_TABLES).isdisjoint(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM users")).scalar_one() == "migration-user"
    assert marker_file.read_text(encoding="utf-8") == "must survive migration"

    command.upgrade(config, "head")
    assert _current_revision(engine) == _WORKBENCH_REVISION
    assert _workbench_contract(engine) == upgraded_contract
    engine.dispose()


def test_workbench_foreign_key_delete_actions_are_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """项目删除置空上下文，用户删除级联清理登记与上下文。"""
    database_path = tmp_path / "foreign-keys.db"
    engine = _sqlite_engine(database_path)
    _create_old_database(engine, with_user=True)
    config = _alembic_config(database_path, monkeypatch)
    command.upgrade(config, "head")
    project_model, context_model, _ = _load_workbench_contract()

    with Session(engine) as session:
        first_project = project_model(
            user_id="migration-user",
            display_name="first",
            registered_root=str(tmp_path / "first"),
            canonical_root=str(tmp_path / "first"),
        )
        session.add(first_project)
        session.flush()
        session.add(
            context_model(
                user_id="migration-user",
                current_project_id=first_project.id,
            )
        )
        session.commit()
        first_project_id = first_project.id

        session.delete(first_project)
        session.commit()
        context = session.get(context_model, "migration-user")
        assert context is not None
        assert context.current_project_id is None

        second_project = project_model(
            user_id="migration-user",
            display_name="second",
            registered_root=str(tmp_path / "second"),
            canonical_root=str(tmp_path / "second"),
        )
        session.add(second_project)
        session.flush()
        second_project_id = second_project.id
        context.current_project_id = second_project.id
        session.commit()

        user = session.get(User, "migration-user")
        assert user is not None
        session.delete(user)
        session.commit()
        assert session.get(project_model, first_project_id) is None
        assert session.get(project_model, second_project_id) is None
        assert session.get(context_model, "migration-user") is None
    engine.dispose()


def test_orm_runtime_and_alembic_schema_are_equivalent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ORM、runtime migration 与 Alembic 必须生成完全相同的工作台 schema。"""
    _, _, migrate_workbench = _load_workbench_contract()

    orm_engine = _sqlite_engine(tmp_path / "orm.db")
    Base.metadata.create_all(orm_engine)

    runtime_engine = _sqlite_engine(tmp_path / "runtime.db")
    User.__table__.create(runtime_engine)
    migrate_workbench(use_engine=runtime_engine)
    migrate_workbench(use_engine=runtime_engine)

    alembic_path = tmp_path / "alembic.db"
    alembic_engine = _sqlite_engine(alembic_path)
    _create_old_database(alembic_engine, with_user=False)
    config = _alembic_config(alembic_path, monkeypatch)
    command.upgrade(config, "head")

    orm_contract = _workbench_contract(orm_engine)
    assert _workbench_contract(runtime_engine) == orm_contract
    assert _workbench_contract(alembic_engine) == orm_contract

    orm_engine.dispose()
    runtime_engine.dispose()
    alembic_engine.dispose()


def test_runtime_created_schema_is_adopted_by_alembic_upgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧库先经 runtime 建表后，Alembic 应校验并只推进 revision。"""
    database_path = tmp_path / "runtime-then-alembic.db"
    engine = _sqlite_engine(database_path)
    _create_old_database(engine, with_user=True)
    _, _, migrate_workbench = _load_workbench_contract()
    migrate_workbench(use_engine=engine)
    runtime_contract = _workbench_contract(engine)
    config = _alembic_config(database_path, monkeypatch)

    command.upgrade(config, "head")

    assert _current_revision(engine) == _WORKBENCH_REVISION
    assert _workbench_contract(engine) == runtime_contract
    engine.dispose()


def test_alembic_created_schema_accepts_new_code_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧库先经 Alembic 建表后，新代码启动应保持 schema 不变。"""
    database_path = tmp_path / "alembic-then-startup.db"
    engine = _sqlite_engine(database_path)
    _create_old_database(engine, with_user=True)
    config = _alembic_config(database_path, monkeypatch)
    command.upgrade(config, "head")
    alembic_contract = _workbench_contract(engine)

    init_db(bind_engine=engine)

    assert _current_revision(engine) == _WORKBENCH_REVISION
    assert _workbench_contract(engine) == alembic_contract
    engine.dispose()


def test_alembic_upgrade_fails_fast_when_only_one_workbench_table_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """桥接状态只有一张表时不得猜测修复。"""
    database_path = tmp_path / "partial-schema.db"
    engine = _sqlite_engine(database_path)
    _create_old_database(engine, with_user=False)
    project_model, _, _ = _load_workbench_contract()
    project_model.__table__.create(engine)
    config = _alembic_config(database_path, monkeypatch)

    with pytest.raises(RuntimeError, match="部分存在"):
        command.upgrade(config, "head")

    assert _current_revision(engine) == _PREVIOUS_REVISION
    engine.dispose()


def test_alembic_upgrade_fails_fast_when_existing_schema_is_inconsistent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """桥接状态缺少关键索引时不得静默接管。"""
    database_path = tmp_path / "inconsistent-schema.db"
    engine = _sqlite_engine(database_path)
    _create_old_database(engine, with_user=False)
    _, _, migrate_workbench = _load_workbench_contract()
    migrate_workbench(use_engine=engine)
    with engine.begin() as connection:
        connection.execute(
            text("DROP INDEX ix_workbench_projects_user_enabled_opened")
        )
    config = _alembic_config(database_path, monkeypatch)

    with pytest.raises(RuntimeError, match="schema 不一致"):
        command.upgrade(config, "head")

    assert _current_revision(engine) == _PREVIOUS_REVISION
    engine.dispose()
