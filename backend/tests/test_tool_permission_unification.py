"""
工具权限 action 命名统一与用户级 RBAC 接入测试。

覆盖：
1. 命令工具在 _infer_permission_action / permission_guard / _BUILTIN_PERMISSION_MAP
   三处 call 路径使用一致的 action 命名（统一为 command:execute）
2. 用户级 RBAC 接入工具权限决策：无 RBAC 配置时默认放行，用户被显式分配角色
   且缺少对应 resource:action 权限时拒绝（denied_by=rbac）
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base
from security.rbac import RBACManager
from core.execution_tool_runtime import (
    ExecutionToolRuntimeMixin,
    _infer_permission_action,
    _tool_rbac_permission,
)
from core.task_runtime.permission_guard import _TOOL_OPERATION_MAP
from core.tool_entries import _BUILTIN_PERMISSION_MAP


# ==================== action 命名统一测试 ====================


class TestCommandToolActionNamingUnified:
    """命令工具在三个权限决策 call 路径中的命名必须一致。"""

    def test_infer_permission_action_command_tools(self):
        """_infer_permission_action 将命令工具统一映射为 command:execute。"""
        assert _infer_permission_action("run_command") == "command:execute"
        assert _infer_permission_action("execute_command") == "command:execute"
        assert _infer_permission_action("run_shell") == "command:execute"
        assert _infer_permission_action("builtin_run_command") == "command:execute"

    def test_permission_guard_command_tools(self):
        """permission_guard 的操作映射同样使用 command:execute。"""
        assert _TOOL_OPERATION_MAP["run_command"] == "command:execute"
        assert _TOOL_OPERATION_MAP["execute_command"] == "command:execute"
        assert _TOOL_OPERATION_MAP["run_shell"] == "command:execute"

    def test_builtin_permission_map_command_tool(self):
        """_BUILTIN_PERMISSION_MAP 的 action/resource 均为 command:execute。"""
        assert _BUILTIN_PERMISSION_MAP["run_command"] == ("command:execute", "command:execute")

    def test_three_sources_agree_on_command_tool(self):
        """三处 call 路径对同一命令工具 use 一致的 action 命名。"""
        assert _infer_permission_action("run_command") == "command:execute"
        assert _TOOL_OPERATION_MAP["run_command"] == "command:execute"
        assert _BUILTIN_PERMISSION_MAP["run_command"][0] == "command:execute"
        assert _BUILTIN_PERMISSION_MAP["run_command"][1] == "command:execute"

    def test_tool_rbac_permission_command_tool(self):
        """用户级 RBAC 权限字符串推导同样得到 command:execute。"""
        assert _tool_rbac_permission("run_command") == "command:execute"
        assert _tool_rbac_permission("builtin_run_command") == "command:execute"


# ==================== 用户级 RBAC 接入工具权限测试 ====================


@pytest.fixture
def db_session(tmp_path):
    """创建临时 SQLite 数据库会话（含 Role/UserRole 表）。"""
    db_path = tmp_path / "test_tool_permission.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestUserRbacToolPermission:
    """用户级 RBAC 接入工具权限决策的行为测试。"""

    @pytest.mark.asyncio
    async def test_passthrough_without_db(self):
        """无 db 会话时无法校验用户级 RBAC，应默认放行（行为不变）。"""
        runtime = ExecutionToolRuntimeMixin()
        result = await runtime._check_user_rbac_permission(
            "run_command", {"user_id": "u1"},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_passthrough_without_explicit_role(self, db_session):
        """用户未被显式分配角色时默认放行（保持既有行为）。"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        runtime = ExecutionToolRuntimeMixin()
        result = await runtime._check_user_rbac_permission(
            "run_command", {"user_id": "stranger", "db": db_session},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_denies_when_role_lacks_permission(self, db_session):
        """用户角色缺少 command:execute 权限时拒绝命令工具调用。"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        await rbac.set_user_role("viewer_user", "viewer")
        runtime = ExecutionToolRuntimeMixin()
        result = await runtime._check_user_rbac_permission(
            "run_command", {"user_id": "viewer_user", "db": db_session},
        )
        assert result is not None
        assert result["ok"] is False
        assert result["denied_by"] == "rbac"

    @pytest.mark.asyncio
    async def test_allows_admin(self, db_session):
        """admin 角色拥有通配符权限，应放行命令工具调用。"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        await rbac.set_user_role("admin_user", "admin")
        runtime = ExecutionToolRuntimeMixin()
        result = await runtime._check_user_rbac_permission(
            "run_command", {"user_id": "admin_user", "db": db_session},
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_check_tool_permission_denied_by_rbac(self, db_session):
        """完整权限检查链中，用户级 RBAC 拒接无权限的命令工具调用。"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        await rbac.set_user_role("viewer_user", "viewer")
        runtime = ExecutionToolRuntimeMixin()
        result = await runtime._check_tool_permission(
            "run_command",
            {"command": "ls"},
            {"user_id": "viewer_user", "db": db_session},
        )
        assert result is not None
        assert result["denied_by"] == "rbac"