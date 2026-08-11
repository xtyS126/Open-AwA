"""工作台项目根路径的允许根解析、登记规范化与使用期复验。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from workbench.errors import ProjectRootChanged, ProjectRootForbidden, ProjectRootInvalid


def _normalized_path(path: Path) -> str:
    """生成适合当前平台比较与唯一约束的规范路径。"""
    return os.path.normcase(str(path))


def _is_sensitive_root(path: Path) -> bool:
    """拒绝文件系统根、驱动器根和服务账户主目录本身。"""
    if path == Path(path.anchor):
        return True
    try:
        service_home = Path.home().resolve(strict=True)
    except OSError:
        service_home = Path.home().resolve()
    return _normalized_path(path) == _normalized_path(service_home)


def _resolve_configured_root(raw_root: str) -> Path:
    """严格解析一个允许根；配置错误必须阻止启动。"""
    if not isinstance(raw_root, str) or not raw_root.strip():
        raise ProjectRootInvalid("工作台允许根必须是非空字符串")
    candidate = raw_root.strip()
    if "\x00" in candidate or "~" in candidate:
        raise ProjectRootInvalid("工作台允许根格式无效")
    path = Path(candidate)
    if not path.is_absolute():
        raise ProjectRootInvalid("工作台允许根必须是绝对路径")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectRootInvalid("工作台允许根不存在或无法解析") from exc
    if not resolved.is_dir() or _is_sensitive_root(resolved):
        raise ProjectRootInvalid("工作台允许根必须是非敏感目录")
    if os.name == "nt" and str(resolved).startswith("\\\\"):
        raise ProjectRootInvalid("工作台允许根不支持 UNC 路径")
    return resolved


def _parse_json_array(raw_value: str, *, field_name: str) -> list[str]:
    try:
        value = json.loads(raw_value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProjectRootInvalid(f"{field_name} 必须是 JSON 字符串数组") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProjectRootInvalid(f"{field_name} 必须是 JSON 字符串数组")
    return value


def _deduplicate_roots(raw_roots: Sequence[str]) -> tuple[Path, ...]:
    resolved_by_key: dict[str, Path] = {}
    for raw_root in raw_roots:
        resolved = _resolve_configured_root(raw_root)
        resolved_by_key[_normalized_path(resolved)] = resolved
    return tuple(sorted(resolved_by_key.values(), key=lambda item: _normalized_path(item)))


@dataclass(frozen=True)
class WorkbenchPathPolicy:
    """按用户和部署模式分配允许根，并对登记路径执行两阶段校验。"""

    global_roots: tuple[Path, ...]
    user_roots: Mapping[str, tuple[Path, ...]]
    single_user_mode: bool = False

    @classmethod
    def from_json(
        cls,
        *,
        global_roots_json: str | None,
        user_roots_json: str | None,
        project_root: Path,
        workspace_root: Path,
        single_user_mode: bool = False,
    ) -> "WorkbenchPathPolicy":
        """从严格 JSON 配置创建策略；空字符串表示采用稳定默认根。"""
        if global_roots_json is None or not global_roots_json.strip():
            raw_global_roots = [str(project_root), str(workspace_root)]
        else:
            raw_global_roots = _parse_json_array(
                global_roots_json,
                field_name="WORKBENCH_ALLOWED_ROOTS",
            )

        raw_user_value = user_roots_json if user_roots_json is not None else "{}"
        try:
            parsed_users: Any = json.loads(raw_user_value or "{}")
        except json.JSONDecodeError as exc:
            raise ProjectRootInvalid("WORKBENCH_ALLOWED_ROOTS_BY_USER 必须是 JSON 对象") from exc
        if not isinstance(parsed_users, dict):
            raise ProjectRootInvalid("WORKBENCH_ALLOWED_ROOTS_BY_USER 必须是 JSON 对象")

        user_roots: dict[str, tuple[Path, ...]] = {}
        for user_id, roots in parsed_users.items():
            if not isinstance(user_id, str) or not isinstance(roots, list):
                raise ProjectRootInvalid("用户允许根映射格式无效")
            if any(not isinstance(root, str) for root in roots):
                raise ProjectRootInvalid("用户允许根必须是字符串数组")
            user_roots[user_id] = _deduplicate_roots(roots)

        return cls(
            global_roots=_deduplicate_roots(raw_global_roots),
            user_roots=user_roots,
            single_user_mode=single_user_mode,
        )

    @classmethod
    def from_settings(cls, app_settings: Any) -> "WorkbenchPathPolicy":
        """从应用设置构建策略，避免领域包依赖具体 Settings 类型。"""
        from config.runtime_paths import PROJECT_ROOT, WORKSPACE_DIR

        return cls.from_json(
            global_roots_json=getattr(app_settings, "WORKBENCH_ALLOWED_ROOTS", ""),
            user_roots_json=getattr(app_settings, "WORKBENCH_ALLOWED_ROOTS_BY_USER", "{}"),
            project_root=PROJECT_ROOT,
            workspace_root=WORKSPACE_DIR,
            single_user_mode=bool(getattr(app_settings, "WORKBENCH_SINGLE_USER_MODE", True)),
        )

    def allowed_roots_for(self, *, user_id: str, user_role: str) -> tuple[Path, ...]:
        """用户显式映射优先；管理员或单用户部署才可使用全局根。"""
        if user_id in self.user_roots:
            return self.user_roots[user_id]
        if self.single_user_mode or user_role.strip().lower() == "admin":
            return self.global_roots
        return ()

    def canonicalize_registration(
        self,
        raw_root: str,
        *,
        user_id: str,
        user_role: str,
    ) -> tuple[str, str]:
        """校验登记输入并返回原始审计值与平台规范路径。"""
        if not isinstance(raw_root, str):
            raise ProjectRootInvalid()
        registered_root = raw_root.strip()
        if not registered_root or "\x00" in registered_root or "~" in registered_root:
            raise ProjectRootInvalid()
        candidate = Path(registered_root)
        if not candidate.is_absolute():
            raise ProjectRootInvalid("工作台项目根必须是绝对路径")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProjectRootInvalid() from exc
        if not resolved.is_dir() or _is_sensitive_root(resolved):
            raise ProjectRootInvalid()
        self._assert_allowed(resolved, user_id=user_id, user_role=user_role)
        return registered_root, _normalized_path(resolved)

    def resolve_registered_root(
        self,
        registered_root: str,
        canonical_root: str,
        *,
        user_id: str,
        user_role: str,
    ) -> Path:
        """每次实际使用前重解析登记路径并检测链接或 junction 漂移。"""
        try:
            resolved = Path(registered_root).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ProjectRootInvalid() from exc
        if not resolved.is_dir():
            raise ProjectRootInvalid()
        if _normalized_path(resolved) != canonical_root:
            raise ProjectRootChanged()
        self._assert_allowed(resolved, user_id=user_id, user_role=user_role)
        return resolved

    def _assert_allowed(self, path: Path, *, user_id: str, user_role: str) -> None:
        roots = self.allowed_roots_for(user_id=user_id, user_role=user_role)
        for root in roots:
            if _normalized_path(path) == _normalized_path(root):
                return
            try:
                path.relative_to(root)
                return
            except ValueError:
                continue
        raise ProjectRootForbidden()

