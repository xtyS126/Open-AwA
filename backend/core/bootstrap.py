"""
首次部署初始化编排模块。

封装 6 步初始化流程，供 `POST /api/system/init` 端点调用。
不直接处理用户输入校验（由 API 端点完成 Schema 校验），
不打印任何输出（仅记录 loguru 日志，返回结构化结果）。

6 步流程：
1. 前置检查（标记文件不存在、数据库无用户；force=True 跳过）
2. 生成三密钥（JWT/CSRF/ENCRYPTION，已存在的保留，除非 regenerate_secrets=True）
3. 生成 OPENAWA_API_KEY（已存在的保留，除非 regenerate_secrets=True）
4. 创建 owner 用户（pbkdf2_sha256 哈希 + admin 角色）
5. 写入 .env.local（仅三密钥与 API Key，原子写入 + 0o600 权限）
6. 创建标记文件（调用 mark_initialized）

并发保护：
- Linux/Mac 使用 `fcntl.flock` 非阻塞独占锁
- Windows 回退到模块级标志（单进程内防重入，不跨进程互斥）
"""

import os
import sys
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from config.security import get_password_hash
from core.initialization import (
    has_any_user,
    is_initialized,
    mark_initialized,
    reset_initialization,
)
from db.models import SessionLocal, User, init_db
from generate_api_key import generate_key, _restrict_permissions
from security.rbac import RBACManager


# ============================================================================
# 异常层级
# ============================================================================

class BootstrapError(Exception):
    """初始化编排基础异常。"""


class PrerequisiteError(BootstrapError):
    """前置检查失败（标记文件存在 / 已有用户 / 缺密钥）。"""


class SecretGenerationError(BootstrapError):
    """密钥生成失败。"""


class EnvFileWriteError(BootstrapError):
    """.env.local 写入失败。"""


class DbInitError(BootstrapError):
    """数据库初始化失败。"""


class OwnerCreationError(BootstrapError):
    """owner 用户创建失败。"""


class RbacAssignError(BootstrapError):
    """RBAC 角色赋予失败。"""


class MarkerWriteError(BootstrapError):
    """标记文件写入失败。"""


class LockAcquireError(BootstrapError):
    """文件锁获取失败（并发初始化）。"""


# ============================================================================
# 路径常量
# ============================================================================

BACKEND_DIR: Path = Path(__file__).resolve().parent.parent
"""backend 目录绝对路径。"""

ENV_LOCAL_PATH: Path = BACKEND_DIR / ".env.local"
""".env.local 文件路径（与 generate_api_key.py 保持一致）。"""

INIT_LOCK_PATH: Path = BACKEND_DIR / ".init.lock"
"""初始化锁文件路径（与 .env.local 同目录）。"""

# 三密钥变量名
SECRET_KEY_NAMES: tuple[str, ...] = ("JWT_SECRET_KEY", "CSRF_SECRET_KEY", "ENCRYPTION_KEY")

# OPENAWA_API_KEY 变量名
API_KEY_NAME: str = "OPENAWA_API_KEY"


# ============================================================================
# 文件锁（并发保护）
# ============================================================================

# 模块级锁状态：Windows 回退方案 + 测试用 mock 注入点
_init_lock_fd: Any = None
"""文件锁文件描述符（Linux/Mac），None 表示未持有。"""

_init_lock_acquired: bool = False
"""模块级标志位：Windows 下防止单进程内重入。"""


def _acquire_init_lock() -> None:
    """获取初始化文件锁。

    Linux/Mac 使用 `fcntl.flock` 非阻塞独占锁；
    Windows 回退到模块级标志（单进程内防重入，不跨进程互斥）。

    Raises:
        LockAcquireError: 锁已被其他进程/调用持有。
    """
    global _init_lock_fd, _init_lock_acquired

    # Windows 或无 fcntl 的平台：仅用模块级标志
    if sys.platform == "win32" or not hasattr(os, "fcntl") and not hasattr(__import__("sys"), "platform"):
        if _init_lock_acquired:
            raise LockAcquireError("另一个初始化进程正在运行")
        _init_lock_acquired = True
        logger.bind(
            event="init_lock_acquired",
            module="core.bootstrap",
            platform="windows",
        ).debug("初始化锁已获取（Windows 模块级标志）")
        return

    # POSIX 平台：使用 fcntl.flock
    import fcntl
    INIT_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = open(INIT_LOCK_PATH, "w")
    except OSError as exc:
        raise LockAcquireError(f"无法创建锁文件 {INIT_LOCK_PATH}: {exc}") from exc

    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fd.close()
        raise LockAcquireError("另一个初始化进程正在运行") from exc

    _init_lock_fd = fd
    _init_lock_acquired = True
    logger.bind(
        event="init_lock_acquired",
        module="core.bootstrap",
        platform="posix",
        lock_path=str(INIT_LOCK_PATH),
    ).debug(f"初始化锁已获取: {INIT_LOCK_PATH}")


def _release_init_lock() -> None:
    """释放初始化文件锁。"""
    global _init_lock_fd, _init_lock_acquired

    if not _init_lock_acquired:
        return

    if _init_lock_fd is not None:
        try:
            import fcntl
            fcntl.flock(_init_lock_fd.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            logger.bind(
                event="init_lock_release_failed",
                module="core.bootstrap",
                error_type=type(exc).__name__,
            ).warning(f"释放初始化锁失败: {exc}")
        try:
            _init_lock_fd.close()
        except OSError:
            pass
        _init_lock_fd = None

    _init_lock_acquired = False
    logger.bind(
        event="init_lock_released",
        module="core.bootstrap",
    ).debug("初始化锁已释放")


# ============================================================================
# 前置检查
# ============================================================================

def _check_prerequisites(force: bool) -> None:
    """检查标记文件与用户表。

    Args:
        force: True 时跳过检查并删除已有标记文件。

    Raises:
        PrerequisiteError: 标记文件存在或已有用户（force=False 时）。
    """
    if force:
        # force=True 时删除已有标记文件
        if is_initialized():
            reset_initialization()
            logger.bind(
                event="init_marker_reset_for_force",
                module="core.bootstrap",
            ).info("force=True，已删除已有标记文件")
        return

    if is_initialized():
        raise PrerequisiteError("系统已初始化，如需重新初始化请使用 force=True")

    db = SessionLocal()
    try:
        if has_any_user(db):
            raise PrerequisiteError("系统已有用户，禁止创建新 owner（如需强制创建请使用 force=True）")
    finally:
        db.close()


# ============================================================================
# 密钥生成
# ============================================================================

def _read_env_local_values() -> dict[str, str]:
    """读取 .env.local 已有键值对。

    Returns:
        键值字典；文件不存在时返回空字典。
    """
    if not ENV_LOCAL_PATH.exists():
        return {}
    try:
        from dotenv import dotenv_values
        return {k: v for k, v in dotenv_values(ENV_LOCAL_PATH).items() if k and v is not None}
    except Exception as exc:
        logger.bind(
            event="env_local_read_failed",
            module="core.bootstrap",
            error_type=type(exc).__name__,
        ).warning(f"读取 .env.local 失败，按空文件处理: {exc}")
        return {}


def _generate_three_secrets(regenerate: bool) -> dict[str, str]:
    """生成或保留三密钥（JWT_SECRET_KEY / CSRF_SECRET_KEY / ENCRYPTION_KEY）。

    Args:
        regenerate: True 时强制重新生成（覆盖已有值）。

    Returns:
        {"JWT_SECRET_KEY": str, "CSRF_SECRET_KEY": str, "ENCRYPTION_KEY": str}
    """
    from cryptography.fernet import Fernet

    existing = _read_env_local_values()
    # 同时考虑环境变量（settings 加载顺序：进程环境变量 > .env.local）
    result: dict[str, str] = {}
    generated_any = False

    for key_name in SECRET_KEY_NAMES:
        existing_value = existing.get(key_name) or os.getenv(key_name, "").strip()
        if existing_value and not regenerate:
            result[key_name] = existing_value
            logger.bind(
                event="init_secret_preserved",
                module="core.bootstrap",
                key_name=key_name,
            ).info(f"保留已有密钥: {key_name}")
        else:
            if key_name == "ENCRYPTION_KEY":
                result[key_name] = Fernet.generate_key().decode("utf-8")
            else:
                # JWT_SECRET_KEY / CSRF_SECRET_KEY：64 字符 base64-urlsafe
                result[key_name] = secrets_token_urlsafe(48)
            generated_any = True
            logger.bind(
                event="init_secret_generated",
                module="core.bootstrap",
                key_name=key_name,
                regenerated=regenerate,
            ).debug(f"生成密钥: {key_name}")

    if regenerate and generated_any:
        logger.bind(
            event="init_secrets_regenerated",
            module="core.bootstrap",
        ).warning("已重新生成密钥，旧值已丢失，所有现有 token 失效")

    return result


def secrets_token_urlsafe(nbytes: int) -> str:
    """生成 URL 安全的随机字符串（secrets.token_urlsafe 的简单包装，便于测试 mock）。"""
    import secrets
    return secrets.token_urlsafe(nbytes)


def _generate_openawa_api_key(regenerate: bool) -> str:
    """生成或保留 OPENAWA_API_KEY。

    Args:
        regenerate: True 时强制重新生成。

    Returns:
        API Key 字符串（sk- 前缀 + 43 字符随机）。
    """
    existing = _read_env_local_values()
    existing_value = existing.get(API_KEY_NAME) or os.getenv(API_KEY_NAME, "").strip()
    if existing_value and not regenerate:
        logger.bind(
            event="init_api_key_preserved",
            module="core.bootstrap",
        ).info("保留已有 OPENAWA_API_KEY")
        return existing_value

    new_key = generate_key()
    logger.bind(
        event="init_api_key_generated",
        module="core.bootstrap",
        regenerated=regenerate,
    ).debug("生成新 OPENAWA_API_KEY")
    return new_key


# ============================================================================
# owner 创建
# ============================================================================

def _create_owner_in_db(
    username: str,
    password: str,
    email: str | None,
    nickname: str | None,
) -> str:
    """创建 owner 用户并赋予 admin 角色。

    Args:
        username: 用户名（已校验合法性）。
        password: 密码明文（已校验强度）。
        email: 邮箱（可选）。
        nickname: 昵称（可选）。

    Returns:
        user_id（UUID 字符串）。

    Raises:
        OwnerCreationError: 创建失败（约束冲突 / 连接断开）。
        RbacAssignError: 角色赋予失败。
    """
    # 确保 RBAC 内置角色已存在（避免角色缺失导致分配失败）
    db = SessionLocal()
    try:
        try:
            rbac = RBACManager(db)
            rbac.ensure_built_in_roles()
        except Exception as exc:
            raise DbInitError(f"RBAC 内置角色初始化失败: {exc}") from exc

        try:
            password_hash = get_password_hash(password)
        except Exception as exc:
            raise SecretGenerationError(f"密码哈希生成失败: {exc}") from exc

        user = User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=password_hash,
            role="admin",
            nickname=nickname or None,
            email=email or None,
        )
        try:
            db.add(user)
            db.commit()
            db.refresh(user)
        except Exception as exc:
            db.rollback()
            raise OwnerCreationError(f"创建 owner 用户失败: {exc}") from exc

        # 使用同步实现避免在 sync 上下文中调用 async 方法
        try:
            success = rbac._set_user_role_sync(user.id, "admin")
            if not success:
                raise RbacAssignError(f"RBAC 角色赋予返回 False（角色 admin 可能不存在）")
        except RbacAssignError:
            raise
        except Exception as exc:
            db.rollback()
            raise RbacAssignError(f"赋予 admin 角色失败: {exc}") from exc

        logger.bind(
            event="owner_user_created",
            module="core.bootstrap",
            username=username,
            user_id=user.id,
        ).info(f"已创建 owner 用户 {username}（id={user.id}）并赋予 admin 角色")

        return user.id
    finally:
        db.close()


# ============================================================================
# .env.local 写入
# ============================================================================

def _write_env_file(updates: dict[str, str]) -> None:
    """原子写入 .env.local，保留已有内容，权限 0o600。

    流程：
    1. 若 .env.local 存在，复制到 .env.local.tmp
    2. 在 .tmp 上原位修改（使用 python-dotenv set_key，保留注释）
    3. os.replace 原子替换
    4. 设置文件权限 0o600

    Args:
        updates: 需要更新的键值字典。

    Raises:
        EnvFileWriteError: 写入失败。
    """
    from dotenv import set_key

    ENV_LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ENV_LOCAL_PATH.with_suffix(ENV_LOCAL_PATH.suffix + ".tmp")

    try:
        # 复制已有内容到 tmp（保留注释）
        if ENV_LOCAL_PATH.exists():
            tmp_path.write_text(ENV_LOCAL_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            tmp_path.write_text("", encoding="utf-8")

        # 原位修改 tmp（set_key 保留注释）
        for key, value in updates.items():
            set_key(str(tmp_path), key, value, quote_mode="never")

        # 原子替换
        os.replace(tmp_path, ENV_LOCAL_PATH)

        # 设置权限 0o600
        _restrict_permissions(ENV_LOCAL_PATH)
    except OSError as exc:
        # 清理 tmp 残留
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise EnvFileWriteError(f".env.local 写入失败: {exc}") from exc
    except Exception as exc:
        # 处理 set_key 等非 OSError 异常
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise EnvFileWriteError(f".env.local 写入失败: {exc}") from exc

    logger.bind(
        event="env_local_written",
        module="core.bootstrap",
        keys_updated=list(updates.keys()),
    ).info(f".env.local 已更新（{len(updates)} 项）")


# ============================================================================
# 标记文件创建
# ============================================================================

def _create_initialized_marker(steps: list[str]) -> None:
    """调用 mark_initialized 创建标记文件。

    Args:
        steps: 已完成的步骤列表。

    Raises:
        MarkerWriteError: 写入失败（含"请手动创建标记文件"提示）。
    """
    try:
        mark_initialized(steps)
    except OSError as exc:
        raise MarkerWriteError(
            f"标记文件写入失败: {exc}。"
            "owner 已创建，请手动创建标记文件或调用 force=true 重新初始化"
        ) from exc


# ============================================================================
# 数据库初始化
# ============================================================================

def _ensure_db_initialized() -> None:
    """确保数据库表结构已创建。

    Raises:
        DbInitError: 数据库初始化失败。
    """
    try:
        init_db()
    except Exception as exc:
        raise DbInitError(f"数据库初始化失败: {exc}") from exc


# ============================================================================
# 公共入口
# ============================================================================

def initialize_system(
    username: str,
    password: str,
    email: str | None = None,
    nickname: str | None = None,
    force: bool = False,
    regenerate_secrets: bool = False,
) -> dict[str, Any]:
    """执行首次部署初始化的 6 步流程。

    Args:
        username: owner 用户名（已校验合法性）。
        password: owner 密码明文（已校验强度）。
        email: owner 邮箱（可选）。
        nickname: owner 昵称（可选）。
        force: 跳过前置检查（标记文件 / 用户表）。
        regenerate_secrets: 强制重新生成三密钥与 API Key（需配合 force=True）。

    Returns:
        {"user_id": str, "username": str, "secrets_generated": bool, "api_key_generated": bool}

    Raises:
        PrerequisiteError: 前置检查失败。
        SecretGenerationError: 密钥生成失败。
        EnvFileWriteError: .env.local 写入失败。
        DbInitError: 数据库初始化失败。
        OwnerCreationError: owner 创建失败。
        RbacAssignError: RBAC 角色赋予失败。
        MarkerWriteError: 标记文件写入失败。
        LockAcquireError: 并发初始化锁获取失败。
    """
    # 6 步流程的步骤名列表（用于标记文件）
    steps_completed: list[str] = []
    secrets_generated = False
    api_key_generated = False

    # 获取文件锁（确保所有路径都释放）
    _acquire_init_lock()
    try:
        # 步骤 1：前置检查
        _check_prerequisites(force=force)
        steps_completed.append("prerequisite_check")

        # 步骤 2：生成三密钥
        secrets = _generate_three_secrets(regenerate=regenerate_secrets and force)
        secrets_generated = bool(secrets)
        steps_completed.append("generate_secrets")

        # 步骤 3：生成 OPENAWA_API_KEY
        api_key = _generate_openawa_api_key(regenerate=regenerate_secrets and force)
        api_key_generated = bool(api_key)
        steps_completed.append("generate_api_key")

        # 步骤 4：创建 owner（需先确保 DB 表结构）
        _ensure_db_initialized()
        user_id = _create_owner_in_db(
            username=username,
            password=password,
            email=email,
            nickname=nickname,
        )
        steps_completed.append("create_owner")

        # 步骤 5：写入 .env.local
        env_updates = {**secrets, API_KEY_NAME: api_key}
        _write_env_file(env_updates)
        steps_completed.append("write_env_file")

        # 步骤 6：创建标记文件
        _create_initialized_marker(steps_completed)
        steps_completed.append("create_marker")

        logger.bind(
            event="system_initialized",
            module="core.bootstrap",
            username=username,
            user_id=user_id,
            secrets_generated=secrets_generated,
            api_key_generated=api_key_generated,
            force=force,
            regenerate_secrets=regenerate_secrets,
        ).info(f"系统初始化完成: owner={username}, user_id={user_id}")

        return {
            "user_id": user_id,
            "username": username,
            "secrets_generated": secrets_generated,
            "api_key_generated": api_key_generated,
        }
    finally:
        _release_init_lock()
