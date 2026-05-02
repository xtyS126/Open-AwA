"""
本地用户配置加载器，负责从 users.yaml 读取用户列表并同步到数据库。
用户信息的增删仅允许通过编辑 config/users.yaml 进行，不再通过 API 注册。
"""

import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger
from sqlalchemy.orm import Session

from config.security import get_password_hash, verify_password


# 配置文件路径：与本模块同目录下的 users.yaml
_USERS_CONFIG_PATH = Path(__file__).resolve().parent / "users.yaml"
_MAX_USERNAME_LENGTH = 64
_MIN_PASSWORD_LENGTH = 4
_VALID_ROLES = {"admin", "user"}
_PLACEHOLDER_PASSWORD_VALUES = {
    "change-me",
    "change_me",
    "replace-me",
    "replace_me",
    "set-via-env",
}


def _resolve_password(entry: Dict[str, Any], index: int) -> Optional[str]:
    """
    解析配置条目的密码。
    优先支持通过环境变量注入密码，避免将真实凭证提交到仓库中。
    """
    password_env = str(entry.get("password_env", "")).strip()
    if password_env:
        env_password = str(os.getenv(password_env, "")).strip()
        if env_password:
            return env_password
        # 环境变量未设置时，回退到 password 字段
        logger.warning(
            f"用户配置第 {index + 1} 条引用的环境变量 '{password_env}' 未设置，"
            f"回退到 password 字段"
        )

    password = str(entry.get("password", "")).strip()
    if password.lower() in _PLACEHOLDER_PASSWORD_VALUES:
        logger.warning(f"用户配置第 {index + 1} 条仍使用占位密码，已跳过")
        return None
    return password


def _load_users_config(config_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    从 YAML 配置文件加载用户列表，校验格式并返回合法条目。
    """
    path = config_path or _USERS_CONFIG_PATH
    if not path.exists():
        logger.warning(f"用户配置文件不存在: {path}，跳过本地用户同步")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        logger.error(f"用户配置文件解析失败: {exc}")
        return []
    except OSError as exc:
        logger.error(f"用户配置文件读取失败: {exc}")
        return []

    if not isinstance(data, dict):
        logger.error("用户配置文件格式错误: 顶层必须是字典")
        return []

    raw_users = data.get("users")
    if not isinstance(raw_users, list):
        logger.error("用户配置文件格式错误: users 字段必须是列表")
        return []

    valid_users: List[Dict[str, Any]] = []
    seen_usernames: set = set()

    for idx, entry in enumerate(raw_users):
        if not isinstance(entry, dict):
            logger.warning(f"用户配置第 {idx + 1} 条不是字典，已跳过")
            continue

        username = str(entry.get("username", "")).strip()
        password = _resolve_password(entry, idx) or ""
        role = str(entry.get("role", "user")).strip().lower()

        # 校验用户名
        if not username:
            logger.warning(f"用户配置第 {idx + 1} 条缺少 username，已跳过")
            continue
        if len(username) > _MAX_USERNAME_LENGTH:
            logger.warning(f"用户配置第 {idx + 1} 条 username 过长（最大 {_MAX_USERNAME_LENGTH}），已跳过")
            continue
        if username in seen_usernames:
            logger.warning(f"用户配置第 {idx + 1} 条 username '{username}' 重复，已跳过")
            continue

        # 校验密码
        if not password or len(password) < _MIN_PASSWORD_LENGTH:
            logger.warning(f"用户配置第 {idx + 1} 条 password 为空或过短（最少 {_MIN_PASSWORD_LENGTH} 字符），已跳过")
            continue

        # 校验角色
        if role not in _VALID_ROLES:
            logger.warning(f"用户配置第 {idx + 1} 条 role '{role}' 无效，已回退为 'user'")
            role = "user"

        seen_usernames.add(username)
        valid_users.append({
            "username": username,
            "password": password,
            "role": role,
        })

    logger.info(f"从配置文件加载了 {len(valid_users)} 个有效用户条目")
    return valid_users


def sync_local_users_to_db(db: Session, config_path: Optional[Path] = None) -> Dict[str, int]:
    """
    将本地配置文件中的用户同步到数据库。
    - 配置中存在但数据库中不存在的用户：新增
    - 配置中存在且数据库中已存在的用户：更新角色（密码仅在首次创建时设置）
    - 数据库中存在但配置中不存在的用户：标记禁用（设置 role 为 disabled）

    返回操作统计字典: {"created": N, "updated": N, "disabled": N}
    """
    from db.models import User

    users_config = _load_users_config(config_path)
    stats = {"created": 0, "updated": 0, "disabled": 0}

    if not users_config:
        logger.warning("本地用户配置为空，跳过同步")
        return stats

    config_usernames = {u["username"] for u in users_config}

    # 同步配置中的用户到数据库
    for user_cfg in users_config:
        existing = db.query(User).filter(User.username == user_cfg["username"]).first()
        if existing is None:
            # 新增用户
            new_user = User(
                id=str(uuid.uuid4()),
                username=user_cfg["username"],
                password_hash=get_password_hash(user_cfg["password"]),
                role=user_cfg["role"],
            )
            db.add(new_user)
            stats["created"] += 1
            logger.info(f"新增本地用户: {user_cfg['username']} (角色: {user_cfg['role']})")
        else:
            # 更新角色（如果配置中角色发生变化）
            changed = False
            if existing.role != user_cfg["role"]:
                existing.role = user_cfg["role"]
                changed = True
            # 如果密码发生变化，同步更新密码哈希
            if not verify_password(user_cfg["password"], existing.password_hash):
                existing.password_hash = get_password_hash(user_cfg["password"])
                changed = True
            if changed:
                stats["updated"] += 1
                logger.info(f"更新本地用户: {user_cfg['username']}")

    # 禁用配置中不存在的用户（role 设为 disabled，而不是删除记录）
    db_users = db.query(User).all()
    for db_user in db_users:
        if db_user.username not in config_usernames and db_user.role != "disabled":
            db_user.role = "disabled"
            stats["disabled"] += 1
            logger.info(f"禁用不在配置中的用户: {db_user.username}")

    db.commit()
    logger.info(
        f"本地用户同步完成: 新增 {stats['created']}, "
        f"更新 {stats['updated']}, 禁用 {stats['disabled']}"
    )
    return stats
