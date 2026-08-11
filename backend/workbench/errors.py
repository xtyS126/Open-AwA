"""工作台领域异常；HTTP 状态码映射由 API 路由层负责。"""

from typing import Iterable


class WorkbenchError(Exception):
    """所有工作台领域错误的基类。"""

    code = "workbench_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProjectNotFound(WorkbenchError):
    code = "workbench_project_not_found"

    def __init__(self) -> None:
        super().__init__("工作台项目不存在")


class ProjectDisabled(WorkbenchError):
    code = "workbench_project_disabled"

    def __init__(self) -> None:
        super().__init__("工作台项目已禁用")


class ProjectRootInvalid(WorkbenchError):
    code = "workbench_project_root_invalid"

    def __init__(self, message: str = "工作台项目根路径无效") -> None:
        super().__init__(message)


class ProjectRootForbidden(WorkbenchError):
    code = "workbench_project_root_forbidden"

    def __init__(self) -> None:
        super().__init__("工作台项目根路径不在允许范围内")


class ProjectRootChanged(WorkbenchError):
    code = "workbench_project_root_changed"

    def __init__(self) -> None:
        super().__init__("工作台项目根路径已发生变化")


class ProjectRootConflict(WorkbenchError):
    code = "workbench_project_root_conflict"

    def __init__(self) -> None:
        super().__init__("该工作台项目根路径已登记")


class ProjectInUse(WorkbenchError):
    code = "workbench_project_in_use"

    def __init__(self, resource_ids: Iterable[str]) -> None:
        self.resource_ids = tuple(sorted(set(resource_ids)))
        super().__init__("工作台项目仍有活动运行时资源")

